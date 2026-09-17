"""共享夹具。"""
import pytest

from minddock.notes import NoteStore


@pytest.fixture()
def store(tmp_path):
    return NoteStore(tmp_path / "notes")
