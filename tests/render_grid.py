"""
Lay out row-count tests (e.g. round-vert-*.yaml) in a grid for yacv, without showing them.

--> one row per test, front to back (+Y): single-row, odd-rows, even-rows
--> one column per prefix + variant, left to right (+X): e.g. round-vert label, round-vert nolabel
--> each block's row markers are a separate object (<block>-row-markers), drawn in MARKER_COLOR
--> used by the render_*.py scripts, which show the result in a single show() call
"""

import os

from build123d import BuildPart, Color, Location

from threedpy.generate import generate_storage_block
from threedpy.storage import load_storage_block_from_path

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# gap between blocks, along X and Y (mm)
GAP = 10.0
# row markers contrast with the blocks (embark yellow)
MARKER_COLOR = '#ffe6b3'

# front row first
TESTS = ['single-row', 'odd-rows', 'even-rows']
VARIANTS = ['label', 'nolabel']


def build_grid(prefixes: list[str]) -> tuple[list, list[str]]:
    """Build the <prefix>-<variant>-<test>.yaml blocks with arrange=True, laid out in a grid.

    Returns moved copies of the parts and their names. The blocks themselves aren't combined."""

    columns = [(prefix, variant) for prefix in prefixes for variant in VARIANTS]
    parts = {}
    for prefix, variant in columns:
        for test in TESTS:
            name = '{}-{}-{}'.format(prefix, variant, test)
            block = load_storage_block_from_path(os.path.join(TESTS_DIR, name + '.yaml'))
            part = generate_storage_block(block, arrange=True).part
            # rows are aligned by now, so their markers land where build_slots would draw them
            with BuildPart() as markers:
                block.build_row_markers()
            parts[prefix, variant, test] = (block.name, part, markers.part)

    # columns as wide as their widest block, so every row lines up
    widths = [
        max(parts[prefix, variant, test][1].bounding_box().size.X for test in TESTS)
        for prefix, variant in columns
    ]

    shown, names = [], []
    y = 0.0
    # each row starts behind the deepest block of the row in front of it
    for test in TESTS:
        row = [parts[prefix, variant, test] for prefix, variant in columns]
        x = 0.0
        for width, (name, part, markers) in zip(widths, row):
            bb = part.bounding_box()
            offset = Location((x - bb.min.X, y - bb.min.Y, 0))
            shown.append(part.moved(offset))
            names.append(name)
            # markers get the block's offset so they stay on it
            marker_shape = markers.moved(offset)
            marker_shape.color = Color(MARKER_COLOR)
            shown.append(marker_shape)
            names.append(name + '-row-markers')
            x += width + GAP
        y += max(part.bounding_box().size.Y for _, part, _ in row) + GAP

    return shown, names
