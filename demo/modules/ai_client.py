"""AI 调用封装（OpenAI 兼容）。

这是显性 / 隐性两条链路接入 LLM 的唯一外露接缝。
- 配了 key 就调真 LLM（兼容 Qwen/DeepSeek/Moonshot/豆包/GLM/OpenAI，靠 base_url 覆盖）。
- 没 key / 调用失败 / 超时 → 自动返回 fallback，两条链路无感降级。
- 进程内缓存 is_available() 结果；环境变量可热改（便于演示中切模式）。

环境变量（.env.example）：
  OPENAI_API_KEY   必填，留空即走兜底
  OPENAI_BASE_URL  可选，OpenAI 兼容端点（如 https://dashscope.aliyuncs.com/compatible-mode/v1）
  MODEL            可选，模型名（如 qwen-plus / gpt-4o-mini / deepseek-chat）

统一接口：
  is_available() -> bool
  complete_chat(messages, json_mode=False) -> str | None   # 返回 None 即"不可用/失败"
  embed(text) -> list[float] | None                          # 同上
  call_llm(messages, json_mode=False, fallback=None) -> str  # 高层封装，失败直接给 fallback
"""

import json
import os
import time
import httpx
from typing import Any

# openai SDK 在真实路径才 import；没装也不影响兜底模式启动。
try:
    from openai import OpenAI
    from openai import APIError, APITimeoutError, RateLimitError
    _OPENAI_SDK_OK = True
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - 仅在缺包时触发
    OpenAI = None  # type: ignore
    APIError = APITimeoutError = RateLimitError = Exception  # type: ignore
    _OPENAI_SDK_OK = False
    _IMPORT_ERR = repr(e)

# 单次调用超时（秒）。需求 §5.3：15s。
_TIMEOUT = 15.0
# vision 调用超时（秒）：图片体积大，给宽点。
_VISION_TIMEOUT = 20.0
# 失败重试次数（不含首次）。需求 §5.3：重试 1 次。
_RETRIES = 1

# ---- 进程内缓存：客户端 + key 校验 ----
_client_cache: dict[str, Any] = {"key": None, "client": None, "checked": None}


def _env(key: str, default: str = "") -> str:
    """读环境变量（含 .env 文件，若安装了 python-dotenv 则自动加载；否则用 os.environ）。"""
    val = os.environ.get(key, default)
    if val is None:
        return default
    return val.strip()


def _load_dotenv() -> None:
    """从 demo/.env 加载环境变量（不依赖 python-dotenv；demo 现场零额外依赖也能切模式）。"""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        # .env 读失败不应阻塞启动
        pass


# 启动时尝试加载一次 .env
_load_dotenv()


def is_available() -> bool:
    """是否有可用 API key + SDK。

    判据：装了 openai SDK 且环境变量 OPENAI_API_KEY 非空。
    结果做轻量缓存（key 变化时重算），避免每请求都判断。
    """
    if not _OPENAI_SDK_OK:
        return False
    key = _env("OPENAI_API_KEY")
    cached_key = _client_cache["key"]
    if cached_key == key and _client_cache["checked"] is not None:
        return _client_cache["checked"]
    _client_cache["key"] = key
    _client_cache["checked"] = bool(key)
    if _client_cache["checked"]:
        _client_cache["client"] = None  # 让 _get_client() 重建
    else:
        _client_cache["client"] = None
    return _client_cache["checked"]


def _get_client():
    """惰性构建 OpenAI 客户端（带 base_url 覆盖）。"""
    if not is_available():
        return None
    if _client_cache["client"] is None:
        try:
            base_url = _env("OPENAI_BASE_URL")
            kwargs: dict[str, Any] = {
                "api_key": _env("OPENAI_API_KEY"),
                "timeout": _TIMEOUT,
            }
            if base_url:
                kwargs["base_url"] = base_url
            _client_cache["client"] = OpenAI(**kwargs)
        except Exception:
            _client_cache["client"] = None
    return _client_cache["client"]


def _model() -> str:
    return _env("MODEL", "gpt-4o-mini")


def _vision_model() -> str:
    """vision 模型名。默认回落到 MODEL，但 deepseek-chat 不支持图片，需显式配 VISION_MODEL。"""
    return _env("VISION_MODEL", _model())


def is_vision_available() -> bool:
    """是否可调用多模态 vision 模型。

    判据：装了 openai SDK + 有 key + VISION_MODEL 显式非空。
    注意：deepseek-chat 不支持图片。VISION_MODEL 留空 → 返回 False（前端禁用照片按钮，
    提示「未配置 vision 模型」）。要启用照片识别，必须在 .env 显式设 VISION_MODEL
    为支持 vision 的模型（qwen-vl-plus / glm-4v-flash / gpt-4o 等）。
    """
    if not _OPENAI_SDK_OK:
        return False
    if not _env("OPENAI_API_KEY"):
        return False
    if not _env("VISION_MODEL"):
        return False
    return True


