# 相中 demo

> 产品：相亲平台「相中」。Tagline：**"你说不清的喜欢，AI 帮你找得到。"**
>
> 一个能真跑的最小 demo：**显性偏好链路 + 隐性偏好链路都接真实 LLM**（OpenAI 兼容，兼容 Qwen/DeepSeek/Moonshot/豆包/GLM/OpenAI），且**无 API key 时自动降级到本地兜底，照样完整跑通、不报错**。

## 1. 一条命令启动

```bash
cd demo
pip install -r requirements.txt      # fastapi + uvicorn + openai
python app.py                         # 启动
```

浏览器打开 **http://localhost:8000** ，看到一个手机框页面。

- **不需要任何 API key、不联网**也能完整跑通两条链路（本地兜底模式，页面角落有标识）。
- 头像是离线 SVG（`avatars/c01..c12.svg`），不联网。

## 2. 双路说明（AI 模式 / 本地兜底模式）

页面**右上角角标**实时显示当前模式：

| 模式 | 触发条件 | 行为 |
|---|---|---|
| **AI 模式** | 配了 `OPENAI_API_KEY`（+可选 `OPENAI_BASE_URL`/`MODEL`） | 显性解析、语义打分、隐性反推、提示卡文案都走真实 LLM |
| **本地兜底模式** | 无 key / SDK 未装 / LLM 调用失败 | 全部走本地逻辑（关键词解析、结构化打分、统计反推、模板文案），**不报错、不白屏** |

**降级是逐调用、细粒度的**：每条 LLM 调用都有兜底分支。即便配了 key，单次调用超时/失败也只影响那一步（返回 fallback），不影响整个 demo 流程。

## 3. 配置 key 切换到 AI 模式

复制 `.env.example` 为 `.env`，填入你的 key（厂商无关，靠 `OPENAI_BASE_URL` 覆盖）：

```bash
cp .env.example .env
```

```ini
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1   # Qwen；DeepSeek/Moonshot/豆包/GLM 见 .env.example
MODEL=qwen-plus
```

重启 `python app.py`，角标变成红色「AI 模式」即生效。

> 现场演示建议：先用本地兜底模式跑稳（保证不翻车），再展示 AI 模式。两条链路在两种模式下都能完整跑通。

## 4. 两条链路在跑什么

```
显性偏好（用户已明确）  自然语言 → parse_intent → match → 候选卡片 + "为什么推荐"
隐性偏好（用户未发现）  ♡/✕/停留 → track_behavior → infer → suggest → 提示卡
```

### 4.1 显性链路（§3.1）
1. 输入 `温柔、不戴眼镜、瓜子脸、文艺风`，点「AI 帮我找」。
2. `parse_intent(text)`：
   - **AI 路**：prompt 让 LLM 把描述解析成 `{glasses, faceShape, style, vibe}`，未提及字段返 `null`，要求纯 JSON；失败重试 1 次仍失败走兜底。
   - **兜底路**：`fallback.parse_intent` 关键词字典匹配（`不戴眼镜→glasses:false`、`瓜子脸→faceShape:瓜子脸`、`温柔→vibe:温柔`、`文艺→style:文艺` 等）。
3. `match(intent, candidates)`：
   - **结构化分**：命中字段数 / 非空字段数。
   - **AI 语义分（可选）**：用户原始描述 + candidate.bio 喂 LLM 返回 0~1 相似度，与结构化分加权 `0.6*结构 + 0.4*语义`；无 key 只用结构化分。
   - 排序取 top 3，每个生成「为什么推荐」：命中维度列 ✓ + 第一个差异项写"唯一差异：…"。AI 路额外加一句 LLM 自然语言理由。
4. 顶部"AI 把你的描述理解为：…"（透明化，标注是 AI 解析还是关键词解析）+ 候选卡片流 + ♡/✕。

### 4.2 隐性链路（§3.2）
1. 每次 ♡/✕ 或卡片停留 ≥1.5s，`POST /api/implicit/track`，body `{candidateId, action, dwellMs}`。
2. `track_behavior(event)`：append 到内存 list（进程内，重启清空）。
3. 「看看 AI 发现了什么」→ `GET /api/implicit/suggest`。
4. `infer(log)`：
   - **统计路**：统计 ♡ 过的 candidate 各 attribute 分布，找"用户描述里没提、但 ♡ 占比 ≥50%"的维度值。
   - **AI 路**：把行为摘要喂 LLM，推断"用户可能未自意识的偏好"+ 可解释理由。
   - 无 ♡ 数据时返回"再多看看几张卡片…"。
