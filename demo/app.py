"""相中 demo —— 后端入口（FastAPI）。

路由就位、处理函数仅委托 modules/*，不持业务逻辑（web 层 / 控制器）。
启动：python app.py → http://localhost:8000

两条链路：
  显性：POST /api/explicit/match {text} → {intent, matches, mode}
  隐性：POST /api/implicit/track {candidateId, action, dwellMs}
        GET  /api/implicit/suggest → {preference, suggestion, mode}
模式标识：GET /api/status → {mode, available, ...}
"""

import sys
from pathlib import Path

# 保证任意 cwd 下都能 import modules（不依赖启动目录）。
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

STATIC_DIR = BASE_DIR / "static"
AVATAR_DIR = BASE_DIR / "avatars"

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from typing import Any
from modules import ai_client, explicit_preference, implicit_preference, candidate_store

# 铁律#1 不崩：静态 / 头像目录缺失时先建空目录，避免 StaticFiles 挂载抛错。
STATIC_DIR.mkdir(exist_ok=True)
AVATAR_DIR.mkdir(exist_ok=True)

app = FastAPI(title="相中 demo")
candidate_store.load()  # 冷加载：启动读 candidates.json 为已预计算索引

# 静态资源挂载（前端不持有 key，资源全本地，无 CDN）。
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/avatars", StaticFiles(directory=str(AVATAR_DIR)), name="avatars")


@app.get("/")
def index():
    """手机框页面。"""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status")
def status():
    """当前 AI 模式 / 本地兜底模式（前端角落角标用）。"""
    return ai_client.status()


# ===== 显性偏好链路 =====
@app.post("/api/explicit/match")
async def explicit_match(request: Request):
    """自然语言 → 意图 → 排序候选 + "为什么推荐"。"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    text = (data or {}).get("text", "")
    intent = await run_in_threadpool(explicit_preference.parse_intent, text)
    # 回写最近 intent，供隐性 suggest 做"嘴上说 X"对照。
    implicit_preference.set_last_intent(intent)
    matches = await run_in_threadpool(explicit_preference.match, intent)
    return {
        "intent": intent,
        "matches": matches,
        "mode": ai_client.status()["mode"],
    }


class ImageBody(BaseModel):
    image: str = ""


@app.post("/api/explicit/match_image")
def explicit_match_image(body: ImageBody):
    """参考照片 → 意图（vision）→ 和库里已预计算的候选 attributes 结构化匹配 + 兜底 feed。

    架构：候选 attributes 是创建时异步预计算的（candidate_store），查询只做轻量结构化匹配（低延时）。
    多级兜底：pending/failed 候选 → fallback_feed；vision 失效（source=none）→ 全候选作兜底 feed。
    """
    intent = explicit_preference.parse_intent_from_image(body.image)
    if intent.get("source") == "ai":
        implicit_preference.set_last_intent(intent)
    if intent.get("source") == "none":
        results, fallback_pool = [], candidate_store.all_candidates()
    else:
        results, fallback_pool = candidate_store.match(intent)
    matches = results[:3]
    fallback_feed = [
        {"candidate": c, "score": 0.0, "analysis_status": c.get("analysis_status"), "fallback": True}
        for c in fallback_pool
    ]
    return {
        "intent": intent,
        "matches": matches,
        "fallback_feed": fallback_feed,
        "mode": ai_client.status()["mode"],
        "vision_available": ai_client.is_vision_available(),
    }


@app.get("/api/candidate/{cid}")
def candidate_detail(cid: str):
    """单个候选详情：只返回基本信息 + 匹配度 + 分析状态。

    刻意不返回 AI 标定的 attributes（glasses/faceShape/style/vibe）和详细匹配理由：
    看一个人详情时不暴露 AI 给 ta 打的标签（避免物化），只看 ta 是谁 + 和你多匹配。
    """
    cand = candidate_store.get(cid)
    if cand is None:
        return {"ok": False, "error": "not_found", "id": cid}
    last_intent = implicit_preference.get_last_intent()
    match_score = candidate_store.match_score_for(cid, last_intent) if last_intent else None
    return {
        "ok": True,
        "candidate": {
            "id": cand.get("id"),
            "name": cand.get("name"),
            "age": cand.get("age"),
            "city": cand.get("city"),
            "bio": cand.get("bio"),
            "photo": cand.get("photo"),
        },
        "match_score": match_score,
        "analysis_status": cand.get("analysis_status"),
        "has_intent": last_intent is not None,
    }


class CreateBody(BaseModel):
    name: str = ""
    age: Any = None
    city: str = ""
    bio: str = ""
    photo: str = ""  # base64，不带 data: 前缀


@app.post("/api/candidate/create")
async def create_candidate(body: CreateBody):
    """注册自己成为候选人 → 立即返回成功 → 后台异步 vision 分析照片（预计算 attributes）。

    架构（传统 C 端思想）：写入即时反馈，分析异步（模拟消息队列），不阻塞注册。
    后台 _analyze 用 asyncio.to_thread 跑同步 vision，不阻塞 event loop。
    """
    cand = candidate_store.create(body.name, body.age, body.city, body.photo, body.bio)
    return {
        "ok": True,
        "id": cand["id"],
        "status": "created",
        "msg": "注册成功，AI 正在分析你的照片",
        "analysis_status": cand["analysis_status"],
    }


# ===== 隐性偏好链路 =====
@app.post("/api/implicit/track")
async def implicit_track(request: Request):
    """记录一次行为事件（like / pass / dwell）。

    body 兼容 {candidateId, action, dwellMs} 与旧字段 {type, durationMs}。
    """
    try:
        event = await request.json()
    except Exception:
        event = {}
    event = event or {}
    # 归一化：action 优先，否则用 type
    action = event.get("action") or event.get("type")
    dwell = event.get("dwellMs") or event.get("durationMs")
    norm = {
        "candidateId": event.get("candidateId"),
        "action": action,
        "type": action,  # 内部统计仍用 type
        "dwellMs": dwell,
        "durationMs": dwell,
        "ts": event.get("ts"),
    }
    return implicit_preference.track_behavior(norm)


@app.get("/api/implicit/suggest")
async def implicit_suggest():
    """反推隐性偏好 → 主动提示卡。"""
    preference = implicit_preference.infer()
    suggestion = implicit_preference.suggest(preference)
    return {
        "preference": preference,
        "suggestion": suggestion,
        "mode": ai_client.status()["mode"],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
