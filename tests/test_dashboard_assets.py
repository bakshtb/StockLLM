"""
Tests for dashboard/assets.py's ensure_vendored_assets(): copies the
vendored chart runtime (echarts.min.js, dashboard.js) and the app icon
(icon.png) next to a generated dashboard, so relative asset references in
the HTML resolve regardless of how the page is served (file://, plain
Flask, Ingress, or the add-on's direct port).

The required-vs-optional distinction matters concretely: icon.png is
cosmetic (iOS just shows a generic icon if it's missing), so its absence
must never be able to break every dashboard write the way a missing
required asset (no charts at all without echarts.min.js) correctly still
does.
"""

import os

import pytest

from dashboard.assets import ensure_vendored_assets


class TestEnsureVendoredAssets:
    def test_copies_required_and_optional_assets(self, tmp_path):
        ensure_vendored_assets(str(tmp_path))
        assets_dir = tmp_path / "assets"
        assert (assets_dir / "echarts.min.js").exists()
        assert (assets_dir / "dashboard.js").exists()
        assert (assets_dir / "icon.png").exists()

    def test_missing_optional_asset_does_not_crash(self, tmp_path, monkeypatch):
        # icon.png intentionally absent from the source dir this run --
        # required assets must still copy fine, no exception raised.
        import dashboard.assets as da

        fake_source = tmp_path / "fake_source"
        fake_source.mkdir()
        (fake_source / "echarts.min.js").write_text("// fake")
        (fake_source / "dashboard.js").write_text("// fake")
        monkeypatch.setattr(da, "_SOURCE_DIR", str(fake_source))

        dest = tmp_path / "dest"
        ensure_vendored_assets(str(dest))

        assert (dest / "assets" / "echarts.min.js").exists()
        assert (dest / "assets" / "dashboard.js").exists()
        assert not (dest / "assets" / "icon.png").exists()

    def test_missing_required_asset_still_raises(self, tmp_path, monkeypatch):
        import dashboard.assets as da

        fake_source = tmp_path / "fake_source"
        fake_source.mkdir()
        (fake_source / "dashboard.js").write_text("// fake")
        # echarts.min.js deliberately missing
        monkeypatch.setattr(da, "_SOURCE_DIR", str(fake_source))

        with pytest.raises(FileNotFoundError):
            ensure_vendored_assets(str(tmp_path / "dest"))

    def test_does_not_rewrite_an_up_to_date_file(self, tmp_path):
        # Avoids rewriting on every single run -- skip if dest is already
        # present and not older than its source.
        ensure_vendored_assets(str(tmp_path))
        icon_path = tmp_path / "assets" / "icon.png"
        first_mtime = os.path.getmtime(icon_path)

        ensure_vendored_assets(str(tmp_path))
        assert os.path.getmtime(icon_path) == first_mtime
