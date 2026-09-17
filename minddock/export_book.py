"""单文件 HTML 导出：把整个笔记库打包成一个可离线浏览、可搜索的 HTML 文件。

渲染器复用 static/md.js（与应用内预览同一份代码，保证渲染一致）。
内嵌脚本时统一转义 `</script>` 与 JSON 中的 `</`，防止提前终止脚本块。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .attachments import collect_images

STATIC_DIR = Path(__file__).resolve().parent / "static"

_IMG_RE = re.compile(r"!\[[^\]]*\]\((attachments/[^\)\s]+)\)")

_BOOK_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#f4f5fa; --panel:#fff; --border:#e2e5ef; --text:#20263a; --muted:#6d7488;
  --accent:#4f6df5; --accent-weak:rgba(79,109,245,.12); }
* { box-sizing: border-box; }
body { margin:0; font-family:"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
  background:var(--bg); color:var(--text); font-size:14.5px; line-height:1.6; }
header { display:flex; align-items:center; gap:12px; padding:10px 16px; background:var(--panel);
  border-bottom:1px solid var(--border); position:sticky; top:0; z-index:5; }
header h1 { font-size:16px; margin:0; color:var(--accent); white-space:nowrap; }
header input { flex:1; max-width:420px; height:32px; border:1px solid var(--border);
  border-radius:9px; padding:0 12px; background:var(--bg); outline:none; }
header .count { color:var(--muted); font-size:12px; }
#wrap { display:flex; min-height:calc(100vh - 53px); }
#nav { width:280px; flex-shrink:0; border-right:1px solid var(--border); background:var(--panel);
  overflow-y:auto; padding:8px; }
#nav .item { padding:8px 10px; border-radius:8px; cursor:pointer; margin-bottom:2px; }
#nav .item:hover { background:var(--bg); }
#nav .item.active { background:var(--accent-weak); }
#nav .item .t { font-weight:600; font-size:13.5px; }
#nav .item .d { color:var(--muted); font-size:11.5px; }
#content { flex:1; min-width:0; padding:24px 34px; max-width:860px; }
.md h1,.md h2,.md h3 { line-height:1.4; }
.md h1 { font-size:21px; border-bottom:1px solid var(--border); padding-bottom:6px; }
.md code { background:var(--accent-weak); padding:.5px 5px; border-radius:5px; font-size:12.8px;
  font-family:Consolas,monospace; }
.md pre { background:#eceef7; border-radius:10px; padding:12px 14px; overflow-x:auto; }
.md pre code { background:none; padding:0; }
.md blockquote { margin:.6em 0; padding:6px 14px; border-left:3px solid var(--accent);
  background:var(--accent-weak); border-radius:0 8px 8px 0; color:var(--muted); }
.md table { border-collapse:collapse; margin:.7em 0; font-size:13px; }
.md th,.md td { border:1px solid var(--border); padding:5px 10px; }
.md .wikilink { color:var(--accent); background:var(--accent-weak); padding:0 5px;
  border-radius:5px; cursor:pointer; }
.md .wikilink.missing { color:#b45309; background:none; border:1px dashed #b45309; }
.md .inline-tag { color:var(--accent); }
.md img { max-width:100%; border-radius:8px; border:1px solid var(--border); }
.tags span { display:inline-block; background:var(--accent-weak); color:var(--accent);
  font-size:11.5px; padding:1px 9px; border-radius:999px; margin-right:6px; }
.meta { color:var(--muted); font-size:12px; margin-top:8px; }
footer { text-align:center; color:var(--muted); font-size:11.5px; padding:26px 0 34px; }
@media (max-width:760px){ #nav { width:190px; } #content { padding:16px; } }
</style>
</head>
<body>
<header>
  <h1>⚓ __TITLE__</h1>
  <input id="q" placeholder="在整库中搜索…">
  <span class="count" id="count"></span>
</header>
<div id="wrap">
  <nav id="nav"></nav>
  <main id="content"></main>
</div>
<footer>由 MindDock 导出 · __DATE__ · 双击链接可在库内跳转</footer>
<script>__MDJS__</script>
<script>
var NOTES = __MDDATA__;
var IMGS = __MDATTS__;
var byName = {};
NOTES.forEach(function (n) { byName[n.name] = n; });
var current = null;
var nav = document.getElementById("nav");
var content = document.getElementById("content");
var q = document.getElementById("q");

function renderList() {
  var kw = q.value.trim().toLowerCase();
  nav.innerHTML = "";
  NOTES.forEach(function (n) {
    if (kw && (n.title + " " + n.content + " " + n.tags.join(" ")).toLowerCase().indexOf(kw) === -1) return;
    var d = document.createElement("div");
    d.className = "item" + (current && current.name === n.name ? " active" : "");
    d.innerHTML = '<div class="t">' + MindMD.esc(n.title) + '</div><div class="d">' +
      MindMD.esc((n.updated || "").slice(0, 10)) + " · " + MindMD.esc(n.tags.join(" / ")) + "</div>";
    d.onclick = function () { open(n.name); };
    nav.appendChild(d);
  });
  document.getElementById("count").textContent = nav.children.length + " / " + NOTES.length + " 篇";
}

function open(name) {
  var n = byName[name];
  if (!n) return;
  current = n;
  var missing = (n.missing || []).filter(function (m) { return !byName[m]; });
  content.innerHTML =
    '<h1 style="font-size:23px;margin-top:0">' + MindMD.esc(n.title) + "</h1>" +
    '<div class="tags">' + n.tags.map(function (t) { return "<span>" + MindMD.esc(t) + "</span>"; }).join("") + "</div>" +
    '<div class="meta">更新于 ' + MindMD.esc((n.updated || "").slice(0, 16).replace("T", " ")) + "</div>" +
    '<div class="md">' + MindMD.render(n.content, missing) + "</div>" +
    ((n.incoming && n.incoming.length)
      ? '<p class="meta">🔗 反链：' + n.incoming.map(function (s) {
          return '<a class="wikilink" data-note="' + encodeURIComponent(s) + '">' + MindMD.esc(s) + "</a>";
        }).join("、") + "</p>"
      : "");
  // 图片：用内嵌 data URI 替换相对路径
  content.querySelectorAll('img[src^="attachments/"]').forEach(function (img) {
    var key = img.getAttribute("src");
    if (IMGS[key]) img.src = IMGS[key];
  });
  var active = nav.querySelector(".item.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

content.addEventListener("click", function (e) {
  var a = e.target.closest ? e.target.closest("a[data-note]") : null;
  if (a) {
    var name = decodeURIComponent(a.getAttribute("data-note"));
    if (byName[name]) open(name);
  }
});
q.addEventListener("input", renderList);
renderList();
open(NOTES.length ? NOTES[0].name : "");
</script>
</body>
</html>
"""