5. `suggest(preference)`：生成提示卡（"你嘴上说喜欢温柔文艺，但最近心动更多是高冷运动风——要不要看看？"）。AI 路让 LLM 写自然；兜底用模板。

### 4.3 参考图通道（唯一占位）
"上传理想型照片"按钮**置灰**，旁边小字"（v1 未接入图片识别）"。不报错。

## 5. 目录结构

```
demo/
  app.py                          # FastAPI 入口：路由 + 静态托管
  data/candidates.json            # 12 个候选样本（真实静态数据）
  modules/
    explicit_preference.py        # 显性：parse_intent() / match()
    implicit_preference.py        # 隐性：track_behavior() / infer() / suggest()
    ai_client.py                  # OpenAI 兼容封装：complete_chat/embed/call_llm，带兜底/重试
    fallback.py                   # 本地兜底：关键词解析、结构化打分、统计反推、模板文案
  static/{index.html, app.js, style.css}
  avatars/c01..c12.svg            # 自绘 SVG 头像，属性与图一致（眼镜/脸型看得出来）
  requirements.txt
  .env.example
  README.md
```

两条偏好的边界在文件层面就看得见：`explicit_preference` 与 `implicit_preference` 互不 import；AI 只经 `ai_client`。

## 6. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 手机框页面 |
| GET | `/api/status` | `{available, mode, model, ...}`（前端角标用） |
| GET | `/static/*` `/avatars/*` | 前端资源 / SVG 头像 |
| POST | `/api/explicit/match` | `{text}` → `{intent, matches, mode}` |
| POST | `/api/implicit/track` | `{candidateId, action, dwellMs}` → `{ok, logged, count}` |
| GET | `/api/implicit/suggest` | → `{preference, suggestion, mode}` |

## 7. 12 个候选样本（覆盖各种属性组合）

| id | 眼镜 | 脸型 | 风格 | 气质 | 姓名·年龄·城市 |
|---|---|---|---|---|---|
| c01 | 否 | 瓜子脸 | 文艺 | 温柔 | 林同学·26·上海 |
| c02 | 是 | 鹅蛋脸 | 极简 | 知性 | 陈同学·27·北京 |
| c03 | 否 | 圆脸 | 运动 | 阳光 | 苏同学·25·杭州 |
| c04 | 否 | 方脸 | 街头 | 活泼 | 周同学·29·成都 |
| c05 | 是 | 瓜子脸 | 商务 | 知性 | 黄同学·28·上海 |
| c06 | 否 | 鹅蛋脸 | 文艺 | 温柔 | 赵同学·24·广州 |
| c07 | 否 | 方脸 | 运动 | 高冷 | 吴同学·30·深圳 |
| c08 | 是 | 圆脸 | 极简 | 活泼 | 郑同学·26·北京 |
| c09 | 否 | 瓜子脸 | 街头 | 阳光 | 王同学·27·杭州 |
| c10 | 是 | 鹅蛋脸 | 商务 | 知性 | 冯同学·31·成都 |
| c11 | 否 | 圆脸 | 文艺 | 温柔 | 蒋同学·25·上海 |
| c12 | 否 | 方脸 | 极简 | 高冷 | 韩同学·28·广州 |

戴/不戴眼镜、4 种脸型、5 种风格、5 种气质都覆盖，方便演示匹配差异和"唯一差异"。

## 8. 演示动线

1. 打开页面 → 手机框 + tagline，看右上角**模式角标**（先本地兜底模式）。
2. 输入 `温柔、不戴眼镜、瓜子脸、文艺风` → 点「AI 帮我找」→ 指"AI 把你的描述理解为"那行（**显性偏好的获取与透明化**）。
3. 滑到候选卡片，看"匹配度"+"为什么推荐"（命中 ✓ + 唯一差异）→ 点 ♡/✕。
4. 点「看看 AI 发现了什么」→ 提示卡（**隐性偏好的反推与主动提示**）。
5. （可选）配 key 后重启，角标变红「AI 模式」，重复上述流程对比 LLM 自然语言理由。
