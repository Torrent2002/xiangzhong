# Demo Agent 需求文档

> 本文档是给"做 demo 的 agent"看的执行 brief。
> **目标：做一个能真跑的最小 demo**——显性偏好链路 + 隐性偏好链路都接真实 LLM（OpenAI 兼容），且**无 API key 时自动走本地兜底，照样能跑**。不要占位 stub。

---

## 1. 背景与目标

- **产品**：相亲平台「相中」。Tagline：**"你说不清的喜欢，AI 帮你找得到。"**
- **核心概念（demo 要体现的主线）**——用户偏好分两类，两条链路都要真实实现：
  - **A 显性偏好（用户已明确）**：自然语言描述 → 意图解析 → 候选匹配 → 透明化"为什么推荐"。
  - **B 隐性偏好（用户自己没发现）**：♡/✕/停留 等行为信号 → 反推偏好 → 主动提示"你可能其实喜欢…"。
- **铁律（最高优先级）**：
  1. **配了 key 就接真 AI**（显性解析、语义打分、隐性反推都用 LLM），体验最佳。
  2. **没 key / AI 失败时自动降级到本地兜底**，demo 照样完整跑通，不报错、不白屏。演示现场不可控，这是底线。
  3. **两条链路都要真实有逻辑**，不要 `# TODO` 占位。
  4. 占位只在"参考图多模态"这一处（本次不做真图识别，按钮置灰 + 说明）。

## 2. 交付物规格

- **形式**：本地 web 应用，手机框风格页面 + Python 后端。
- **启动**：`pip install -r requirements.txt && python app.py`，浏览器开 `http://localhost:8000`。
- **输出位置**：当前目录下 `demo/`。
- **目录结构**（两类偏好的边界在文件层面就看得见）：
  ```
  demo/
    app.py                          # FastAPI 入口：路由 + 静态托管
    data/candidates.json            # 12 个候选样本（真实静态数据）
    modules/
      explicit_preference.py        # 显性：parse_intent(), match()
      implicit_preference.py        # 隐性：track_behavior(), infer(), suggest()
      ai_client.py                  # OpenAI 兼容封装：call_llm()，带兜底/重试
      fallback.py                   # 本地兜底：关键词解析、结构化打分、统计反推
    static/{index.html, app.js, style.css}
    avatars/*.svg                   # 自绘 SVG 头像，属性与图一致
    requirements.txt
    .env.example
    README.md                       # demo 启动说明
  ```
- **栈**：Python + FastAPI + 原生 HTML/CSS/JS。AI 用 `openai` SDK（支持 `base_url` 覆盖，兼容 Qwen/DeepSeek/Moonshot/豆包/GLM/OpenAI）。

## 3. 功能需求

### 3.1 显性偏好链路（真实实现）
1. 输入框输入自然语言，如 `温柔、不戴眼镜、瓜子脸、文艺风`，点「AI 帮我找」。
2. 前端 `POST /api/explicit/match`，body `{text}`。
3. `parse_intent(text)`：
   - **AI 路**：prompt 让 LLM 把描述解析成 `{glasses, faceShape, style, vibe}`，未提及字段返 `null`，要求**纯 JSON**；解析失败重试 1 次，仍失败走兜底。
   - **兜底路**：`fallback.parse_intent(text)` 关键词字典匹配（`不戴眼镜→glasses:false`、`瓜子脸→faceShape:瓜子脸`、`温柔→vibe:温柔`、`文艺→style:文艺` 等）。
4. `match(intent, candidates)`：
   - **结构化分**：对每个 candidate，遍历 intent 非空字段，命中 +1、不命中记差异项；归一化 `命中数/非空字段数` ∈ [0,1]。
   - **AI 语义分（可选）**：把用户原始描述 + candidate.bio 喂 LLM，让它返回 0~1 相似度；与结构化分加权 `0.6*结构 + 0.4*语义`。无 key 时只用结构化分。
   - 排序取 top 3，每个生成「为什么推荐」：命中维度列 ✓ + 取第一个差异项写"唯一差异：…"。AI 路可让 LLM 写一句自然语言理由；兜底用模板。
5. 前端展示：顶部"AI 把你的描述理解为：…"（透明化）+ 候选卡片流 + ♡/✕。

### 3.2 隐性偏好链路（真实实现）
1. 每次 ♡/✕/卡片停留 ≥1.5s，前端 `POST /api/implicit/track`，body `{candidateId, action, dwellMs}`。
2. `track_behavior(event)`：append 到内存 list（进程内即可，刷新清空可接受）。
3. 「看看 AI 发现了什么」按钮 → `GET /api/implicit/suggest`。
4. `infer(log)`：
   - **统计路**：统计 ♡ 过的 candidate 的各 attribute 分布，找出"用户描述里没提、但 ♡ 占比明显高"的维度值（如 vibe=高冷 占 60% 但用户描述没提高冷）。
   - **AI 路**：把行为摘要喂 LLM，让它推断"用户可能未自意识的偏好"+ 一句可解释理由。
   - 无 ♡ 数据时返回"再多看看几张卡片，我才能发现你的偏好"。
