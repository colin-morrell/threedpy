"""
Render round_horz row-count tests in yacv.

--> labeled versions in front row
--> no-label versions in a row behind (+Y)
--> run with `uv run python tests/render_round_horz.py` or `%run tests/render_round_horz.py`
"""

import os
import sys

from yacv_server import show

from threedpy.generate import SHOW_KWARGS

# make render_grid importable however this script is run
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_grid import build_grid  # noqa: E402

# %%

shown, names, _, _ = build_grid('round-horz')
# one call so auto_clear (default) removes everything previously shown except these blocks
show(*shown, names=names, **SHOW_KWARGS)


# %%
