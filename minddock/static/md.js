/* MindMD —— 共享 Markdown 渲染器。
   同时被两个场景加载：应用内预览（app.js）与导出的单文件 HTML，
   保证两处渲染结果一致。暴露 window.MindMD.render(text, missing)。 */
(function () {
  "use strict";

  var WIKILINK_RE = /\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]/g;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function inlineMd(text, missingSet) {
    return text
      .replace(WIKILINK_RE, function (m, target, alias) {
        var miss = missingSet && missingSet.hasOwnProperty(target.trim());
        return (
          '<a class="wikilink' + (miss ? " missing" : "") + '" data-note="' +
          encodeURIComponent(target.trim()) + '" title="' + esc(target.trim()) + '">' +
          esc(alias || target) + "</a>"
        );
      })
      .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1" loading="lazy">')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
      .replace(/(^|[\s(（])(https?:\/\/[^\s<）)]+)/g, '$1<a href="$2" target="_blank" rel="noreferrer">$2</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>")
      .replace(/(^|[\s(（>])(#([\w\u4e00-\u9fff\-\/]{1,32}))/g, '$1<span class="inline-tag">$2</span>');
  }

  function mdToHtml(src, missing) {
    var missingSet = {};
    (missing || []).forEach(function (m) { missingSet[m] = true; });
    var blocks = [];
    src = String(src == null ? "" : src).replace(/```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g, function (m, lang, code) {
      blocks.push({ code: code.replace(/\n$/, "") });
      return "\u0000B" + (blocks.length - 1) + "\u0000";
    });
    var text = esc(src);
    var codes = [];
    text = text.replace(/`([^`\n]+)`/g, function (m, c) {
      codes.push(c);
      return "\u0000C" + (codes.length - 1) + "\u0000";
    });

    var lines = text.split("\n");
    var out = [];
    var para = [];
    var listStack = [];
    var quoteBuf = [];
    var tableRows = [];

    function closePara() { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } }
    function closeList() { while (listStack.length) out.push("</" + listStack.pop() + ">"); }
    function closeQuote() { if (quoteBuf.length) { out.push("<blockquote>" + quoteBuf.join("<br>") + "</blockquote>"); quoteBuf = []; } }
    function closeTable() {
      if (!tableRows.length) return;
      var html = "<table><thead><tr>";
      html += tableRows[0].map(function (c) { return "<th>" + inlineMd(c, missingSet) + "</th>"; }).join("");
      html += "</tr></thead><tbody>";
      for (var i = 1; i < tableRows.length; i++) {
        (function (row) {
          if (row.every(function (c) { return /^-{2,}$/.test(c.trim()); })) return;
          html += "<tr>" + row.map(function (c) { return "<td>" + inlineMd(c, missingSet) + "</td>"; }).join("") + "</tr>";
        })(tableRows[i]);
      }
      html += "</tbody></table>";
      out.push(html);
      tableRows = [];
    }
    function closeAll() { closePara(); closeList(); closeQuote(); closeTable(); }

    lines.forEach(function (raw) {
      var trimmed = raw.trim();
      if (/^\|.+\|$/.test(trimmed)) {
        closePara(); closeList(); closeQuote();
        tableRows.push(trimmed.slice(1, -1).split("|").map(function (c) { return c.trim(); }));
        return;
      }
      closeTable();
      if (!trimmed) { closePara(); closeList(); closeQuote(); return; }
      var h = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      if (h) { closeAll(); out.push("<h" + h[1].length + ">" + inlineMd(h[2], missingSet) + "</h" + h[1].length + ">"); return; }
      if (/^(-{3,}|\*{3,})$/.test(trimmed)) { closeAll(); out.push("<hr>"); return; }
      if (/^&gt;\s?/.test(trimmed)) {
        closePara(); closeList();
        quoteBuf.push(inlineMd(trimmed.replace(/^&gt;\s?/, ""), missingSet));
        return;
      }
      var task = /^[-*]\s+\[([ xX])\]\s+(.*)$/.exec(trimmed);
      if (task) {
        closePara(); closeQuote();
        if (listStack[listStack.length - 1] !== "task") { closeList(); listStack.push("task"); out.push('<ul class="task-list">'); }
        out.push('<li><input type="checkbox" disabled' + (task[1] !== " " ? " checked" : "") + "> " + inlineMd(task[2], missingSet) + "</li>");
        return;
      }
      var ul = /^[-*]\s+(.*)$/.exec(trimmed);
      if (ul) {
        closePara(); closeQuote();
        if (listStack[listStack.length - 1] !== "ul") { closeList(); listStack.push("ul"); out.push("<ul>"); }
        out.push("<li>" + inlineMd(ul[1], missingSet) + "</li>");
        return;
      }
      var ol = /^\d+\.\s+(.*)$/.exec(trimmed);
      if (ol) {
        closePara(); closeQuote();
        if (listStack[listStack.length - 1] !== "ol") { closeList(); listStack.push("ol"); out.push("<ol>"); }
        out.push("<li>" + inlineMd(ol[1], missingSet) + "</li>");
        return;
      }
      closeList(); closeQuote();
      para.push(inlineMd(trimmed, missingSet));
    });
    closeAll();

    var html = out.join("\n");
    html = html.replace(/\u0000B(\d+)\u0000/g, function (m, i) {
      return "<pre><code>" + esc(blocks[Number(i)].code) + "</code></pre>";
    });
    html = html.replace(/\u0000C(\d+)\u0000/g, function (m, i) { return "<code>" + codes[Number(i)] + "</code>"; });
    return html;
  }

  window.MindMD = { render: mdToHtml, esc: esc };
})();
