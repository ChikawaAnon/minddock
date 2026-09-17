"""搜索与双链/图谱测试。"""
import pytest

from minddock.links import (
    build_graph,
    build_index,
    extract_headings,
    extract_inline_tags,
    extract_links,
    strip_code,
)
from minddock.search import make_snippet, search


@pytest.fixture()
def corpus():
    return {
        "Python 装饰器": {
            "name": "Python 装饰器",
            "title": "Python 装饰器入门",
            "tags": ["python", "笔记"],
            "headings": ["什么是装饰器"],
            "body": "# 什么是装饰器\n\n装饰器是 [[函数式编程]] 的应用 #python\n",
            "updated": "2026-09-01T10:00:00",
        },
        "函数式编程": {
            "name": "函数式编程",
            "title": "函数式编程",
            "tags": ["python"],
            "headings": [],
            "body": "闭包与高阶函数。参考 [[Python 装饰器]]。",
            "updated": "2026-09-02T10:00:00",
        },
        "购物清单": {
            "name": "购物清单",
            "title": "购物清单",
            "tags": [],
            "headings": [],
            "body": "牛奶、鸡蛋、python 教程书",
            "updated": "2026-09-03T10:00:00",
        },
    }


class TestExtractLinks:
    def test_basic(self):
        assert extract_links("见 [[目标]] 与 [[其他|别名]]") == [
            {"target": "目标", "alias": ""},
            {"target": "其他", "alias": "别名"},
        ]

    def test_dedup_keep_order(self):
        assert extract_links("[[a]] [b] [[a]] [[b]]") == [
            {"target": "a", "alias": ""},
            {"target": "b", "alias": ""},
        ]

    def test_ignores_single_bracket(self):
        assert extract_links("[普通链接](http://x)") == []

    def test_ignores_code(self):
        assert extract_links("正文 [[真实]]\n```py\n[[代码里]]\n```\n`[[行内]]`") == [
            {"target": "真实", "alias": ""}
        ]

    def test_empty_target_skipped(self):
        assert extract_links("[[ ]]") == []


class TestInlineTags:
    def test_basic(self):
        assert extract_inline_tags("#python #AI/子标签 x#不匹配") == ["python", "AI/子标签"]

    def test_heading_not_tag(self):
        assert extract_inline_tags("# 一级标题\n## 二级") == []

    def test_code_not_tag(self):
        assert extract_inline_tags("```\n#注释\n```") == []

    def test_url_fragment_not_tag(self):
        assert extract_inline_tags("http://x.com/#frag") == []


class TestHeadings:
    def test_levels(self):
        assert extract_headings("# A\n## B\n正文\n### C #") == ["A", "B", "C"]


class TestBuildIndex:
    def test_outgoing_incoming(self, corpus):
        idx = build_index({k: v["body"] for k, v in corpus.items()})
        assert idx["outgoing"]["Python 装饰器"] == ["函数式编程"]
        assert idx["incoming"]["Python 装饰器"] == {"函数式编程": 1}

    def test_missing(self, corpus):
        bodies = {"a": "链到 [[幽灵]]"}
        idx = build_index(bodies)
        assert idx["missing"]["a"] == ["幽灵"]
        assert idx["incoming"] == {}

    def test_case_insensitive_resolve(self):
        idx = build_index({"MyNote": "link [[mynote]]"})
        assert idx["outgoing"]["MyNote"] == []

    def test_self_link_ignored(self):
        idx = build_index({"a": "[[a]]"})
        assert idx["outgoing"]["a"] == []


class TestGraph:
    def test_nodes_and_links(self, corpus):
        g = build_graph(
            {k: v["body"] for k, v in corpus.items()},
            {k: v["title"] for k, v in corpus.items()},
            {k: v["tags"] for k, v in corpus.items()},
        )
        ids = {n["id"] for n in g["nodes"]}
        assert "Python 装饰器" in ids and "函数式编程" in ids
        assert {"source": "Python 装饰器", "target": "函数式编程"} in g["links"]

    def test_ghost_nodes(self):
        g = build_graph({"a": "[[不存在]]"}, {"a": "a"}, {"a": []})
        ghosts = [n for n in g["nodes"] if n["missing"]]
        assert len(ghosts) == 1 and ghosts[0]["title"] == "不存在"

    def test_degree(self, corpus):
        g = build_graph(
            {k: v["body"] for k, v in corpus.items()},
            {k: v["title"] for k, v in corpus.items()},
            {},
        )
        deg = {n["id"]: n["degree"] for n in g["nodes"]}
        assert deg["函数式编程"] >= 1


class TestSearch:
    def test_single_term(self, corpus):
        r = search(corpus, "装饰器")
        assert r[0]["name"] == "Python 装饰器"

    def test_and_semantics(self, corpus):
        r = search(corpus, "闭包 高阶")
        assert [x["name"] for x in r] == ["函数式编程"]

    def test_and_no_match(self, corpus):
        assert search(corpus, "闭包 牛奶") == []

    def test_title_beats_body(self, corpus):
        r = search(corpus, "python")
        assert r[0]["name"] == "Python 装饰器"  # 标题+标签双重命中

    def test_tag_match(self, corpus):
        r = search(corpus, "python")
        names = [x["name"] for x in r]
        assert "购物清单" in names and "函数式编程" in names

    def test_ascii_word_boundary(self, corpus):
        assert search(corpus, "pyth") == []  # 整词匹配，前缀/嵌词不算
        tricky = {"a": {"name": "a", "title": "a", "tags": [], "headings": [], "body": "pythonista pyth3", "updated": ""}}
        assert search(tricky, "pyth") == []
        assert search(tricky, "pyth3") != []  # 字母数字混合词可整词命中

    def test_cjk_substring(self, corpus):
        r = search(corpus, "清单")
        assert r[0]["name"] == "购物清单"

    def test_empty_query(self, corpus):
        assert search(corpus, "  ") == []

    def test_snippet_contains_term(self, corpus):
        r = search(corpus, "闭包")
        assert "闭包" in r[0]["snippet"]

    def test_snippet_no_match_falls_back(self):
        s = make_snippet("第一行内容", [("不存在词", False)])
        assert "第一行内容" in s

    def test_limit(self, corpus):
        r = search(corpus, "python", limit=1)
        assert len(r) == 1

    def test_case_insensitive_ascii(self):
        corpus = {"a": {"name": "a", "title": "Note", "tags": [], "headings": [], "body": "Hello World", "updated": ""}}
        assert search(corpus, "hello")[0]["name"] == "a"
        assert search(corpus, "WORLD")[0]["name"] == "a"
