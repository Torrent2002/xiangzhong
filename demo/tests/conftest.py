"""pytest 公共配置。

关键：强制【兜底模式】跑测试。
demo/.env 里有真 API key，若不拦，ai_client 会在 import 时 _load_dotenv() 把 key 灌进
os.environ，于是 is_available()=True，测试就去打真 LLM（慢、不稳定、花钱、要联网）。

拦法：在导入任何 modules.* 之前，先把 OPENAI_API_KEY / VISION_MODEL 置空。
ai_client._load_dotenv() 只在 `k not in os.environ` 时写入，故预先置空即可挡住 .env。
"""
import os
import sys

# —— 必须在任何 modules 导入之前 ——
os.environ["OPENAI_API_KEY"] = ""
os.environ["VISION_MODEL"] = ""

# 让 `import modules` / `import app` 在任意 cwd 下可用。
DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DEMO_DIR not in sys.path:
    sys.path.insert(0, DEMO_DIR)

import pytest


@pytest.fixture(autouse=True)
def _force_fallback():
    """每个测试前清空 ai_client 缓存，确保 is_available() 按空 key 重判为 False。"""
    from modules import ai_client as ac
    ac._client_cache.update({"key": None, "client": None, "checked": None})
    yield


@pytest.fixture(autouse=True)
def _reset_implicit():
    """每个测试前清空隐性偏好的内存日志 / last_intent / 候选缓存，隔离测试。"""
    from modules import implicit_preference as ip
    ip._behavior_log.clear()
    ip._last_intent = None
    ip._candidates_cache = None
    yield
    ip._behavior_log.clear()
    ip._last_intent = None
    ip._candidates_cache = None


@pytest.fixture(autouse=True)
def _reset_store():
    """每个测试前把 candidate_store 复位到 candidates.json 原态（12 个预计算）。"""
    from modules import candidate_store as cs
    cs._candidates = []
    cs._by_id = {}
    cs._loaded = False
    cs.load()
    yield
    cs._candidates = []
    cs._by_id = {}
    cs._loaded = False
    cs.load()


@pytest.fixture
def client():
    """FastAPI TestClient（兜底模式）。store 已由 _reset_store 复位。"""
    from fastapi.testclient import TestClient
    import app
    with TestClient(app.app) as c:
        yield c
