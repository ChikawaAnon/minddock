"""NoteStore 核心测试：frontmatter、增删改查、回收站、每日笔记、统计。"""
import json

import pytest

from minddock.notes import (
    NoteStore,
    normalize_tags,
    parse_frontmatter,
    serialize_note,
)
from minddock.util import safe_name


class TestFrontmatter:
    def test_parse_basic(self):
        fm, body = parse_frontmatter("---\ntitle: T\ntags: [a, b]\n---\n\n正文")
        assert fm == {"title": "T", "tags": ["a", "b"]}
        assert body == "\n正文"

    def test_parse_without_fm(self):
        fm, body = parse_frontmatter("纯正文")
        assert fm == {}
        assert body == "纯正文"

    def test_parse_empty_tags(self):
        fm, body = parse_frontmatter("---\ntags: []\n---\nX")
        assert fm["tags"] == []
        assert body == "X"

    def test_parse_quoted_value(self):
        fm, _ = parse_frontmatter('---\ntitle: "带 引号"\n---\nX')
        assert fm["title"] == "带 引号"

    def test_parse_crlf(self):
        fm, body = parse_frontmatter("---\r\ntitle: T\r\n---\r\nX")
        assert fm["title"] == "T"
        assert body == "X"

    def test_parse_ignores_colon_in_value(self):
        fm, _ = parse_frontmatter("---\ntitle: 键: 值\n---\nX")
        assert fm["title"] == "键: 值"

    def test_serialize_roundtrip(self):
        text = serialize_note({"title": "T", "tags": ["a", "b"]}, "# 正文")
        fm, body = parse_frontmatter(text)
        assert fm["title"] == "T"
        assert fm["tags"] == ["a", "b"]
        assert body == "# 正文"

    def test_serialize_empty_fm(self):
        assert serialize_note({}, "X") == "X"


class TestTags:
    def test_normalize_string(self):
        assert normalize_tags("a, b，c  d") == ["a", "b", "c", "d"]

    def test_normalize_list_dedup(self):
        assert normalize_tags(["a", "a", "#b", ""]) == ["a", "b"]

    def test_normalize_none(self):
        assert normalize_tags(None) == []

    def test_normalize_caps_length(self):
        assert normalize_tags(["x" * 50]) == ["x" * 32]


class TestSafeName:
    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            safe_name("  ")

    def test_rejects_path_separator(self):
        for bad in ("a/b", "a\\b", "..", "../x"):
            with pytest.raises(ValueError):
                safe_name(bad)

    def test_rejects_windows_reserved(self):
        for bad in ("con", "CON.md", "nul.txt", "com1"):
            with pytest.raises(ValueError):
                safe_name(bad)

    def test_rejects_leading_dot(self):
        with pytest.raises(ValueError):
            safe_name(".hidden")

    def test_rejects_long(self):
        with pytest.raises(ValueError):
            safe_name("x" * 121)

    def test_accepts_chinese_and_spaces(self):
        assert safe_name("  我的 笔记-01  ") == "我的 笔记-01"


class TestCrud:
    def test_create_and_get(self, store):
        n = store.save("测试", "内容", title="标题", tags=["t1"])
        assert n["title"] == "标题"
        assert n["tags"] == ["t1"]
        assert n["content"] == "内容"

    def test_save_persists_file(self, store):
        store.save("测试", "内容")
        assert (store.root / "测试.md").exists()

    def test_update_keeps_created(self, store):
        n1 = store.save("测试", "v1")
        n2 = store.save("测试", "v2")
        assert n2["created"] == n1["created"]
        assert n2["content"] == "v2"

    def test_update_preserves_fm_fields(self, store):
        store.save("测试", "v1", tags=["old"])
        n = store.save("测试", "v2", tags=["new"])
        assert n["tags"] == ["new"]

    def test_get_missing_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.get("不存在")

    def test_absorb_pasted_frontmatter(self, store):
        n = store.save("粘贴", "---\ntitle: 外来标题\nsource: web\n---\n正文")
        assert n["title"] == "外来标题"
        assert n["content"] == "正文"
        again = store.get("粘贴")
        assert again["fm"].get("source") == "web"

    def test_external_edit_detected(self, store):
        store.save("测试", "v1")
        (store.root / "测试.md").write_text("---\ntitle: 外改\n---\n外部修改", encoding="utf-8")
        n = store.get("测试")
        assert n["title"] == "外改"
        assert n["content"] == "外部修改"

    def test_list_sorted_by_mtime(self, store):
        store.save("甲", "1")
        store.save("乙", "2")
        store.save("甲", "1 updated")
        names = [n["name"] for n in store.list_notes()]
        assert names[0] == "甲"

    def test_excerpt_and_words(self, store):
        n = store.save("统计", "hello world " * 10 + "中文字符")
        assert n["words"] >= 22
        assert "hello" in n["excerpt"]


