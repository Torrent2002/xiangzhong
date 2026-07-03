"""隐性偏好链路：行为信号 → 偏好反推 → 主动提示。

高聚合：本模块只负责隐性偏好的采集、反推与提示。
低耦合：只依赖 ai_client（真实 LLM）与 fallback（统计路）；不依赖 explicit_preference；
       持有内存行为日志，不持久化（符合需求 §6 克制）。

需求文档 §3.2 双路实现：
  track_behavior: append 到内存 list（真实动作）
  infer: 统计路（♡ 占比明显高的隐性维度）/ AI 路（LLM 推断 + 可解释理由）
  suggest: 生成"嘴上说 X，实际 Y"提示卡；AI 路 LLM 写自然，兜底用模板
"""

import json
import time
from typing import Any

from modules import ai_client, fallback

# 内存行为日志（仅本次进程生命周期有效，重启即清空，不做数据库持久化）。
_behavior_log: list[dict] = []

# 最近一次显性 intent（由 app 层在显性匹配后回写，供 suggest 做"差异"对照）。
_last_intent: dict | None = None

# candidate id → candidate 缓存（首次 infer 时从 explicit 模块读，避免循环依赖）。
_candidates_cache: list[dict] | None = None


def _candidates_by_id() -> dict[str, dict]:
    global _candidates_cache
    if _candidates_cache is None:
        # 延迟 import explicit_preference 仅为读静态数据；不构成业务耦合（无回调用其解析/匹配）。
        from modules import explicit_preference
        _candidates_cache = explicit_preference.load_candidates()
    return {c["id"]: c for c in _candidates_cache}


def track_behavior(event: dict) -> dict:
    """记录一次行为事件（like / pass / dwell）。

    真实动作：append 到内存 list，归一化字段。
    """
    e = dict(event or {})
    # 兼容字段：type/action 二选一；candidateId；durationMs/dwellMs。
    action = e.get("type") or e.get("action") or ""
    if action == "dwell":
        # 停留事件阈值在 §3.2：≥1.5s 才上报，这里仍记录原始值。
        pass
    e.setdefault("ts", time.time())
    _behavior_log.append(e)
    return {"ok": True, "logged": True, "count": len(_behavior_log)}


def get_log() -> list[dict]:
    """返回当前行为日志副本（供 infer 与调试用）。"""
    return list(_behavior_log)


def set_last_intent(intent: dict | None) -> None:
    """app 层在显性匹配后回写最近 intent，供 suggest 做"嘴上说 X"对照。"""
    global _last_intent
    _last_intent = intent


def get_last_intent() -> dict | None:
    return _last_intent


def _likes_in_log(log: list[dict]) -> list[dict]:
    return [e for e in log if e.get("type") == "like" or e.get("action") == "like"]


# ===== infer =====

_SYSTEM_INFER_PROMPT = (
    "你是相亲平台的隐性偏好分析师。根据用户的心动（♡）行为记录，"
    "推断「用户可能未自意识到的偏好」——即用户嘴上没明确说、但实际心动中占比明显高的属性。"
    "可用维度：glasses(bool)、faceShape(瓜子脸/鹅蛋脸/圆脸/方脸)、"
    "style(文艺/运动/商务/街头/极简)、vibe(温柔/活泼/高冷/阳光/知性)。\n"
    "只返回纯 JSON：{\"fields\":[{\"field\":\"vibe\",\"value\":\"高冷\",\"reason\":\"你嘴上没提高冷，但心动的4张里有3张是高冷\"}],\"summary\":\"一句话总结\", \"confidence\":0.0~1.0}。"
    "只挑最显著的 1 个字段即可。"
)


