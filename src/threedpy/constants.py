"""
Fixed values the code depends on: paths, the gridfinity spec, config schema and limits.
Tunable values used when a config doesn't set them live in defaults.py.
"""

import os

from gridfinity_build123d.constants import gf_bin, gridfinity_standard

""" Config """
# repo root, two levels up from src/threedpy/
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.yaml')

""" Font """
FONTS_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
FONT_PATH: str = os.path.join(FONTS_DIR, 'IBMPlexMono-Bold.ttf')
MIN_FONT_SIZE: float = 5.0  # TODO validate
MIN_FONT_SIZE_WITH_GLYPHS: float = 8.0

""" Gridfinity spec """
TOLERANCE: float = gridfinity_standard.grid.tollerance
GFU_GRID_NOMINAL: float = gridfinity_standard.grid.size  # 42mm; use for mm -> GFU conversion
GFU_GRID: float = GFU_GRID_NOMINAL - (TOLERANCE / 2)
GFU_HEIGHT: float = 7.0  # from gf spec https://gridfinity.xyz/assets/img/spec_draft_willtree8.jpg
# a gridfinity part's top face sits this far below z * GFU_HEIGHT (mm)
GF_TOP_BELOW_Z_MM: float = 2.5
# height of a gridfinity bin's compartment floor (mm)
GF_BIN_FLOOR_Z: float = 5.3

""" storageBlock """
STORAGE_BLOCK_KEYS = (
    'name', 'type', 'font_size', 'x', 'y', 'z', 'x_mm', 'y_mm', 'z_mm', 'global', 'round_to_gfu',
    'manual_scoops',
)

""" storageBin """
STORAGE_BIN_KEYS = ('x', 'y', 'z', 'font_size', 'label')
LABEL_TAB_WIDTH: float = gf_bin.label.width
