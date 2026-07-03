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
from fastapi.staticfiles import StaticFiles

from modules import ai_client, explicit_preference, implicit_preference

# 铁律#1 不崩：静态 / 头像目录缺失时先建空目录，避免 StaticFiles 挂载抛错。
STATIC_DIR.mkdir(exist_ok=True)
AVATAR_DIR.mkdir(exist_ok=True)

app = FastAPI(title="相中 demo")

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
    intent = explicit_preference.parse_intent(text)
    # 回写最近 intent，供隐性 suggest 做"嘴上说 X"对照。
    implicit_preference.set_last_intent(intent)
    matches = explicit_preference.match(intent)
    return {
        "intent": intent,
        "matches": matches,
        "mode": ai_client.status()["mode"],
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
