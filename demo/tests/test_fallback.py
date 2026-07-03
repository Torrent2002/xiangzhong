"""fallback 模块：纯本地兜底逻辑（关键词解析 / 结构化打分 / 统计反推 / 模板提示）。

无外部依赖、无 LLM、无网络 —— 兜底模式的核心，最该被测试覆盖。
"""
from modules import fallback


# ===== parse_intent =====

def test_parse_intent_empty():
    assert fallback.parse_intent("") == {
        "glasses": None, "faceShape": None, "style": None, "vibe": None
    }


def test_parse_intent_none_input():
    assert fallback.parse_intent(None)["glasses"] is None


def test_parse_intent_glasses_false_precedence():
    """「不戴眼镜」必须优先于「戴眼镜」（避免子串误命中）。"""
    i = fallback.parse_intent("不戴眼镜、温柔")
    assert i["glasses"] is False


def test_parse_intent_glasses_true():
    assert fallback.parse_intent("戴眼镜、文艺")["glasses"] is True


def test_parse_intent_face_shape():
    assert fallback.parse_intent("瓜子脸")["faceShape"] == "瓜子脸"


def test_parse_intent_style_alias():
    # 文艺风 → 文艺（别名归一化，先命中先返回）
    assert fallback.parse_intent("文艺风")["style"] == "文艺"


def test_parse_intent_vibe_alias():
    # 温婉 → 温柔
    assert fallback.parse_intent("温婉")["vibe"] == "温柔"


def test_parse_intent_full_sentence():
    i = fallback.parse_intent("温柔、不戴眼镜、瓜子脸、文艺风")
    assert i == {"glasses": False, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔"}


# ===== intent_fields =====

def test_intent_fields_filters_none_in_order():
    i = {"glasses": True, "faceShape": None, "style": "文艺", "vibe": None}
    assert fallback.intent_fields(i) == ["glasses", "style"]


def test_intent_fields_all_none():
    assert fallback.intent_fields({"glasses": None, "faceShape": None, "style": None, "vibe": None}) == []


# ===== match_score =====

def test_match_score_all_hit():
    intent = {"glasses": False, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔"}
    c = {"attributes": {"glasses": False, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔"}}
    score, hits, diffs = fallback.match_score(intent, c)
    assert score == 1.0
    assert set(hits) == {"glasses", "faceShape", "style", "vibe"}
    assert diffs == []


def test_match_score_partial():
    # 2 个非空字段：style 命中、glasses 差异 → 0.5
    intent = {"glasses": False, "style": "文艺"}
    c = {"attributes": {"glasses": True, "style": "文艺"}}
    score, hits, diffs = fallback.match_score(intent, c)
    assert score == 0.5
    assert hits == ["style"]
    assert diffs == ["glasses"]


def test_match_score_no_nonzero_avoids_div_zero():
    # intent 全 None → 除零保护，返回 0.0
    score, hits, diffs = fallback.match_score(
        {"glasses": None, "style": None},
        {"attributes": {"glasses": True, "style": "文艺"}},
    )
    assert score == 0.0
    assert hits == [] and diffs == []


# ===== why_reasons =====

def test_why_reasons_hit_diff_and_bio():
    intent = {"glasses": False, "style": "文艺"}
    c = {"name": "林同学", "bio": "爱看书",
         "attributes": {"glasses": True, "style": "文艺"}}
    _, hits, diffs = fallback.match_score(intent, c)
    reasons = fallback.why_reasons(intent, c, hits, diffs)
    assert any("命中" in r for r in reasons)
    assert any("唯一差异" in r for r in reasons)
    assert any("爱看书" in r for r in reasons)


# ===== infer_from_log（统计反推）=====

def test_infer_no_likes_not_enough():
    r = fallback.infer_from_log([], {"c01": {}})
    assert r["has_enough"] is False
    assert r["liked_count"] == 0
    assert r["fields"] == []


def test_infer_dominant_implicit_attr():
    # 3 张心动：style 全文艺（但 intent 已提 style → 不算隐性），
    # vibe 未提 → 高冷占 2/3 ≥0.5 → 被识别为隐性偏好。
    by_id = {
        "c01": {"attributes": {"style": "文艺", "vibe": "温柔"}},
        "c02": {"attributes": {"style": "文艺", "vibe": "高冷"}},
        "c03": {"attributes": {"style": "文艺", "vibe": "高冷"}},
    }
    log = [{"type": "like", "candidateId": cid} for cid in ("c01", "c02", "c03")]
    r = fallback.infer_from_log(log, by_id, intent={"style": "文艺"})
    assert r["has_enough"] is True
    assert r["liked_count"] == 3
    assert r["fields"][0]["field"] == "vibe"
    assert r["fields"][0]["value"] == "高冷"
    assert r["fields"][0]["ratio"] == 0.67


# ===== suggest_template =====

def test_suggest_template_not_enough():
    s = fallback.suggest_template({"has_enough": False}, None)
    assert s["title"] == "再多看看几张卡片"
    assert s["fields"] == []


def test_suggest_template_with_field():
    pref = {"has_enough": True, "liked_count": 3,
            "fields": [{"field": "vibe", "value": "高冷", "ratio": 0.67}]}
    s = fallback.suggest_template(pref, intent={"vibe": "温柔"})
    assert "高冷" in s["body"]
    assert s["fields"] == pref["fields"]
