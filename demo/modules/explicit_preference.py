"""显性偏好链路：自然语言 → 意图 → 匹配。

高聚合：本模块只负责显性偏好的解析与匹配。
低耦合：只依赖 ai_client（真实 LLM）与 fallback（本地兜底）与 data/candidates.json（只读）；
       不依赖 implicit_preference（两类偏好边界互不 import）。

需求文档 §3.1 双路实现：
  parse_intent: AI 路（LLM 抽 JSON，失败重试 1 次仍失败走兜底） / 兜底路（关键词）
  match: 结构化分 + 可选 AI 语义分（0.6*结构 + 0.4*语义），无 key 只用结构化分
  "为什么推荐": 命中维度 ✓ + 第一个差异项"唯一差异：…"；AI 路可加一句自然语言
"""

import json
import os
from typing import Any

from modules import ai_client, fallback

# candidates.json 路径相对本文件解析，保证任意目录启动都正确。
_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "candidates.json")

# intent 字段顺序（与 fallback 保持一致）
_INTENT_FIELDS = ["glasses", "faceShape", "style", "vibe"]


def _load_candidates() -> list[dict]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _candidates_by_id(candidates: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in candidates}


# ===== parse_intent =====

_SYSTEM_PROMPT = (
    "你是相亲平台的偏好解析器。把用户对理想型的自然语言描述解析成结构化意图 JSON。\n"
    "字段：glasses(bool true=戴眼镜 false=不戴眼镜)、faceShape(瓜子脸/鹅蛋脸/圆脸/方脸)、"
    "style(文艺/运动/商务/街头/极简)、vibe(温柔/活泼/高冷/阳光/知性)。\n"
    "用户未提及的字段填 null。只返回纯 JSON，不要解释、不要 markdown。"
)


def _parse_intent_ai(text: str) -> dict | None:
    """AI 路：让 LLM 把描述解析成纯 JSON。失败返回 None。"""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text or ""},
    ]
    out = ai_client.call_llm(messages, json_mode=True, fallback=None)
    if not out:
        return None
    # LLM 可能仍带 markdown 围栏，剥一下。
    raw = out.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        # 去掉可能的 json 语言标识行
        raw = raw.split("\n", 1)[-1] if raw.lower().startswith("json") else raw
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # 规整：只取需要的字段，做轻度校验/归一。
    intent = {}
    intent["glasses"] = _normalize_glasses(data.get("glasses"))
    intent["faceShape"] = _normalize_choice(data.get("faceShape"), fallback.FACE_SHAPES)
    intent["style"] = _normalize_choice(data.get("style"), fallback.STYLES + list(fallback.STYLE_ALIASES.values()))
    intent["vibe"] = _normalize_choice(data.get("vibe"), fallback.VIBES + list(fallback.VIBE_ALIASES.values()))
    return intent


def _normalize_glasses(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "戴眼镜", "有眼镜"):
        return True
    if s in ("false", "0", "no", "不戴眼镜", "没眼镜"):
        return False
    return None


def _normalize_choice(v: Any, allowed: list[str]) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s in allowed:
        return s
    # 模糊：允许包含关系
    for a in allowed:
        if a in s or s in a:
            return a
    return None


def parse_intent(text: str) -> dict:
    """把自然语言描述解析为结构化意图对象。

    AI 路：LLM 抽 JSON（失败重试 1 次仍失败走兜底）。
    兜底路：fallback.parse_intent 关键词字典匹配。
    返回 {glasses, faceShape, style, vibe, raw_text, source}。
      - source: "ai" | "fallback"，供前端透明化"是怎么理解的"。
    """
    text = (text or "").strip()
    intent = None
    if ai_client.is_available():
        intent = _parse_intent_ai(text)
    if intent is None:
        intent = fallback.parse_intent(text)
        source = "fallback"
    else:
        source = "ai"
    intent["raw_text"] = text
    intent["source"] = source
    return intent


# ===== parse_intent_from_image（多模态参考图通道）=====

_VISION_SYSTEM_PROMPT = (
    "你是相亲平台「相中」的理想型照片解析器。看一张人物照片，提取其外观特征并"
    "标准化到候选字段的可选值，输出纯 JSON。\n"
    "字段与取值：\n"
    "  glasses: bool，true=戴眼镜 false=不戴眼镜\n"
    "  faceShape: 瓜子脸 / 圆脸 / 方脸 / 鹅蛋脸\n"
    "  style: 文艺 / 运动 / 商务 / 街头 / 极简\n"
    "  vibe: 温柔 / 活泼 / 高冷 / 阳光 / 知性\n"
    "判断依据：是否戴眼镜看面部；脸型看下颌与轮廓；style 看穿搭；vibe 看整体气质与表情。\n"
    "看不清或无法判断的字段填 null（不要瞎猜）。只返回纯 JSON，不要解释、不要 markdown 围栏。"
)


