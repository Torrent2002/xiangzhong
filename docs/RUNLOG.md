# 运行实录 · RUNLOG

> 以下为**无 API key、本地兜底模式**下的真实运行记录，证明两条链路均可跑通。
> 配置 key 后显性解析 / 语义打分 / 隐性反推会走真实 LLM，体验更佳（无 key 也能完整运行）。

环境：Python 3.13 · fastapi 0.139 · 无 OPENAI_API_KEY · 模式角标「本地兜底模式」

---

## 1. 显性偏好链路：自然语言 → 意图解析 → 候选匹配 → 透明化理由

**请求**
```
POST /api/explicit/match
{"text": "温柔、不戴眼镜、瓜子脸、文艺风"}
```

**返回（节选）**
```json
{
  "intent": {
    "glasses": false, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔",
    "source": "fallback"
  },
  "mode": "本地兜底模式",
  "matches": [
    { "candidate": { "id": "c01", "name": "林同学", "attributes": { "glasses": false, "faceShape": "瓜子脸", "style": "文艺", "vibe": "温柔" } },
      "score": 1.0, "hits": ["glasses","faceShape","style","vibe"], "diffs": [],
      "reasons": ["命中你的描述：不戴眼镜、瓜子脸、文艺、温柔 ✓", "简介：一个安静、喜欢看展和旧书店的女生。"] },
    { "candidate": { "id": "c06", "name": "赵同学", "attributes": { "glasses": false, "faceShape": "鹅蛋脸", "style": "文艺", "vibe": "温柔" } },
      "score": 0.75, "hits": ["glasses","style","vibe"], "diffs": ["faceShape"],
      "reasons": ["命中你的描述：不戴眼镜、文艺、温柔 ✓",
                  "唯一差异：你要「瓜子脸」，赵同学是「鹅蛋脸」。",
                  "简介：写诗、养猫、雨天最开心。"] },
    { "candidate": { "id": "c11", "name": "蒋同学", "attributes": { "faceShape": "圆脸" } },
      "score": 0.75, "diffs": ["faceShape"],
      "reasons": ["命中你的描述：不戴眼镜、文艺、温柔 ✓",
                  "唯一差异：你要「瓜子脸」，蒋同学是「圆脸」。"] }
  ]
}
```

**要点**：c01 全中排第一（1.0 分）；c06/c11 命中 3/4（0.75 分），透明化标出"唯一差异：脸型"。

---

## 2. 隐性偏好链路：行为采集 → 反推 → 主动提示

先采集行为（♡ 6 张卡片，其中 c04 / c07 / c12 是方脸）：
```
POST /api/implicit/track  {"candidateId":"c04","action":"like"}  → {"count":5}
POST /api/implicit/track  {"candidateId":"c12","action":"like"}  → {"count":6}
```

关键一步：显性描述**只提部分字段**（`温柔、不戴眼镜`，把 faceShape 留空），让隐性有发现空间——
```
POST /api/explicit/match  {"text":"温柔、不戴眼镜"}
→ intent: {"glasses":false, "faceShape":null, "style":null, "vibe":"温柔"}
```

再反推：
```
GET /api/implicit/suggest
```

**返回**
```json
{
  "preference": {
    "fields": [{ "field": "faceShape", "value": "方脸", "ratio": 0.5, "sample_count": 3, "total": 6 }],
    "summary_text": "在你心动的 6 张卡片里，脸型=「方脸」占 50%",
    "has_enough": true, "liked_count": 6, "source": "stats"
  },
  "suggestion": {
    "title": "AI 发现了一个苗头",
    "body": "你嘴上没特别提，但你最近 ♡ 的更多是脸型=「方脸」（占 50%）——要不要看看这类？这可能是你「自己没发现的喜欢」。",
    "source": "stats"
  },
  "mode": "本地兜底模式"
}
```

**要点**：用户嘴上没提脸型，但行为暴露出偏好方脸——AI 主动发现并提示。这正是「隐性偏好」的核心卖点。

> 设计细节：显性提过的字段不再作为隐性发现对象（避免重复），所以演示时显性描述要留 1-2 个维度不提，才能触发隐性反推。详见 `docs/architecture.md`。

---

## 3. AI 模式（配 key · deepseek-chat）

配置 `OPENAI_API_KEY` + `OPENAI_BASE_URL=https://api.deepseek.com` + `MODEL=deepseek-chat` 后，角标变「AI 模式」，连测 3 次稳定走真 LLM：

```
GET /api/status → {"mode":"AI 模式","model":"deepseek-chat","available":true}

POST /api/explicit/match {"text":"温柔、不戴眼镜、瓜子脸、文艺风"}  （连测 3 次）
  #1 intent.source=ai | top=林同学 | score=0.96 | score_source=ai_blend
  #2 intent.source=ai | top=林同学 | score=0.92 | score_source=ai_blend
  #3 intent.source=ai | top=林同学 | score=0.96 | score_source=ai_blend
```

**对比兜底模式**：意图解析从关键词匹配升级为 LLM 语义理解；匹配分从纯结构化（1.0）变为 AI 语义分 + 结构化加权（ai_blend，0.9x）；推荐理由从模板变为 LLM 自然语言。

> 选型说明：`deepseek-v4-flash` 间歇性返回空 content（导致偶发降级到兜底），已换 `deepseek-chat`（稳定）。DeepSeek 不提供 embedding 端点，显性语义分走 LLM 打分路径（非向量），失败时仍降级结构化打分。