5. `suggest(preference)`：生成提示卡文案（"你嘴上说喜欢温柔文艺，但最近心动更多是高冷运动风——要不要看看？"）。AI 路让 LLM 写自然；兜底用模板。

### 3.3 参考图通道（唯一占位）
- "上传理想型照片"按钮**置灰**，旁边小字"（v1 未接入图片识别）"。不要尝试真做。

### 3.4 模式标识
- 页面角落小字显示当前模式：`AI 模式` / `本地兜底模式`，让面试官一眼看到双路都通。

## 4. UI / UX 规格

- 单页，居中**手机外框**（CSS 画圆角矩形 + 顶部状态栏），宽 ~390px。
- 配色与 PPT 对齐：小红书红 `#FF2442` 点缀，白底，文字 `#1a1a1a`，次要 `#999`。
- 顶部：产品名「相中」+ tagline。
- 输入区：多行输入框（placeholder 用示例描述）+ 主按钮「AI 帮我找」。
- 结果区：一行"AI 把你的描述理解为：…"（维度 ✓）+ 卡片流（头像 / 姓名·年龄·城市 / "为什么推荐" / ♡·✕）。
- 底部：「看看 AI 发现了什么」按钮 → 展示隐性偏好提示卡。
- loading 态："AI 正在理解你的描述…"，避免假死。
- 空状态：引导语 + 2 个示例描述一键填入。
- 角落：模式标识小字。

## 5. 数据模型与逻辑

### 5.1 candidate schema
```json
{
  "id": "c01", "name": "林同学", "age": 26, "city": "上海",
  "photo": "avatars/c01.svg",
  "attributes": {
    "glasses": false,
    "faceShape": "瓜子脸",
    "style": "文艺",
    "vibe": "温柔"
  },
  "bio": "一个安静、喜欢看展和旧书店的女生。"
}
```
- attributes 至少：`glasses`(bool)、`faceShape`(瓜子脸/圆脸/方脸/鹅蛋脸)、`style`(文艺/运动/商务/街头/极简)、`vibe`(温柔/活泼/高冷/阳光/知性)。
- **内置 12 个 candidate**，组合覆盖全（要有戴/不戴眼镜、各脸型、各风格、各气质），方便演示匹配差异和"唯一差异"。

### 5.2 头像
- 自绘 SVG，风格统一，attributes 与图一致（眼镜、脸型要看得出来）。放 `demo/avatars/`。不要真人照片。

### 5.3 ai_client 设计要点
- `call_llm(messages, json_mode=False, fallback=None)`：统一封装，超时 15s，重试 1 次，失败/无 key 返回 `fallback`。
- 环境变量（`.env.example`）：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL`（如 `qwen-plus` / `gpt-4o-mini` / `deepseek-chat`）。
- 无 key 时所有 AI 调用直接返回 fallback，全程不报错。

## 6. 不要做的事

- ❌ 不要做用户注册/登录/数据库持久化（行为日志进程内即可）。
- ❌ 不要做真实双边撮合、视频/语音/聊天。
- ❌ 不要做真实图片识别（置灰即可）。
- ❌ 不要用真人照片。
- ❌ 不要堆功能——**两条链路跑顺 + 透明化 + 双路兜底**就够。

## 7. 验收标准

- [ ] 一条命令启动，浏览器打开能正常用。
- [ ] **无 key 也能完整跑通**两条链路（兜底模式，页面有标识）。
- [ ] **配 key 后**显性解析/语义打分/隐性反推走真实 LLM，且无 key 自动降级不报错。
- [ ] 输入示例 → 看到意图拆解 → 排序卡片 → "为什么推荐"（命中 ✓ + 唯一差异）→ ♡/✕ → "看看 AI 发现了什么"出提示卡。
- [ ] 12 个 candidate 数据齐全，组合有差异；头像是离线 SVG。
- [ ] 参考图按钮置灰不报错。
- [ ] `demo/README.md` 写清启动、配置 key、双路说明。
- [ ] 手机框外观与配色符合 §4。

## 8. 与 PPT / 思考文档的对齐

- 产品名：**相中**；Tagline：**"你说不清的喜欢，AI 帮你找得到。"**
- 核心概念——偏好分两类：显性（用户已明确→解析为意图向量）/ 隐性（用户未发现→行为反推为偏好向量），两条向量汇入同一匹配器，反馈同时更新两类偏好。
- 透明化"为什么推荐"是核心卖点，UI 必须完整呈现。
- 双路架构（AI + 兜底）本身是技术取舍的体现，详见根目录 `THINKING.md`「技术取舍」一节。
