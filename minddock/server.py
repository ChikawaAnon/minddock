"""HTTP 服务：静态页面 + JSON API（ThreadingHTTPServer，纯标准库）。

路由约定：
  GET  /                     单页应用入口
  GET  /static/*             静态资源
  GET  /api/notes?q=&tag=    列表 / 搜索（q 有值时走搜索引擎）
  GET  /api/notes/<name>     笔记全文（含出链/反链）
  POST /api/notes            创建或保存 {name, content, title, tags}
  DELETE /api/notes/<name>   移入回收站
  GET  /api/tags             标签统计
  GET  /api/graph            图谱数据
  GET  /api/daily?date=      每日笔记（缺省今天，自动建）
  GET  /api/stats            统计
  GET  /api/trash            回收站列表
  POST /api/trash/<file>/restore   恢复
  DELETE /api/trash/<file>   彻底删除
  GET  /api/workspace        驾驶舱数据（只读聚合）
  GET  /api/meta             版本与配置信息

所有写操作经线程锁串行化；笔记名统一过 safe_name 校验，杜绝路径穿越。
"""
from __future__ import annotations

import json
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from . import auth as auth_mod
from .attachments import ATT_DIR, content_type_of, collect_images, save_attachment, valid_attachment_name
from .export_book import build_book_html, load_md_js, referenced_images
from .notes import NoteStore
from .util import safe_name
from .workspace import WorkspaceReader

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

# 无需登录即可访问的路径：应用静态壳、PWA 资源、登录端点本身。
# 其余（全部 /api/* 与 /attachments/*）在启用鉴权时要求会话 token。
PUBLIC_PREFIXES = ("/static/", "/api/auth/", "/icons/")


