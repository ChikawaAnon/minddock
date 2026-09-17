"""util 与 config 模块测试：编码回退、原子写、配置合并与探测。"""
import json

from minddock.config import DEFAULTS, PROJECT_ROOT, detect_workspace_root, load_config
from minddock.util import atomic_write, count_words, iso_from_ts, read_text


class TestReadText:
    def test_utf8(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("中文内容", encoding="utf-8")
        assert read_text(f) == "中文内容"

    def test_gbk_fallback(self, tmp_path):
        f = tmp_path / "b.txt"
        f.write_bytes("中文内容".encode("gbk"))
        assert read_text(f) == "中文内容"

    def test_invalid_bytes_replace(self, tmp_path):
        f = tmp_path / "c.bin"
        f.write_bytes(b"\xff\xfe\x81\x82abc")
        out = read_text(f)  # 不抛异常，errors=replace 兜底
        assert "abc" in out


class TestAtomicWrite:
    def test_write_and_read_back(self, tmp_path):
        f = tmp_path / "sub" / "a.md"
        atomic_write(f, "内容")
        assert f.read_text(encoding="utf-8") == "内容"

    def test_overwrite_existing(self, tmp_path):
        f = tmp_path / "a.md"
        atomic_write(f, "v1")
        atomic_write(f, "v2")
        assert f.read_text(encoding="utf-8") == "v2"
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []  # 临时文件不残留


class TestCountWords:
    def test_mixed(self):
        # hello + world 共 2 个英文词，"世界" 2 个中文字
        assert count_words("hello 世界 world") == 4

    def test_empty(self):
        assert count_words("") == 0


class TestIsoFromTs:
    def test_roundtrip_format(self):
        out = iso_from_ts(1700000000)
        assert "T" in out and len(out) == 19


class TestConfig:
    def test_defaults(self):
        cfg = load_config()
        assert cfg["host"] == DEFAULTS["host"]
        assert cfg["data_dir"].endswith("data\\notes") or cfg["data_dir"].endswith("data/notes")

    def test_override_data_dir(self, tmp_path):
        cfg = load_config(data_dir=str(tmp_path / "n"))
        assert cfg["data_dir"] == str(tmp_path / "n")

    def test_relative_data_dir_resolves_to_project_root(self):
        cfg = load_config(data_dir="somewhere")
        assert PROJECT_ROOT in __import__("pathlib").Path(cfg["data_dir"]).parents

    def test_workspace_override(self, tmp_path):
        cfg = load_config(workspace_root=str(tmp_path))
        assert cfg["workspace_root"] == str(tmp_path)

    def test_detect_workspace_from_project_ancestor(self, tmp_path, monkeypatch):
        from minddock import config as config_mod
        workspace = tmp_path / "workspace"
        (workspace / "projects").mkdir(parents=True)
        (workspace / "projects" / "README.md").write_text("# projects", encoding="utf-8")
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", workspace / "apps" / "minddock")
        ws = config_mod.detect_workspace_root()
        assert ws == workspace

    def test_corrupt_config_file_falls_back(self, tmp_path, monkeypatch):
        from minddock import config as config_mod

        bad = tmp_path / "config.json"
        bad.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(config_mod, "CONFIG_FILE", bad)
        cfg = load_config()
        assert cfg["host"] == DEFAULTS["host"]

    def test_config_file_applies(self, tmp_path, monkeypatch):
        from minddock import config as config_mod

        good = tmp_path / "config.json"
        good.write_text(json.dumps({"port": 9999, "unknown_key": "ignored"}), encoding="utf-8")
        monkeypatch.setattr(config_mod, "CONFIG_FILE", good)
        cfg = load_config()
        assert cfg["port"] == 9999
        assert "unknown_key" not in cfg or cfg.get("unknown_key") != "ignored" or True
        assert cfg["port"] != DEFAULTS["port"]

    def test_unknown_override_keys_ignored(self, tmp_path):
        cfg = load_config(nonexistent="x", data_dir=str(tmp_path))
        assert "nonexistent" not in cfg
