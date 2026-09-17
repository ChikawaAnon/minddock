/* MindDock 前端单页应用 —— 原生 JS，无任何依赖。
   结构：工具 → API → Markdown 渲染 → 主题 → 弹窗/提示 → 路由 → 笔记列表/编辑器
        → 图谱（canvas 力导向）→ 驾驶舱（SVG 图表）→ 启动 */
"use strict";

/* ================= 工具 ================= */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;
const isMobile = () => window.matchMedia("(max-width: 860px)").matches;

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 10);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return sameDay ? `今天 ${hm}` : `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* ================= API ================= */

// 子路径部署自适应：根部署为 ""，nginx 反代 /app/minddock/ 下自动取到前缀。
const BASE = location.pathname.replace(/\/index\.html$/, "").replace(/\/+$/, "");
const AUTH_KEY = "minddock-token";
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

function authToken() {
  try { return localStorage.getItem(AUTH_KEY) || ""; } catch (e) { return ""; }
}

// 公网明文链路偶发连接重置（ERR_CONNECTION_RESET）：网络层错误统一重试 2 次
async function fetchRetry(url, init) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fetch(url, init);
    } catch (e) {
      if (attempt >= 2) throw e;
      await sleep(350 * (attempt + 1));
    }
  }
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET" };
  if (opts.body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.body);
  }
  const token = authToken();
  if (token) init.headers = Object.assign(init.headers || {}, { Authorization: "Bearer " + token });
  const res = await fetchRetry(BASE + path, init);
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    /* 非 JSON 响应 */
  }
  if (res.status === 401) {
    showAuth();  // 会话过期/未登录：弹登录层，登录成功后整页重载
    throw new Error((data && data.error) || "需要登录");
  }
  if (!res.ok) throw new Error((data && data.error) || `请求失败（${res.status}）`);
  return data;
}

/* ================= 登录鉴权（服务端启用时才可见） ================= */

function showAuth() {
  const mask = $("#auth-mask");
  if (!mask) return;
  if (!mask.hidden) return;
  mask.hidden = false;
  $("#auth-error").hidden = true;
  setTimeout(() => { try { $("#auth-password").focus(); } catch (e) { } }, 60);
}

function hideAuth() { $("#auth-mask").hidden = true; }

async function doLogin(password) {
  // 挑战-响应：x = sha256(salt + password)，回传 resp = sha256(x + nonce)。
  // 密码与 x 都不出本机，nonce 一次性防重放（明文 HTTP 下够用的登录保护）。
  const ch = await fetchRetry(BASE + "/api/auth/challenge");
  if (!ch.ok) throw new Error("获取挑战失败（" + ch.status + "）");
  const cc = await ch.json();
  const x = sha256hex(cc.salt + password);
  const res = await api("/api/auth/login", {
    method: "POST",
    body: { nonce: cc.nonce, resp: sha256hex(x + cc.nonce) },
  });
  try { localStorage.setItem(AUTH_KEY, res.token); } catch (e) { /* 无痕环境忽略 */ }
}

function bindAuth() {
  const box = $("#auth-box");
  if (!box) return;
  box.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("#auth-submit"), err = $("#auth-error");
    err.hidden = true;
    btn.disabled = true; btn.textContent = "验证中…";
    try {
      await doLogin($("#auth-password").value);
      hideAuth();
      location.reload();  // 登录成功整体重载，状态最干净
    } catch (e) {
      err.textContent = (e && e.message) || "登录失败，请重试";
      err.hidden = false;
      btn.disabled = false; btn.textContent = "进 入";
    }
  });
}

/* Markdown 渲染使用共享的 static/md.js（window.MindMD），与导出 HTML 保持一致 */

/* ================= 主题 ================= */

function loadTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem("minddock-theme");
  } catch (e) {
    /* 受限环境无 localStorage */
  }
  if (!saved) saved = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  return saved;
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#btn-theme").textContent = theme === "dark" ? "☀️" : "🌙";
  try {
    localStorage.setItem("minddock-theme", theme);
  } catch (e) {
    /* 忽略 */
  }
}

/* ================= 提示与弹窗 ================= */

function toast(msg, isError) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = msg;
  $("#toast-wrap").appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

function showModal(opts) {
  const mask = $("#modal-mask");
  const modal = $("#modal");
  modal.innerHTML =
    `<h3>${esc(opts.title)}</h3>` +
    `<div class="modal-body">${opts.bodyHTML || ""}</div>` +
    (opts.input ? `<input id="modal-input" placeholder="${esc(opts.inputPlaceholder || "")}" value="${esc(opts.inputValue || "")}">` : "") +
    `<div class="modal-actions"><button id="modal-cancel">取消</button><button id="modal-ok" class="primary">${esc(opts.okText || "确定")}</button></div>`;
  mask.hidden = false;
  const input = $("#modal-input");
  const close = () => {
    mask.hidden = true;
    document.removeEventListener("keydown", onKey);
  };
  const ok = () => {
    const val = input ? input.value : null;
    Promise.resolve(opts.onOk ? opts.onOk(val) : null).then(close).catch((e) => toast(e.message, true));
  };
  $("#modal-cancel").onclick = close;
  $("#modal-ok").onclick = ok;
  mask.onclick = (e) => {
    if (e.target === mask) close();
  };
  function onKey(e) {
    if (e.key === "Escape") close();
    if (e.key === "Enter" && input) ok();
  }
  document.addEventListener("keydown", onKey);
  if (input) {
    input.focus();
    input.select();
  }
}

function confirmModal(title, bodyText, onOk, danger) {
  showModal({
    title,
    bodyHTML: esc(bodyText),
    okText: danger ? "确认删除" : "确定",
    onOk,
  });
  if (danger) $("#modal-ok").style.background = "var(--danger)";
}

/* ================= 全局状态与路由 ================= */

const state = {
  view: "notes",
  query: "",
  tag: "",
  trashMode: false,
  notes: [],
  tagList: [],
  current: null,
  currentTags: [],
  dirty: false,
  previewOn: false,
  graphData: null,
  graphLoaded: false,
  cockpit: null,
  stats: null,
  meta: null,
};

function switchView(view) {
  state.view = view;
  $$(".view").forEach((v) => v.classList.remove("active"));
  $(`#view-${view}`).classList.add("active");
  $$("#main-nav .nav-btn, #mobile-nav .mnav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "graph") loadGraph();
  else if (sim) sim.stop(); // 离开图谱页停掉力导向循环，避免后台空转
  if (view === "cockpit") loadCockpit();
}

