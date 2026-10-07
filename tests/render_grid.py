"""
Lay out a shape's row-count tests (e.g. round-vert-*.yaml) in a grid for yacv, without showing them.

--> labeled versions in the front row, no-label versions in the row behind (+Y)
--> one column per test (single-row, odd-rows, even-rows)
--> used by the render_*.py scripts, which show the result in a single show() call
"""

import os

from build123d import Location

from threedpy.generate import generate_storage_block
from threedpy.storage import load_storage_block_from_path

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# gap between blocks, along X and Y (mm)
GAP = 10.0

TESTS = ['single-row', 'odd-rows', 'even-rows']
# front row first
VARIANTS = ['label', 'nolabel']


def build_grid(
        prefix: str,
        x: float = 0.0,
        y: float = 0.0
    ) -> tuple[list, list[str], float, float]:
    """Build the <prefix>-<variant>-<test>.yaml blocks with arrange=True, starting at (x, y).

    Returns moved copies of the parts, their names, and the X/Y where a grid to the right of or
    behind this one can start (past the last column/row, plus GAP). The blocks themselves aren't
    combined."""

    parts = {}
    for variant in VARIANTS:
        for test in TESTS:
            name = '{}-{}-{}'.format(prefix, variant, test)
            block = load_storage_block_from_path(os.path.join(TESTS_DIR, name + '.yaml'))
            parts[variant, test] = (block.name, generate_storage_block(block, arrange=True).part)

    shown, names = [], []
    x_start = x
    # each row starts behind the deepest block of the row in front of it
    for variant in VARIANTS:
        row = [parts[variant, test] for test in TESTS]
        x = x_start
        for test, (name, part) in zip(TESTS, row):
            bb = part.bounding_box()
            shown.append(part.moved(Location((x - bb.min.X, y - bb.min.Y, 0))))
            names.append(name)
            # columns as wide as the widest block of the test, so both rows line up
            x += max(p.bounding_box().size.X for _, p in (parts[v, test] for v in VARIANTS)) + GAP
        y += max(part.bounding_box().size.Y for _, part in row) + GAP

    return shown, names, x, y