def _infer_ai(log: list[dict]) -> dict | None:
    """AI 路：把行为摘要喂 LLM，推断隐性偏好 + 可解释理由。失败返回 None。"""
    if not ai_client.is_available():
        return None
    by_id = _candidates_by_id()
    likes = _likes_in_log(log)
    liked = [
        {
            "name": by_id[e["candidateId"]].get("name"),
            "attributes": by_id[e["candidateId"]].get("attributes"),
            "bio": by_id[e["candidateId"]].get("bio"),
        }
        for e in likes if e.get("candidateId") in by_id
    ]
    if not liked:
        return None
    intent_desc = _last_intent or {}
    user_msg = (
        f"用户显性描述（嘴上说的）：{json.dumps(intent_desc, ensure_ascii=False) or '无'}\n"
        f"用户最近心动的候选人列表：{json.dumps(liked, ensure_ascii=False)}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_INFER_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    out = ai_client.call_llm(messages, json_mode=True, fallback=None)
    if not out:
        return None
    raw = out.strip().strip("`")
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    fields = data.get("fields") or []
    if not fields:
        return None
    return {
        "fields": fields,
        "summary_text": data.get("summary") or "",
        "has_enough": True,
        "liked_count": len(liked),
        "source": "ai",
        "confidence": data.get("confidence"),
    }


def infer(log: list[dict] | None = None) -> dict:
    """从行为日志反推隐性偏好向量。

    优先 AI 路；不可用/失败走统计路。无 ♡ 数据返回 has_enough=False。
    """
    log = log if log is not None else _behavior_log
    likes = _likes_in_log(log)
    if not likes:
        return {
            "fields": [],
            "summary_text": "暂无足够心动数据",
            "has_enough": False,
            "liked_count": 0,
            "source": "none",
        }
    # 先试 AI
    ai_result = _infer_ai(log)
    if ai_result is not None:
        return ai_result
    # 兜底统计路
    by_id = _candidates_by_id()
    result = fallback.infer_from_log(log, by_id, _last_intent)
    result["source"] = "stats"
    return result


# ===== suggest =====

_SYSTEM_SUGGEST_PROMPT = (
    "你是相亲平台的提示卡文案写手。基于用户显性描述（嘴上说的）与反推的隐性偏好（实际心动的），"
    "写一句自然、有洞察的提示文案，体现「嘴上说 X，实际心动更多是 Y」。语气温暖、像朋友点醒。"
    "只返回纯 JSON：{\"title\":\"≤10字标题\",\"body\":\"≤60字正文\"}。"
)


def _suggest_ai(preference: dict, intent: dict | None) -> dict | None:
    """AI 路：让 LLM 写自然提示卡。失败返回 None。"""
    if not ai_client.is_available():
        return None
    fields = preference.get("fields") or []
    if not fields:
        return None
    user_msg = (
        f"用户显性描述（嘴上说的）：{json.dumps(intent or {}, ensure_ascii=False) or '无'}\n"
        f"反推的隐性偏好（实际心动的）：{json.dumps(preference, ensure_ascii=False)}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_SUGGEST_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    out = ai_client.call_llm(messages, json_mode=True, fallback=None)
    if not out:
        return None
    raw = out.strip().strip("`")
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    title = data.get("title")
    body = data.get("body")
    if not title or not body:
        return None
    return {"title": title, "body": body, "fields": fields, "source": "ai"}


def suggest(preference: dict | None = None) -> dict:
    """根据反推偏好生成主动提示卡。

    AI 路：LLM 写自然；失败走兜底模板。
    无 ♡ 数据返回引导语。
    """
    preference = preference or {}
    if not preference.get("has_enough"):
        return {
            "title": "再多看看几张卡片",
            "body": "你还没有点过 ♡，AI 暂时发现不了你的隐性偏好。多心动几张，我再来告诉你「你可能其实喜欢…」。",
            "fields": [],
            "source": preference.get("source", "none"),
        }
    # 先试 AI
    ai_sug = _suggest_ai(preference, _last_intent)
    if ai_sug is not None:
        return ai_sug
    # 兜底模板
    tpl = fallback.suggest_template(preference, _last_intent)
    tpl["source"] = preference.get("source", "stats")
    return tpl
