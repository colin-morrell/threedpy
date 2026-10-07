"""
Render all row-count tests in yacv, round_vert and round_horz together.

--> one row per test (single-row in front, then odd-rows, even-rows); see render_grid.py
--> columns: round_vert labeled, round_vert no-label, round_horz labeled, round_horz no-label
--> run with `uv run python tests/render_all.py` or `%run tests/render_all.py`
"""

import os
import sys

from yacv_server import show

from threedpy.generate import SHOW_KWARGS

# make render_grid importable however this script is run
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_grid import build_grid  # noqa: E402

# %%

shown, names = build_grid(['round-vert', 'round-horz'])
# one call for all 12, since each show() with auto_clear (default) removes everything else
show(*shown, names=names, **SHOW_KWARGS)


# %%
