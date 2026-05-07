"""Bake a run payload into the viewer template and write it to disk.

Pure file-system operation: produces a single self-contained HTML file with
the run's payload inlined as a `<script type="application/json">` tag. No
server, no fetch — opens directly via `file://`.
"""

from __future__ import annotations

import json
import webbrowser
from importlib import resources
from pathlib import Path
from typing import Any

_TEMPLATE_PLACEHOLDERS = {
    "run_title": "__RUN_TITLE__",
    "run_data": "__RUN_DATA__",
}


def _load_template() -> str:
    return resources.files("roma_sim.viewer").joinpath("template.html").read_text(
        encoding="utf-8"
    )


def build_viewer_html(payload: dict[str, Any]) -> str:
    """Inline `payload` into the viewer template and return the HTML string."""
    title = (
        f"{payload.get('run_id', 'unknown')} — "
        f"{payload.get('scenario', {}).get('name', '?')} × "
        f"{payload.get('dispatcher', {}).get('name', '?')}"
    )
    template = _load_template()
    # JSON inside a <script type="application/json"> tag must escape `</`.
    blob = (
        json.dumps(payload, separators=(",", ":"))
        .replace("</", "<\\/")
    )
    html = template.replace(_TEMPLATE_PLACEHOLDERS["run_title"], title)
    html = html.replace(_TEMPLATE_PLACEHOLDERS["run_data"], blob)
    return html


def write_viewer(payload: dict[str, Any], out_path: Path) -> Path:
    """Write the viewer HTML for `payload` to `out_path`. Returns the path."""
    html = build_viewer_html(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def open_in_browser(html_path: Path) -> bool:
    url = html_path.resolve().as_uri()
    return webbrowser.open(url)
