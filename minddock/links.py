"""双链解析：[[目标]] / [[目标|别名]]、行内标签、反链索引、图谱构建。

提取前会先剥离围栏代码块与行内代码，避免代码示例中的链接
语法被误认为真实链接。
"""
from __future__ import annotations

import re
from collections import Counter

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")
_CODE_FENCE_RE = re.compile(r"```.*?(?:```|$)|~~~.*?(?:~~~|$)", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_INLINE_TAG_RE = re.compile(r"(?<![\w/#])#([\w\u4e00-\u9fff\-/]{1,32})")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def strip_code(text: str) -> str:
    """剥离围栏代码块与行内代码，返回用于链接/标签提取的纯文本。"""
    return _INLINE_CODE_RE.sub("", _CODE_FENCE_RE.sub("", text))


def extract_links(body: str) -> list[dict]:
    """提取正文中的双链，返回 [{target, alias}]，保持出现顺序去重。"""
    text = strip_code(body)
    seen: set[str] = set()
    out: list[dict] = []
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if not target or target in seen:
            continue
        seen.add(target)
        out.append({"target": target, "alias": (m.group(2) or "").strip()})
    return out


def extract_headings(body: str) -> list[str]:
    """提取各级标题文本（剥代码后），供搜索加权使用。"""
    return [m.group(1) for m in _HEADING_RE.finditer(strip_code(body))]


def extract_inline_tags(body: str) -> list[str]:
    """提取行内标签（#标签 形式，剥代码后），保持顺序去重。"""
    text = strip_code(body)
    seen: set[str] = set()
    out: list[str] = []
    for m in _INLINE_TAG_RE.finditer(text):
        tag = m.group(1).strip().strip("-")
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def _resolve(target: str, names: set[str], names_lower: dict[str, str]) -> str | None:
    """双链目标解析：先精确匹配，再大小写不敏感匹配，返回规范笔记名。"""
    if target in names:
        return target
    return names_lower.get(target.lower())


def build_index(bodies: dict[str, str]) -> dict:
    """构建链接索引。

    bodies: {笔记名: 正文}。返回:
      outgoing: {name: [解析后的目标名]}
      missing:  {name: [未解析目标]}（图谱中作为幽灵节点展示）
      incoming: {name: {来源名: 链接次数}}
    """
    names = set(bodies)
    names_lower = {n.lower(): n for n in bodies}
    outgoing: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    incoming: dict[str, dict[str, int]] = {}
    for name, body in bodies.items():
        o: list[str] = []
        miss: list[str] = []
        for link in extract_links(body):
            resolved = _resolve(link["target"], names, names_lower)
            if resolved is None:
                if link["target"] not in miss:
                    miss.append(link["target"])
            elif resolved != name and resolved not in o:
                o.append(resolved)
                incoming.setdefault(resolved, {})
                incoming[resolved][name] = incoming[resolved].get(name, 0) + 1
        outgoing[name] = o
        if miss:
            missing[name] = miss
    return {"outgoing": outgoing, "missing": missing, "incoming": incoming}


def build_graph(bodies: dict[str, str], titles: dict[str, str], tag_of: dict[str, list[str]]) -> dict:
    """构建图谱数据：节点按链接度定权重，未解析目标作为幽灵节点。"""
    idx = build_index(bodies)
    nodes: dict[str, dict] = {}
    for name in bodies:
        nodes[name] = {
            "id": name,
            "title": titles.get(name, name),
            "tags": tag_of.get(name, []),
            "degree": 0,
            "missing": False,
        }
    for targets in idx["outgoing"].values():
        for t in targets:
            if t in nodes:
                nodes[t]["degree"] += 1
    for miss_map in idx["missing"].values():
        for target in miss_map:
            key = f"::{target}"
            if key not in nodes:
                nodes[key] = {
                    "id": key,
                    "title": target,
                    "tags": [],
                    "degree": 0,
                    "missing": True,
                }
    links = []
    for source, targets in idx["outgoing"].items():
        for t in targets:
            links.append({"source": source, "target": t})
            nodes[source]["degree"] += 1
    for source, miss_map in idx["missing"].items():
        for target in miss_map:
            links.append({"source": source, "target": f"::{target}"})
    top_tags = Counter(t for ts in tag_of.values() for t in ts)
    for node in nodes.values():
        node["tag"] = node["tags"][0] if node["tags"] else ""
    return {
        "nodes": list(nodes.values()),
        "links": links,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags.most_common(12)],
    }
