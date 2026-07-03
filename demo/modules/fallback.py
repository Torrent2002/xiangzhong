"""本地兜底逻辑：无 key / AI 失败时的全部本地实现。

显性链路：
  parse_intent(text)   关键词字典 → 结构化意图
  match_score(intent, candidate)  结构化打分（命中/字段数）
  semantic_reason(...)  模板"为什么推荐"理由
隐性链路：
  infer_from_log(log, candidates_by_id, intent)  统计 ♡ 过的 candidate 的属性分布
  suggest_template(...)  模板提示卡

需求文档 §3.1（兜底路）/ §3.2（统计路）的落地。
不 import ai_client（它只管真实调用，兜底完全离线）。
"""

import re
from typing import Any

# ---- 字典：关键词 → 属性值 ----
# 显式覆盖"不戴眼镜 / 戴眼镜"，避免"戴眼镜"误命中"不戴眼镜"的子串。
GLASSES_TRUE = ["戴眼镜", "戴眼镜的", "眼镜男", "眼镜妹", "斯文眼镜"]
GLASSES_FALSE = ["不戴眼镜", "不带眼镜", "没戴眼镜", "没带眼镜", "不近视"]

FACE_SHAPES = ["瓜子脸", "鹅蛋脸", "圆脸", "方脸"]
STYLES = ["文艺", "运动", "商务", "街头", "极简"]
VIBES = ["温柔", "活泼", "高冷", "阳光", "知性"]

# 同义扩展（用户口语 → 标准值）
STYLE_ALIASES = {
    "文艺范": "文艺", "文艺风": "文艺", "书卷气": "文艺",
    "运动风": "运动", "运动范": "运动", "阳光运动": "运动",
    "商务风": "商务", "正装": "商务",
    "街头风": "街头", "嘻哈": "街头", "潮": "街头",
    "极简风": "极简", "简约": "极简", "性冷淡": "极简",
}
VIBE_ALIASES = {
    "温婉": "温柔", "软萌": "温柔", "暖暖的": "温柔",
    "外向": "活泼", "开朗": "活泼", "话多": "活泼",
    "冷淡": "高冷", "酷": "高冷", "高冷范": "高冷", "疏离": "高冷",
    "暖男": "阳光", "少年感": "阳光", "阳光开朗": "阳光",
    "聪明": "知性", "学识": "知性", "学霸": "知性", "理性": "知性",
}


def _has(text: str, kws: list[str]) -> bool:
    return any(k in text for k in kws)


def parse_intent(text: str) -> dict:
    """关键词字典匹配 → {glasses, faceShape, style, vibe}，未提及字段为 None。

    与显性链路 parse_intent 的契约一致：未提及即 None（不是 False）。
    glasses：提到"不戴眼镜"→False；提到"戴眼镜"→True；都没提→None。
    """
    if not text:
        return {"glasses": None, "faceShape": None, "style": None, "vibe": None}

    t = text.strip()

    # glasses：先判"不戴"（更具体），否则判"戴"。
    glasses: bool | None = None
    if _has(t, GLASSES_FALSE):
        glasses = False
    elif _has(t, GLASSES_TRUE):
        glasses = True

    # faceShape
    face_shape: str | None = None
    for fs in FACE_SHAPES:
        if fs in t:
            face_shape = fs
            break

    # style（含别名）
    style: str | None = None
    for alias, std in STYLE_ALIASES.items():
        if alias in t:
            style = std
            break
    if style is None:
        for s in STYLES:
            if s in t:
                style = s
                break

    # vibe（含别名）
    vibe: str | None = None
    for alias, std in VIBE_ALIASES.items():
        if alias in t:
            vibe = std
            break
    if vibe is None:
        for v in VIBES:
            if v in t:
                vibe = v
                break

    return {"glasses": glasses, "faceShape": face_shape, "style": style, "vibe": vibe}


# 用于 intent 非空字段顺序（"唯一差异"取第一个）
_INTENT_FIELDS = ["glasses", "faceShape", "style", "vibe"]

_FIELD_LABELS = {
    "glasses": "戴眼镜",
    "faceShape": "脸型",
    "style": "风格",
    "vibe": "气质",
}


def intent_fields(intent: dict) -> list[str]:
    """返回 intent 中非 None 的字段名，按固定顺序。"""
    return [f for f in _INTENT_FIELDS if intent.get(f) is not None]


def match_score(intent: dict, candidate: dict) -> tuple[float, list[str], list[str]]:
    """结构化打分。

    返回 (score ∈ [0,1], 命中字段列表, 差异字段列表)。
    score = 命中数 / 非空字段数；无非空字段时返回 0.0（避免除零）。
    """
    attr = candidate.get("attributes", {}) or {}
    hits: list[str] = []
    diffs: list[str] = []
    nonzero = intent_fields(intent)
    for f in nonzero:
        want = intent.get(f)
        got = attr.get(f)
        if f == "glasses":
            got_bool = bool(got)
            if want is got_bool or want == got_bool:
                hits.append(f)
            else:
                diffs.append(f)
        else:
            if want == got:
                hits.append(f)
            else:
                diffs.append(f)
    score = (len(hits) / len(nonzero)) if nonzero else 0.0
    return score, hits, diffs


