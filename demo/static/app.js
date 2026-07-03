/* 相中 demo 前端逻辑 —— 调后端接口，渲染真实结果。
 * 显性链路：POST /api/explicit/match → 意图透明化 + 候选卡片 + "为什么推荐"
 * 隐性链路：POST /api/implicit/track（♡/✕/停留）→ GET /api/implicit/suggest（提示卡）
 * 模式标识：GET /api/status → 角落角标
 */
const $ = (id) => document.getElementById(id);

const els = {
  desc: $("desc"),
  examples: $("examples"),
  matchBtn: $("matchBtn"),
  refBtn: $("refBtn"),
  refImage: $("refImage"),
  refHint: $("refHint"),
  emptyState: $("emptyState"),
  loading: $("loading"),
  result: $("result"),
  intentPills: $("intentPills"),
  intentSourceTag: $("intentSourceTag"),
  cards: $("cards"),
  suggestBtn: $("suggestBtn"),
  suggestion: $("suggestion"),
  modeBadge: $("modeBadge"),
  detailOverlay: $("detailOverlay"),
  detailMask: $("detailMask"),
  detailPanel: $("detailPanel"),
  detailBody: $("detailBody"),
  detailClose: $("detailClose"),
  createImage: $("createImage"),
  createImageBtn: $("createImageBtn"),
  createPhotoName: $("createPhotoName"),
  createName: $("createName"),
  createAge: $("createAge"),
  createCity: $("createCity"),
  createBtn: $("createBtn"),
  createMsg: $("createMsg"),
};

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ===== 模式角标 + vision 可用态 ===== */
let visionAvailable = false;
async function refreshMode() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const badge = els.modeBadge;
    if (data.available) {
      badge.textContent = "AI 模式";
      badge.classList.add("ai");
      badge.title = `AI 模式 · ${data.model || ""}（base_url ${data.base_url_set ? "已设" : "默认"}）`;
    } else {
      badge.textContent = "本地兜底模式";
      badge.classList.remove("ai");
      badge.title = "本地兜底模式（无 API key，AI 调用走本地逻辑，不报错）";
    }
    visionAvailable = !!data.vision_available;
    applyVisionState();
  } catch (e) {
    els.modeBadge.textContent = "本地兜底模式";
    visionAvailable = false;
    applyVisionState();
  }
}

function applyVisionState() {
  const btn = els.refBtn;
  if (visionAvailable) {
    btn.disabled = false;
    btn.textContent = "📷 上传理想型照片";
    els.refHint.textContent = "让 AI 看照片反推理想型";
  } else {
    btn.disabled = true;
    btn.textContent = "📷 未配置 vision 模型";
    els.refHint.textContent = "需在 .env 配 VISION_MODEL（如 qwen-vl-plus / glm-4v-flash / gpt-4o）";
  }
}
refreshMode();

/* 示例一键填入（空状态便捷入口） */
els.examples.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  els.desc.value = chip.dataset.text;
  els.desc.focus();
});

/* ===== 参考照片链路（多模态 vision） ===== */
els.refBtn.addEventListener("click", () => {
  if (els.refBtn.disabled) return;
  els.refImage.click();
});

els.refImage.addEventListener("change", () => {
  const file = els.refImage.files && els.refImage.files[0];
  if (!file) return;
  if (!visionAvailable) {
    // 双保险：即便按钮被启用，也再校验一次。
    applyVisionState();
    return;
  }
  const reader = new FileReader();
  reader.onload = async (ev) => {
    // FileReader 结果形如 data:image/jpeg;base64,xxxx，去掉前缀只留 b64。
    const dataUrl = String(ev.target.result || "");
    const comma = dataUrl.indexOf(",");
    const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
    await runMatchImage(b64);
    // 清空，便于再次选同一张图触发 change。
    els.refImage.value = "";
  };
  reader.readAsDataURL(file);
});