function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const seg = h.split("/");
  const view = ["notes", "graph", "cockpit"].includes(seg[0]) ? seg[0] : "notes";
  if (view !== state.view) switchView(view);
  if (view === "notes" && seg.length > 1) {
    const name = decodeURIComponent(seg.slice(1).join("/"));
    if (!state.current || state.current.name !== name) openNoteById(name, true);
  }
  if (view === "graph" && !state.graphLoaded) loadGraph();
}

function navTo(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

/* ================= 笔记列表 ================= */

async function refreshList() {
  if (state.trashMode) return refreshTrash();
  const q = state.query.trim();
  let url = "/api/notes";
  const params = [];
  if (q) params.push(`q=${enc(q)}`);
  if (state.tag) params.push(`tag=${enc(state.tag)}`);
  if (params.length) url += "?" + params.join("&");
  try {
    const data = await api(url);
    state.notes = data.items;
    renderList(q);
    $("#list-title").textContent = q ? `搜索“${q}”` : state.tag ? `标签：${state.tag}` : "最近笔记";
  } catch (e) {
    toast(e.message, true);
  }
}

function highlight(text, query) {
  const safe = esc(text);
  if (!query.trim()) return safe;
  const terms = query.trim().split(/\s+/).filter(Boolean).map(esc);
  let html = safe;
  for (const t of terms) {
    html = html.replace(new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), (m) => `<mark>${m}</mark>`);
  }
  return html;
}

function renderList(query) {
  const ul = $("#note-list");
  if (!state.notes.length) {
    ul.innerHTML = `<div class="list-empty">${state.query || state.tag ? "没有匹配的笔记" : "还没有笔记，点击右上角 ＋ 新建"}</div>`;
    return;
  }
  ul.innerHTML = state.notes
    .map(
      (n) => `
    <li class="note-item${state.current && state.current.name === n.name ? " active" : ""}" data-name="${esc(n.name)}">
      <div class="ni-title">${highlight(n.title, query)}</div>
      <div class="ni-excerpt">${highlight(n.excerpt || "", query)}</div>
      <div class="ni-meta">
        <span class="ni-date">${fmtDate(n.updated)}</span>
        ${n.tags.slice(0, 3).map((t) => `<span class="ni-tag">${esc(t)}</span>`).join("")}
      </div>
    </li>`
    )
    .join("");
}

async function refreshTrash() {
  try {
    const data = await api("/api/trash");
    const ul = $("#note-list");
    $("#list-title").textContent = "回收站";
    if (!data.items.length) {
      ul.innerHTML = '<div class="list-empty">回收站是空的</div>';
      return;
    }
    ul.innerHTML = data.items
      .map(
        (i) => `
      <li class="note-item" data-file="${esc(i.file)}">
        <div class="ni-title">${esc(i.name)}</div>
        <div class="ni-meta"><span class="ni-date">删除于 ${fmtDate(i.deleted)}</span></div>
        <div class="trash-actions">
          <button class="t-restore">↩ 恢复</button>
          <button class="t-purge">✕ 彻底删除</button>
        </div>
      </li>`
      )
      .join("");
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadTagBar() {
  try {
    const data = await api("/api/tags");
    state.tagList = data.tags;
    renderTagBar();
  } catch (e) {
    /* 静默 */
  }
}

function renderTagBar() {
  const bar = $("#tag-bar");
  const top = state.tagList.slice(0, 24);
  bar.innerHTML =
    `<button class="tag-chip${!state.tag ? " on" : ""}" data-tag="">全部</button>` +
    top
      .map(
        ([t, c]) =>
          `<button class="tag-chip${state.tag === t ? " on" : ""}" data-tag="${esc(t)}">${esc(t)} ${c}</button>`
      )
      .join("") +
    `<button class="tag-chip tag-edit-btn" id="btn-tag-rename" title="重命名标签（先点选要改的标签）">✎</button>`;
}

function renameTagDialog(oldTag) {
  if (!oldTag) {
    toast("请先点击选中一个标签，再点 ✎ 重命名");
    return;
  }
  showModal({
    title: `重命名标签「${oldTag}」`,
    bodyHTML: "全库该标签（含行内 #标签）将同步更新；若目标名已存在则为合并。",
    input: true,
    inputValue: oldTag,
    inputPlaceholder: "新的标签名",
    okText: "重命名",
    onOk: async (val) => {
      const nn = (val || "").trim().replace(/^#/, "");
      if (!nn) throw new Error("标签名不能为空");
      if (nn === oldTag) return;
      const n = await api("/api/tags/rename", { method: "POST", body: { old: oldTag, new: nn } });
      toast(`已更新 ${n} 篇笔记的标签`);
      if (state.tag === oldTag) state.tag = nn;
      await loadTagBar();
      await refreshList();
      if (state.current && !state.dirty && state.current.tags.includes(oldTag)) {
        await openNoteById(state.current.name, true);
      }
    },
  });
}

/* ================= 编辑器 ================= */

const autosave = debounce(() => saveCurrent(), 900);
const previewRefresh = debounce(() => {
  if (state.previewOn) $("#preview").innerHTML = MindMD.render($("#note-content").value, state.current && state.current.missing);
}, 250);

function showEditor(show) {
  $("#editor-empty").hidden = show;
  $("#editor").hidden = !show;
  if (isMobile()) {
    $("#btn-back").hidden = !show;
    $("#editor-panel").classList.toggle("show", show);
  }
}

async function openNoteById(name, fromRoute) {
  // 防丢字：上一篇还有未落盘的自动保存时，先强制落盘再切换
  if (state.dirty && state.current && state.current.name !== name) {
    await saveCurrent();
  }
  try {
    const note = await api(`/api/notes/${enc(name)}`);
    state.current = note;
    state.currentTags = note.tags.slice();
    state.dirty = false;
    $("#note-title").value = note.title;
    $("#note-content").value = note.content;
    renderTagEdit();
    renderBacklinks(note);
    renderOutline();
    applyPreview();
    showEditor(true);
    if (!fromRoute) navTo(`#/notes/${enc(note.name)}`);
    $("#save-state").textContent = "";
    if (isMobile()) $("#editor-panel").classList.add("show");
    $$("#note-list .note-item").forEach((li) => li.classList.toggle("active", li.dataset.name === note.name));
  } catch (e) {
    toast(e.message, true);
  }
}

function renderTagEdit() {
  const box = $("#tag-edit");
  box.innerHTML =
    state.currentTags.map((t) => `<span class="tag-pill">${esc(t)}<button data-tag="${esc(t)}" title="移除标签">✕</button></span>`).join("") +
    `<input id="tag-input" placeholder="+ 标签，回车确认">`;
  box.querySelector("#tag-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const val = e.target.value.trim().replace(/^#/, "");
      if (val && !state.currentTags.includes(val)) {
        state.currentTags.push(val);
        markDirty();
        renderTagEdit();
      }
    }
  });
}

function renderBacklinks(note) {
  const ul = $("#backlinks");
  $("#bk-count").textContent = note.incoming.length ? `(${note.incoming.length})` : "";
  ul.innerHTML = note.incoming.length
    ? note.incoming.map((n) => `<li data-name="${esc(n)}">${esc(n)}</li>`).join("")
    : '<span class="bk-none">暂无其他笔记链接到这里</span>';
}

function markDirty() {
  state.dirty = true;
  $("#save-state").textContent = "未保存…";
  $("#save-state").className = "save-state saving";
  autosave();
  previewRefresh();
}

async function saveCurrent() {
  if (!state.current) return;
  const payload = {
    name: state.current.name,
    title: $("#note-title").value,
    tags: state.currentTags,
    content: $("#note-content").value,
  };
  $("#save-state").textContent = "保存中…";
  try {
    const note = await api("/api/notes", { method: "POST", body: payload });
    state.current = note;
    state.dirty = false;
    renderOutline();
    const now = new Date();
    $("#save-state").textContent = `已保存 ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    $("#save-state").className = "save-state";
    refreshList();
  } catch (e) {
    $("#save-state").textContent = "保存失败";
    $("#save-state").className = "save-state";
    toast(e.message, true);
  }
}

async function newNoteDialog(prefill) {
  const templates = state.notes.filter((n) => n.tags.includes("模板"));
  const tplBar = templates.length
    ? `<div class="tpl-bar"><span class="tpl-label">从模板开始：</span>` +
      templates.map((t) => `<button class="tpl-chip" data-name="${esc(t.name)}">${esc(t.title)}</button>`).join("") +
      `</div>`
    : "";
  showModal({
    title: "新建笔记",
    input: true,
    inputPlaceholder: "笔记名，如：会议纪要 2026-09-07",
    bodyHTML: tplBar,
    onOk: async (val) => {
      const name = (val || "").trim();
      if (!name) throw new Error("笔记名不能为空");
      let content = `# ${name}\n\n`;
      const activeTpl = modalTemplate;
      if (activeTpl) {
        const tpl = await api(`/api/notes/${enc(activeTpl)}`);
        content = tpl.content;
      }
      const note = await api("/api/notes", {
        method: "POST",
        body: { name, content, title: name },
      });
      state.query = "";
      $("#global-search").value = "";
      state.trashMode = false;
      modalTemplate = null;
      await refreshList();
      await openNoteById(note.name);
      $("#note-content").focus();
      toast(`已创建「${name}」` + (activeTpl ? `（来自模板）` : ""));
    },
  });
  if (prefill) $("#modal-input").value = prefill;
  let modalTemplate = null;
  $$("#modal .tpl-chip").forEach((chip) => {
    chip.onclick = () => {
      $$("#modal .tpl-chip").forEach((c) => c.classList.remove("on"));
      if (modalTemplate === chip.dataset.name) {
        modalTemplate = null; // 再点一次取消模板
      } else {
        modalTemplate = chip.dataset.name;
        chip.classList.add("on");
      }
    };
  });
}

