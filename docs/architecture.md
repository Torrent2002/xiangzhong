# 架构 · Architecture

> demo 的工程架构与模块说明。设计取舍见 [`../THINKING.md`](./THINKING.md) §4，本文聚焦实现层。

## 总览

```
┌──────────────────────── 浏览器（手机框 UI） ────────────────────────┐
│  输入描述 ──►「AI 帮我找」          «看看 AI 发现了什么»            │
│      │                                  │                          │
│      ▼                                  ▼                          │
│  POST /api/explicit/match       GET /api/implicit/suggest           │
│  POST /api/implicit/track (♡/✕/停留)                                 │
└──────────────────────────┬───────────────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼───────────────────────────────────────┐
│                         FastAPI (app.py)                          │
└─────┬───────────────────────────────┬────────────────────────────┘
      │                               │
      ▼                               ▼
┌─────────────────────┐     ┌──────────────────────┐
│ explicit_preference │     │ implicit_preference   │
│  parse_intent()     │     │  track_behavior()     │
│  match()            │     │  infer()              │
└────┬────────┬───────┘     │  suggest()            │
     │        │             └────┬──────────┬────────┘
     │        │                  │          │
     ▼        ▼                  ▼          ▼
┌─────────┐ ┌─────────┐    ┌─────────┐ ┌─────────┐
│ ai_client│ │fallback │    │ai_client│ │fallback │
│(LLM 路) │ │(本地路) │    │(LLM 路) │ │(本地路) │
└─────────┘ └─────────┘    └─────────┘ └─────────┘
     │                                      │
     ▼                                      ▼
   OpenAI 兼容 API               本地关键词 / 统计反推
   (无 key 时自动走 fallback)
```

**核心：每个能力都有两条路**——AI 路给最佳体验，fallback 路保证下限。`ai_client.call_llm()` 统一封装「尝试 AI → 失败/无 key → 返回 fallback」，调用方不感知降级。

## 模块说明

| 模块 | 职责 | 关键函数 |
|---|---|---|
| `app.py` | 路由 + 静态托管 | `/api/explicit/match`、`/api/implicit/track`、`/api/implicit/suggest` |
| `modules/explicit_preference.py` | 显性偏好链路 | `parse_intent(text)→intent`、`match(intent, candidates)→[结果]` |
| `modules/implicit_preference.py` | 隐性偏好链路 | `track_behavior(event)`、`infer(log)→preference`、`suggest(preference)→文案` |
| `modules/ai_client.py` | LLM 调用封装 | `call_llm(messages, fallback=None)`，带超时/重试/降级 |
| `modules/fallback.py` | 本地兜底 | 关键词解析、结构化打分、统计反推、模板理由 |
| `data/candidates.json` | 12 个候选样本 | 静态数据 |

## 数据流

### 显性偏好链路
```
用户输入 "温柔、不戴眼镜、瓜子脸、文艺风"
  └─► parse_intent(text)
        ├─ AI 路：LLM 解析为 {glasses:false, faceShape:瓜子脸, style:文艺, vibe:温柔}, 未提及→null
        └─ 兜底：关键词字典匹配
  └─► match(intent, candidates)
        ├─ 结构化分：命中字段/非空字段 ∈ [0,1]，记录差异项
        ├─ AI 语义分（可选）：LLM 对 (原始描述, candidate.bio) 给 0~1
        └─ 加权 0.6*结构 + 0.4*语义，排序取 top3
  └─► 生成「为什么推荐」：命中维度 ✓ + 第一个差异项
  └─► 返回前端：意图拆解 + 候选卡 + 理由
```

### 隐性偏好链路
```
每次 ♡/✕/停留 ≥1.5s
  └─► track_behavior(event) → 内存 log[]

用户点「看看 AI 发现了什么」
  └─► infer(log)
        ├─ 统计路：♡ 过的 candidate 属性分布，找"用户没说但 ♡ 占比高"的维度值
        └─ AI 路：行为摘要喂 LLM 推断偏好 + 可解释理由
  └─► suggest(preference) → 提示卡文案
        ├─ AI 路：LLM 生成自然语言
        └─ 兜底：模板拼接
```

## 双路降级策略

| 能力 | AI 路（有 key） | 兜底路（无 key / 失败） |
|---|---|---|
| 意图解析 | LLM 结构化解析 | 关键词字典匹配 |
| 候选打分 | 结构化分 + LLM 语义分加权 | 仅结构化分 |
| 推荐理由 | LLM 自然语言 | 模板（命中 ✓ + 差异） |
| 隐性反推 | LLM 推断偏好 | 属性分布统计 |
| 提示文案 | LLM 生成 | 模板拼接 |

降级是**逐调用**的：某次 LLM 超时就这一项走兜底，不影响其他项，不会整链路崩。

## 分层理由

- **显性 / 隐性分模块**：迭代节奏不同（显性偏稳，隐性需持续调）、可独立灰度、可独立降级（隐性反推挂了不影响显性匹配主链路）。
- **`ai_client` 统一封装**：便于后续加缓存层、限流、重试策略、成本埋点。
- **`fallback` 独立**：兜底逻辑可单测、可独立演进，是产品体验下限的保障，不是临时补丁。

## 扩展点（后续填实现的位置）

1. **意图向量缓存**：相似描述命中缓存，`ai_client` 加一层 LRU。
2. **候选向量离线库**：bio 向量离线算好存库，线上只算 `意图向量 · 候选向量` 点积，把单次匹配 LLM 调用从 O(候选数) 降到 O(1)。
3. **真实多模态参考图**：`explicit_preference` 加 `parse_intent_from_image()`，走 vision 模型。
4. **行为建模升级**：`implicit_preference.infer()` 从统计换成偏好向量模型（停留时长、滑动速度、回看加权）。
5. **探索性推荐**：ε-greedy 偶尔推画像外候选，破信息茧房。
6. **双边匹配**：在 `match()` 之上加撮合层（对方也 like 才成对）。

## 运行时假设

- 单进程，行为日志进程内（v1 不持久化，刷新清空——可接受，因为是 demo）。
- 单城市 / 单人群灰度（未做地理维度）。
- 候选池静态 12 个（非真实双边）。
