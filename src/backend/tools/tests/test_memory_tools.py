import pytest
from backend.tools.memory_tools import (
    _safe_resolve, execute_read_memory, execute_write_memory, execute_write_memory_stub,
)


def test_safe_resolve_normal_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    assert _safe_resolve("notes.md") == str(tmp_path / "notes.md")


def test_safe_resolve_blocks_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        _safe_resolve("../outside.md")


def test_safe_resolve_blocks_deep_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        _safe_resolve("sub/../../outside.md")


def test_safe_resolve_blocks_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        _safe_resolve("/etc/passwd")


def test_write_soul_md_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    result = execute_write_memory("SOUL.md", "overwrite")
    assert "read-only" in result
    assert not (tmp_path / "SOUL.md").exists()


def test_write_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    execute_write_memory("notes.md", "hello world")
    assert "hello world" in execute_read_memory("notes.md")


def test_write_empty_content_deletes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    execute_write_memory("to_delete.md", "something")
    result = execute_write_memory("to_delete.md", "   ")
    assert "Deleted" in result
    assert not (tmp_path / "to_delete.md").exists()


def test_write_empty_nonexistent_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    assert "Error" in execute_write_memory("missing.md", "")


def test_read_nonexistent_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    assert "Error" in execute_read_memory("missing.md")


def test_write_creates_subdirectories(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    execute_write_memory("sub/dir/file.md", "nested content")
    assert (tmp_path / "sub" / "dir" / "file.md").exists()


# --- stub: same messages/validation, no actual disk writes ---

def test_stub_write_soul_md_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    result = execute_write_memory_stub("SOUL.md", "overwrite")
    assert "read-only" in result


def test_stub_write_matches_real_success_message_but_does_not_touch_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    result = execute_write_memory_stub("notes.md", "hello world")
    assert result == "Written to notes.md"
    assert not (tmp_path / "notes.md").exists()


def test_stub_delete_of_existing_file_reports_deleted_without_deleting(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    execute_write_memory("to_keep.md", "something")
    result = execute_write_memory_stub("to_keep.md", "   ")
    assert "Deleted" in result
    assert (tmp_path / "to_keep.md").exists()


def test_stub_delete_of_missing_file_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    assert "Error" in execute_write_memory_stub("missing.md", "")
