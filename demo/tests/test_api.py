"""app.py API 端点（FastAPI TestClient，兜底模式）。

覆盖：首页 / status / 显性匹配 / 参考图 / 候选详情 / 行为上报 / 隐性提示 / 注册。
不联网、不打真 LLM（conftest 强制兜底）。
"""


def test_index_returns_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "相中" in r.text


def test_status_fallback_mode(client):
    j = client.get("/api/status").json()
    assert j["mode"] == "本地兜底模式"
    assert j["available"] is False
    assert j["vision_available"] is False


# ===== 显性 =====

def test_explicit_match_fallback(client):
    j = client.post("/api/explicit/match",
                    json={"text": "温柔、不戴眼镜、瓜子脸、文艺风"}).json()
    assert j["intent"]["source"] == "fallback"
    assert j["intent"]["glasses"] is False
    assert j["intent"]["style"] == "文艺"
    assert len(j["matches"]) == 3
    assert j["matches"][0]["candidate"]["id"] == "c01"
    assert j["mode"] == "本地兜底模式"


def test_explicit_match_empty_text(client):
    j = client.post("/api/explicit/match", json={"text": ""}).json()
    assert j["intent"]["source"] == "fallback"


def test_match_image_vision_unavailable(client):
    j = client.post("/api/explicit/match_image", json={"image": "fake=="}).json()
    assert j["intent"]["source"] == "none"
    assert j["vision_available"] is False
    # vision 失效 → 全候选作兜底 feed，matches 空
    assert j["matches"] == []
    assert len(j["fallback_feed"]) == 12
    assert j["fallback_feed"][0]["fallback"] is True


# ===== 候选详情（产品克制：不返回 AI 标定）=====

def test_candidate_detail_existing(client):
    j = client.get("/api/candidate/c01").json()
    assert j["ok"] is True
    assert j["candidate"]["name"] == "林同学"
    assert j["candidate"]["bio"] is not None
    # 刻意不返回 AI 标定 attributes（避免物化）
    assert "attributes" not in j["candidate"]


def test_candidate_detail_missing(client):
    j = client.get("/api/candidate/zzz").json()
    assert j == {"ok": False, "error": "not_found", "id": "zzz"}


def test_candidate_detail_match_score_requires_intent(client):
    # 未先匹配（无 last_intent）→ match_score=None, has_intent=False
    j = client.get("/api/candidate/c01").json()
    assert j["match_score"] is None
    assert j["has_intent"] is False
    # 先匹配一次再查 → 有 match_score
    client.post("/api/explicit/match", json={"text": "温柔、不戴眼镜、瓜子脸、文艺"})
    j2 = client.get("/api/candidate/c01").json()
    assert j2["has_intent"] is True
    assert j2["match_score"] is not None


# ===== 隐性 =====

def test_implicit_track_then_suggest(client):
    r = client.post("/api/implicit/track", json={"candidateId": "c01", "action": "like"})
    assert r.json()["count"] == 1
    j = client.get("/api/implicit/suggest").json()
    assert j["preference"]["has_enough"] is True
    assert j["preference"]["liked_count"] == 1
    assert j["suggestion"]["fields"]  # c01 各维度 100% → 有隐性发现
    assert j["mode"] == "本地兜底模式"


def test_implicit_suggest_empty(client):
    j = client.get("/api/implicit/suggest").json()
    assert j["preference"]["has_enough"] is False
    assert j["suggestion"]["title"] == "再多看看几张卡片"


# ===== 注册（写入路径）=====

def test_create_candidate(client):
    j = client.post("/api/candidate/create", json={
        "name": "测试用户", "age": 27, "city": "深圳", "bio": "爱跑步", "photo": "fake=="
    }).json()
    assert j["ok"] is True
    assert j["id"].startswith("u")
    assert j["status"] == "created"
    assert j["analysis_status"] in ("pending", "failed")