function deleteCurrent() {
  if (!state.current) return;
  const name = state.current.name;
  confirmModal("删除笔记", `确定把「${name}」移入回收站吗？可随时恢复。`, async () => {
    await api(`/api/notes/${enc(name)}`, { method: "DELETE" });
    toast("已移入回收站");
    state.current = null;
    showEditor(false);
    refreshList();
    loadTagBar();
  }, true);
}

function applyPreview() {
  const body = $(".editor-body");
  body.classList.toggle("with-preview", state.previewOn);
  body.classList.toggle("show-source", !state.previewOn && isMobile());
  $("#preview").hidden = !state.previewOn;
  $("#btn-preview").textContent = state.previewOn ? "编辑" : "预览";
  if (state.previewOn) $("#preview").innerHTML = MindMD.render($("#note-content").value, state.current && state.current.missing);
}

function downloadBlob(text, filename) {
  const blob = new Blob([text], { type: "text/html;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
}

async function exportCurrentNote() {
  if (!state.current) return;
  const n = state.current;
  const mdSrc = await (await fetch(`${BASE}/static/md.js`)).text();
  const safeMd = mdSrc.replace(/<\/script>/gi, "<\\/script>");
  // 引用到的图片转 data URI，保证单文件离线可看
  const imgRe = /!\[[^\]]*\]\((attachments\/[^)\s]+)\)/g;
  const paths = [];
  let m;
  while ((m = imgRe.exec(n.content))) {
    if (!paths.includes(m[1])) paths.push(m[1]);
  }
  const imgMap = {};
  for (const p of paths) {
    try {
      const blob = await (await fetch(`${BASE}/${enc(p)}`)).blob();
      const dataUrl = await new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(fr.result);
        fr.onerror = () => reject(new Error("图片读取失败"));
        fr.readAsDataURL(blob);
      });
      imgMap[p] = dataUrl;
    } catch (e) {
      /* 缺图就保留原相对路径 */
    }
  }
  let rendered = MindMD.render(n.content, n.missing);
  for (const [p, uri] of Object.entries(imgMap)) {
    rendered = rendered.split(`src="${p}"`).join(`src="${uri}"`);
  }
  const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(n.title)}</title>
