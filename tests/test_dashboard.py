"""Tests for tools/build_dashboard.py — the previously untested
dashboard builder.

Degenerate inputs used to crash the SVG helpers: line_chart died on
min() of an empty iterable for an empty series list (or a series with
no points), and bar_chart died on max() of an empty iterable for an
empty values list. Both now render a finite 'No data' SVG.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_dashboard() -> ModuleType:
    path = ROOT / "tools" / "build_dashboard.py"
    spec = importlib.util.spec_from_file_location("build_dashboard", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_dashboard"] = module
    spec.loader.exec_module(module)
    return module


def _finite(svg: str) -> bool:
    return "nan" not in svg.lower() and "inf" not in svg.lower()


def test_line_chart_empty_series_list_renders_no_data():
    bd = load_dashboard()
    svg = bd.line_chart([])
    assert "No data" in svg and _finite(svg)


def test_line_chart_all_empty_series_renders_no_data():
    bd = load_dashboard()
    svg = bd.line_chart([([], [], "#58a6ff", "Empty", False)])
    assert "No data" in svg and _finite(svg)


def test_bar_chart_empty_values_renders_no_data():
    bd = load_dashboard()
    svg = bd.bar_chart([])
    assert "No data" in svg and _finite(svg)


def test_single_point_flat_and_zero_charts_are_finite():
    bd = load_dashboard()
    single = bd.line_chart([([1.0], [2.0], "#58a6ff", "One", False)])
    flat = bd.line_chart([([1.0, 2.0, 3.0], [4.0, 4.0, 4.0],
                           "#58a6ff", "Flat", False)])
    bars = bd.bar_chart([0.0, 0.0])
    one_bar = bd.bar_chart([0.5])
    assert "<polyline" in single and _finite(single)
    assert "<polyline" in flat and _finite(flat)
    assert "<rect" in bars and _finite(bars)
    assert "<rect" in one_bar and _finite(one_bar)


def test_dashboard_build_end_to_end_on_real_results(tmp_path):
    # Run the builder in a scratch copy so the committed dashboard is
    # not overwritten: it must rebuild from the real docs/results.json,
    # stay self-contained (no external refs) and contain no NaN.
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "tools" / "build_dashboard.py",
                tmp_path / "tools" / "build_dashboard.py")
    shutil.copy(ROOT / "docs" / "results.json",
                tmp_path / "docs" / "results.json")
    proc = subprocess.run(
        [sys.executable, str(tmp_path / "tools" / "build_dashboard.py")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    html = (tmp_path / "docs" / "dashboard.html").read_text()
    assert "Exotics" in html and _finite(html)
    for bad in ("http://", "https://", "<link", "src=", "url("):
        assert bad not in html
    # The real results file the dashboard is built from parses cleanly.
    assert json.loads((ROOT / "docs" / "results.json").read_text())