def parse_intent_from_image(image_b64: str) -> dict:
    """从参考照片解析结构化意图（与文本 parse_intent 同 schema）。

    AI vision 路：vision_analyze 让模型看照片抽 JSON，再归一化到候选字段可选值。
    vision 不可用 / 调用失败 → 返回 {"source":"none","error":"vision_unavailable"}，
    调用方据 source="none" 走文本兜底或提示用户。

    返回 {glasses, faceShape, style, vibe, raw_text, source, [error]}。
      - source: "ai" | "none"
    """
    if not ai_client.is_vision_available():
        return {"source": "none", "error": "vision_unavailable"}

    out = ai_client.vision_analyze(image_b64, _VISION_SYSTEM_PROMPT, json_mode=True)
    if not out:
        return {"source": "none", "error": "vision_unavailable"}

    raw = out.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if raw.lower().startswith("json") else raw
    try:
        data = json.loads(raw)
    except Exception:
        return {"source": "none", "error": "vision_unavailable"}
    if not isinstance(data, dict):
        return {"source": "none", "error": "vision_unavailable"}

    intent = {
        "glasses": _normalize_glasses(data.get("glasses")),
        "faceShape": _normalize_choice(data.get("faceShape"), fallback.FACE_SHAPES),
        "style": _normalize_choice(
            data.get("style"), fallback.STYLES + list(fallback.STYLE_ALIASES.values())
        ),
        "vibe": _normalize_choice(
            data.get("vibe"), fallback.VIBES + list(fallback.VIBE_ALIASES.values())
        ),
    }
    # raw_text 用归一化后的字段拼一句自然描述，供 _semantic_score 当作用户描述、
    # 也供隐性 suggest 做「嘴上说 X」对照（图片场景下「嘴上说」即「照片里看出的」）。
    parts = []
    if intent["glasses"] is True:
        parts.append("戴眼镜")
    elif intent["glasses"] is False:
        parts.append("不戴眼镜")
    for f in ("faceShape", "style", "vibe"):
        if intent.get(f):
            parts.append(intent[f])
    intent["raw_text"] = "、".join(parts) if parts else "（参考照片未识别到明确维度）"
    intent["source"] = "ai"
    return intent


# ===== match =====

_SYSTEM_SCORE_PROMPT = (
    "你是相亲匹配评分器。判断单个候选人 bio 是否符合用户对理想型的描述，返回 0~1 的相似度分数。"
    "只返回纯 JSON：{\"score\": 0.0~1.0, \"reason\": \"一句话自然语言理由（≤30字，中文）\"}。"
)


def _semantic_score(text: str, candidate: dict) -> tuple[float | None, str | None]:
    """AI 路：把用户描述 + candidate.bio 喂 LLM，返回 (相似度, 自然语言理由)。无 key 返 (None,None)。"""
    if not ai_client.is_available():
        return None, None
    bio = candidate.get("bio", "")
    user_msg = (
        f"用户描述：{text or '（未提供描述）'}\n"
        f"候选人：{candidate.get('name', '')}，{candidate.get('age', '')}岁，{candidate.get('city', '')}，"
        f"风格={candidate.get('attributes', {}).get('style', '')}，"
        f"气质={candidate.get('attributes', {}).get('vibe', '')}。简介：{bio}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_SCORE_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    out = ai_client.call_llm(messages, json_mode=True, fallback=None)
    if not out:
        return None, None
    raw = out.strip().strip("`")
    try:
        data = json.loads(raw)
        score = float(data.get("score", 0))
        score = max(0.0, min(1.0, score))
        reason = data.get("reason")
        return score, reason
    except Exception:
        return None, None


def match(intent: dict, candidates: list[dict] | None = None) -> list[dict]:
    """根据意图对候选人打分排序，取 top 3，每个附"为什么推荐"。

    结构化分：命中字段数 / 非空字段数。
    AI 语义分（可选）：0.4 * 语义 + 0.6 * 结构化；无 key 时只用结构化分。
    """
    if candidates is None:
        candidates = _load_candidates()
    text = (intent or {}).get("raw_text", "")
    use_ai = ai_client.is_available()

    scored: list[dict] = []
    for c in candidates:
        struct_score, hits, diffs = fallback.match_score(intent or {}, c)
        # 不再逐候选调 LLM 语义打分（原 12 次 LLM ~70s，且 sem_score 常返固定值不可靠）。
        # 速度优先：只用结构化分 + 模板理由。意图解析仍走 AI（source=ai），透明化命中/差异足够。
        sem_score = None
        final = struct_score
        score_source = "structured"

        reasons = fallback.why_reasons(intent or {}, c, hits, diffs)

        scored.append({
            "candidate": c,
            "score": round(final, 3),
            "struct_score": round(struct_score, 3),
            "sem_score": round(sem_score, 3) if sem_score is not None else None,
            "score_source": score_source,
            "hits": hits,
            "diffs": diffs,
            "reasons": reasons,
        })

    # 排序：分数降序，平局按命中维度数（更"全中"的靠前）
    scored.sort(key=lambda x: (x["score"], len(x["hits"])), reverse=True)
    return scored[:3]


def why_for_candidate(intent: dict | None, candidate: dict) -> list[str]:
    """为单个 candidate 生成「为什么推荐」理由，复用 match() 内部逻辑。

    供详情页等"非打分排序"场景使用：给定一个 intent（可能来自显性文本/图片，
    或 implicit 的 last_intent）与单个 candidate，返回理由列表。
    intent 为 None / 空时退化为兜底模板（"整体气质相近 + bio"）。
    """
    intent = intent or {}
    text = intent.get("raw_text", "")
    use_ai = ai_client.is_available() and bool(text)
    struct_score, hits, diffs = fallback.match_score(intent, candidate)

    reasons = fallback.why_reasons(intent, candidate, hits, diffs)
    if use_ai:
        _, ai_reason = _semantic_score(text, candidate)
        if ai_reason:
            reasons = [ai_reason] + reasons
    return reasons


def load_candidates() -> list[dict]:
    """暴露给 app 层（隐性反推也需要按 id 查 candidate）。"""
    return _load_candidates()
