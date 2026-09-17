"""导出单文件 HTML 测试。"""
from minddock.export_book import _escape_script, build_book_html

SAMPLE_MD_JS = 'window.MindMD = { render: function () {}; };'  # 结构占位，仅验证内嵌


class TestEscapeScript:
    def test_closes_script_escaped(self):
        assert _escape_script("a</script>b") == "a<\\/script>b"
        assert _escape_script("x</SCRIPT>y") == "x<\\/SCRIPT>y"  # 保留原大小写，同样无害化

    def test_plain_source_untouched(self):
        assert _escape_script("var a = 1;") == "var a = 1;"


class TestBuildBook:
    def _items(self):
        return [
            {
                "name": "甲",
                "title": "甲笔记",
                "tags": ["t"],
                "updated": "2026-09-07T01:00:00",
                "content": "# 甲\n\n[[乙]]",
                "missing": ["乙"],
                "incoming": [],
            },
            {
                "name": "乙",
                "title": "乙",
                "tags": [],
                "updated": "2026-09-06T01:00:00",
                "content": "含 </script> 的正文",
                "missing": [],
                "incoming": ["甲"],
            },
        ]

    def test_contains_data_and_renderer(self):
        html = build_book_html(self._items(), SAMPLE_MD_JS)
        assert "MindMD" in html
        assert "\\u7532" not in html  # ensure_ascii=False，中文直出
        assert "甲笔记" in html

    def test_script_safety(self):
        html = build_book_html(self._items(), SAMPLE_MD_JS)
        body_script = html.split("<script>__MDJS__".replace("__MDJS__", ""))  # 模板已填充
        # 正文里的 </script> 必须被转义，不得出现裸露的闭合标签
        assert "</script> 的正文" not in html
        assert "<\\/script> 的正文" in html

    def test_json_closing_escaped(self):
        html = build_book_html(self._items(), SAMPLE_MD_JS)
        assert html.count("</script>") == 2  # 仅两个真实脚本闭合：md.js 与 viewer

    def test_title_replaced(self):
        html = build_book_html(self._items(), SAMPLE_MD_JS, title="我的库")
        assert "我的库" in html
        assert "__MDDATA__" not in html and "__MDJS__" not in html and "__TITLE__" not in html

    def test_real_md_js_loads(self):
        from minddock.export_book import load_md_js

        html = build_book_html(self._items(), load_md_js())
        assert "MindMD" in html
        assert html.count("</script>") == 2
