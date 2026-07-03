"""explicit_preference 模块：显性偏好链路（解析 → 匹配 → 理由）。

兜底模式下：parse_intent source=fallback；match 走纯结构化打分（sem_score=None）；
parse_intent_from_image 因 vision 不可用返回 source=none。
"""
from modules import explicit_preference as ep
from modules import fallback


# ===== parse_intent =====

def test_parse_intent_fallback_source_and_fields():
    i = ep.parse_intent("温柔、不戴眼镜、瓜子脸、文艺风")
    assert i["source"] == "fallback"
    assert i["raw_text"] == "温柔、不戴眼镜、瓜子脸、文艺风"
    assert i["glasses"] is False
    assert i["faceShape"] == "瓜子脸"
    assert i["style"] == "文艺"
    assert i["vibe"] == "温柔"


def test_parse_intent_empty_text():
    i = ep.parse_intent("")
    assert i["source"] == "fallback"
    assert i["glasses"] is None


# ===== 数据加载 =====

def test_load_candidates_count_and_shape():
    cs = ep.load_candidates()
    assert len(cs) == 12
    assert all("id" in c and "attributes" in c and "bio" in c for c in cs)


# ===== match =====

def test_match_returns_top3_sorted_with_best_first():
    intent = {"glasses": False, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔",
              "raw_text": "温柔不戴眼镜瓜子脸文艺", "source": "fallback"}
    ms = ep.match(intent)
    assert len(ms) == 3
    scores = [m["score"] for m in ms]
    assert scores == sorted(scores, reverse=True)  # 降序
    # c01 全中 → 第一 + 满分
    assert ms[0]["candidate"]["id"] == "c01"
    assert ms[0]["score"] == 1.0
    assert ms[0]["score_source"] == "structured"
    assert ms[0]["sem_score"] is None  # 兜底不调语义分


def test_match_reasons_populated():
    intent = {"glasses": False, "style": "文艺", "raw_text": "不戴眼镜文艺", "source": "fallback"}
    ms = ep.match(intent)
    assert ms and isinstance(ms[0]["reasons"], list) and ms[0]["reasons"]


# ===== parse_intent_from_image（vision 兜底）=====

def test_parse_intent_from_image_unavailable_returns_none():
    r = ep.parse_intent_from_image("fakebase64==")
    assert r["source"] == "none"
    assert r.get("error") == "vision_unavailable"


# ===== 归一化工具（纯函数）=====

def test_normalize_glasses_variants():
    assert ep._normalize_glasses(True) is True
    assert ep._normalize_glasses(False) is False
    assert ep._normalize_glasses("戴眼镜") is True
    assert ep._normalize_glasses("不戴眼镜") is False
    assert ep._normalize_glasses(None) is None
    assert ep._normalize_glasses("乱七八糟") is None


def test_normalize_choice_exact_and_fuzzy():
    allowed = fallback.FACE_SHAPES
    assert ep._normalize_choice("瓜子脸", allowed) == "瓜子脸"
    assert ep._normalize_choice("一只瓜子脸", allowed) == "瓜子脸"  # 包含关系
    assert ep._normalize_choice(None, allowed) is None
    assert ep._normalize_choice("不存在的脸型", allowed) is None
