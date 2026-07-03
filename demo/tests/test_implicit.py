"""implicit_preference 模块：隐性偏好链路（行为采集 → 反推 → 提示卡）。

兜底模式下：infer 走统计路 source=stats；suggest 走模板。
模块持有内存全局态（_behavior_log / _last_intent），conftest autouse 已逐测试清空。
"""
from modules import implicit_preference as ip


# ===== track_behavior =====

def test_track_behavior_appends_and_counts():
    r = ip.track_behavior({"candidateId": "c01", "type": "like"})
    assert r["ok"] is True
    assert r["count"] == 1
    r2 = ip.track_behavior({"candidateId": "c02", "action": "like"})
    assert r2["count"] == 2
    assert len(ip.get_log()) == 2


def test_track_behavior_accepts_action_alias():
    r = ip.track_behavior({"candidateId": "c01", "action": "pass"})
    assert r["count"] == 1
    assert ip.get_log()[0]["action"] == "pass"


# ===== last_intent 回写 =====

def test_last_intent_roundtrip():
    assert ip.get_last_intent() is None
    ip.set_last_intent({"vibe": "温柔"})
    assert ip.get_last_intent() == {"vibe": "温柔"}


# ===== infer =====

def test_infer_no_likes_returns_none():
    r = ip.infer([])
    assert r["has_enough"] is False
    assert r["source"] == "none"
    assert r["liked_count"] == 0


def test_infer_stats_with_likes():
    # 1 张心动 c01（不戴眼镜/瓜子脸/文艺/温柔），无 last_intent → 4 维都 100% 命中
    ip.track_behavior({"candidateId": "c01", "type": "like"})
    r = ip.infer()
    assert r["source"] == "stats"
    assert r["has_enough"] is True
    assert r["liked_count"] == 1
    assert r["fields"]  # 至少一个隐性维度
    # _INTENT_FIELDS 顺序第一个是 glasses，ratio 1.0 排最前
    assert r["fields"][0]["field"] == "glasses"


# ===== suggest =====

def test_suggest_not_enough_guidance():
    s = ip.suggest({"has_enough": False, "source": "none"})
    assert s["title"] == "再多看看几张卡片"
    assert "♡" in s["body"]


def test_suggest_with_field_template():
    pref = {"has_enough": True, "liked_count": 3, "source": "stats",
            "fields": [{"field": "vibe", "value": "高冷", "ratio": 1.0}]}
    ip.set_last_intent({"vibe": "温柔"})  # 嘴上说温柔
    s = ip.suggest(pref)
    assert "高冷" in s["body"]
    assert s["fields"] == pref["fields"]
