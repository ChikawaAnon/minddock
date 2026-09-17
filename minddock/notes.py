"""笔记存储：frontmatter 解析、增删改查、软删除回收站、每日笔记、统计。

存储布局（全部位于数据根目录内，扁平命名空间，文件名即笔记 ID）：

    <data_dir>/<笔记名>.md        普通笔记
    <data_dir>/.trash/*.md        回收站（软删除）
    <data_dir>/.trash/index.json  回收站索引（记录原始笔记名与删除时间）

frontmatter 只支持平铺 `key: value` 与 `tags: [a, b]` 列表两种形式，
满足自身需要即可，不做完整 YAML 解析。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path

from .links import extract_headings, extract_inline_tags, extract_links
from .util import (
    atomic_write,
    count_words,
    iso_from_ts,
    now_iso,
    read_text,
    safe_name,
)

TRASH_DIR = ".trash"
HISTORY_DIR = ".history"
HISTORY_KEEP = 20  # 每篇笔记保留的历史版本数
MANAGED_KEYS = {"title", "tags", "created", "updated"}
_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)
_DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DAILY_TAG = "每日笔记"
DAILY_TEMPLATE = """# {title}

## 今日完成

-

## 明日计划

-

## 随记

"""


# ---------------------------------------------------------------- frontmatter


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """拆分 (fm_dict, body)。无 frontmatter 时返回 ({}, 原文)。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if not key:
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            fm[key] = (
                [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
                if inner
                else []
            )
        else:
            fm[key] = val.strip("'\"")
    return fm, text[m.end():]


def serialize_note(fm: dict, body: str) -> str:
    """把 frontmatter 与正文拼回文件文本。"""
    if not fm:
        return body
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines += ["---", ""]
    return "\n".join(lines) + body


def normalize_tags(tags) -> list[str]:
    """标签归一化：接受字符串（逗号/空格分隔）或列表，去重去空。"""
    if tags is None:
        return []
    if isinstance(tags, str):
        parts = re.split(r"[,，\s]+", tags)
    else:
        parts = [str(t) for t in tags]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        t = p.strip().strip("#").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t[:32])
    return out


# ------------------------------------------------------------------- NoteStore