async function runMatchImage(b64) {
  hide(els.emptyState);
  hide(els.result);
  els.loading.classList.remove("hidden");
  setLoadingText("AI 正在看照片…");
  const minDelay = delay(600);
  try {
    const res = await fetch("/api/explicit/match_image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: b64 }),
    });
    const data = await res.json();
    await minDelay;
    if (data.intent && data.intent.source === "none") {
      // vision 不可用 / 失败：温和提示，不报错。
      els.result.innerHTML =
        '<p class="empty-sub">照片识别暂不可用（' + esc(data.intent.error || "vision_unavailable") +
        "）。可在 .env 配置 VISION_MODEL 后重试，或直接文字描述 ↑</p>";
      show(els.result);
      refreshMode();
      return;
    }
    renderResult(data.intent, data.matches, data.fallback_feed);
    refreshMode();
  } catch (err) {
    els.result.innerHTML = '<p class="empty-sub">出错了：' + esc(err) + "（请确认后端已启动）</p>";
    show(els.result);
  } finally {
    hide(els.loading);
    setLoadingText("AI 正在理解你的描述…");
  }
}

function setLoadingText(txt) {
  const p = els.loading.querySelector("p");
  if (p) p.textContent = txt;
}

/* ===== 显性偏好链路 ===== */
els.matchBtn.addEventListener("click", async () => {
  const text = els.desc.value.trim();
  if (!text) {
    els.desc.style.borderColor = "#FF2442";
    setTimeout(() => (els.desc.style.borderColor = ""), 800);
    els.desc.focus();
    return;
  }
  hide(els.emptyState);
  hide(els.result);
  show(els.loading);

  // 即使后端秒回，也保证 loading 这一拍可见（体验完整）。
  const minDelay = delay(450);
  try {
    const res = await fetch("/api/explicit/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    await minDelay;
    renderResult(data.intent, data.matches, data.fallback_feed);
    refreshMode();
  } catch (err) {
    els.result.innerHTML = '<p class="empty-sub">出错了：' + esc(err) + "（请确认后端已启动）</p>";
    show(els.result);
  } finally {
    hide(els.loading);
  }
});

function statusLabel(s) {
  return s === "analyzed" ? "已分析" : s === "pending" ? "分析中" : s === "failed" ? "分析失败" : s === "precomputed" ? "已预计算" : "";
}

function renderResult(intent, matches, fallbackFeed) {
  renderIntent(intent);
  renderCards(matches, false);
  if (fallbackFeed && fallbackFeed.length) renderFallbackFeed(fallbackFeed);
  show(els.result);
}

function renderFallbackFeed(feed) {
  const block = document.createElement("div");
  block.className = "fallback-block";
  block.innerHTML = '<div class="fallback-title">兜底推荐（属性未就绪 / vision 失效，按预填信息）</div>' +
    feed.map((m) => {
      const c = m.candidate;
      return '<div class="card fallback-card" data-cid="' + esc(c.id) + '">' +
        '<div class="card-top">' +
          '<img src="/' + esc(c.photo) + '" alt="' + esc(c.name) + '" />' +
          '<div class="who">' +
            '<span class="name">' + esc(c.name) + "</span>" +
            '<span class="meta">' + esc(c.age) + " · " + esc(c.city) + "</span>" +
            '<span class="fallback-tag">兜底 · ' + esc(statusLabel(m.analysis_status)) + "</span>" +
          "</div>" +
          '<span class="card-more" title="查看详情">›</span>' +
        "</div></div>";
    }).join("");
  els.cards.appendChild(block);
}

function renderIntent(intent) {
  const pills = [];
  if (intent.glasses === true) pills.push("戴眼镜 ✓");
  else if (intent.glasses === false) pills.push("不戴眼镜 ✓");
  if (intent.faceShape) pills.push(esc(intent.faceShape) + " ✓");
  if (intent.style) pills.push(esc(intent.style) + " ✓");
  if (intent.vibe) pills.push(esc(intent.vibe) + " ✓");
  if (pills.length === 0) pills.push("未识别到明确维度");
  els.intentPills.innerHTML = pills
    .map((p) => '<span class="pill">' + p + "</span>")
    .join("");
  const tag = els.intentSourceTag;
  if (intent.source === "ai") {
    tag.textContent = "AI 解析";
    tag.classList.add("ai");
  } else if (intent.source === "none") {
    tag.textContent = "未识别";
    tag.classList.remove("ai");
  } else {
    tag.textContent = "关键词解析（兜底）";
    tag.classList.remove("ai");
  }
}

function attrLine(a) {
  return [a.style, a.vibe, a.glasses ? "戴眼镜" : "不戴眼镜", a.faceShape].join(" · ");
}

function renderCards(matches, isFallback) {
  els.cards.innerHTML = matches
    .map((m) => {
      const c = m.candidate;
      const a = c.attributes || {};
      const stTag = m.analysis_status ? '<span class="status-tag">' + esc(statusLabel(m.analysis_status)) + "</span>" : "";
      return (
        '<div class="card" data-cid="' + esc(c.id) + '">' +
        '<div class="card-top">' +
          '<img src="/' + esc(c.photo) + '" alt="' + esc(c.name) + '" />' +
          '<div class="who">' +
            '<span class="name">' + esc(c.name) + " " + stTag + "</span>" +
            '<span class="meta">' + esc(c.age) + " · " + esc(c.city) + "</span>" +
            '<span class="meta">' + esc(attrLine(a)) + "</span>" +
            '<span class="score">匹配度 ' + Math.round((m.score || 0) * 100) + "%</span>" +
          "</div>" +
          '<span class="card-more" title="查看详情">›</span>' +
        "</div>" +
        '<div class="why"><b>为什么推荐</b><ul>' +
          (m.reasons || []).map((r) => "<li>" + esc(r) + "</li>").join("") +
        "</ul></div>" +
        '<div class="card-actions">' +
          '<button class="btn-like" data-cid="' + esc(c.id) + '" data-action="like">♡ 心动</button>' +
          '<button class="btn-pass" data-cid="' + esc(c.id) + '" data-action="pass">✕ 跳过</button>' +
        "</div>" +
        "</div>"
      );
    })
    .join("");
  attachDwellTracking();
}

/* ===== 隐性偏好链路：♡ / ✕ 上报 + 停留计时 ===== */
function attachDwellTracking() {
  const cards = els.cards.querySelectorAll(".card");
  cards.forEach((card) => {
    let t0 = Date.now();
    card.addEventListener("mouseenter", () => { t0 = Date.now(); });
    card.addEventListener("mouseleave", async () => {
      if (card.dataset.dwellSent) return;
      const dwell = Date.now() - t0;
      if (dwell >= 1500) {
        card.dataset.dwellSent = "1";
        try {
          await fetch("/api/implicit/track", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              candidateId: card.dataset.cid,
              action: "dwell",
              dwellMs: dwell,
            }),
          });
        } catch (e) { /* 静默 */ }
      }
    });
  });
}

