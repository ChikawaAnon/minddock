"""通用工具：编码安全读写、原子写、安全文件名、时间格式。

约定：本项目写入的所有文本一律 UTF-8；读取外部文件时按
UTF-8 → GBK 顺序尝试解码，避免中文 Windows 环境下的乱码问题。
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

_WINDOWS_RESERVED_RE = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE
)
_FORBIDDEN_CHARS = '\\/:*?"<>|'


def safe_name(name: str) -> str:
    """校验并返回合法的笔记名（同时充当文件名 stem）。

    规则：非空；不含 Windows 非法字符；不以点开头；长度不超过 120；
    不得是 Windows 保留设备名。返回去除首尾空白后的名称。
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("笔记名不能为空")
    if any(ch in _FORBIDDEN_CHARS for ch in name):
        raise ValueError(f"笔记名含非法字符: {name!r}")
    if name.startswith("."):
        raise ValueError("笔记名不能以点开头")
    if len(name) > 120:
        raise ValueError("笔记名过长（超过 120 字符）")
    if _WINDOWS_RESERVED_RE.match(name):
        raise ValueError(f"笔记名是 Windows 保留设备名: {name!r}")
    return name


def read_text(path: str | os.PathLike) -> str:
    """读取文本文件：UTF-8 优先，失败回退 GBK，最后 errors=replace 兜底。"""
    data = Path(path).read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def atomic_write(path: str | os.PathLike, text: str) -> None:
    """原子写文本：先写临时文件再 os.replace，避免半截文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def now_iso() -> str:
    """本地时间 ISO 字符串（秒级），用于 frontmatter 时间戳。"""
    return datetime.now().replace(microsecond=0).isoformat()


def iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).replace(microsecond=0).isoformat()


def count_words(text: str) -> int:
    """字数统计：CJK 按字计，ASCII 按词计。"""
    cjk = sum(1 for ch in text if "\u2e80" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    ascii_words = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + ascii_words
