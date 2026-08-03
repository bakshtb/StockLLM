"""
Copies the vendored chart-rendering assets (echarts.min.js, dashboard.js)
next to a generated dashboard HTML file. The HTML always references them via
a plain relative path ("assets/echarts.min.js"), which resolves correctly
whether the page is opened directly (file://), served by Flask without
Ingress, or served behind Home Assistant's Ingress proxy -- a relative URL
resolves against the document's own location, so no route or ingress-prefix
handling is needed here at all.

Called from every place that writes a dashboard HTML file to disk, passing
that call's *actual* output directory -- not a single hardcoded OUTPUT_DIR --
since main.py's `dashboard <file.json>` command can write next to an
arbitrary source file or an explicit -o path, not just into OUTPUT_DIR.
"""

import os
import shutil

_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_ASSET_FILES = ("echarts.min.js", "dashboard.js")


def ensure_vendored_assets(dest_dir: str) -> None:
    """Copies both vendored asset files into dest_dir/assets/, skipping any
    file that's already present and not older than its source (avoids
    rewriting on every single run)."""
    dest_assets_dir = os.path.join(dest_dir, "assets")
    os.makedirs(dest_assets_dir, exist_ok=True)
    for name in _ASSET_FILES:
        src = os.path.join(_SOURCE_DIR, name)
        dst = os.path.join(dest_assets_dir, name)
        if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        shutil.copyfile(src, dst)