<style>body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;max-width:820px;margin:0 auto;padding:28px 20px;color:#20263a;line-height:1.7}
h1{font-size:23px}.tags span{background:rgba(79,109,245,.12);color:#4f6df5;font-size:12px;padding:2px 10px;border-radius:999px;margin-right:6px}
.meta{color:#6d7488;font-size:12px;margin-bottom:18px}
pre{background:#f0f2f8;border-radius:10px;padding:12px 14px;overflow-x:auto}code{font-family:Consolas,monospace;font-size:13px;background:rgba(79,109,245,.1);padding:.5px 5px;border-radius:5px}
pre code{background:none;padding:0}blockquote{border-left:3px solid #4f6df5;background:rgba(79,109,245,.08);margin:.6em 0;padding:6px 14px;border-radius:0 8px 8px 0;color:#6d7488}
table{border-collapse:collapse;font-size:13px}th,td{border:1px solid #e2e5ef;padding:5px 10px}
.wikilink{color:#4f6df5;background:rgba(79,109,245,.12);padding:0 5px;border-radius:5px}.inline-tag{color:#4f6df5}
.md img{max-width:100%;border-radius:8px}
footer{color:#9aa1b4;font-size:11.5px;margin-top:40px;text-align:center}</style></head>
<body><h1>${esc(n.title)}</h1><div class="tags">${n.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>
<div class="meta">更新于 ${esc(String(n.updated).slice(0, 16).replace("T", " "))}</div>
<div class="md">${rendered}</div>
<footer>导出自 MindDock · ${esc(n.name)}</footer>
<script>${safeMd}<\/script></body></html>`;
  downloadBlob(html, `${n.name}.html`);
  toast("已导出单篇 HTML");
}

async function showHistory() {
  if (!state.current) return;
  const name = state.current.name;
  let data;
  try {
    data = await api(`/api/notes/${enc(name)}?history=1`);
  } catch (e) {
    toast(e.message, true);
    return;
  }
  const rows = data.items.length
    ? data.items
        .map(
          (v) => `
      <div class="hist-row" data-file="${esc(v.file)}">
        <span class="hist-time">${esc(String(v.time).slice(0, 19).replace("T", " "))}</span>
        <span class="hist-size">${(v.size / 1024).toFixed(1)} KB</span>
        <button class="hist-view">查看</button>
        <button class="hist-restore">恢复此版本</button>
      </div>`
        )
        .join("")
    : '<div class="modal-body">暂无历史版本。每次保存都会自动留档（保留最近 20 个），从下一次修改开始生效。</div>';
  showModal({ title: `版本历史 · ${name}`, bodyHTML: rows, okText: "关闭" });
  const modal = $("#modal");
  modal.onclick = async (e) => {
    const viewBtn = e.target.closest(".hist-view");
    const restoreBtn = e.target.closest(".hist-restore");
    if (viewBtn) {
      const row = viewBtn.closest(".hist-row");
      try {
        const v = await api(`/api/notes/${enc(name)}/history/${enc(row.dataset.file)}`);
        const bodyEl = modal.querySelector(".modal-body");
        let preWrap = bodyEl.querySelector("#hist-pre-wrap");
        if (!preWrap) {
          preWrap = document.createElement("div");
          preWrap.id = "hist-pre-wrap";
          preWrap.style.marginTop = "10px";
          bodyEl.appendChild(preWrap);
        }
        preWrap.innerHTML =
          `<div class="hist-pre-title">${esc(row.querySelector(".hist-time").textContent)} 的内容：</div>` +
          `<pre class="hist-pre">${esc(v.content)}</pre>`;
      } catch (err) {
        toast(err.message, true);
      }
    } else if (restoreBtn) {
      if (restoreBtn.dataset.armed !== "1") {
        restoreBtn.dataset.armed = "1";
        restoreBtn.textContent = "确认恢复？";
        restoreBtn.classList.add("armed");
        return;
      }
      try {
        const note = await api(`/api/notes/${enc(name)}/history/${enc(restoreBtn.closest(".hist-row").dataset.file)}/restore`, {
          method: "POST",
          body: {},
        });
        $("#modal-mask").hidden = true;
        state.current = note;
        state.currentTags = note.tags.slice();
        $("#note-title").value = note.title;
        $("#note-content").value = note.content;
        renderTagEdit();
        renderBacklinks(note);
        renderOutline();
        applyPreview();
        toast("已恢复到所选版本");
        refreshList();
      } catch (err) {
        toast(err.message, true);
      }
    }
  };
}

function renameCurrent() {
  if (!state.current) return;
  showModal({
    title: "重命名笔记",
    input: true,
    inputValue: state.current.name,
    inputPlaceholder: "新的笔记名",
    okText: "重命名",
    onOk: async (val) => {
      const nn = (val || "").trim();
      if (!nn || nn === state.current.name) return;
      const note = await api(`/api/notes/${enc(state.current.name)}/rename`, {
        method: "POST",
        body: { new_name: nn },
      });
      toast(`已重命名为「${nn}」，全库双链已同步`);
      await refreshList();
      await openNoteById(note.name);
    },
  });
}

/* ================= 图谱 ================= */

const PALETTE = ["#4f6df5", "#16a34a", "#d97706", "#dc2626", "#0891b2", "#7c3aed", "#db2777", "#65a30d", "#ea580c", "#0d9488"];
function tagColor(tag) {
  if (!tag) return "#94a3b8";
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

let sim = null;

async function loadGraph() {
  try {
    const fresh = await api("/api/graph");
    const changed =
      !state.graphData ||
      fresh.nodes.length !== state.graphData.nodes.length ||
      fresh.links.length !== state.graphData.links.length;
    state.graphData = fresh;
    if (changed || !sim) {
      if (sim) sim.stop();
      sim = createSim($("#graph-canvas"), state.graphData);
    }
    state.graphLoaded = true;
    renderGraphLegend();
    sim.start();
  } catch (e) {
    toast(e.message, true);
  }
}

function renderGraphLegend() {
  const g = state.graphData;
  $("#graph-legend").innerHTML =
    '<div class="gl-title">标签着色</div>' +
    g.top_tags
      .map(
        (o) =>
          `<div class="gl-item" data-tag="${esc(o.tag)}"><span class="gl-dot" style="background:${tagColor(o.tag)}"></span>${esc(o.tag)} · ${o.count}</div>`
      )
      .join("");
  $$("#graph-legend .gl-item").forEach((el) => {
    el.onclick = () => {
      el.classList.toggle("on");
      sim.highlightTag(el.classList.contains("on") ? el.dataset.tag : null);
    };
  });
}

function createSim(canvas, graphData) {
  const ctx = canvas.getContext("2d");
  const nodes = graphData.nodes.map((n) => ({
    ...n,
    x: (Math.random() - 0.5) * 400,
    y: (Math.random() - 0.5) * 400,
    vx: 0,
    vy: 0,
    r: n.missing ? 5 : Math.min(7 + n.degree * 1.6, 17),
    color: n.missing ? "#d97706" : tagColor(n.tags[0]),
  }));
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const links = graphData.links.map((l) => ({ source: byId[l.source], target: byId[l.target] })).filter((l) => l.source && l.target);
  const view = { x: 0, y: 0, scale: 1 };
  let highlight = null;
  let running = false;
  let raf = 0;
  let drag = null;
  let panning = false;
  let moved = false;
  let hover = null;
  const dpr = window.devicePixelRatio || 1;

  function resize() {
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
  }
  resize();
  window.addEventListener("resize", resize);

  function step() {
    // 斥力
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d2 = 1;
        }
        const d = Math.sqrt(d2);
        const f = 2200 / d2;
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
      // 向心力
      a.vx -= a.x * 0.0035;
      a.vy -= a.y * 0.0035;
    }
    // 弹簧
    for (const l of links) {
      const dx = l.target.x - l.source.x;
      const dy = l.target.y - l.source.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 95) * 0.012;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      l.source.vx += fx;
      l.source.vy += fy;
      l.target.vx -= fx;
      l.target.vy -= fy;
    }
    for (const n of nodes) {
      if (n === drag) {
        n.vx = 0;
        n.vy = 0;
        continue;
      }
      n.vx *= 0.86;
      n.vy *= 0.86;
      n.x += Math.max(-6, Math.min(6, n.vx));
      n.y += Math.max(-6, Math.min(6, n.vy));
    }
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.translate(canvas.clientWidth / 2 + view.x, canvas.clientHeight / 2 + view.y);
    ctx.scale(view.scale, view.scale);
    // 边
    for (const l of links) {
      const dim = highlight && l.source.tags[0] !== highlight && l.target.tags[0] !== highlight;
      ctx.strokeStyle = dim ? "rgba(128,138,160,0.10)" : "rgba(128,138,160,0.35)";
      if (l.target.missing) ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // 节点
    const labelColor = getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#333";
    for (const n of nodes) {
      const dim = highlight && n.tags[0] !== highlight && !n.missing;
      ctx.globalAlpha = dim ? 0.18 : 1;
      if (n.missing) {
        ctx.strokeStyle = n.color;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = n.color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = dim ? 0.25 : 0.9;
      ctx.fillStyle = labelColor;
      ctx.font = `${n === hover ? 700 : 400} ${n.missing ? 10 : 11}px "Segoe UI", sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(n.title, n.x, n.y + n.r + 13);
      ctx.globalAlpha = 1;
    }
  }

  function loop() {
    if (!running) return;
    step();
    draw();
    raf = requestAnimationFrame(loop);
  }

  function toWorld(px, py) {
    return {
      x: (px - canvas.clientWidth / 2 - view.x) / view.scale,
      y: (py - canvas.clientHeight / 2 - view.y) / view.scale,
    };
  }
  function pickNode(e) {
    const rect = canvas.getBoundingClientRect();
    const p = toWorld(e.clientX - rect.left, e.clientY - rect.top);
    for (const n of nodes) {
      if ((p.x - n.x) ** 2 + (p.y - n.y) ** 2 <= (n.r + 4) ** 2) return n;
    }
    return null;
  }

  canvas.addEventListener("mousedown", (e) => {
    moved = false;
    const n = pickNode(e);
    if (n) {
      drag = n;
    } else {
      panning = true;
    }
    canvas.classList.add("dragging");
  });
  window.addEventListener("mousemove", (e) => {
    if (drag) {
      moved = true;
      const rect = canvas.getBoundingClientRect();
      const p = toWorld(e.clientX - rect.left, e.clientY - rect.top);
      drag.x = p.x;
      drag.y = p.y;
    } else if (panning) {
      moved = true;
      view.x += e.movementX;
      view.y += e.movementY;
    } else {
      hover = pickNode(e);
      canvas.style.cursor = hover ? "pointer" : "grab";
    }
  });
  window.addEventListener("mouseup", (e) => {
    if (drag && !moved) {
      if (drag.missing) {
        newNoteDialog(drag.title);
      } else {
        navTo("#/notes");
        openNoteById(drag.id);
      }
    }
    drag = null;
    panning = false;
    canvas.classList.remove("dragging");
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    view.scale = Math.min(3, Math.max(0.3, view.scale * factor));
  }, { passive: false });
  window.addEventListener("resize", () => {
    if (running) draw();
  });

  return {
    start() {
      if (running) return;
      running = true;
      resize();
      loop();
    },
    stop() {
      running = false;
      cancelAnimationFrame(raf);
    },
    highlightTag(tag) {
      highlight = tag;
    },
  };
}

/* ================= 驾驶舱 ================= */

async function loadCockpit() {
  try {
    const [ws, stats] = await Promise.all([api("/api/workspace"), api("/api/stats")]);
    state.cockpit = ws;
    state.stats = stats;
    renderCockpit();
  } catch (e) {
    toast(e.message, true);
  }
}

function donutSvg(done, active, other) {
  const total = done + active + other || 1;
  const C = 2 * Math.PI * 40;
  const segs = [
    ["var(--ok)", done],
    ["var(--warn)", active],
    ["#94a3b8", other],
  ];
  let offset = 0;
  let circles = "";
  for (const [color, val] of segs) {
    if (!val) continue;
    const len = (val / total) * C;
    circles += `<circle r="40" cx="60" cy="60" fill="none" stroke="${color}" stroke-width="16" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-offset}" transform="rotate(-90 60 60)"></circle>`;
    offset += len;
  }
  return `<svg width="120" height="120" viewBox="0 0 120 120">
    <circle r="40" cx="60" cy="60" fill="none" stroke="var(--panel-2)" stroke-width="16"></circle>${circles}
    <text x="60" y="57" text-anchor="middle" font-size="20" font-weight="700" fill="var(--text)">${total}</text>
    <text x="60" y="74" text-anchor="middle" font-size="10" fill="var(--muted)">个项目</text>
  </svg>`;
}

function activitySvg(activity) {
  const days = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    days.push({ key, count: activity[key] || 0, label: `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` });
  }
  const max = Math.max(1, ...days.map((d) => d.count));
  const W = 700, H = 130, bw = W / 30;
  let bars = "";
  days.forEach((d, i) => {
    const h = (d.count / max) * 95;
    bars += `<rect class="bar" x="${(i * bw + bw * 0.18).toFixed(1)}" y="${(110 - h).toFixed(1)}" width="${(bw * 0.64).toFixed(1)}" height="${h.toFixed(1)}"><title>${d.key}：${d.count} 篇更新</title></rect>`;
    if (i % 5 === 0) bars += `<text class="axis" x="${(i * bw + bw / 2).toFixed(1)}" y="126" text-anchor="middle">${d.label}</text>`;
  });
  return `<svg class="activity-chart" viewBox="0 0 700 130" preserveAspectRatio="none">${bars}</svg>`;
}

function renderCockpit() {
  const ws = state.cockpit;
  const st = state.stats;
  const s = ws.stats;
  const root = $("#cockpit-root");
  const isDemo = state.meta && state.meta.workspace_is_demo;
  root.innerHTML = `
    <div class="cockpit-head">
      <h1>🛳 工作区驾驶舱</h1>
      ${isDemo ? '<span class="badge-demo">演示数据</span>' : ""}
      <span class="cockpit-sub">${esc(ws.root || "")}（只读）</span>
      <a class="chip-btn" href="/api/export/book" style="margin-left:auto;text-decoration:none">⬇ 整库导出</a>
    </div>
    ${ws.error ? `<div class="cockpit-error">⚠ ${esc(ws.error)}</div>` : ""}
    <div class="stat-grid">
      <div class="stat-card"><div class="sc-num">${st.total}</div><div class="sc-label">笔记总数</div></div>
      <div class="stat-card tone-accent"><div class="sc-num">${st.words.toLocaleString()}</div><div class="sc-label">累计字数</div></div>
      <div class="stat-card"><div class="sc-num">${st.tag_count}</div><div class="sc-label">标签数</div></div>
      <div class="stat-card tone-warn"><div class="sc-num">${st.trash_count}</div><div class="sc-label">回收站</div></div>
      <div class="stat-card tone-accent"><div class="sc-num">${s.project_total}</div><div class="sc-label">项目总数</div></div>
      <div class="stat-card tone-ok"><div class="sc-num">${s.done}</div><div class="sc-label">已完成项目</div></div>
      <div class="stat-card tone-warn"><div class="sc-num">${s.active}</div><div class="sc-label">进行中项目</div></div>
      <div class="stat-card"><div class="sc-num">${s.lesson_count}</div><div class="sc-label">有效避坑教训</div></div>
    </div>
    <div class="cockpit-grid">
      <div class="panel">
        <h2>项目登记表<span class="h2-sub">projects/README.md</span></h2>
        ${
          ws.projects.length
            ? `<table class="proj-table"><thead><tr><th>序号</th><th>项目</th><th>状态</th></tr></thead><tbody>${ws.projects
                .map(
                  (p) =>
                    `<tr><td>${esc(p.seq)}</td><td><div class="proj-dir">${esc(p.dir)}</div><div class="proj-desc">${esc(p.desc)}</div></td><td><span class="status-badge status-${p.status_class}" title="${esc(p.status)}">${esc(p.status)}</span></td></tr>`
                )
                .join("")}</tbody></table>`
            : '<div class="bk-none">未解析到项目</div>'
        }
      </div>
      <div>
        <div class="panel" style="margin-bottom:14px">
          <h2>项目状态分布</h2>
          <div class="donut-wrap">
            ${donutSvg(s.done, s.active, s.other)}
            <div class="donut-legend">
              <div class="dl-item"><span class="dl-dot" style="background:var(--ok)"></span>已完成 <b class="dl-num">${s.done}</b></div>
              <div class="dl-item"><span class="dl-dot" style="background:var(--warn)"></span>进行中 <b class="dl-num">${s.active}</b></div>
              <div class="dl-item"><span class="dl-dot" style="background:#94a3b8"></span>其他 <b class="dl-num">${s.other}</b></div>
            </div>
          </div>
        </div>
        <div class="panel">
          <h2>近 30 天笔记活跃度</h2>
          ${activitySvg(st.activity)}
        </div>
      </div>
    </div>
    <div class="panel" style="margin-bottom:14px">
      <h2>标签分布</h2>
      ${st.tags
        .slice(0, 10)
        .map(([t, c]) => {
          const max = st.tags[0][1];
          return `<div class="tag-dist-row"><span class="td-name">${esc(t)}</span><div class="td-bar-wrap"><div class="td-bar" style="width:${(c / max) * 100}%"></div></div><span class="td-count">${c}</span></div>`;
        })
        .join("")}
    </div>
    <div class="panel" style="margin-bottom:14px">
      <h2>当前有效教训<span class="h2-sub">docs/pitfall-log.md</span></h2>
      <div class="lesson-list">
        ${ws.pitfalls.lessons
          .map(
            (l, i) =>
              `<div class="lesson-card"><div class="lc-title"><span class="lesson-num">${i + 1}</span>${esc(l.title)}</div><div class="lc-desc">${esc(l.desc)}</div></div>`
          )
          .join("") || '<div class="bk-none">暂无教训</div>'}
      </div>
    </div>
    <div class="panel">
      <h2>历史避坑记录</h2>
      ${ws.pitfalls.dated
        .map(
          (d) => `
        <details class="pit-dated">
          <summary><span class="pd-date">${esc(d.date)}</span>${esc(d.title)}</summary>
          <ul>${d.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
        </details>`
        )
        .join("") || '<div class="bk-none">暂无归档记录</div>'}
    </div>`;
}

/* ================= 双链自动补全 ================= */

const wikiAc = { el: null, items: [], active: 0, from: -1 };

function wikiAcEnsure() {
  if (wikiAc.el) return wikiAc.el;
  wikiAc.el = document.createElement("div");
  wikiAc.el.id = "wiki-ac";
  wikiAc.el.hidden = true;
  $(".editor-body").appendChild(wikiAc.el);
  wikiAc.el.addEventListener("mousedown", (e) => {
    const item = e.target.closest(".ac-item");
    if (item) {
      e.preventDefault();
      wikiAcPick(Number(item.dataset.idx));
    }
  });
  return wikiAc.el;
}

function caretPosInTextarea(ta, pos) {
  const div = document.createElement("div");
  const st = getComputedStyle(ta);
  for (const p of ["fontFamily", "fontSize", "lineHeight", "padding", "borderWidth", "borderStyle", "width", "letterSpacing", "boxSizing", "tabSize"]) {
    div.style[p] = st[p];
  }
  div.style.position = "absolute";
  div.style.visibility = "hidden";
  div.style.whiteSpace = "pre-wrap";
  div.style.wordWrap = "break-word";
  div.textContent = ta.value.slice(0, pos);
  const span = document.createElement("span");
  span.textContent = "\u200b";
  div.appendChild(span);
  ta.parentNode.appendChild(div);
  const pt = { x: span.offsetLeft, y: span.offsetTop };
  div.remove();
  return pt;
}

function wikiAcUpdate() {
  const ta = $("#note-content");
  const pos = ta.selectionStart;
  const before = ta.value.slice(0, pos);
  const open = before.lastIndexOf("[[");
  if (open === -1 || before.slice(open, pos).includes("]]") || before.includes("\n", open)) {
    wikiAcHide();
    return;
  }
  const query = before.slice(open + 2).toLowerCase();
  const pool = state.notes
    .map((n) => ({ name: n.name, title: n.title }))
    .filter((n) => n.name.toLowerCase().includes(query) || n.title.toLowerCase().includes(query))
    .slice(0, 7);
  if (!pool.length) {
    wikiAcHide();
    return;
  }
  wikiAc.items = pool;
  wikiAc.active = 0;
  wikiAc.from = open + 2;
  const el = wikiAcEnsure();
  el.innerHTML = pool
    .map(
      (n, i) =>
        `<div class="ac-item${i === 0 ? " on" : ""}" data-idx="${i}">${esc(n.title)}<span class="ac-name">${esc(n.name)}</span></div>`
    )
    .join("");
  const pt = caretPosInTextarea(ta, pos);
  const lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 21;
  const body = $(".editor-body").getBoundingClientRect();
  const taRect = ta.getBoundingClientRect();
  el.style.left = `${taRect.left - body.left + Math.min(pt.x, taRect.width - 260)}px`;
  el.style.top = `${taRect.top - body.top + pt.y - ta.scrollTop + lineHeight + 6}px`;
  el.hidden = false;
}

function wikiAcHide() {
  if (wikiAc.el) wikiAc.el.hidden = true;
  wikiAc.items = [];
}

function wikiAcPick(idx) {
  const ta = $("#note-content");
  const item = wikiAc.items[idx];
  if (!item) return;
  const pos = ta.selectionStart;
  const after = ta.value.slice(pos);
  const rest = after.startsWith("]]") ? "" : "]]";
  ta.value = ta.value.slice(0, wikiAc.from) + item.name + rest + after;
  const newPos = wikiAc.from + item.name.length + 2;
  ta.setSelectionRange(newPos, newPos);
  wikiAcHide();
  markDirty();
  ta.focus();
}

function wikiAcKeydown(e) {
  if (wikiAc.el.hidden || !wikiAc.items.length) return false;
  const items = $$("#wiki-ac .ac-item");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    wikiAc.active = (wikiAc.active + (e.key === "ArrowDown" ? 1 : wikiAc.items.length - 1)) % wikiAc.items.length;
    items.forEach((el, i) => el.classList.toggle("on", i === wikiAc.active));
    items[wikiAc.active].scrollIntoView({ block: "nearest" });
    return true;
  }
  if (e.key === "Enter" || e.key === "Tab") {
    e.preventDefault();
    wikiAcPick(wikiAc.active);
    return true;
  }
  if (e.key === "Escape") {
    e.preventDefault();
    wikiAcHide();
    return true;
  }
  return false;
}

/* ================= 图片附件 ================= */

async function uploadImageFile(file) {
  const dataUrl = await new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(new Error("读取图片失败"));
    fr.readAsDataURL(file);
  });
  const b64 = dataUrl.split(",")[1] || "";
  const out = await api("/api/attachments", {
    method: "POST",
    body: { name: file.name || "image.png", data_b64: b64 },
  });
  return out.path;
}

function insertAtCaret(text) {
  const ta = $("#note-content");
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  ta.value = ta.value.slice(0, s) + text + ta.value.slice(e);
  ta.setSelectionRange(s + text.length, s + text.length);
  markDirty();
}

async function handleImageFiles(files) {
  for (const f of files) {
    if (!f.type || !f.type.startsWith("image/")) {
      toast("只支持图片文件", true);
      continue;
    }
    try {
      const path = await uploadImageFile(f);
      insertAtCaret(`\n![](${path})\n`);
      toast("图片已入库");
    } catch (e) {
      toast(e.message, true);
    }
  }
}

/* ================= 命令面板（Ctrl+P 快速跳转） ================= */

const palette = { el: null, input: null, listEl: null, notes: [], active: 0 };

function paletteEnsure() {
  if (palette.el) return;
  palette.el = document.createElement("div");
  palette.el.id = "palette-mask";
  palette.el.hidden = true;
  palette.el.innerHTML =
    '<div id="palette"><input id="palette-input" placeholder="跳转到笔记…（↑↓ 选择，回车打开）"><div id="palette-list"></div></div>';
  document.body.appendChild(palette.el);
  palette.input = palette.el.querySelector("#palette-input");
  palette.listEl = palette.el.querySelector("#palette-list");
  palette.el.addEventListener("mousedown", (e) => {
    if (e.target === palette.el) paletteClose();
  });
  palette.input.addEventListener("input", paletteRender);
  palette.input.addEventListener("keydown", (e) => {
    const items = $$("#palette-list .pal-item");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      palette.active = (palette.active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      items.forEach((el, i) => el.classList.toggle("on", i === palette.active));
      items[palette.active].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (items[palette.active]) items[palette.active].click();
    } else if (e.key === "Escape") {
      e.preventDefault();
      paletteClose();
    }
  });
  palette.listEl.addEventListener("click", (e) => {
    const item = e.target.closest(".pal-item");
    if (item) {
      paletteClose();
      openNoteById(item.dataset.name);
    }
  });
}

async function paletteOpen() {
  paletteEnsure();
  palette.el.hidden = false;
  palette.input.value = "";
  palette.active = 0;
  try {
    const data = await api("/api/notes");
    palette.notes = data.items;
  } catch (e) {
    palette.notes = [];
  }
  paletteRender();
  palette.input.focus();
}

function paletteClose() {
  if (palette.el) palette.el.hidden = true;
}

function paletteRender() {
  const kw = palette.input.value.trim().toLowerCase();
  const pool = palette.notes
    .filter((n) => !kw || n.name.toLowerCase().includes(kw) || n.title.toLowerCase().includes(kw))
    .slice(0, 9);
  palette.active = Math.min(palette.active, Math.max(0, pool.length - 1));
  palette.listEl.innerHTML = pool.length
    ? pool
        .map(
          (n, i) =>
            `<div class="pal-item${i === palette.active ? " on" : ""}" data-name="${esc(n.name)}">
              <span class="pal-title">${esc(n.title)}</span>
              <span class="pal-tags">${esc(n.tags.slice(0, 2).join(" / "))}</span>
            </div>`
        )
        .join("")
    : '<div class="pal-empty">没有匹配的笔记</div>';
}

/* ================= 大纲导航 ================= */

function renderOutline() {
  const wrap = $("#outline-panel");
  const hs = state.current && state.current.headings ? state.current.headings : [];
  $("#outline-count").textContent = hs.length ? `(${hs.length})` : "";
  wrap.innerHTML = hs.length
    ? hs.slice(0, 30).map((h) => `<li data-h="${esc(h)}">${esc(h)}</li>`).join("")
    : '<span class="bk-none">正文暂无标题行</span>';
}

function outlineJump(h) {
  if (state.previewOn) {
    const target = [...$("#preview").querySelectorAll("h1,h2,h3,h4,h5,h6")].find(
      (el) => el.textContent.trim() === h
    );
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
  }
  const ta = $("#note-content");
  const lines = ta.value.split("\n");
  const lineIdx = lines.findIndex((l) => {
    const m = /^#{1,6}\s+(.+?)\s*#*\s*$/.exec(l.trim());
    return m && m[1] === h;
  });
  if (lineIdx >= 0) {
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 21;
    ta.scrollTop = Math.max(0, lineIdx * lh - 40);
  }
}

/* ================= 事件绑定与启动 ================= */

function bindEvents() {
  $("#btn-theme").onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  $("#btn-new").onclick = () => newNoteDialog();
  $("#btn-daily").onclick = async () => {
    try {
      const note = await api("/api/daily");
      state.trashMode = false;
      navTo("#/notes");
      await openNoteById(note.name);
      toast("今日笔记就绪");
    } catch (e) {
      toast(e.message, true);
    }
  };
  $$("#main-nav .nav-btn, #mobile-nav .mnav-btn").forEach((b) => {
    b.onclick = () => navTo(`#/${b.dataset.view}`);
  });
  $("#btn-trash").onclick = () => {
    state.trashMode = !state.trashMode;
    $("#btn-trash").classList.toggle("on", state.trashMode);
    if (state.trashMode) refreshTrash();
    else refreshList();
  };
  $("#btn-back").onclick = () => {
    $("#editor-panel").classList.remove("show");
    $("#btn-back").hidden = true;
  };
  $("#btn-preview").onclick = () => {
    state.previewOn = !state.previewOn;
    applyPreview();
  };
  $("#btn-delete").onclick = deleteCurrent;
  $("#btn-rename").onclick = renameCurrent;
  $("#btn-history").onclick = () => showHistory();
  $("#btn-export").onclick = () => exportCurrentNote().catch((e) => toast(e.message, true));

  // 搜索
  const searchDebounced = debounce(() => {
    if (state.view !== "notes") navTo("#/notes");
    refreshList();
  }, 350);
  $("#global-search").addEventListener("input", (e) => {
    state.query = e.target.value;
    searchDebounced();
  });
  $("#global-search").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.target.value = "";
      state.query = "";
      refreshList();
      e.target.blur();
    }
  });

  // 标签栏：筛选；✎ 重命名当前选中标签
  $("#tag-bar").addEventListener("click", (e) => {
    const editBtn = e.target.closest("#btn-tag-rename");
    if (editBtn) {
      renameTagDialog(state.tag);
      return;
    }
    const chip = e.target.closest(".tag-chip");
    if (!chip) return;
    state.tag = chip.dataset.tag;
    refreshList();
  });

  // 列表点击（事件委托：普通/搜索/回收站三种条目）
  $("#note-list").addEventListener("click", (e) => {
    const restoreBtn = e.target.closest(".t-restore");
    if (restoreBtn) {
      const file = restoreBtn.closest("li").dataset.file;
      api(`/api/trash/${enc(file)}/restore`, { method: "POST" })
        .then((n) => {
          toast(`已恢复「${n.name}」`);
          refreshTrash();
          loadTagBar();
        })
        .catch((err) => toast(err.message, true));
      return;
    }
    const purgeBtn = e.target.closest(".t-purge");
    if (purgeBtn) {
      const li = purgeBtn.closest("li");
      confirmModal("彻底删除", `彻底删除「${li.querySelector(".ni-title").textContent}」？此操作不可恢复。`, async () => {
        await api(`/api/trash/${enc(li.dataset.file)}`, { method: "DELETE" });
        toast("已彻底删除");
        refreshTrash();
      }, true);
      return;
    }
    const li = e.target.closest(".note-item");
    if (li && li.dataset.name) openNoteById(li.dataset.name);
  });

  // 编辑器
  $("#note-title").addEventListener("input", markDirty);
  $("#note-content").addEventListener("input", markDirty);
  $("#note-content").addEventListener("input", wikiAcUpdate);
  $("#note-content").addEventListener("keydown", (e) => {
    if (wikiAcKeydown(e)) e.stopPropagation();
  });
  $("#note-content").addEventListener("click", wikiAcHide);
  $("#note-content").addEventListener("blur", () => setTimeout(wikiAcHide, 150));
  // 粘贴/拖拽图片入库
  $("#note-content").addEventListener("paste", (e) => {
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []).filter((f) => f.type.startsWith("image/"));
    if (files.length) {
      e.preventDefault();
      handleImageFiles(files);
    }
  });
  $("#note-content").addEventListener("dragover", (e) => e.preventDefault());
  $("#note-content").addEventListener("drop", (e) => {
    const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []).filter((f) => f.type.startsWith("image/"));
    if (files.length) {
      e.preventDefault();
      handleImageFiles(files);
    }
  });
  $("#tag-edit").addEventListener("click", (e) => {
    const btn = e.target.closest(".tag-pill button");
    if (btn) {
      state.currentTags = state.currentTags.filter((t) => t !== btn.dataset.tag);
      markDirty();
      renderTagEdit();
    }
  });

  // 预览区与反链（委托）
  $("#outline-panel").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-h]");
    if (li) outlineJump(li.dataset.h);
  });
  $("#preview").addEventListener("click", (e) => {
    const a = e.target.closest("a.wikilink");
    if (a) {
      e.preventDefault();
      const name = a.dataset.note;
      if (a.classList.contains("missing")) newNoteDialog(name);
      else openNoteById(name);
    }
  });
  $("#backlinks").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-name]");
    if (li) openNoteById(li.dataset.name);
  });

  // 图例标签高亮事件在 renderGraphLegend 里绑定

  // 全局快捷键
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      $("#global-search").focus();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "p") {
      e.preventDefault();
      paletteOpen();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (state.current) saveCurrent();
    }
  });

  // 移动端编辑面板随视口变化复位
  window.addEventListener("resize", () => {
    if (!isMobile()) {
      $("#editor-panel").classList.remove("show");
      $("#btn-back").hidden = true;
    } else if (state.current) {
      $("#btn-back").hidden = false;
    }
  });
}

async function boot() {
  applyTheme(loadTheme());
  bindEvents();
  bindAuth();
  window.addEventListener("hashchange", route);
  // 鉴权探测：服务端启用登录且会话无效时，只弹登录层不拉数据
  try {
    const t0 = authToken();
    const c = await fetchRetry(BASE + "/api/auth/check",
      t0 ? { headers: { Authorization: "Bearer " + t0 } } : undefined
    ).then((r) => r.json());
    if (c.enabled && !c.ok) { showAuth(); return; }
  } catch (e) { /* 服务不可达时仍尝试正常启动，错误交给具体请求 */ }
  try {
    state.meta = await api("/api/meta");
  } catch (e) {
    /* 首次加载失败不阻塞 */
  }
  await Promise.all([refreshList(), loadTagBar()]);
  route();
  if (!location.hash) location.hash = "#/notes";
  // PWA：service worker 相对 BASE 注册，scope 即应用子路径
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(BASE + "/sw.js").catch(() => { });
  }
}

boot();
