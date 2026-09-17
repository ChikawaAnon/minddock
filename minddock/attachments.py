"""图片附件存储：笔记可粘贴/拖入图片，存到数据根的 attachments/ 目录。

安全边界：扩展名白名单（仅常见位图格式）；文件名清洗；大小上限；
服务层只以对应图片 Content-Type 提供白名单文件，杜绝把上传目录当
HTML 宿主（存储型 XSS）的可能。
"""
from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from pathlib import Path

ATT_DIR = "attachments"
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024  # 8MB

# 扩展名 → Content-Type（刻意不含 svg/html 等可执行类型）
ALLOWED = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

_NAME_CLEAN_RE = re.compile(r"[^\w\u4e00-\u9fff\-.]+")
_VALID_FILE_RE = re.compile(r"^[\w\u4e00-\u9fff\-]+\.(png|jpe?g|gif|webp|bmp)$", re.IGNORECASE)


class AttachmentError(ValueError):
    """附件校验失败。"""


def save_attachment(root: Path, data_b64: str, filename: str) -> str:
    """保存 base64 图片，返回 Markdown 里应使用的相对路径。"""
    if not data_b64:
        raise AttachmentError("附件内容为空")
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise AttachmentError("附件不是合法的 base64 数据")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("图片超过 8MB 上限")

    fname = (filename or "image").replace("\\", "/").split("/")[-1]
    stem, dot, ext = fname.rpartition(".")
    ext = f"{dot}{ext}".lower()
    if ext not in ALLOWED:
        raise AttachmentError(f"不支持的图片格式: {ext or '(无扩展名)'}")
    stem = _NAME_CLEAN_RE.sub("-", stem).strip("-") or "image"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    rel = f"{ATT_DIR}/{stamp}-{stem}{ext}"

    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    import os

    os.replace(tmp, target)
    return rel


def content_type_of(filename: str) -> str | None:
    """白名单文件的 Content-Type；非白名单一律 None（拒绝提供）。"""
    return ALLOWED.get(Path(filename).suffix.lower())


def valid_attachment_name(filename: str) -> bool:
    """服务层提供的文件名必须匹配白名单形态，防路径穿越与任意文件读取。"""
    return bool(_VALID_FILE_RE.match(filename))


def collect_images(root: Path, rel_paths: list[str]) -> dict[str, str]:
    """为导出收集图片的 data URI。路径必须形如 attachments/xxx 且在白名单内。"""
    out: dict[str, str] = {}
    for rel in rel_paths:
        name = rel.split("/", 1)[-1]
        if not rel.startswith(f"{ATT_DIR}/") or not valid_attachment_name(name):
            continue
        f = root / rel
        if not f.exists():
            continue
        ctype = content_type_of(name)
        if ctype is None:
            continue
        out[rel] = f"data:{ctype};base64,{base64.b64encode(f.read_bytes()).decode('ascii')}"
    return out
