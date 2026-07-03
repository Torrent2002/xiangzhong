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

## 3. AI 模式（配 key · doubao-seed-2.0-pro，文本 + vision 同一多模态模型）

配置 `OPENAI_API_KEY` + `OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3` + `MODEL=doubao-seed-2.0-pro` + `VISION_MODEL=doubao-seed-2.0-pro`。角标变「AI 模式」。doubao-seed-2.0-pro 是多模态，文本意图解析 + 照片识别用同一套配置。

### 文本链路
```
POST /api/explicit/match {"text":"温柔、不戴眼镜、瓜子脸、文艺风"}
→ intent.source=ai | top=林同学 | score=1.0 | score_source=structured
```
意图解析走 LLM（source=ai）；匹配用结构化打分（命中字段 / 非空字段）。

### 照片分析链路（参考图通道）
上传一张圆脸、不戴眼镜、笑容的测试图：
```
POST /api/explicit/match_image {"image":"<base64>"}
耗时 39.4s | status:200 | source:ai | mode:AI 模式
intent: {glasses:false, faceShape:"圆脸", style:null, vibe:"温柔"}
  蒋同学 score=1.0 src=structured | 命中你的描述：不戴眼镜、圆脸、温柔 ✓
  林同学 score=0.667 | 命中你的描述：不戴眼镜、温柔 ✓
```
vision 真识别出圆脸 / 不戴眼镜 / 温柔，匹配透明化命中。`style=null`（测试图无穿搭，vision 诚实返 null 不瞎猜）。

> 工程取舍：
> - **match 去掉逐候选 LLM 语义打分**：原对 12 个候选各调一次 LLM 语义分（~70s，且 sem_score 常返固定值不可靠），改纯结构化打分（速度优先，意图解析仍走 AI）。
> - **vision 不经 openai SDK 同步 client**：其在 uvicorn 线程池里对图片调用会卡死（async def + 同步阻塞 + timeout 不生效），改用 httpx 直接请求豆包端点，超时严格生效。
> - **选型**：deepseek-chat 不支持图片；doubao-seed-2.0-pro 多模态，文本 + vision 都可用，已实测（deepseek-v4-flash 间歇性返空 content 已弃用）。
