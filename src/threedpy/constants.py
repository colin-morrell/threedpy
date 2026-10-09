import os

from gridfinity_build123d.constants import gridfinity_standard

""" Config """
# repo root, two levels up from src/threedpy/
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.yaml')

""" Font """
FONTS_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
FONT_PATH: str = os.path.join(FONTS_DIR, 'IBMPlexMono-Bold.ttf')
MIN_FONT_SIZE: float = 5.0  # TODO validate

""" Gridfinity defaults """
TOLERANCE: float = gridfinity_standard.grid.tollerance
GFU_GRID_NOMINAL: float = gridfinity_standard.grid.size  # 42mm; use for mm -> GFU conversion
GFU_GRID: float = GFU_GRID_NOMINAL - (TOLERANCE / 2)
GFU_HEIGHT: float = 7.0  # from gf spec https://gridfinity.xyz/assets/img/spec_draft_willtree8.jpg

""" Slots """
# added to each slot's measured depth/diameter so the item fits (mm)
SLOT_DEPTH_CLEARANCE: float = 0.25
SLOT_DIAMETER_CLEARANCE: float = 0.25

""" Scoops """
# Scoop X-axis defaults
SCOOP_FLAT_WIDTH: float = 10.0
SCOOP_WALL_WIDTH: float = 7.5
# Scoop Y-axis default
SCOOP_LENGTH: float = 20.0
SCOOP_FILLET_RADIUS: float = 2.5

""" yacv preview """
# Y gap between blocks when previewing several in yacv (mm)
PREVIEW_GAP: float = 10.0

""" storageBlock """
ROUND_KEYS = ('round_to_gfu_x', 'round_to_gfu_y', 'round_to_gfu_z', 'round_to_gfu_all')
STORAGE_BLOCK_KEYS = (
    'name', 'type', 'font_size', 'x', 'y', 'z', 'x_mm', 'y_mm', 'z_mm', 'global', *ROUND_KEYS
)
