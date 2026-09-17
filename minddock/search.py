"""全文搜索：CJK 子串匹配 + ASCII 整词匹配，字段加权评分。

查询按空白拆分为多个关键词，全部命中（AND）才算匹配；
字段权重：标题 8 > 笔记名 6 > 标签 5 > 标题行 3 > 正文 1。
单字段命中数封顶 5，防止长文刷分。
"""
from __future__ import annotations

import re

_FIELD_WEIGHTS = [
    ("title", 8.0),
    ("name", 6.0),
    ("tags_str", 5.0),
    ("headings_str", 3.0),
    ("body", 1.0),
]
_PER_FIELD_CAP = 5
_SNIPPET_CONTEXT = 60

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _split_terms(query: str) -> list[str]:
    return [t for t in re.split(r"\s+", (query or "").strip()) if t]


def _is_ascii_term(term: str) -> bool:
    return term.isascii() and term.isalnum()


def _hits(term: str, text: str, word_mode: bool) -> int:
    """返回 term 在 text 中的命中次数（大小写不敏感）。"""
    if not text:
        return 0
    if word_mode:
        pat = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        return len(re.findall(pat, text, re.IGNORECASE))
    return text.casefold().count(term.casefold())


def _first_pos(terms: list[tuple[str, bool]], text: str) -> int:
    """各关键词在 text 中最早出现位置的最小值；找不到返回 -1。"""
    best = -1
    low = text.casefold()
    for term, word_mode in terms:
        if word_mode:
            m = re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE)
            pos = m.start() if m else -1
        else:
            pos = low.find(term.casefold())
        if pos != -1 and (best == -1 or pos < best):
            best = pos
    return best


def make_snippet(body: str, terms: list[tuple[str, bool]], width: int = _SNIPPET_CONTEXT) -> str:
    """围绕首个命中位置生成摘要片段。"""
    pos = _first_pos(terms, body)
    if pos == -1:
        return body.strip()[: width * 2]
    start = max(0, pos - width // 2)
    end = min(len(body), pos + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return f"{prefix}{body[start:end].strip()}{suffix}"


def search(notes: dict, query: str, limit: int = 50) -> list[dict]:
    """在索引字典上执行搜索。

    notes: {name: {name,title,tags,headings,body,updated,...}}（NoteStore._index 的值）。
    返回按分数降序的结果列表，每项含 score 与 snippet。
    """
    terms = [(t, _is_ascii_term(t)) for t in _split_terms(query)]
    if not terms:
        return []
    results = []
    for name, note in notes.items():
        fields = {
            "title": note.get("title", ""),
            "name": name,
            "tags_str": " ".join(note.get("tags", [])),
            "headings_str": " ".join(note.get("headings", [])),
            "body": note.get("body", ""),
        }
        score = 0.0
        matched_all = True
        for term, word_mode in terms:
            term_score = 0.0
            hit = False
            for field, weight in _FIELD_WEIGHTS:
                n = _hits(term, fields[field], word_mode)
                if n > 0:
                    hit = True
                    term_score += weight * min(n, _PER_FIELD_CAP)
            if not hit:
                matched_all = False
                break
            score += term_score
        if not matched_all:
            continue
        results.append(
            {
                "name": name,
                "title": note.get("title", name),
                "tags": note.get("tags", []),
                "updated": note.get("updated", ""),
                "score": round(score, 2),
                "snippet": make_snippet(fields["body"], terms),
            }
        )
    # 借助稳定排序实现“分数降序，同分按更新时间新者优先”
    results.sort(key=lambda r: r.get("updated", ""), reverse=True)
    results.sort(key=lambda r: -r["score"])
    return results[:limit]
