"""candidate_store 模块：候选人内存索引 + 异步预计算架构。

冷加载 12 个预计算候选；create 即写、后台 vision 异步预计算 attributes；
查询走结构化匹配 + 多级兜底（pending/failed 进 fallback_pool）。
conftest autouse 已逐测试复位到 candidates.json 原态。
"""
import asyncio

from modules import candidate_store as cs


# ===== 冷加载 / 查询 =====

def test_load_12_precomputed():
    allc = cs.all_candidates()
    assert len(allc) == 12
    assert all(c.get("analysis_status") == "precomputed" for c in allc)


def test_get_existing_and_missing():
    c = cs.get("c01")
    assert c is not None and c["name"] == "林同学"
    assert cs.get("does-not-exist") is None
    assert cs.get(None) is None


# ===== match（查询路径）=====

def test_match_precomputed_no_fallback_pool():
    intent = {"glasses": False, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔"}
    results, pool = cs.match(intent)
    # 全部候选有 attributes → fallback_pool 空
    assert pool == []
    assert len(results) == 12
    assert results[0]["candidate"]["id"] == "c01"  # 全中排第一
    assert results[0]["score"] == 1.0
    assert results[0]["analysis_status"] == "precomputed"
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_match_score_for_single():
    # c01 全中 → 1.0；c02 戴眼镜/极简：要 不戴眼镜+文艺 全差 → 0.0
    assert cs.match_score_for("c01", {"glasses": False, "style": "文艺"}) == 1.0
    assert cs.match_score_for("c02", {"glasses": False, "style": "文艺"}) == 0.0
    # intent 空（无非空字段）→ 0.0
    assert cs.match_score_for("c01", {}) == 0.0
    # 不存在 → None
    assert cs.match_score_for("zzz", {"glasses": False}) is None


# ===== create（写入路径）=====

def test_create_no_running_loop_marks_failed():
    # 同步测试无 event loop → create 走 except → status=failed
    cand = cs.create("测试用户", 28, "上海", "fakephoto", "一句介绍")
    assert cand["id"].startswith("u")
    assert cand["name"] == "测试用户"
    assert cand["bio"] == "一句介绍"
    assert cand["attributes"] is None
    assert cand["analysis_status"] == "failed"
    assert cs.get(cand["id"]) is not None  # 已入池


def test_create_with_loop_then_async_analyze_fails():
    # 兜底模式 vision 不可用 → 后台 _analyze 把 pending 置 failed
    async def go():
        cand = cs.create("异步用户", 30, "北京", "fakephoto", "")
        await asyncio.sleep(0.1)  # 让后台 task 跑完
        return cand

    cand = asyncio.run(go())
    assert cand["id"].startswith("u")
    assert cand["analysis_status"] == "failed"
    assert cand["attributes"] is None