class ApiError(Exception):
    """业务异常：携带 HTTP 状态码与用户可读消息。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class MindDockServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store: NoteStore, workspace: WorkspaceReader, config: dict):
        super().__init__(address, MindDockHandler)
        self.store = store
        self.workspace = workspace
        self.config = config
        self.lock = threading.Lock()
        self.auth = auth_mod.AuthManager(config.get("auth_salt"), config.get("password_sha256"))


class MindDockHandler(BaseHTTPRequestHandler):
    server_version = "MindDock/" + __version__

    # ---- 基础设施 ----

    def log_message(self, fmt, *args):  # 静默常规访问日志，异常时统一打印
        pass

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 2_000_000:
            raise ApiError(413, "请求体过大（>2MB）")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "请求体应为 JSON 对象")
        return data

    @staticmethod
    def _safe(name: str) -> str:
        """URL 段在 _route 里已做过一次 unquote，这里只做安全校验，严禁二次解码。"""
        try:
            return safe_name(name)
        except ValueError as e:
            raise ApiError(400, str(e))

    # ---- 路由 ----

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        try:
            self._route(method)
        except ApiError as e:
            self._error(e.status, e.message)
        except FileNotFoundError:
            self._error(404, "笔记不存在")
        except ValueError as e:
            self._error(400, str(e))
        except Exception:
            traceback.print_exc()
            self._error(500, "服务器内部错误，详见服务端日志")

    def _route(self, method: str):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        srv = self.server

        # ---- 鉴权拦截：启用时，静态壳/PWA 资源/登录端点公开，其余一律要会话 ----
        if srv.auth.enabled:
            public = (path.startswith(PUBLIC_PREFIXES)
                      or path in ("/", "/index.html", "/manifest.webmanifest", "/sw.js"))
            if method != "GET" and not path.startswith("/api/auth/"):
                public = False  # 写操作仅放行登录端点
            if not public:
                token = (self.headers.get("Authorization") or "")
                if token.startswith("Bearer "):
                    token = token[len("Bearer "):]
                if not srv.auth.check(token):
                    return self._error(401, "需要登录")

        if method == "GET":
            if path == "/" or path == "/index.html":
                return self._send(200, "text/html; charset=utf-8", self._index_page())
            if path.startswith("/static/"):
                return self._static_file(path[len("/static/"):])
            if path == "/manifest.webmanifest":
                return self._static_file("manifest.webmanifest")
            if path == "/sw.js":
                return self._static_file("sw.js")
            if path == "/api/notes":
                return self.api_notes_list(query)
            if path == "/api/tags":
                return self._json({"tags": srv.store.stats()["tags"]})
            if path == "/api/graph":
                return self._json(srv.store.graph())
            if path == "/api/stats":
                return self._json(srv.store.stats())
            if path == "/api/daily":
                return self._wrap(srv.store.ensure_daily, query.get("date", [None])[0])
            if path == "/api/trash":
                return self._json({"items": srv.store.trash_list()})
            if path == "/api/workspace":
                return self._json(srv.workspace.overview())
            if path == "/api/export/book":
                return self.api_export_book(query)
            if path == "/api/meta":
                return self.api_meta()
            if path == "/api/auth/check":
                token = (self.headers.get("Authorization") or "")
                if token.startswith("Bearer "):
                    token = token[len("Bearer "):]
                return self._json({"ok": srv.auth.check(token), "enabled": True})
            if path == "/api/auth/challenge":
                try:
                    nonce = srv.auth.new_challenge(self.client_address[0])
                except PermissionError as e:
                    return self._error(429, str(e))
                return self._json({"nonce": nonce, "salt": srv.auth.salt})
            m = re.match(r"^/attachments/([^/]+)$", path)
            if m:
                return self.api_attachment(m.group(1))
            m = re.match(r"^/api/notes/(.+?)/history/([^/]+)$", path)
            if m:
                return self._wrap(srv.store.history_get, self._safe(m.group(1)), self._safe(m.group(2)))
            m = re.match(r"^/api/notes/(.+)$", path)
            if m:
                name = self._safe(m.group(1))
                if query.get("history", [""])[0] == "1":
                    return self._json({"items": srv.store.history_list(name)})
                return self._wrap(srv.store.get, name)
            return self._error(404, "未知路径")

        if method == "POST":
            data = self._body()
            if path == "/api/auth/login":
                token = srv.auth.login(str(data.get("nonce") or ""), str(data.get("resp") or ""))
                if not token:
                    return self._error(401, "密码错误或挑战已过期，请重试")
                return self._json({"token": token})
            if path == "/api/auth/logout":
                token = (self.headers.get("Authorization") or "")
                if token.startswith("Bearer "):
                    token = token[len("Bearer "):]
                srv.auth.logout(token)
                return self._json({"ok": True})
            if path == "/api/notes":
                return self.api_notes_save(data)
            if path == "/api/attachments":
                return self.api_attachment_upload(data)
            if path == "/api/tags/rename":
                old = str(data.get("old") or "")
                new = str(data.get("new") or "")
                if not old.strip() or not new.strip():
                    raise ApiError(400, "old/new 标签名不能为空")
                return self._wrap(srv.store.rename_tag, old, new)
            m = re.match(r"^/api/notes/(.+?)/history/([^/]+)/restore$", path)
            if m:
                return self._wrap(srv.store.history_restore, self._safe(m.group(1)), self._safe(m.group(2)))
            m = re.match(r"^/api/notes/(.+?)/rename$", path)
            if m:
                return self._wrap(srv.store.rename, self._safe(m.group(1)), str(data.get("new_name") or ""))
            m = re.match(r"^/api/trash/(.+?)/restore$", path)
            if m:
                return self._wrap(srv.store.restore, self._safe(m.group(1)))
            return self._error(404, "未知路径")

        if method == "DELETE":
            m = re.match(r"^/api/notes/(.+)$", path)
            if m:
                return self._wrap(srv.store.delete, self._safe(m.group(1)))
            m = re.match(r"^/api/trash/(.+)$", path)
            if m:
                return self._wrap(srv.store.purge, self._safe(m.group(1)))
            return self._error(404, "未知路径")

        self._error(405, "不支持的 HTTP 方法")

    # ---- 处理器封装 ----

    def _wrap(self, fn, *args):
        """统一加锁执行写/读操作，保证线程安全。"""
        with self.server.lock:
            return self._json(fn(*args))

    def _static_file(self, rel: str) -> None:
        rel = rel.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._error(404, "静态资源不存在")
        suffix = target.suffix.lower()
        ctype = STATIC_TYPES.get(suffix)
        if ctype is None:
            return self._error(404, "不支持的资源类型")
        self._send(200, ctype, target.read_bytes())

    def _index_page(self) -> bytes:
        """首页 HTML：CSS/JS 全部内联成单响应。

        公网明文链路对新建连接有较高概率 RST（连接建立后复用则稳定），
        把首屏压成 1 个请求能把加载成功率从单文件 25% 提到接近一次连接
        即可用的水平；SW 命中后二次访问直接走缓存。
        """
        html_path = STATIC_DIR / "index.html"
        parts = [html_path.stat().st_mtime_ns]
        for name in ("style.css", "sha256.js", "md.js", "app.js"):
            parts.append((STATIC_DIR / name).stat().st_mtime_ns)
        key = tuple(parts)
        cache = getattr(self.server, "_index_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        html = html_path.read_text(encoding="utf-8")
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        html = html.replace('<link rel="stylesheet" href="static/style.css">',
                            "<style>\n" + css + "\n</style>", 1)
        for js in ("sha256.js", "md.js", "app.js"):
            code = (STATIC_DIR / js).read_text(encoding="utf-8")
            # 防御：JS 源码（含注释/字符串）中出现脚本闭合标签会截断内联脚本块
            code = code.replace("</script>", "<\\/script>")
            html = html.replace('<script src="static/' + js + '"></script>',
                                "<script>\n" + code + "\n</script>", 1)
        body = html.encode("utf-8")
        self.server._index_cache = (key, body)
        return body

    # ---- 具体端点 ----

    def api_notes_list(self, query: dict):
        q = (query.get("q", [""])[0] or "").strip()
        tag = (query.get("tag", [""])[0] or "").strip()
        if q:
            results = self.server.store.search(q, tag=tag)
            return self._json({"mode": "search", "query": q, "tag": tag, "items": results})
        items = self.server.store.list_notes()
        if tag:
            items = [n for n in items if tag in n["tags"]]
        return self._json({"mode": "list", "query": "", "tag": tag, "items": items})

    def api_notes_save(self, data: dict):
        name = data.get("name")
        if not name or not str(name).strip():
            raise ApiError(400, "缺少笔记名 name")
        with self.server.lock:
            note = self.server.store.save(
                str(name),
                content=str(data.get("content") or ""),
                title=data.get("title"),
                tags=data.get("tags"),
            )
        return self._json(note)

    def api_attachment_upload(self, data: dict):
        name = str(data.get("name") or "image")
        b64 = str(data.get("data_b64") or "")
        with self.server.lock:
            rel = save_attachment(Path(self.server.config["data_dir"]), b64, name)
        return self._json({"path": rel})

    def api_attachment(self, filename: str):
        """提供图片附件：仅白名单扩展名，杜绝把上传目录当 HTML 宿主。"""
        if not valid_attachment_name(filename):
            return self._error(404, "附件不存在")
        f = Path(self.server.config["data_dir"]) / ATT_DIR / filename
        if not f.is_file():
            return self._error(404, "附件不存在")
        self.send_response(200)
        self.send_header("Content-Type", content_type_of(filename) or "application/octet-stream")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "max-age=86400")
        body = f.read_bytes()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def api_export_book(self, query: dict | None = None):
        """整库导出为单文件离线 HTML（下载；?inline=1 时直接在浏览器打开便于预览）。"""
        srv = self.server
        with srv.lock:
            items = []
            for lite in srv.store.list_notes():
                full = srv.store.get(lite["name"])
                items.append(
                    {
                        "name": full["name"],
                        "title": full["title"],
                        "tags": full["tags"],
                        "updated": full["updated"],
                        "content": full["content"],
                        "missing": full["missing"],
                        "incoming": full["incoming"],
                    }
                )
        atts = collect_images(
            Path(srv.config["data_dir"]), referenced_images(items)
        )
        html = build_book_html(items, load_md_js(), attachments=atts)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if not (query and query.get("inline", [""])[0] == "1"):
            self.send_header(
                "Content-Disposition", 'attachment; filename="minddock-book.html"'
            )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_meta(self):
        srv = self.server
        return self._json(
            {
                "version": __version__,
                "data_dir": srv.config["data_dir"],
                "workspace_root": srv.config["workspace_root"],
                "workspace_is_demo": bool(srv.config.get("workspace_is_demo")),
                "notes": len(srv.store._index()),
            }
        )
