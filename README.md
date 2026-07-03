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

**无 API key、本地兜底模式**已实测跑通两条链路（显性匹配 + 隐性偏好发现），真实 API 输入输出见 [`docs/RUNLOG.md`](./docs/RUNLOG.md)。

要看 UI 效果，clone 后跑 `python app.py` 打开 http://localhost:8000。

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
cp .env.example .env       # 填入 OPENAI_API_KEY / OPENAI_BASE_URL / MODEL

python app.py              # → 浏览器打开 http://localhost:8000
```

### 体验路径
1. 输入 `温柔、不戴眼镜、瓜子脸、文艺风` → 点「AI 帮我找」
2. 看"AI 把你的描述理解为…"（透明化）+ 候选卡 + "为什么推荐"
3. 点几张 ♡ → 点「看看 AI 发现了什么」→ 隐性偏好提示卡

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
│   │   ├── ai_client.py              # OpenAI 兼容封装 + 兜底
│   │   └── fallback.py              # 本地兜底逻辑
│   ├── data/candidates.json          # 12 个候选样本
│   ├── static/                       # 手机框 UI
│   └── avatars/                      # 自绘 SVG 头像（属性与图一致）
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

## 已知局限

- 候选池是 mock 的 12 个，非真实双边
- 头像为 SVG 插画，无真实照片识别（参考图通道置灰）
- 行为反推为雏形统计，非偏好向量建模
- 行为日志进程内，刷新清空

详见 [`THINKING.md`](./THINKING.md) §5 §6。

---

## License

MIT
