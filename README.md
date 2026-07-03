# 相中 · Xiangzhong

> 你说不清的喜欢，AI 帮你找得到。
>
> 小红书"社交突破"面试题补交方案 —— 用 AI 理解用户"说不清的喜欢"（隐含意图），把相亲匹配从"填字段检索"升级为**语义 + 视觉向量匹配 + 行为反推**。

---

## 这是什么

一个产品方案 + 可跑的最小 demo，演示一个核心想法：**用户的偏好分两类，AI 各自击破**——

- **显性偏好**（用户已明确）：自然语言描述 → AI 解析为意图向量 → 候选匹配 → 透明化"为什么推荐"。
- **隐性偏好**（用户自己没发现）：♡/✕/停留 等行为信号 → AI 反推偏好 → 主动提示"你可能其实喜欢…"。

配了 AI key 就走真实 LLM，**没 key 自动降级到本地兜底，照样能跑**。

> 📖 **先读 [`THINKING.md`](./THINKING.md)** —— 设计思考与取舍是这份补交的核心，比代码更重要。PPT 在 [`deck/`](./deck/)，可跑的 demo 在 [`demo/`](./demo/)。

---

## 运行实录

- **本地兜底模式**（无 key）：显性匹配 + 隐性偏好发现两条链路已实测跑通。
- **AI 模式**（配 key · `doubao-seed-2.0-pro` 多模态）：文本意图解析 + 照片 vision 识别外貌特征均实测跑通。

真实 API 输入输出、异步预计算架构、详情页去标定见 [`docs/RUNLOG.md`](./docs/RUNLOG.md)（§3 AI 模式 / §4 异步预计算 / §5 详情页克制）。要看 UI 效果，clone 后跑 `python app.py` 打开 http://localhost:8000。

---

## 快速开始

### 看 PPT
```bash
open deck/index.html      # macOS，浏览器全屏播放
```

### 跑 demo
```bash
cd demo
pip install -r requirements.txt

# 可选：接真 AI（不配也能跑，走本地兜底）
cp .env.example .env       # 填 OPENAI_API_KEY / OPENAI_BASE_URL / MODEL
# 启用「上传理想型照片」识别：再配支持 vision 的 VISION_MODEL（如 doubao-seed-2.0-pro）

python app.py              # → 浏览器打开 http://localhost:8000
```

### 跑测试
```bash
cd demo
pip install -r requirements-dev.txt   # pytest
python -m pytest                       # 50 用例，~0.5s，全兜底模式（不打真 LLM、不联网）
```
覆盖范围见下方 [测试覆盖](#测试覆盖)。

### 体验路径
1. 输入 `温柔、不戴眼镜、瓜子脸、文艺风` → 点「AI 帮我找」（或点「上传理想型照片」让 AI vision 反推）
2. 看"AI 把你的描述理解为…"（透明化）+ 候选卡 + "为什么推荐" → 点卡进详情页
3. 详情页只露基本信息 + 匹配度（AI 标定藏在后台，产品克制）
4. 点几张 ♡ → 点「看看 AI 发现了什么」→ 隐性偏好提示卡
5. 点顶部「我的资料」→ 注册自己（资料 + 照片 + bio）→ 进入候选人池被别人匹配

---

## 核心概念

```
        ┌─ 显性偏好（用户已明确）─→ 自然语言/参考图/预设 → AI 解析为【意图向量】
用户 ──┤                                                              ┐
        └─ 隐性偏好（用户未发现）─→ 行为信号(停留/♡/✕) → AI 反推为【偏好向量】
                                                                         ├─→ 匹配打分 → Top-N → 透明化理由 → 反馈微调
        候选人资料：照片 → 多模态特征 / 简介 → 语义特征 → 【候选特征向量】 ┘
```

---

## 项目结构

```
.
├── THINKING.md              # ⭐ 设计思考与取舍（核心）
├── README.md                # 本文件
├── deck/index.html          # 7 页 HTML 幻灯片（离线可播、可导出 PDF）
├── demo/                    # 可跑的最小 demo（FastAPI + 原生前端）
│   ├── app.py
│   ├── modules/
│   │   ├── explicit_preference.py   # 显性偏好链路
│   │   ├── implicit_preference.py   # 隐性偏好链路
│   │   ├── ai_client.py              # OpenAI 兼容封装 + vision + 兜底
│   │   ├── candidate_store.py       # 候选人内存索引 + 异步预计算
│   │   └── fallback.py              # 本地兜底逻辑
│   ├── data/candidates.json          # 12 个候选样本（启动即预计算）
│   ├── static/                       # 手机框 UI
│   ├── avatars/                      # 自绘 SVG 头像（属性与图一致）
│   ├── tests/                        # pytest 用例（兜底模式，见「测试覆盖」）
│   ├── pytest.ini
│   └── requirements-dev.txt          # 测试依赖（pytest）
└── docs/
    ├── 题目背景.md           # 面试原题
    ├── architecture.md      # 架构图与模块说明
    ├── RUNLOG.md            # 运行实录（真实 API 输入输出）
    ├── PPT-agent-需求文档.md
    └── Demo-agent-需求文档.md
```

---

## 技术栈

- **demo**：Python / FastAPI / 原生 HTML·CSS·JS / OpenAI 兼容 SDK（Qwen / DeepSeek / Moonshot / 豆包 / GLM / OpenAI 均可）
- **deck**：自包含 HTML（离线、可导出 PDF）

---

## 测试覆盖

50 个用例，全部跑在**兜底模式**（不打真 LLM、不联网），约 0.5s 跑完。

| 测试文件 | 覆盖模块 | 覆盖点 |
|---|---|---|
| `test_fallback.py` | `fallback` | 关键词解析（眼镜优先级/别名归一）、结构化打分（全中/部分/除零保护）、统计反推、提示模板 |
| `test_explicit.py` | `explicit_preference` | fallback source、match top3 降序+最佳优先、图片通道不可用、归一化工具 |
| `test_implicit.py` | `implicit_preference` | 行为采集+计数、last_intent 回写、infer 统计路、suggest 模板 |
| `test_candidate_store.py` | `candidate_store` | 冷加载/查询、match 无兜底池、create 异步预计算失败 |
| `test_api.py` | `app.py` | 8 个 API 端点全覆盖（含详情页不返回 AI 标定的产品克制） |

设计要点：
- **强制兜底**：`tests/conftest.py` 在导入任何模块**之前**清空 `OPENAI_API_KEY`，否则 `demo/.env` 的真 key 会让测试去打真 LLM（慢、花钱、要联网）。
- **测试隔离**：autouse fixture 逐测试复位 `implicit_preference` / `candidate_store` 的内存全局态，避免用例间互相污染。
- **AI 路不在单测范围**：`_parse_intent_ai` / `_infer_ai` 等真实 LLM 调用依赖外部网络与计费，由 [`docs/RUNLOG.md`](./docs/RUNLOG.md) 的真实 API 输入输出实录覆盖。

---

## 已知局限

- 候选池以 12 个 mock 种子起步；用户可注册成为候选人（候选人 = 注册用户自己），但仍是单机 demo、无真实多用户
- 种子候选头像是离线 SVG；**用户上传的照片**走真实 vision 识别（glasses/faceShape/style/vibe），未配 vision 模型则降级
- 注册即写、后台异步预计算 attributes（不阻塞注册），查询走结构化匹配 + 多级兜底
- 行为反推为雏形统计，非偏好向量建模
- 行为日志进程内，刷新清空

详见 [`THINKING.md`](./THINKING.md) §5 §6。

---

## License

MIT
