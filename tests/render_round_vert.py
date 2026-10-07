"""
Render round_vert row-count tests in yacv.

--> one row per test (single-row in front, then odd-rows, even-rows); see render_grid.py
--> labeled versions on the left, no-label versions on the right (+X)
--> run with `uv run python tests/render_round_vert.py` or `%run tests/render_round_vert.py`
"""

import os
import sys

from yacv_server import show

from threedpy.generate import SHOW_KWARGS

# make render_grid importable however this script is run
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_grid import build_grid  # noqa: E402

# %%

shown, names = build_grid(['round-vert'])
# one call so auto_clear (default) removes everything previously shown except these blocks
show(*shown, names=names, **SHOW_KWARGS)


# %%
