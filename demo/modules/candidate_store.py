"""候选人内存存储 —— 照片分析改线下异步预计算架构。

写入路径：create() 立即返回 → 后台 asyncio.create_task 跑 vision 分析 → 回填 attributes。
查询路径：match(intent) 与已预计算 attributes 做结构化匹配（fallback.match_score），无逐候选 LLM。
多级兜底：① attributes=None（pending/failed）→ fallback_pool ② 属性匹配空 → 调用方 feed ③ vision 失效 → 全兜底。
冷加载：load() 读 candidates.json，attributes 已有 → status=precomputed。
"""

import asyncio
import time
from typing import Any

from modules import explicit_preference, fallback

_candidates: list[dict] = []
_by_id: dict[str, dict] = {}
_loaded: bool = False
_tasks: set = set()  # 持有后台 task 引用，避免被 GC 回收导致不执行


def load() -> None:
    global _candidates, _by_id, _loaded
    if _loaded:
        return
    raw = explicit_preference.load_candidates()
    for c in raw:
        c.setdefault("analysis_status", "precomputed")
    _candidates = raw
    _by_id = {c["id"]: c for c in _candidates}
    _loaded = True


def all_candidates() -> list[dict]:
    load()
    return list(_candidates)


def get(cid: str) -> dict | None:
    load()
    return _by_id.get((cid or "").strip())


def _new_id() -> str:
    return "u" + str(int(time.time() * 1000))


def create(name: str, age: Any, city: str, photo_b64: str) -> dict:
    load()
    cid = _new_id()
    cand: dict = {
        "id": cid,
        "name": (name or "").strip() or "新候选人",
        "age": age,
        "city": (city or "").strip(),
        "photo": "avatars/c01.svg",  # 占位头像（新建候选无成品头像）
        "attributes": None,
        "analysis_status": "pending",
        "bio": "",
    }
    _candidates.append(cand)
    _by_id[cid] = cand
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_analyze(cid, photo_b64 or ""))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        cand["analysis_status"] = "failed"
    return cand


async def _analyze(cid: str, photo_b64: str) -> None:
    """后台 vision 分析（模拟消息队列消费）。用 to_thread 隔离同步调用，不阻塞 event loop。"""
    cand = _by_id.get(cid)
    if cand is None:
        return
    try:
        intent = await asyncio.to_thread(
            explicit_preference.parse_intent_from_image, photo_b64
        )
    except Exception:
        intent = {"source": "none"}
    if cand.get("analysis_status") != "pending":
        return
    if intent.get("source") == "ai":
        cand["attributes"] = {
            "glasses": intent.get("glasses"),
            "faceShape": intent.get("faceShape"),
            "style": intent.get("style"),
            "vibe": intent.get("vibe"),
        }
        cand["analysis_status"] = "analyzed"
    else:
        cand["analysis_status"] = "failed"


def match(intent: dict) -> tuple[list[dict], list[dict]]:
    """查询匹配：attributes 非空的候选结构化打分；pending/failed 进 fallback_pool。"""
    load()
    intent = intent or {}
    results: list[dict] = []
    fallback_pool: list[dict] = []
    for c in _candidates:
        attr = c.get("attributes")
        if attr:
            try:
                score, hits, diffs = fallback.match_score(intent, c)
            except Exception:
                fallback_pool.append(c)
                continue
            reasons = fallback.why_reasons(intent, c, hits, diffs)
            results.append({
                "candidate": c,
                "score": round(score, 3),
                "hits": hits,
                "diffs": diffs,
                "reasons": reasons,
                "analysis_status": c.get("analysis_status", "precomputed"),
            })
        else:
            fallback_pool.append(c)
    results.sort(key=lambda x: (x["score"], len(x["hits"])), reverse=True)
    return results, fallback_pool


def match_score_for(cid: str, intent: dict) -> float | None:
    """详情页匹配度：基于 last_intent 算单个候选的 score。"""
    load()
    cand = _by_id.get((cid or "").strip())
    if cand is None or not cand.get("attributes"):
        return None
    try:
        score, _h, _d = fallback.match_score(intent or {}, cand)
    except Exception:
        return None
    return round(score, 3)
