"""Bundle web/index.html with data/processed/dashboard.json into one self-contained page.

Used for hosting the dashboard as a single static file (e.g. a claude.ai Artifact
or any static host without an API). The production deployment instead serves
index.html next to data/dashboard.json (or points API_BASE at the backend).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(out: Path = ROOT / "dist" / "earth-vital-signs.html") -> Path:
    html = (ROOT / "web" / "index.html").read_text()
    data = (ROOT / "data" / "processed" / "dashboard.json").read_text()
    data = data.replace("</", "<\\/")  # keep the JSON from closing the script element
    tag = f'<script id="dash-data" type="application/json">{data}</script>\n'
    marker = '<script src="https://cdnjs.cloudflare.com'
    assert marker in html
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html.replace(marker, tag + marker, 1))
    return out


if __name__ == "__main__":
    print(build())
