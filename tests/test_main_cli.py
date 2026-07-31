"""
Tests for main.py's _resolve_output_path -- the shared path-resolution logic
behind both `check --dry-run` and `dashboard`'s --output flag.
"""

import os

import pytest

import main


@pytest.fixture(autouse=True)
def patched_output_dir(monkeypatch, tmp_path):
    # main.py imports OUTPUT_DIR by name (`from config import ... OUTPUT_DIR`),
    # which binds a local copy at import time -- patch main.OUTPUT_DIR
    # directly, not config.OUTPUT_DIR, or _resolve_output_path won't see it.
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    return tmp_path


class TestResolveOutputPath:
    def test_no_explicit_path_uses_output_dir_and_default_filename(self, patched_output_dir):
        path = main._resolve_output_path(None, "AAPL.json")
        assert path == os.path.join(str(patched_output_dir), "AAPL.json")

    def test_empty_string_explicit_path_treated_as_no_path(self, patched_output_dir):
        path = main._resolve_output_path("", "AAPL.json")
        assert path == os.path.join(str(patched_output_dir), "AAPL.json")

    def test_bare_filename_redirected_into_output_dir(self, patched_output_dir):
        path = main._resolve_output_path("custom.json", "AAPL.json")
        assert path == os.path.join(str(patched_output_dir), "custom.json")

    def test_explicit_relative_path_with_directory_honored_as_is(self, patched_output_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = main._resolve_output_path("subdir/custom.json", "AAPL.json")
        assert path == "subdir/custom.json"

    def test_explicit_absolute_path_honored_as_is(self, patched_output_dir, tmp_path):
        target = str(tmp_path / "elsewhere" / "custom.json")
        path = main._resolve_output_path(target, "AAPL.json")
        assert path == target

    def test_creates_parent_directory(self, patched_output_dir):
        path = main._resolve_output_path(None, "AAPL.json")
        assert os.path.isdir(os.path.dirname(path))

    def test_creates_parent_directory_for_explicit_path(self, patched_output_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        main._resolve_output_path("newdir/custom.json", "AAPL.json")
        assert os.path.isdir("newdir")