class TestTrash:
    def test_delete_moves_to_trash(self, store):
        store.save("测试", "内容")
        info = store.delete("测试")
        assert not (store.root / "测试.md").exists()
        assert (store.trash / info["file"]).exists()
        assert store.list_notes() == []

    def test_delete_missing_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.delete("不存在")

    def test_trash_list_and_restore(self, store):
        store.save("测试", "内容")
        info = store.delete("测试")
        items = store.trash_list()
        assert len(items) == 1
        assert items[0]["name"] == "测试"
        n = store.restore(info["file"])
        assert n["name"] == "测试"
        assert n["content"] == "内容"
        assert store.trash_list() == []

    def test_restore_name_conflict(self, store):
        store.save("测试", "v1")
        info = store.delete("测试")
        store.save("测试", "v2")
        n = store.restore(info["file"])
        assert n["name"] == "测试 (恢复)"
        assert n["content"] == "v1"

    def test_purge(self, store):
        store.save("测试", "内容")
        info = store.delete("测试")
        assert store.purge(info["file"]) == {"purged": "测试"}
        assert store.trash_list() == []
        assert not (store.trash / info["file"]).exists()

    def test_double_delete_ok(self, store):
        store.save("测试", "内容")
        store.delete("测试")
        with pytest.raises(FileNotFoundError):
            store.delete("测试")

    def test_trash_index_survives_corruption(self, store):
        store.save("测试", "内容")
        store.trash.mkdir(exist_ok=True)
        (store.trash / "index.json").write_text("{broken", encoding="utf-8")
        assert store.trash_list() == []  # 损坏时回退空索引，不崩溃


class TestDaily:
    def test_ensure_daily_creates_with_template(self, store):
        n = store.ensure_daily("2026-09-07")
        assert n["name"] == "2026-09-07"
        assert "每日笔记" in n["tags"]
        assert "今日完成" in n["content"]

    def test_ensure_daily_idempotent(self, store):
        a = store.ensure_daily("2026-09-07")
        a2 = store.ensure_daily("2026-09-07")
        assert a["name"] == a2["name"]

    def test_ensure_daily_bad_date(self, store):
        with pytest.raises(ValueError):
            store.ensure_daily("2026/09/07")


class TestStats:
    def test_stats_counts(self, store):
        store.save("甲", "内容一", tags=["x", "y"])
        store.save("乙", "内容二", tags=["x"])
        st = store.stats()
        assert st["total"] == 2
        assert st["tags"][0][0] == "x"
        assert st["words"] > 0
        assert st["trash_count"] == 0

    def test_stats_activity_by_day(self, store):
        store.save("甲", "内容")
        st = store.stats()
        assert any(v >= 1 for v in st["activity"].values())

    def test_trash_count(self, store):
        store.save("甲", "内容")
        store.delete("甲")
        assert store.stats()["trash_count"] == 1


class TestRename:
    def test_rename_updates_file(self, store):
        store.save("旧名", "内容")
        n = store.rename("旧名", "新名")
        assert n["name"] == "新名"
        assert not (store.root / "旧名.md").exists()
        assert (store.root / "新名.md").exists()
        assert store.get("新名")["content"] == "内容"

    def test_rename_updates_backlinks_text(self, store):
        store.save("目标", "正文")
        store.save("来源", "参考 [[目标]] 与 [[目标|别名]]")
        store.rename("目标", "新目标")
        assert "[[新目标]]" in store.get("来源")["content"]
        assert "[[新目标|别名]]" in store.get("来源")["content"]
        assert store.get("新目标")["incoming"] == ["来源"]

    def test_rename_conflict_raises(self, store):
        store.save("甲", "1")
        store.save("乙", "2")
        with pytest.raises(ValueError):
            store.rename("甲", "乙")

    def test_rename_missing_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.rename("不存在", "随便")

    def test_rename_bad_name_raises(self, store):
        store.save("甲", "1")
        with pytest.raises(ValueError):
            store.rename("甲", "a/b")

    def test_rename_same_name_noop(self, store):
        store.save("甲", "1")
        n = store.rename("甲", "甲")
        assert n["name"] == "甲"