def _label(field: str, value: Any) -> str:
    if field == "glasses":
        return "戴眼镜" if value else "不戴眼镜"
    return str(value)


def why_reasons(intent: dict, candidate: dict, hits: list[str], diffs: list[str], top: int = 3) -> list[str]:
    """兜底"为什么推荐"理由模板。

    命中维度列 ✓ + 取第一个差异项写"唯一差异：…"。
    """
    attr = candidate.get("attributes", {}) or {}
    reasons: list[str] = []
    if hits:
        hit_txt = "、".join(_label(f, intent.get(f)) for f in hits)
        reasons.append(f"命中你的描述：{hit_txt} ✓")
    else:
        reasons.append("未完全命中你描述的维度，但整体气质相近。")
    if diffs:
        first = diffs[0]
        reasons.append(
            f"唯一差异：你要「{_label(first, intent.get(first))}」，"
            f"{candidate.get('name', 'TA')} 是「{_label(first, attr.get(first))}」。"
        )
    # 兜底补充一句自然语言（基于 bio），让"为什么推荐"更有人味。
    bio = candidate.get("bio")
    if bio:
        reasons.append(f"简介：{bio}")
    # 截断
    return reasons[:top]


def infer_from_log(
    log: list[dict],
    candidates_by_id: dict[str, dict],
    intent: dict | None = None,
) -> dict:
    """统计路：从 ♡ 过的 candidate 反推隐性偏好。

    找出"用户描述里没提、但 ♡ 占比明显高"的维度值。
    阈值：某值在 ♡ 集合中占比 ≥ 0.5，且该维度在 intent 中未提及（None）。
    返回 {fields: [{field, value, ratio, sample_count}], summary_text, has_enough}。
    无 ♡ 数据时 has_enough=False。
    """
    likes = [e for e in log if e.get("type") == "like" or e.get("action") == "like"]
    liked_candidates = [
        candidates_by_id[e["candidateId"]]
        for e in likes
        if e.get("candidateId") in candidates_by_id
    ]
    if not liked_candidates:
        return {
            "fields": [],
            "summary_text": "暂无足够心动数据",
            "has_enough": False,
            "liked_count": 0,
        }

    intent = intent or {}
    n = len(liked_candidates)
    findings: list[dict] = []
    for f in _INTENT_FIELDS:
        if intent.get(f) is not None:
            continue  # 用户已明确提及，不算"隐性"
        counts: dict[Any, int] = {}
        for c in liked_candidates:
            val = (c.get("attributes") or {}).get(f)
            if val is None:
                continue
            counts[val] = counts.get(val, 0) + 1
        if not counts:
            continue
        best_val, best_cnt = max(counts.items(), key=lambda kv: kv[1])
        ratio = best_cnt / n
        if ratio >= 0.5:
            findings.append({
                "field": f,
                "value": best_val,
                "ratio": round(ratio, 2),
                "sample_count": best_cnt,
                "total": n,
            })

    # 选最强的那个做提示卡主轴
    findings.sort(key=lambda x: x["ratio"], reverse=True)
    if findings:
        top = findings[0]
        summary = f"在你心动的 {n} 张卡片里，{_FIELD_LABELS[top['field']]}=「{_label(top['field'], top['value'])}」占 {int(top['ratio']*100)}%"
    else:
        summary = f"你心动了 {n} 张卡片，但还没有形成明显的隐性偏好倾向"

    return {
        "fields": findings,
        "summary_text": summary,
        "has_enough": True,
        "liked_count": n,
    }


def suggest_template(infer_result: dict, intent: dict | None = None) -> dict:
    """兜底提示卡模板：把反推偏好与显性 intent 的"差异"拼成自然语言。"""
    if not infer_result.get("has_enough"):
        return {
            "title": "再多看看几张卡片",
            "body": "你还没有点过 ♡，AI 暂时发现不了你的隐性偏好。多心动几张，我再来告诉你「你可能其实喜欢…」。",
            "fields": [],
        }

    intent = intent or {}
    fields = infer_result.get("fields", [])
    if not fields:
        # 有 ♡ 但无明显倾向
        return {
            "title": "偏好还不够清晰",
            "body": f"你心动了 {infer_result.get('liked_count', 0)} 张卡片，但目前还没形成压倒性的偏好。再心动几张，让 AI 更确定。",
            "fields": [],
        }

    top = fields[0]
    said = intent.get(top["field"])
    if said is None:
        said_txt = "你嘴上没特别提"
    else:
        said_txt = f"你嘴上说喜欢「{_label(top['field'], said)}」"
    body = (
        f"{said_txt}，但你最近 ♡ 的更多是"
        f"{_FIELD_LABELS[top['field']]}=「{_label(top['field'], top['value'])}」"
        f"（占 {int(top['ratio']*100)}%）——"
        f"要不要看看这类？这可能是你「自己没发现的喜欢」。"
    )
    return {
        "title": "AI 发现了一个苗头",
        "body": body,
        "fields": fields,
    }