def _escape_script(src: str) -> str:
    """防止内嵌代码里的 </script> 提前终止脚本块（大小写不敏感）。"""
    return re.sub(r"</(script)", r"<\\/\1", src, flags=re.IGNORECASE)


def referenced_images(items: list[dict]) -> list[str]:
    """提取全部笔记正文引用的附件图片路径（去重保序）。"""
    seen: list[str] = []
    for it in items:
        for m in _IMG_RE.finditer(it.get("content") or ""):
            if m.group(1) not in seen:
                seen.append(m.group(1))
    return seen


def build_book_html(
    items: list[dict], md_js: str, title: str = "MindDock 知识库", attachments: dict[str, str] | None = None
) -> str:
    """items: 每篇笔记的 {name,title,tags,updated,content,missing,incoming}。

    attachments: {相对路径: data URI}，供离线查看图片；缺省为空。
    """
    data_json = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")  # JSON 内 <\/ 合法等价
    atts_json = json.dumps(attachments or {}, ensure_ascii=False).replace("</", "<\\/")
    return (
        _BOOK_TEMPLATE.replace("__TITLE__", title)
        .replace("__DATE__", __import__("datetime").date.today().isoformat())
        .replace("__MDJS__", _escape_script(md_js))
        .replace("__MDDATA__", _escape_script(data_json))
        .replace("__MDATTS__", _escape_script(atts_json))
    )


def load_md_js() -> str:
    return (STATIC_DIR / "md.js").read_text(encoding="utf-8")
