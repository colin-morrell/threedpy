import os

from gridfinity_build123d.constants import gridfinity_standard

FONTS_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
FONT_PATH: str = os.path.join(FONTS_DIR, 'IBMPlexMono-Bold.ttf')

MIN_FONT_SIZE: float = 5.0  # TODO validate

TOLERANCE: float = gridfinity_standard.grid.tollerance
GFU_GRID_NOMINAL: float = gridfinity_standard.grid.size  # 42mm; use for mm -> GFU conversion
GFU_GRID: float = GFU_GRID_NOMINAL - (TOLERANCE / 2)
GFU_HEIGHT: float = 7.0  # from gf spec https://gridfinity.xyz/assets/img/spec_draft_willtree8.jpg
