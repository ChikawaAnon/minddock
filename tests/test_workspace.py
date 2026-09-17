"""工作区驾驶舱解析测试。"""
from minddock.workspace import WorkspaceReader, parse_pitfalls, parse_projects

SAMPLE_README = """# Projects

| 序号 | 项目目录 | 说明 | 状态 |
| --- | --- | --- | --- |
| 001 | `Project-001-a` | 项目 A | 已完成 |
| 002 | `Project-002-b` | 项目 B | 进行中 |
| 003 | `Project-003-c` | 项目 C | 已完成初版 |

| 004 | `Project-004-d` | 项目 D | 纯软件阶段已完成 |
"""

SAMPLE_LOG = """# 避坑日志

## 记录标准

- 记录标准说明，不是教训

## 当前有效教训

1. **中文与编码**：读取中文文件显式 UTF-8。
2. **大文本写入**：优先直接写文件。
3. **无冒号条目** 不应被收录

## 2026-08-29：按文件复制克隆会跳过被占用文件

- 坑：克隆后索引目录为空。
- 解决：重建索引。

## 2026-08-30：本机 Python 环境的两个坑

- 坑 1：py 启动器失效。
- 坑 2：pip 不存在。
"""


class TestParseProjects:
    def test_rows(self):
        rows = parse_projects(SAMPLE_README)
        assert len(rows) == 4
        assert rows[0]["seq"] == "001"
        assert rows[0]["dir"] == "Project-001-a"  # 反引号被剥离
        assert rows[1]["status_class"] == "active"

    def test_table_break_survives(self):
        rows = parse_projects(SAMPLE_README)
        assert rows[3]["seq"] == "004"  # 空行打断后的表格行仍被收录

    def test_status_classes(self):
        rows = parse_projects(SAMPLE_README)
        assert [r["status_class"] for r in rows] == ["done", "active", "done", "done"]

    def test_header_ignored(self):
        assert parse_projects("| 序号 | 项目目录 | 说明 | 状态 |") == []
        assert parse_projects("| --- | --- | --- | --- |") == []

    def test_empty(self):
        assert parse_projects("") == []


class TestParsePitfalls:
    def test_lessons(self):
        out = parse_pitfalls(SAMPLE_LOG)
        assert len(out["lessons"]) == 2
        assert out["lessons"][0]["title"] == "中文与编码"
        assert "UTF-8" in out["lessons"][0]["desc"]

    def test_dated_sections(self):
        out = parse_pitfalls(SAMPLE_LOG)
        assert [d["date"] for d in out["dated"]] == ["2026-08-30", "2026-08-29"]  # 新的在前
        assert out["dated"][0]["title"] == "本机 Python 环境的两个坑"
        assert len(out["dated"][0]["bullets"]) == 2

    def test_empty(self):
        out = parse_pitfalls("")
        assert out == {"lessons": [], "dated": []}


class TestWorkspaceReader:
    def test_missing_root_degrades(self, tmp_path):
        ws = WorkspaceReader(str(tmp_path / "不存在")).overview()
        assert ws["available"] is False
        assert ws["error"]
        assert ws["projects"] == []

    def test_full_overview(self, tmp_path):
        (tmp_path / "projects").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "projects" / "README.md").write_text(SAMPLE_README, encoding="utf-8")
        (tmp_path / "docs" / "pitfall-log.md").write_text(SAMPLE_LOG, encoding="utf-8")
        ws = WorkspaceReader(str(tmp_path)).overview()
        assert ws["available"] is True
        assert ws["stats"]["project_total"] == 4
        assert ws["stats"]["done"] == 3
        assert ws["stats"]["active"] == 1
        assert ws["stats"]["lesson_count"] == 2
        assert not ws["error"]

    def test_missing_docs_degrades(self, tmp_path):
        (tmp_path / "projects").mkdir()
        (tmp_path / "projects" / "README.md").write_text(SAMPLE_README, encoding="utf-8")
        ws = WorkspaceReader(str(tmp_path)).overview()
        assert ws["stats"]["project_total"] == 4
        assert "pitfall-log.md 不存在" in ws["error"]

    def test_none_root(self):
        ws = WorkspaceReader(None).overview()
        assert ws["available"] is False
