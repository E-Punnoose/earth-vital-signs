"""Assemble the static frontend into ./site for Vercel or GitHub Pages.

    python web/build_site.py                 # site reads ./data/dashboard.json shipped beside it
    API_BASE=https://xyz.onrender.com python web/build_site.py   # site reads from the backend first,
                                                                  # falling back to the bundled file
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def build() -> Path:
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    html = (ROOT / "web" / "index.html").read_text()
    api = os.environ.get("API_BASE", "").strip()
    if api:
        marker = '<script src="https://cdnjs.cloudflare.com'
        html = html.replace(marker, f'<script>window.API_BASE = {api!r};</script>\n' + marker, 1)
    (SITE / "index.html").write_text(html)
    shutil.copy(ROOT / "data" / "processed" / "dashboard.json", SITE / "data" / "dashboard.json")
    (SITE / ".nojekyll").write_text("")
    return SITE


if __name__ == "__main__":
    print(build())
