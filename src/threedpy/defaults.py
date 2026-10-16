"""
Values used when a config doesn't set them; tune them here. Fixed values (paths, the gridfinity
spec, config schema) live in constants.py.
"""

""" BlockScoops """
# TODO --> min row-scoop width (10-12mm??)
BLOCK_SCOOP_DEPTH_RATIO: float = 0.5
BLOCK_SCOOP_EDGE_MARGIN: float = 0.5
# rim fillet cap for max_width scoops: a smaller rim leaves more room for their walls
BLOCK_SCOOP_MAX_WIDTH_FILLET_RADIUS: float = 0.5
BLOCK_SCOOP_FILLET_MIN_RADIUS: float = 0.5
BLOCK_SCOOP_FILLET_RADIUS: float = 2.5
BLOCK_SCOOP_FILLET_REFINE: float = 0.25
BLOCK_SCOOP_FILLET_STEP: float = 0.5
BLOCK_SCOOP_FLAT_WIDTH: float = 10.0
BLOCK_SCOOP_FLOOR_MARGIN: float = 1.0
BLOCK_SCOOP_LENGTH: float = 20.0
BLOCK_SCOOP_RIM_TOLERANCE: float = 1e-3
BLOCK_SCOOP_WALL_WIDTH: float = 7.5
ROW_SCOOP_LENGTH_RATIO: float = 0.5
SOCKET_EXTENSION_SCOOP_MARGIN: float = 1.0


""" Gridfinity base """
BASE_MAGNET_HOLES: bool = True


""" Items """
ITEM_ORIENTATION: str = 'vertical'
ITEM_ROTATION: str = 'up'


""" Labels """
FONT_SIZE: float = 6.0
LABEL_HEIGHT: float = 1.0
LABEL_SPACING: float = 1.0


""" Slots """
# with --draw-solids, vertical items sink by this fraction of their height so they show
DRAW_SOLIDS_SINK_RATIO: float = 0.5
SLOT_DEPTH_CLEARANCE: float = 0.2
SLOT_DIAMETER_CLEARANCE: float = 0.2


""" StorageBin """
BIN_SCOOP_RADIUS: float = 15.0
BIN_SCOOP_RADIUS_MARGIN: float = 0.1
BIN_LABEL_MIN_Z: int = 3


""" StorageBlock """
BLOCK_TYPE: str = 'rowed'
MIN_SLOT_SPACING: float = 10.0
ROW_MARKER_SIZE: float = 1.0


""" yacv preview """
PREVIEW_GAP: float = 10.0
PREVIEW_VERTICES: bool = False
