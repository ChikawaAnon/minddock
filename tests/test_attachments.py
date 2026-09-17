"""图片附件测试。"""
import base64

import pytest

from minddock.attachments import (
    AttachmentError,
    collect_images,
    content_type_of,
    save_attachment,
    valid_attachment_name,
)
from minddock.export_book import build_book_html, load_md_js, referenced_images

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"fakepngdata" * 20).decode("ascii")


class TestSaveAttachment:
    def test_save_valid_png(self, tmp_path):
        rel = save_attachment(tmp_path, PNG_B64, "截图 01.png")
        assert rel.startswith("attachments/")
        assert rel.endswith(".png")
        assert (tmp_path / rel).read_bytes().startswith(b"\x89PNG")

    def test_no_tmp_leftovers(self, tmp_path):
        save_attachment(tmp_path, PNG_B64, "a.png")
        assert list((tmp_path / "attachments").glob("*.tmp")) == []

    def test_rejects_bad_base64(self, tmp_path):
        with pytest.raises(AttachmentError):
            save_attachment(tmp_path, "!!!not-b64!!!", "a.png")

    def test_rejects_empty(self, tmp_path):
        with pytest.raises(AttachmentError):
            save_attachment(tmp_path, "", "a.png")

    def test_rejects_bad_ext(self, tmp_path):
        with pytest.raises(AttachmentError):
            save_attachment(tmp_path, PNG_B64, "page.html")
        with pytest.raises(AttachmentError):
            save_attachment(tmp_path, PNG_B64, "noext")

    def test_rejects_oversize(self, tmp_path, monkeypatch):
        from minddock import attachments as am

        monkeypatch.setattr(am, "MAX_ATTACHMENT_BYTES", 10)
        with pytest.raises(AttachmentError):
            save_attachment(tmp_path, PNG_B64, "a.png")

    def test_path_traversal_in_filename(self, tmp_path):
        rel = save_attachment(tmp_path, PNG_B64, "../../etc/x.png")
        assert ".." not in rel
        assert (tmp_path / rel).exists()


class TestValidation:
    def test_valid_names(self):
        assert valid_attachment_name("a.png")
        assert valid_attachment_name("截图-01.JPG")
        assert valid_attachment_name("x-20260907.webp")

    def test_invalid_names(self):
        assert not valid_attachment_name("../x.png")
        assert not valid_attachment_name("sub/x.png")
        assert not valid_attachment_name("a.html")
        assert not valid_attachment_name("a.svg")
        assert not valid_attachment_name("a")

    def test_content_types(self):
        assert content_type_of("a.png") == "image/png"
        assert content_type_of("a.JPG") == "image/jpeg"
        assert content_type_of("a.svg") is None


class TestCollectImages:
    def test_collect_and_embed(self, tmp_path):
        rel = save_attachment(tmp_path, PNG_B64, "p.png")
        out = collect_images(tmp_path, [rel, "attachments/missing.png", "attachments/../x.png"])
        assert rel in out
        assert out[rel].startswith("data:image/png;base64,")
        assert len(out) == 1  # 缺失与非法路径被跳过

    def test_referenced_images(self):
        items = [
            {"content": "看图 ![a](attachments/1.png) 与 ![b](attachments/2.png) 和 ![](attachments/1.png)"},
            {"content": "没有图片"},
        ]
        assert referenced_images(items) == ["attachments/1.png", "attachments/2.png"]

    def test_book_html_embeds_images(self, tmp_path):
        rel = save_attachment(tmp_path, PNG_B64, "p.png")
        items = [{"name": "甲", "title": "甲", "tags": [], "updated": "2026-09-07T00:00:00",
                  "content": f"![图]({rel})", "missing": [], "incoming": []}]
        atts = collect_images(tmp_path, referenced_images(items))
        html = build_book_html(items, load_md_js(), attachments=atts)
        assert "data:image/png;base64," in html
        assert html.count("</script>") == 2
