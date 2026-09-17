"""应用内登录鉴权集成测试：挑战-响应、会话 token、路径白名单。"""
import hashlib
import json
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import quote

import pytest

from minddock.auth import hash_password
from minddock.notes import NoteStore
from minddock.seed import seed_notes
from minddock.server import MindDockServer
from minddock.workspace import WorkspaceReader

SALT = "unit-test-salt"
PASSWORD = "pw-123456"


def _make_server(tmp_path, config_extra):
    store = NoteStore(tmp_path / "notes")
    store.ensure_dirs()
    seed_notes(store.root)
    config = {"data_dir": str(store.root), "workspace_root": None}
    config.update(config_extra)
    srv = MindDockServer(("127.0.0.1", 0), store, WorkspaceReader(None), config)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture()
def auth_base(tmp_path):
    srv, url = _make_server(
        tmp_path, {"auth_salt": SALT, "password_sha256": hash_password(SALT, PASSWORD)})
    yield url
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def plain_base(tmp_path):
    srv, url = _make_server(tmp_path, {})
    yield url
    srv.shutdown()
    srv.server_close()


def _status(base, path, token=None, method="GET", data=None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(base + path, data=body, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read().decode("utf-8")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw  # 静态资源等非 JSON 响应
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _login_ok(base, password=PASSWORD):
    """按客户端算法走完整登录流程，返回 token。"""
    _, ch = _status(base, "/api/auth/challenge")
    x = hashlib.sha256((SALT + password).encode()).hexdigest()
    resp = hashlib.sha256((x + ch["nonce"]).encode()).hexdigest()
    _, out = _status(base, "/api/auth/login", method="POST",
                     data={"nonce": ch["nonce"], "resp": resp})
    return out["token"]


def test_auth_disabled_by_default(plain_base):
    status, _ = _status(plain_base, "/api/notes")
    assert status == 200  # 未配置密码时不启用鉴权，本机行为不变


def test_api_requires_token(auth_base):
    status, body = _status(auth_base, "/api/notes")
    assert status == 401 and "登录" in body["error"]


def test_static_shell_public(auth_base):
    assert _status(auth_base, "/")[0] == 200
    assert _status(auth_base, "/static/style.css")[0] == 200
    assert _status(auth_base, "/manifest.webmanifest")[0] == 200
    assert _status(auth_base, "/sw.js")[0] == 200
    status, body = _status(auth_base, "/api/auth/check")
    assert status == 200 and body["enabled"] is True and body["ok"] is False


def test_login_flow_and_access(auth_base):
    token = _login_ok(auth_base)
    assert token
    status, _ = _status(auth_base, "/api/notes", token=token)
    assert status == 200
    # 写接口同样放行
    status, _ = _status(auth_base, "/api/notes", token=token, method="POST",
                        data={"name": "新笔记", "content": "# hi"})
    assert status == 200


def test_wrong_password_rejected(auth_base):
    _, ch = _status(auth_base, "/api/auth/challenge")
    x = hashlib.sha256((SALT + "wrong").encode()).hexdigest()
    resp = hashlib.sha256((x + ch["nonce"]).encode()).hexdigest()
    status, _ = _status(auth_base, "/api/auth/login", method="POST",
                        data={"nonce": ch["nonce"], "resp": resp})
    assert status == 401


def test_nonce_single_use(auth_base):
    _, ch = _status(auth_base, "/api/auth/challenge")
    x = hashlib.sha256((SALT + PASSWORD).encode()).hexdigest()
    resp = hashlib.sha256((x + ch["nonce"]).encode()).hexdigest()
    payload = {"nonce": ch["nonce"], "resp": resp}
    assert _status(auth_base, "/api/auth/login", method="POST", data=payload)[0] == 200
    assert _status(auth_base, "/api/auth/login", method="POST", data=payload)[0] == 401


def test_write_blocked_without_token(auth_base):
    status, _ = _status(auth_base, "/api/notes", method="POST",
                        data={"name": "匿名", "content": "x"})
    assert status == 401
    assert _status(auth_base, "/api/notes/" + quote("新笔记"), method="DELETE")[0] == 401


def test_bad_token_rejected(auth_base):
    assert _status(auth_base, "/api/notes", token="forged-token")[0] == 401


def test_logout_invalidates(auth_base):
    token = _login_ok(auth_base)
    assert _status(auth_base, "/api/notes", token=token)[0] == 200
    _status(auth_base, "/api/auth/logout", token=token, method="POST")
    assert _status(auth_base, "/api/notes", token=token)[0] == 401