class TestHistory:
    def test_save_archives_previous_version(self, store):
        store.save("甲", "v1 内容")
        store.save("甲", "v2 内容")
        items = store.history_list("甲")
        assert len(items) == 1
        assert store.history_get("甲", items[0]["file"])["content"] == "v1 内容"

    def test_history_empty_for_new_note(self, store):
        store.save("甲", "v1")
        assert store.history_list("甲") == []

    def test_restore_roundtrip(self, store):
        store.save("甲", "v1")
        store.save("甲", "v2")
        fname = store.history_list("甲")[0]["file"]
        n = store.history_restore("甲", fname)
        assert n["content"] == "v1"
        # 恢复时当前版本 v2 也被留档
        assert len(store.history_list("甲")) == 2

    def test_prune_keeps_recent_20(self, store):
        for i in range(25):
            store.save("甲", f"v{i}")
        items = store.history_list("甲")
        assert len(items) == 20
        oldest = store.history_get("甲", items[-1]["file"])
        assert oldest["content"] == "v4"  # 最旧 4 个版本被淘汰

    def test_history_get_rejects_bad_fname(self, store):
        store.save("甲", "v1")
        store.save("甲", "v2")
        with pytest.raises(ValueError):
            store.history_get("甲", "../甲/v1.md")

    def test_history_missing_raises(self, store):
        store.save("甲", "v1")
        with pytest.raises(FileNotFoundError):
            store.history_get("甲", "20990101-000000-000000.md")

    def test_history_isolated_from_scan(self, store):
        store.save("甲", "v1")
        store.save("甲", "v2")
        # .history 里的文件不应出现在笔记列表
        assert [n["name"] for n in store.list_notes()] == ["甲"]


class TestRenameTag:
    def test_renames_frontmatter_tags(self, store):
        store.save("甲", "内容", tags=["旧", "其他"])
        n = store.rename_tag("旧", "新")
        assert store.get("甲")["tags"] == ["新", "其他"]
        assert n == 1

    def test_renames_inline_tags_with_boundaries(self, store):
        store.save("甲", "#旧 标记和 #旧尾 以及 #新的 不动")
        store.rename_tag("旧", "新")
        # 独立的 #旧 被改写；#旧尾、#新的 这类更长标签不受影响
        assert store.get("甲")["content"] == "#新 标记和 #旧尾 以及 #新的 不动"

    def test_no_prefix_false_positive(self, store):
        store.save("甲", "标签 #ai 和 #ai2 都在")
        store.rename_tag("ai", "ML")
        body = store.get("甲")["content"]
        assert "#ML" in body and "#ai2" in body

    def test_merge_dedups(self, store):
        store.save("甲", "内容", tags=["a", "b"])
        store.rename_tag("a", "b")  # 合并到已存在的 b
        assert store.get("甲")["tags"] == ["b"]

    def test_empty_new_raises(self, store):
        store.save("甲", "内容", tags=["x"])
        with pytest.raises(ValueError):
            store.rename_tag("x", "  ")

    def test_same_name_is_noop(self, store):
        store.save("甲", "内容", tags=["x"])
        assert store.rename_tag("x", "x") == 0  # 同名重命名视为无操作

    def test_unknown_tag_returns_zero(self, store):
        store.save("甲", "内容", tags=["x"])
        assert store.rename_tag("不存在", "y") == 0


class TestTrashIndexFile:
    def test_index_json_writable(self, store):
        store.save("甲", "内容")
        info = store.delete("甲")
        data = json.loads((store.trash / "index.json").read_text(encoding="utf-8"))
        assert data["entries"][0]["file"] == info["file"]