def _get_vision_client():
    """惰性构建一个专用于 vision 的客户端（独立超时）。

    与 _get_client 同源 OpenAI 实例；区别仅在 timeout（图片调用更慢）。
    openai SDK 的 client.timeout 可在单次 create 时覆盖，这里直接复用主 client。
    """
    return _get_client()


def _safe_chat(messages: list[dict], json_mode: bool = False) -> str | None:
    """真实 chat completion，带超时 + 重试 1 次。任何异常都返回 None。"""
    client = _get_client()
    if client is None:
        return None
    last_err: Exception | None = None
    for attempt in range(_RETRIES + 1):
        try:
            kwargs: dict[str, Any] = {
                "model": _model(),
                "messages": messages,
                "temperature": 0.2,
            }
            if json_mode:
                # 不同厂商对 response_format 支持不一；失败时退回普通调用。
                try:
                    kwargs["response_format"] = {"type": "json_object"}
                except Exception:
                    pass
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            if content is None:
                return None
            return content.strip()
        except (APITimeoutError, TimeoutError) as e:
            last_err = e
            time.sleep(0.4 * (attempt + 1))
            continue
        except (RateLimitError, APIError) as e:
            last_err = e
            time.sleep(0.4 * (attempt + 1))
            continue
        except Exception as e:
            # 兼容多厂商的杂项错误（鉴权失败、base_url 错、参数不支持等）。
            # 若是 response_format 不被支持，去掉 json_mode 重试一次。
            if json_mode and attempt == 0:
                try:
                    resp = client.chat.completions.create(
                        model=_model(), messages=messages, temperature=0.2
                    )
                    content = resp.choices[0].message.content
                    if content is not None:
                        return content.strip()
                except Exception as e2:
                    last_err = e2
                    continue
            last_err = e
            break
    return None


def complete_chat(messages: list[dict], json_mode: bool = False) -> str | None:
    """OpenAI 兼容的 chat completion。

    返回字符串内容；不可用 / 失败 / 无 key 时返回 None。
    调用方据 None 走本地兜底。
    """
    if not is_available():
        return None
    return _safe_chat(messages, json_mode=json_mode)


def vision_analyze(image_b64: str, prompt: str, json_mode: bool = False) -> str | None:
    """多模态 vision 调用：用 httpx 直接请求 OpenAI 兼容 vision 端点。

    不经 openai SDK 的同步 client（其在 uvicorn 线程池里对图片调用会卡死），
    改用 httpx 同步请求，超时严格生效，线程池 / 独立进程行为一致。
    模型取 VISION_MODEL（deepseek-chat 不支持图片，需配 doubao-seed-2.0-pro / qwen-vl / glm-4v / gpt-4o）。
    超时 _VISION_TIMEOUT、重试 _RETRIES 次；无 key / 失败 → 返回 None（调用方走兜底）。
    """
    if not is_vision_available():
        return None
    b64 = (image_b64 or "").strip()
    if not b64:
        return None
    base_url = (_env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {_env('OPENAI_API_KEY')}"}
    body: dict[str, Any] = {
        "model": _vision_model(),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt or ""},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
        "temperature": 0.2,
        "max_tokens": 200,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(_RETRIES + 1):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=_VISION_TIMEOUT)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content.strip() if content else None
        except Exception:
            continue
    return None


def embed(text: str) -> list[float] | None:
    """文本向量（用于显性语义打分）。

    无 key / 失败时返回 None。调用方据 None 走结构化兜底打分。
    多数兼容端点不提供 embeddings，因此失败时静默降级。
    """
    if not is_available():
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.embeddings.create(model=_env("EMBED_MODEL", "text-embedding-3-small"), input=text)
        return list(resp.data[0].embedding)
    except Exception:
        return None


def call_llm(messages: list[dict], json_mode: bool = False, fallback: Any = None) -> Any:
    """高层封装：调 LLM，失败直接返回 fallback（不抛错）。

    用途：两条链路里"想用 AI、否则用兜底"的统一写法：
        out = ai_client.call_llm(messages, json_mode=True, fallback=fallback_value)
    """
    if not is_available():
        return fallback
    out = _safe_chat(messages, json_mode=json_mode)
    if out is None or out == "":
        return fallback
    return out


def status() -> dict:
    """诊断用：返回当前 AI 可用性与配置（脱敏）。供 /api/status 暴露给前端显示模式角标。"""
    return {
        "available": is_available(),
        "mode": "AI 模式" if is_available() else "本地兜底模式",
        "model": _model() if is_available() else None,
        "base_url_set": bool(_env("OPENAI_BASE_URL")),
        "sdk_ok": _OPENAI_SDK_OK,
        "import_err": _IMPORT_ERR,
        "vision_available": is_vision_available(),
        "vision_model": _vision_model() if is_vision_available() else None,
    }