class NoteStore:
    """基于文件系统的笔记仓库，带 mtime 签名缓存与外部修改感知。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.trash = self.root / TRASH_DIR
        self.history = self.root / HISTORY_DIR
        self._cache: dict[str, tuple] = {}  # name -> (mtime, size, note_lite)
        self._signature: frozenset | None = None
        self._link_idx: tuple[frozenset, dict] | None = None
        self._scan_cache: dict[str, tuple[float, int]] = {}
        self._last_scan = 0.0

    SCAN_TTL = 0.5  # 秒；单机工具对外部改动的可感知延迟上限

    # ---- 内部 ----

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _note_path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def _scan(self) -> dict[str, tuple[float, int]]:
        """扫描数据根下的 md 文件（不含回收站）。"""
        out: dict[str, tuple[float, int]] = {}
        if not self.root.exists():
            return out
        for p in self.root.glob("*.md"):
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.stem] = (st.st_mtime, st.st_size)
        return out

    def _signature_of(self, scan: dict) -> frozenset:
        return frozenset((n, round(m, 3), s) for n, (m, s) in scan.items())

    def _invalidate(self) -> None:
        """数据变更后调用：强制下次重扫 + 重建链接索引。

        注意不清空笔记内容缓存——缓存项按 (mtime, size) 匹配，
        未变化的文件会被复用，只有真正变更的文件才重新读盘。
        """
        self._signature = None
        self._link_idx = None
        self._last_scan = 0.0

    def _fresh_scan(self) -> dict[str, tuple[float, int]]:
        """带 TTL 的扫描缓存：突发请求窗口内复用一次 stat 全扫。"""
        if self._signature is None or time.time() - self._last_scan > self.SCAN_TTL:
            self._scan_cache = self._scan()
            self._last_scan = time.time()
        return self._scan_cache

    def _load(self, name: str, mtime: float, size: int) -> dict:
        raw = read_text(self._note_path(name))
        fm, body = parse_frontmatter(raw)
        fm_tags = fm.get("tags", [])
        if isinstance(fm_tags, str):
            fm_tags = normalize_tags(fm_tags)
        inline = extract_inline_tags(body)
        tags = list(fm_tags) + [t for t in inline if t not in fm_tags]
        created = fm.get("created") or iso_from_ts(mtime)
        updated = fm.get("updated") or iso_from_ts(mtime)
        return {
            "name": name,
            "title": str(fm.get("title") or name),
            "tags": tags,
            "created": created,
            "updated": updated,
            "mtime": mtime,
            "size": size,
            "words": count_words(body),
            "headings": extract_headings(body),
            "excerpt": body.strip()[:120],
            "body": body,
            "fm": fm,
        }

    def _index(self) -> dict[str, dict]:
        """带缓存的轻量索引：扫描结果短 TTL 复用，笔记项按 (mtime, size) 增量失效。"""
        scan = self._fresh_scan()
        sig = self._signature_of(scan)
        if sig != self._signature:
            self._signature = sig
            self._link_idx = None
        valid = set(scan)
        for name in [n for n in self._cache if n not in valid]:
            del self._cache[name]
        index: dict[str, dict] = {}
        for name, (mtime, size) in scan.items():
            c = self._cache.get(name)
            if c and c[0] == mtime and c[1] == size:
                index[name] = c[2]
            else:
                note = self._load(name, mtime, size)
                self._cache[name] = (mtime, size, note)
                index[name] = note
        return index

    def bodies_map(self) -> dict[str, str]:
        return {n: note["body"] for n, note in self._index().items()}

    def search(self, query: str, tag: str = "", limit: int = 50) -> list[dict]:
        """全文搜索（委托 search 引擎），可叠加标签过滤。"""
        from .search import search as run_search

        results = run_search(self._index(), query, limit)
        if tag:
            results = [r for r in results if tag in r["tags"]]
        return results

    def graph(self) -> dict:
        """图谱数据：节点权重按链接度，未解析目标作为幽灵节点。"""
        from .links import build_graph

        notes = self._index()
        return build_graph(
            {n: note["body"] for n, note in notes.items()},
            {n: note["title"] for n, note in notes.items()},
            {n: note["tags"] for n, note in notes.items()},
        )

    # ---- 查询 ----

    def exists(self, name: str) -> bool:
        return self._note_path(safe_name(name)).exists()

    def list_notes(self) -> list[dict]:
        """全部笔记轻量信息，按更新时间倒序。"""
        notes = [self._lite(n) for n in self._index().values()]
        notes.sort(key=lambda x: x["mtime"], reverse=True)
        return notes

    def _lite(self, note: dict) -> dict:
        keys = ("name", "title", "tags", "created", "updated", "mtime", "words", "excerpt")
        return {k: note[k] for k in keys}

    def link_index(self) -> dict:
        """全库链接索引，随磁盘签名缓存；get 的反链/出链都从这里取。"""
        notes = self._index()
        if self._link_idx is None or self._link_idx[0] != self._signature:
            from .links import build_index

            self._link_idx = (
                self._signature,
                build_index({n: v["body"] for n, v in notes.items()}),
            )
        return self._link_idx[1]

    def get(self, name: str) -> dict:
        """取单篇笔记全文，附带出链、反链、未解析链接。

        对单个文件直接 stat 校验，保证外部修改在扫描 TTL 内也即时可见；
        新落盘的文件若恰逢 TTL 窗口，强制重扫一次，绝不误报 404。
        """
        name = safe_name(name)
        c = self._cache.get(name)
        if c is not None:
            path = self._note_path(name)
            if not path.exists():
                self._invalidate()
            else:
                st = path.stat()
                if c[0] != st.st_mtime or c[1] != st.st_size:
                    self._invalidate()
        notes = self._index()
        if name not in notes and time.time() - self._last_scan < self.SCAN_TTL:
            self._last_scan = 0.0
            notes = self._index()
        if name not in notes:
            raise FileNotFoundError(name)
        note = notes[name]
        idx = self.link_index()
        return {
            **self._lite(note),
            "headings": note["headings"],
            "content": note["body"],
            "fm": note["fm"],
            "outgoing": idx["outgoing"].get(name, []),
            "missing": idx["missing"].get(name, []),
            "incoming": sorted(idx["incoming"].get(name, {}).keys()),
        }

    # ---- 写入 ----

    def save(
        self,
        name: str,
        content: str = "",
        title: str | None = None,
        tags=None,
    ) -> dict:
        """创建或更新笔记。content 自带 frontmatter 时会被吸收合并。"""
        name = safe_name(name)
        path = self._note_path(name)
        existing = None
        if path.exists():
            scan = self._scan()
            if name in scan:
                existing = self._load(name, *scan[name])

        fm: dict = dict(existing["fm"]) if existing else {}
        body = content
        in_fm, rest = parse_frontmatter(content)
        if in_fm:
            if existing is None:
                fm.update(in_fm)
            else:
                fm.update({k: v for k, v in in_fm.items() if k not in MANAGED_KEYS})
            body = rest
        if title is not None and title.strip():
            fm["title"] = title.strip()
        fm.setdefault("title", name)
        if tags is not None:
            fm["tags"] = normalize_tags(tags)
        elif "tags" not in fm:
            fm["tags"] = []
        now = now_iso()
        if "created" not in fm:
            fm["created"] = now
        fm["updated"] = now

        if path.exists():
            self._archive_version(name, read_text(path))
        atomic_write(path, serialize_note(fm, body))
        self._invalidate()
        return self.get(name)

    def _archive_version(self, name: str, raw: str) -> None:
        """保存修改前的版本到 .history/<name>/，超出上限时淘汰最旧的。"""
        vdir = self.history / name
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        atomic_write(vdir / f"{stamp}.md", raw)
        versions = sorted(vdir.glob("*.md"))
        for old in versions[: max(0, len(versions) - HISTORY_KEEP)]:
            try:
                old.unlink()
            except OSError:
                pass

    def history_list(self, name: str) -> list[dict]:
        """某篇笔记的历史版本列表（新的在前）。"""
        name = safe_name(name)
        vdir = self.history / name
        if not vdir.exists():
            return []
        out = []
        for f in sorted(vdir.glob("*.md"), reverse=True):
            try:
                st = f.stat()
            except OSError:
                continue
            out.append(
                {
                    "file": f.name,
                    "time": iso_from_ts(st.st_mtime),
                    "size": st.st_size,
                }
            )
        return out

    def history_get(self, name: str, fname: str) -> dict:
        """读取某个历史版本的内容。fname 必须来自 history_list，防目录穿越。"""
        name = safe_name(name)
        if not re.match(r"^\d{8}-\d{6}-\d{6}\.md$", fname):
            raise ValueError(f"非法的历史版本名: {fname!r}")
        f = self.history / name / fname
        if not f.exists():
            raise FileNotFoundError(fname)
        raw = read_text(f)
        _, body = parse_frontmatter(raw)
        return {"file": fname, "content": body}

    def history_restore(self, name: str, fname: str) -> dict:
        """把当前内容存档后，用历史版本覆盖当前笔记。"""
        name = safe_name(name)
        version = self.history_get(name, fname)
        raw = read_text(self.history / name / fname)
        cur_path = self._note_path(name)
        if not cur_path.exists():
            raise FileNotFoundError(name)
        self._archive_version(name, read_text(cur_path))
        atomic_write(cur_path, raw)
        self._invalidate()
        return self.get(name)

    # ---- 回收站 ----

    def delete(self, name: str) -> dict:
        """软删除：移入 .trash 并登记索引。"""
        name = safe_name(name)
        src = self._note_path(name)
        if not src.exists():
            raise FileNotFoundError(name)
        self.trash.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        fname = f"{stamp}.md"
        dest = self.trash / fname
        atomic_write(dest, read_text(src))
        src.unlink()
        index = self._trash_index()
        index["entries"].append({"file": fname, "name": name, "deleted": now_iso()})
        self._save_trash_index(index)
        self._invalidate()
        return {"trashed": name, "file": fname}

    def _trash_index(self) -> dict:
        f = self.trash / "index.json"
        if f.exists():
            try:
                data = json.loads(read_text(f))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    return data
            except json.JSONDecodeError:
                pass
        return {"entries": []}

    def _save_trash_index(self, index: dict) -> None:
        atomic_write(self.trash / "index.json", json.dumps(index, ensure_ascii=False, indent=2))

    def trash_list(self) -> list[dict]:
        index = self._trash_index()["entries"]
        out = []
        for e in reversed(index):  # 最近删除在前
            f = self.trash / e["file"]
            size = f.stat().st_size if f.exists() else 0
            out.append({**e, "size": size})
        return out

    def restore(self, fname: str) -> dict:
        """从回收站恢复笔记；原名被占用时自动加“ (恢复)”后缀。"""
        index = self._trash_index()
        entry = next((e for e in index["entries"] if e["file"] == fname), None)
        if entry is None:
            raise FileNotFoundError(fname)
        src = self.trash / fname
        if not src.exists():
            raise FileNotFoundError(fname)
        name = safe_name(entry["name"])
        if self._note_path(name).exists():
            name = safe_name(f"{name} (恢复)")
        atomic_write(self._note_path(name), read_text(src))
        src.unlink()
        index["entries"] = [e for e in index["entries"] if e["file"] != fname]
        self._save_trash_index(index)
        self._invalidate()
        return self.get(name)

    def purge(self, fname: str) -> dict:
        """彻底删除回收站中的单个文件（仅限回收站目录内）。"""
        index = self._trash_index()
        entry = next((e for e in index["entries"] if e["file"] == fname), None)
        if entry is None:
            raise FileNotFoundError(fname)
        f = self.trash / fname
        if f.exists():
            f.unlink()
        index["entries"] = [e for e in index["entries"] if e["file"] != fname]
        self._save_trash_index(index)
        return {"purged": entry["name"]}

    # ---- 重命名 ----

    def rename(self, name: str, new_name: str) -> dict:
        """重命名笔记，并同步更新全库中指向旧名的双链文本。"""
        name = safe_name(name)
        new_name = safe_name(new_name)
        src = self._note_path(name)
        if not src.exists():
            raise FileNotFoundError(name)
        if new_name == name:
            return self.get(name)
        dest = self._note_path(new_name)
        if dest.exists():
            raise ValueError(f"目标笔记名已存在: {new_name}")
        # 同步改写其他笔记里的 [[旧名]] / [[旧名|别名]]
        for other, body in self.bodies_map().items():
            if other == name:
                continue
            new_body = body.replace(f"[[{name}]]", f"[[{new_name}]]").replace(
                f"[[{name}|", f"[[{new_name}|"
            )
            if new_body != body:
                note = self._index()[other]
                atomic_write(
                    self._note_path(other), serialize_note(dict(note["fm"]), new_body)
                )
        atomic_write(dest, read_text(src))
        src.unlink()
        self._invalidate()
        return self.get(new_name)

    def rename_tag(self, old: str, new: str) -> int:
        """全库重命名标签：改写 frontmatter tags 与行内 #标签，返回受影响笔记数。

        行内替换带边界约束，#ai 不会误伤 #ai2。
        """
        old_t = normalize_tags([old])
        new_t = normalize_tags([new])
        if not old_t or not new_t:
            raise ValueError("标签名不能为空")
        old, new = old_t[0], new_t[0]
        if old == new:
            return 0
        inline_re = re.compile(
            rf"(?<![\w/#\u4e00-\u9fff])#{re.escape(old)}(?![\w\u4e00-\u9fff\-/])"
        )
        changed_notes = 0
        for name, note in self._index().items():
            fm = dict(note["fm"])
            tags = fm.get("tags")
            fm_changed = False
            if isinstance(tags, list) and old in tags:
                seen: set[str] = set()
                merged: list[str] = []
                for t in tags:
                    t2 = new if t == old else t
                    if t2 not in seen:  # 目标标签已存在时视为合并，避免重复项
                        merged.append(t2)
                        seen.add(t2)
                fm["tags"] = merged
                fm_changed = True
            new_body, n_sub = inline_re.subn(f"#{new}", note["body"])
            if not fm_changed and n_sub == 0:
                continue
            atomic_write(self._note_path(name), serialize_note(fm, new_body))
            changed_notes += 1
        self._invalidate()
        return changed_notes

    # ---- 每日笔记 ----

    def ensure_daily(self, day: str | None = None) -> dict:
        """取当日（或指定日）笔记，不存在则按模板创建。"""
        day = day or date.today().isoformat()
        if not _DAILY_RE.match(day or ""):
            raise ValueError(f"日期格式应为 YYYY-MM-DD: {day!r}")
        if self.exists(day):
            return self.get(day)
        return self.save(day, DAILY_TEMPLATE.format(title=day), tags=[DAILY_TAG])

    # ---- 统计 ----

    def stats(self) -> dict:
        notes = self.list_notes()
        tag_counter: dict[str, int] = {}
        activity: dict[str, int] = {}
        for n in notes:
            for t in n["tags"]:
                tag_counter[t] = tag_counter.get(t, 0) + 1
            day = str(n["updated"])[:10]
            activity[day] = activity.get(day, 0) + 1
        words = sum(n["words"] for n in notes)
        return {
            "total": len(notes),
            "words": words,
            "tag_count": len(tag_counter),
            "tags": sorted(tag_counter.items(), key=lambda x: -x[1]),
            "activity": activity,
            "trash_count": len(self._trash_index()["entries"]),
        }
