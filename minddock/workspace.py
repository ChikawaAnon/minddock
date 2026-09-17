"""工作区驾驶舱数据聚合：解析 projects 登记表与避坑日志（只读）。

对工作区文件只做读取，绝不写入；文件缺失或格式变化时降级返回
可用的空结构并携带 error 字段，保证驾驶舱页面不至于白屏。
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import read_text

_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_LESSON_RE = re.compile(r"^\s*\d+\.\s+\*\*(.+?)\*\*[：:]\s*(.*)$")
_DATED_SECTION_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})[：:]\s*(.+?)\s*$", re.M)


def _status_class(status: str) -> str:
    """状态归一化：done / active / other，驱动前端配色。"""
    s = status or ""
    if "进行" in s:
        return "active"
    if "完成" in s:
        return "done"
    return "other"


def _split_row(line: str) -> list[str]:
    inner = _TABLE_ROW_RE.match(line).group(1)
    return [c.strip() for c in inner.split("|")]


def parse_projects(readme_text: str) -> list[dict]:
    """解析项目登记表：兼容表格被空行打断的情况，逐行提取 4 列数据行。"""
    projects: list[dict] = []
    for line in readme_text.splitlines():
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_row(line)
        if len(cells) < 4:
            continue
        seq, directory, desc, status = cells[0], cells[1], cells[2], cells[3]
        if not re.match(r"^\d{3}$", seq):
            continue  # 表头或分隔行
        if directory in ("项目目录", "") or set(directory) <= set("- :"):
            continue
        projects.append(
            {
                "seq": seq,
                "dir": directory.strip("`").strip(),  # 剥掉源文件里的 markdown 反引号
                "desc": desc,
                "status": status,
                "status_class": _status_class(status),
            }
        )
    return projects


def parse_pitfalls(log_text: str) -> dict:
    """解析避坑日志：当前有效教训 + 按日期归档的详细记录。"""
    lessons: list[dict] = []
    in_current = False
    for line in log_text.splitlines():
        if line.startswith("## "):
            in_current = "当前有效教训" in line
            continue
        if not in_current:
            continue
        m = _LESSON_RE.match(line)
        if m:
            lessons.append({"title": m.group(1).strip(), "desc": m.group(2).strip()})

    dated: list[dict] = []
    sections = _DATED_SECTION_RE.split(log_text)
    # re.split 带捕获组：[前文, 日期1, 标题1, 正文1, 日期2, ...]
    for i in range(1, len(sections) - 1, 3):
        day, title, body = sections[i], sections[i + 1], sections[i + 2]
        bullets = [
            l.lstrip("- ").strip()
            for l in body.splitlines()
            if l.strip().startswith("- ")
        ]
        dated.append({"date": day, "title": title.strip(), "bullets": bullets})
    dated.sort(key=lambda x: x["date"], reverse=True)

    return {"lessons": lessons, "dated": dated}


class WorkspaceReader:
    """只读工作区聚合器。root 为工作区根目录；不存在时返回降级数据。"""

    def __init__(self, root: str | None):
        self.root = Path(root) if root else None

    def overview(self) -> dict:
        if not self.root or not self.root.exists():
            return {
                "root": str(self.root) if self.root else None,
                "available": False,
                "error": "工作区根目录不存在（可用 --workspace 指定）",
                "projects": [],
                "pitfalls": {"lessons": [], "dated": []},
                "stats": {"project_total": 0, "done": 0, "active": 0, "other": 0, "lesson_count": 0},
            }
        projects, proj_err = self._read_projects()
        pitfalls, pit_err = self._read_pitfalls()
        errors = [e for e in (proj_err, pit_err) if e]
        done = sum(1 for p in projects if p["status_class"] == "done")
        active = sum(1 for p in projects if p["status_class"] == "active")
        return {
            "root": str(self.root),
            "available": True,
            "error": "；".join(errors),
            "projects": projects,
            "pitfalls": pitfalls,
            "stats": {
                "project_total": len(projects),
                "done": done,
                "active": active,
                "other": len(projects) - done - active,
                "lesson_count": len(pitfalls["lessons"]),
            },
        }

    def _read_projects(self) -> tuple[list[dict], str]:
        f = self.root / "projects" / "README.md"
        if not f.exists():
            return [], "projects/README.md 不存在"
        try:
            return parse_projects(read_text(f)), ""
        except OSError as e:
            return [], f"读取项目登记表失败: {e}"

    def _read_pitfalls(self) -> tuple[dict, str]:
        f = self.root / "docs" / "pitfall-log.md"
        if not f.exists():
            return {"lessons": [], "dated": []}, "docs/pitfall-log.md 不存在"
        try:
            return parse_pitfalls(read_text(f)), ""
        except OSError as e:
            return {"lessons": [], "dated": []}, f"读取避坑日志失败: {e}"
