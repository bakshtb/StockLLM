"""
Copies the vendored assets (echarts.min.js, dashboard.js, icon.png) next to
a generated dashboard HTML file. The HTML always references them via a
plain relative path ("assets/echarts.min.js", "assets/icon.png"), which
resolves correctly whether the page is opened directly (file://), served by
Flask without Ingress, served behind Home Assistant's Ingress proxy, or
served via the add-on's directly-exposed port -- a relative URL resolves
against the document's own location, so no route or ingress-prefix handling
is needed here at all. (webapp/app.py's index page, which isn't inside an
OUTPUT_DIR run folder, references the same source files a different way --
see its `/assets/<filename>` route.)

Called from every place that writes a dashboard HTML file to disk, passing
that call's *actual* output directory -- not a single hardcoded OUTPUT_DIR --
since main.py's `dashboard <file.json>` command can write next to an
arbitrary source file or an explicit -o path, not just into OUTPUT_DIR.
"""

import os
import shutil

_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
# Required: the dashboard has no charts at all without these (dashboard.js's
# own guard already falls back to table-only view if they fail to load at
# request time -- see dashboard.js -- but that's a runtime fallback for a
# network/proxy failure, not license to skip vendoring them in the first
# place). Optional: purely cosmetic -- iOS just shows a generic icon if
# missing, nothing about the actual dashboard depends on it -- so a missing
# or deleted icon.png must never be able to break every single dashboard
# write the way a missing required asset correctly still does.
_REQUIRED_ASSET_FILES = ("echarts.min.js", "dashboard.js")
_OPTIONAL_ASSET_FILES = ("icon.png",)


def ensure_vendored_assets(dest_dir: str) -> None:
    """Copies the vendored asset files into dest_dir/assets/, skipping any
    file that's already present and not older than its source (avoids
    rewriting on every single run)."""
    dest_assets_dir = os.path.join(dest_dir, "assets")
    os.makedirs(dest_assets_dir, exist_ok=True)
    for name in _REQUIRED_ASSET_FILES:
        _copy_if_stale(os.path.join(_SOURCE_DIR, name), os.path.join(dest_assets_dir, name))
    for name in _OPTIONAL_ASSET_FILES:
        src = os.path.join(_SOURCE_DIR, name)
        if os.path.exists(src):
            _copy_if_stale(src, os.path.join(dest_assets_dir, name))


def _copy_if_stale(src: str, dst: str) -> None:
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    shutil.copyfile(src, dst)
