"""
Copies the vendored/built assets (dist/, icon.png) next to a generated
dashboard HTML file. The HTML always references them via a plain relative
path ("assets/dist/...", "assets/icon.png"), which resolves correctly
whether the page is opened directly (file://), served by Flask without
Ingress, served behind Home Assistant's Ingress proxy, or served via the
add-on's directly-exposed port -- a relative URL resolves against the
document's own location, so no route or ingress-prefix handling is needed
here at all. (webapp/app.py's index page, which isn't inside an OUTPUT_DIR
run folder, references the same source files a different way -- see its
`/assets/<filename>` route.)

Called from every place that writes a dashboard HTML file to disk, passing
that call's *actual* output directory -- not a single hardcoded OUTPUT_DIR --
since main.py's `dashboard <file.json>` command can write next to an
arbitrary source file or an explicit -o path, not just into OUTPUT_DIR.
"""

import os
import shutil

_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_SOURCE_DIST_DIR = os.path.join(_SOURCE_DIR, "dist")
# Required: the dashboard has no CSS or charts at all without this (a
# missing dist/ means webui/ was never built -- see
# dashboard.generate_dashboard.load_built_assets(), which already refuses
# to even generate the HTML in that case, so this should only ever be
# missing if something copied/generated a dashboard file without going
# through build_dashboard() first). Optional: purely cosmetic -- iOS just
# shows a generic icon if missing, nothing about the actual dashboard
# depends on it -- so a missing or deleted icon.png must never be able to
# break every single dashboard write the way a missing dist/ correctly
# still does.
_OPTIONAL_ASSET_FILES = ("icon.png",)


def ensure_vendored_assets(dest_dir: str) -> None:
    """Copies dist/ (webui's Vite build output) and icon.png into
    dest_dir/assets/."""
    dest_assets_dir = os.path.join(dest_dir, "assets")
    os.makedirs(dest_assets_dir, exist_ok=True)
    if not os.path.isdir(_SOURCE_DIST_DIR):
        raise RuntimeError(
            f"webui build output not found at {_SOURCE_DIST_DIR} -- run "
            "`npm ci && npm run build` inside webui/ first."
        )
    _copy_dist_if_changed(_SOURCE_DIST_DIR, os.path.join(dest_assets_dir, "dist"))
    for name in _OPTIONAL_ASSET_FILES:
        src = os.path.join(_SOURCE_DIR, name)
        if os.path.exists(src):
            _copy_if_stale(src, os.path.join(dest_assets_dir, name))


def _copy_dist_if_changed(src: str, dst: str) -> None:
    """dist/'s filenames are content-hashed by Vite, so a per-file staleness
    check (like _copy_if_stale below) can't detect "source changed" the way
    it can for a single fixed-name file -- a changed build produces
    entirely new filenames rather than an updated mtime on an existing one.
    Comparing the manifest's own mtime is a cheap, accurate proxy for "has
    this build output changed since it was last copied here" without
    re-copying on every single dashboard write."""
    src_manifest = os.path.join(src, ".vite", "manifest.json")
    dst_manifest = os.path.join(dst, ".vite", "manifest.json")
    if os.path.isdir(dst) and os.path.exists(dst_manifest) and \
            os.path.getmtime(dst_manifest) >= os.path.getmtime(src_manifest):
        return
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _copy_if_stale(src: str, dst: str) -> None:
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    shutil.copyfile(src, dst)
