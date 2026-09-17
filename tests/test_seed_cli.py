"""演示数据、CLI 与端到端组合测试。"""
import io
import json
from contextlib import redirect_stdout

from minddock.cli import main
from minddock.notes import NoteStore
from minddock.seed import DEMO_NOTES, seed_notes, seed_workspace_fixture
from minddock.workspace import WorkspaceReader


class TestSeed:
    def test_seed_writes_all_notes(self, tmp_path):
        n = seed_notes(tmp_path / "notes")
        assert n == len(DEMO_NOTES)
        store = NoteStore(tmp_path / "notes")
        assert len(store.list_notes()) == len(DEMO_NOTES)

    def test_seed_idempotent(self, tmp_path):
        d = tmp_path / "notes"
        assert seed_notes(d) == len(DEMO_NOTES)
        assert seed_notes(d) == 0  # 非空时跳过

    def test_seed_content_has_links_and_tags(self, tmp_path):
        d = tmp_path / "notes"
        seed_notes(d)
        store = NoteStore(d)
        body = store.get("Python 装饰器入门")
        # 「函数式编程」在演示库中没有对应笔记，应作为未解析目标出现
        assert "函数式编程" in body["missing"]
        assert "Python 生成器与协程" in body["outgoing"]
        assert "python" in body["tags"]

    def test_seed_dates_spread(self, tmp_path):
        d = tmp_path / "notes"
        seed_notes(d)
        store = NoteStore(d)
        updated_days = {str(n["updated"])[:10] for n in store.list_notes()}
        assert len(updated_days) >= 15  # 日期分散，活动图自然

    def test_workspace_fixture_parses(self, tmp_path):
        ws_root = seed_workspace_fixture(tmp_path / "ws")
        ov = WorkspaceReader(str(ws_root)).overview()
        assert ov["available"]
        assert ov["stats"]["project_total"] == 5
        assert ov["stats"]["lesson_count"] == 3


class TestCli:
    def test_check_runs_clean(self, tmp_path, capsys):
        data = tmp_path / "n"
        ws = seed_workspace_fixture(tmp_path / "ws")
        seed_notes(data)
        rc = main(["check", "--data-dir", str(data), "--workspace", str(ws)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "自检通过" in out
        assert "26 篇" in out or f"{len(DEMO_NOTES)} 篇" in out

    def test_check_missing_workspace_warns(self, tmp_path, capsys):
        data = tmp_path / "n"
        seed_notes(data)
        rc = main(["check", "--data-dir", str(data), "--workspace", str(tmp_path / "无")])
        out = capsys.readouterr().out
        assert rc == 0
        assert "警告" in out and "自检完成" in out

    def test_seed_command(self, tmp_path, capsys):
        rc = main(["seed", "--data-dir", str(tmp_path / "n")])
        out = capsys.readouterr().out
        assert rc == 0 and "播种完成" in out

    def test_version_flag(self, capsys):
        try:
            main(["--version"])
        except SystemExit as e:
            assert e.code == 0
        assert "MindDock" in capsys.readouterr().out


class TestRobustness:
    def test_store_on_nonexistent_root_lazily_creates(self, tmp_path):
        store = NoteStore(tmp_path / "deep" / "n")
        store.ensure_dirs()
        n = store.save("测试", "内容")
        assert n["name"] == "测试"

    def test_note_with_crlf_line_endings(self, store):
        store.save("crlf", "# 标题\r\n\r\n- a\r\n- b\r\n")
        got = store.get("crlf")
        assert "标题" in got["content"]

    def test_search_on_note_missing_optional_fields(self):
        from minddock.search import search

        r = search({"a": {"name": "a", "title": "", "tags": [], "headings": [], "body": "", "updated": ""}}, "x")
        assert r == []

    def test_graph_empty_store(self, store):
        g = store.graph()
        assert g["nodes"] == [] and g["links"] == []

    def test_stats_empty_store(self, store):
        st = store.stats()
        assert st["total"] == 0 and st["tags"] == []

    def test_save_empty_content_note(self, store):
        n = store.save("空笔记", "")
        assert n["content"] == ""
        assert n["title"] == "空笔记"  # fm title 回退为笔记名

    def test_wikilink_with_special_chars(self, store):
        store.save("目标(1)", "内容")
        store.save("来源", "见 [[目标(1)]]")
        assert store.get("目标(1)")["incoming"] == ["来源"]

    def test_daily_note_linkable(self, store):
        store.ensure_daily("2026-09-07")
        store.save("日记引用", "见 [[2026-09-07]]")
        assert store.get("2026-09-07")["incoming"] == ["日记引用"]

    def test_many_notes_perf(self, store):
        import time

        for i in range(120):
            store.save(f"笔记{i}", f"内容 {i} 关键词独特{i}")
        t0 = time.perf_counter()
        hits = store.search("独特77")
        elapsed = time.perf_counter() - t0
        assert hits and hits[0]["name"] == "笔记77"
        assert elapsed < 1.5  # 120 篇全量扫描应远快于此