els.cards.addEventListener("click", async (e) => {
  // 1) ♡ / ✕ 按钮：上报行为
  const btn = e.target.closest("button[data-cid]");
  if (btn) {
    const card = btn.closest(".card");
    if (card.dataset.acted) return; // 同卡只记一次 like/pass
    card.dataset.acted = "1";
    btn.classList.add("active");
    try {
      await fetch("/api/implicit/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidateId: btn.dataset.cid,
          action: btn.dataset.action,
          dwellMs: null,
        }),
      });
    } catch (err) {
      // 静默失败，不阻塞体验
    }
    return;
  }
  // 2) 点击卡片其它区域（头像/名字/›/why）：打开详情
  const card = e.target.closest(".card");
  if (card && card.dataset.cid) {
    openDetail(card.dataset.cid);
  }
});

/* ===== 候选详情面板 ===== */
async function openDetail(cid) {
  // 立即弹出骨架，避免点完无反馈。
  els.detailBody.innerHTML =
    '<div class="detail-loading"><div class="spinner"></div><p>加载中…</p></div>';
  show(els.detailOverlay);
  try {
    const res = await fetch("/api/candidate/" + encodeURIComponent(cid));
    const data = await res.json();
    if (!data.ok || !data.candidate) {
      els.detailBody.innerHTML = '<p class="empty-sub">找不到该候选人</p>';
      return;
    }
    renderDetail(data.candidate, data);
  } catch (err) {
    els.detailBody.innerHTML = '<p class="empty-sub">出错了：' + esc(err) + "</p>";
  }
}

