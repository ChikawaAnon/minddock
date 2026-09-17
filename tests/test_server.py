"""HTTP API 集成测试：起真实服务，用 urllib 打请求验证端到端行为。"""
import base64
import json
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import quote

import pytest

from minddock.notes import NoteStore
from minddock.seed import seed_notes
from minddock.server import MindDockServer
from minddock.workspace import WorkspaceReader


@pytest.fixture()
def base(tmp_path):
    store = NoteStore(tmp_path / "notes")
    store.ensure_dirs()
    seed_notes(store.root)
    srv = MindDockServer(
        ("127.0.0.1", 0),
        store,
        WorkspaceReader(None),
        {"data_dir": str(store.root), "workspace_root": None},
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _request(base, path, method="GET", data=None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(base + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class TestNotesApi:
    def test_list(self, base):
        out = _get(base, "/api/notes")
        assert out["mode"] == "list"
        assert out["items"] and "title" in out["items"][0]

    def test_list_tag_filter(self, base):
        out = _get(base, f"/api/notes?tag={quote('每日笔记')}")
        assert out["items"]
        assert all("每日笔记" in n["tags"] for n in out["items"])

    def test_search(self, base):
        out = _get(base, f"/api/notes?q={quote('装饰器')}")
        assert out["mode"] == "search"
        assert any("装饰器" in i["name"] for i in out["items"])
        assert all("snippet" in i for i in out["items"])

    def test_get_note(self, base):
        out = _get(base, f"/api/notes/{quote('Python 装饰器入门')}")
        assert out["title"] == "Python 装饰器入门"
        assert "content" in out and "outgoing" in out and "incoming" in out

    def test_get_missing_404(self, base):
        with pytest.raises(HTTPError) as e:
            _get(base, f"/api/notes/{quote('不存在的笔记')}")
        assert e.value.code == 404

    def test_save_creates(self, base):
        out = _request(base, "/api/notes", "POST", {"name": "新笔记", "content": "正文", "tags": ["x"]})
        assert out["name"] == "新笔记"
        assert _get(base, f"/api/notes/{quote('新笔记')}")["content"] == "正文"

    def test_save_requires_name(self, base):
        with pytest.raises(HTTPError) as e:
            _request(base, "/api/notes", "POST", {"content": "x"})
        assert e.value.code == 400

    def test_save_rejects_bad_name(self, base):
        with pytest.raises(HTTPError) as e:
            _request(base, "/api/notes", "POST", {"name": "a/b", "content": "x"})
        assert e.value.code == 400

    def test_delete_and_trash_roundtrip(self, base):
        info = _request(base, f"/api/notes/{quote('Git 工作流备忘')}", "DELETE")
        assert info["trashed"] == "Git 工作流备忘"
        trash = _get(base, "/api/trash")
        assert any(i["name"] == "Git 工作流备忘" for i in trash["items"])
        restored = _request(base, f"/api/trash/{quote(info['file'])}/restore", "POST")
        assert restored["name"] == "Git 工作流备忘"

    def test_purge(self, base):
        info = _request(base, f"/api/notes/{quote('Docker 基础')}", "DELETE")
        out = _request(base, f"/api/trash/{quote(info['file'])}", "DELETE")
        assert out == {"purged": "Docker 基础"}


class TestMetaApi:
    def test_tags(self, base):
        out = _get(base, "/api/tags")
        assert out["tags"] and out["tags"][0][1] >= 1

    def test_graph(self, base):
        out = _get(base, "/api/graph")
        assert out["nodes"] and out["links"]

    def test_stats(self, base):
        out = _get(base, "/api/stats")
        assert out["total"] > 0

    def test_daily(self, base):
        out = _get(base, "/api/daily")
        assert out["tags"]
        assert "每日笔记" in out["tags"]

    def test_daily_bad_date(self, base):
        with pytest.raises(HTTPError) as e:
            _get(base, "/api/daily?date=2026/01/01")
        assert e.value.code == 400

    def test_meta(self, base):
        out = _get(base, "/api/meta")
        assert "version" in out and "data_dir" in out

    def test_unknown_api_404(self, base):
        with pytest.raises(HTTPError):
            _get(base, "/api/nothing")

    def test_index_page(self, base):
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        assert "MindDock" in html and r.headers["Content-Type"].startswith("text/html")

    def test_static_traversal_blocked(self, base):
        with pytest.raises(HTTPError):
            _get(base, "/static/..%2F..%2Fpyproject.toml")

    def test_rename_endpoint_syncs_links(self, base):
        _request(base, "/api/notes", "POST", {"name": "源笔记", "content": "指向 [[Docker 基础]]"})
        out = _request(base, f"/api/notes/{quote('Docker 基础')}/rename", "POST", {"new_name": "Docker 入门"})
        assert out["name"] == "Docker 入门"
        src = _get(base, f"/api/notes/{quote('源笔记')}")
        assert "[[Docker 入门]]" in src["content"]
        # 重命名回来，保持数据集稳定
        _request(base, f"/api/notes/{quote('Docker 入门')}/rename", "POST", {"new_name": "Docker 基础"})

    def test_export_book(self, base):
        req = urllib.request.Request(base + "/api/export/book")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8")
            assert "minddock-book.html" in r.headers.get("Content-Disposition", "")
        assert "MindMD" in body
        assert body.count("</script>") == 2  # 仅 md.js 与 viewer 两个真实闭合

    def test_history_endpoints(self, base):
        # 修改两次产生一个历史版本
        _request(base, "/api/notes", "POST", {"name": "历史测试", "content": "v1"})
        _request(base, "/api/notes", "POST", {"name": "历史测试", "content": "v2"})
        lst = _get(base, f"/api/notes/{quote('历史测试')}?history=1")
        assert len(lst["items"]) == 1
        fname = lst["items"][0]["file"]
        ver = _get(base, f"/api/notes/{quote('历史测试')}/history/{quote(fname)}")
        assert ver["content"] == "v1"
        restored = _request(base, f"/api/notes/{quote('历史测试')}/history/{quote(fname)}/restore", "POST", {})
        assert restored["content"] == "v1"

    def test_note_name_with_percent_literal(self, base):
        # 名字里含合法 %XX 序列：URL 只应解码一次，二次解码会找错笔记
        _request(base, "/api/notes", "POST", {"name": "A%20B", "content": "x"})
        out = _get(base, f"/api/notes/{quote('A%20B')}")
        assert out["name"] == "A%20B"

    def test_history_bad_fname_400(self, base):
        _request(base, "/api/notes", "POST", {"name": "历史测试2", "content": "v1"})
        with pytest.raises(HTTPError) as e:
            _get(base, f"/api/notes/{quote('历史测试2')}/history/{quote('..%2Fevil.md')}")
        assert e.value.code in (400, 404)

    def test_rename_tag_endpoint(self, base):
        out = _request(base, "/api/tags/rename", "POST", {"old": "读书", "new": "阅读"})
        assert out >= 1
        out2 = _get(base, f"/api/notes?tag={quote('阅读')}")
        assert out2["items"]
        with pytest.raises(HTTPError) as e:
            _request(base, "/api/tags/rename", "POST", {"old": " ", "new": "x"})
        assert e.value.code == 400

    def test_attachment_upload_and_serve(self, base):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
        out = _request(base, "/api/attachments", "POST", {"name": "截图.png", "data_b64": png})
        rel = out["path"]
        assert rel.startswith("attachments/")
        with urllib.request.urlopen(base + "/" + quote(rel), timeout=5) as r:
            assert r.headers["Content-Type"] == "image/png"
            assert r.read().startswith(b"\x89PNG")
        # 非 white-list / 穿越一律 404
        with pytest.raises(HTTPError):
            _get(base, "/attachments/whatever.html")
        with pytest.raises(HTTPError):
            _get(base, "/attachments/..%2F..%2Fpyproject.toml")

    def test_attachment_upload_rejects_bad(self, base):
        with pytest.raises(HTTPError) as e:
            _request(base, "/api/attachments", "POST", {"name": "x.html", "data_b64": "AAAA"})
        assert e.value.code == 400

    def test_workspace_endpoint(self, base):
        out = _get(base, "/api/workspace")
        assert out["available"] is False  # 夹具里 workspace_root=None
        assert "projects" in out
