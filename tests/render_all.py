"""
Render all row-count tests in yacv: the round_vert grid, with the round_horz grid to its right (+X).

--> each grid: labeled versions in front, no-label versions behind (see render_grid.py)
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

vert, vert_names, x, _ = build_grid('round-vert')
horz, horz_names, _, _ = build_grid('round-horz', x=x)
# one call for all 12, since each show() with auto_clear (default) removes everything else
show(*vert, *horz, names=vert_names + horz_names, **SHOW_KWARGS)


# %%
