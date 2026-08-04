"""
Tests for dashboard/assets.py's ensure_vendored_assets(): copies the built
webui/ output (dist/ -- echarts.min.js plus the hashed CSS/JS bundle,
produced by `npm run build`) and the app icon (icon.png) next to a
generated dashboard, so relative asset references in the HTML resolve
regardless of how the page is served (file://, plain Flask, Ingress, or the
add-on's direct port).

The required-vs-optional distinction matters concretely: icon.png is
cosmetic (iOS just shows a generic icon if it's missing), so its absence
must never be able to break every dashboard write the way a missing dist/
(no CSS or charts at all) correctly still does.
"""

import os

import pytest

from dashboard.assets import ensure_vendored_assets


def _make_fake_dist(dist_dir, manifest_contents='{"src/main.js": {"file": "assets/main-a.js", "css": ["assets/main-a.css"]}}'):
    os.makedirs(os.path.join(dist_dir, ".vite"), exist_ok=True)
    os.makedirs(os.path.join(dist_dir, "assets"), exist_ok=True)
    with open(os.path.join(dist_dir, ".vite", "manifest.json"), "w") as f:
        f.write(manifest_contents)
    with open(os.path.join(dist_dir, "echarts.min.js"), "w") as f:
        f.write("// fake echarts")
    with open(os.path.join(dist_dir, "assets", "main-a.js"), "w") as f:
        f.write("// fake bundle")
    with open(os.path.join(dist_dir, "assets", "main-a.css"), "w") as f:
        f.write("/* fake styles */")


class TestEnsureVendoredAssets:
    def test_copies_dist_and_optional_assets(self, tmp_path):
        # Exercises the repo's real, actually-built dist/ (this test suite
        # requires `npm run build` to have been run in webui/ first -- see
        # .github/workflows/tests.yml) -- not a synthetic fixture, so a
        # real manifest/bundle mismatch would be caught here too.
        ensure_vendored_assets(str(tmp_path))
        assets_dir = tmp_path / "assets"
        assert (assets_dir / "dist" / ".vite" / "manifest.json").exists()
        assert (assets_dir / "dist" / "echarts.min.js").exists()
        assert (assets_dir / "icon.png").exists()

    def test_missing_optional_asset_does_not_crash(self, tmp_path, monkeypatch):
        import dashboard.assets as da

        fake_source = tmp_path / "fake_source"
        fake_source.mkdir()
        _make_fake_dist(str(fake_source / "dist"))
        # icon.png intentionally absent from the source dir this run --
        # dist/ must still copy fine, no exception raised.
        monkeypatch.setattr(da, "_SOURCE_DIR", str(fake_source))
        monkeypatch.setattr(da, "_SOURCE_DIST_DIR", str(fake_source / "dist"))

        dest = tmp_path / "dest"
        ensure_vendored_assets(str(dest))

        assert (dest / "assets" / "dist" / "echarts.min.js").exists()
        assert not (dest / "assets" / "icon.png").exists()

    def test_missing_dist_raises(self, tmp_path, monkeypatch):
        import dashboard.assets as da

        fake_source = tmp_path / "fake_source"
        fake_source.mkdir()
        # dist/ deliberately never created
        monkeypatch.setattr(da, "_SOURCE_DIR", str(fake_source))
        monkeypatch.setattr(da, "_SOURCE_DIST_DIR", str(fake_source / "dist"))

        with pytest.raises(RuntimeError, match="webui build output not found"):
            ensure_vendored_assets(str(tmp_path / "dest"))

    def test_does_not_rewrite_an_up_to_date_dist(self, tmp_path, monkeypatch):
        # Avoids re-copying dist/ (and rewriting icon.png) on every single
        # run -- skip if dest is already present and not older than source.
        import dashboard.assets as da

        fake_source = tmp_path / "fake_source"
        fake_source.mkdir()
        _make_fake_dist(str(fake_source / "dist"))
        (fake_source / "icon.png").write_text("fake icon")
        monkeypatch.setattr(da, "_SOURCE_DIR", str(fake_source))
        monkeypatch.setattr(da, "_SOURCE_DIST_DIR", str(fake_source / "dist"))

        dest = tmp_path / "dest"
        ensure_vendored_assets(str(dest))
        bundle_path = dest / "assets" / "dist" / "assets" / "main-a.js"
        icon_path = dest / "assets" / "icon.png"
        first_bundle_mtime = os.path.getmtime(bundle_path)
        first_icon_mtime = os.path.getmtime(icon_path)

        ensure_vendored_assets(str(dest))
        assert os.path.getmtime(bundle_path) == first_bundle_mtime
        assert os.path.getmtime(icon_path) == first_icon_mtime