function renderDetail(c, data) {
  const ms = data.match_score;
  const scoreTxt = (ms == null) ? "暂无匹配度（先匹配一下）" : "匹配度 " + Math.round(ms * 100) + "%";
  const stTag = data.analysis_status ? '<span class="status-tag">' + esc(statusLabel(data.analysis_status)) + "</span>" : "";
  els.detailBody.innerHTML =
    '<div class="detail-hero">' +
      '<img src="/' + esc(c.photo) + '" alt="' + esc(c.name) + '" />' +
      '<div class="detail-name">' + esc(c.name) + " · " + esc(c.age) + " · " + esc(c.city) + " " + stTag + "</div>" +
    "</div>" +
    '<div class="detail-section"><div class="detail-sec-title">匹配度</div>' +
      '<p class="detail-bio">' + esc(scoreTxt) + "</p>" +
    "</div>" +
    '<div class="detail-section"><div class="detail-sec-title">关于 TA</div>' +
      '<p class="detail-bio">' + esc(c.bio || "（暂无简介）") + "</p>" +
    "</div>" +
    '<div class="detail-actions">' +
      '<button class="btn-like" data-cid="' + esc(c.id) + '" data-action="like">♡ 心动</button>' +
      '<button class="btn-pass" data-cid="' + esc(c.id) + '" data-action="pass">✕ 跳过</button>' +
    "</div>";
}

function closeDetail() {
  hide(els.detailOverlay);
}

els.detailClose.addEventListener("click", closeDetail);
els.detailMask.addEventListener("click", closeDetail);

// 详情面板内 ♡ / ✕ 上报（与卡片一致）
els.detailPanel.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-cid]");
  if (!btn) return;
  if (btn.dataset.acted) return;
  btn.dataset.acted = "1";
  btn.classList.add("active");
  try {
    await fetch("/api/implicit/track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidateId: btn.dataset.cid,
        action: btn.dataset.action,
        dwellMs: null,
      }),
    });
  } catch (err) {
    // 静默
  }
  // 点后关闭详情（可改"停留"，这里关掉，回到列表继续浏览）。
  closeDetail();
});

/* ===== 隐性偏好链路：主动提示 ===== */
els.suggestBtn.addEventListener("click", async () => {
  els.suggestBtn.disabled = true;
  els.suggestBtn.textContent = "AI 正在发现…";
  try {
    const res = await fetch("/api/implicit/suggest");
    const data = await res.json();
    const s = data.suggestion || {};
    const srcTag = (s.source === "ai") ? "AI 反推" : (s.source === "stats" ? "统计反推（兜底）" : "");
    els.suggestion.innerHTML =
      '<div class="s-title">' + esc(s.title || "") + "</div>" +
      '<div class="s-body">' + esc(s.body || "") + "</div>" +
      (srcTag ? '<span class="s-tag">' + esc(srcTag) + "</span>" : "");
    show(els.suggestion);
    refreshMode();
  } catch (err) {
    els.suggestion.innerHTML = '<p class="empty-sub">出错了：' + esc(err) + "</p>";
    show(els.suggestion);
  } finally {
    els.suggestBtn.disabled = false;
    els.suggestBtn.textContent = "看看 AI 发现了什么";
  }
});

/* ===== 创建候选人（演示异步预计算：写入即时返回，后台分析） ===== */
let _createPhotoB64 = "";
els.createImageBtn.addEventListener("click", () => els.createImage.click());
els.createImage.addEventListener("change", () => {
  const f = els.createImage.files && els.createImage.files[0];
  if (!f) return;
  els.createPhotoName.textContent = f.name;
  const r = new FileReader();
  r.onload = (ev) => {
    const url = String(ev.target.result || "");
    const i = url.indexOf(",");
    _createPhotoB64 = i >= 0 ? url.slice(i + 1) : url;
  };
  r.readAsDataURL(f);
});
els.createBtn.addEventListener("click", async () => {
  if (!_createPhotoB64) {
    els.createMsg.textContent = "请先上传候选人照片";
    els.createMsg.classList.remove("hidden");
    return;
  }
  els.createBtn.disabled = true;
  els.createBtn.textContent = "创建中…";
  try {
    const res = await fetch("/api/candidate/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: els.createName.value.trim(),
        age: els.createAge.value.trim(),
        city: els.createCity.value.trim(),
        photo: _createPhotoB64,
      }),
    });
    const data = await res.json();
    if (data.ok) {
      els.createMsg.textContent = "✓ " + data.msg + "（ID: " + data.id + "，状态: " + statusLabel(data.analysis_status) + "）。后台异步分析中，下次匹配会用 ta 的预计算特征。";
    } else {
      els.createMsg.textContent = "创建失败";
    }
    els.createMsg.classList.remove("hidden");
  } catch (e) {
    els.createMsg.textContent = "出错：" + e;
    els.createMsg.classList.remove("hidden");
  } finally {
    els.createBtn.disabled = false;
    els.createBtn.textContent = "创建";
  }
});
