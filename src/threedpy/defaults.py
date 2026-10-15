"""
Values used when a config doesn't set them; tune them here. Fixed values (paths, the gridfinity
spec, config schema) live in constants.py.
"""

""" BlockScoops """
# TODO --> min row-scoop width (10-12mm??)
# X-axis
BLOCK_SCOOP_FLAT_WIDTH: float = 10.0
BLOCK_SCOOP_WALL_WIDTH: float = 7.5
# Y-axis
BLOCK_SCOOP_LENGTH: float = 20.0
BLOCK_SCOOP_FILLET_RADIUS: float = 2.5
# Z-axis: depth as a fraction of the flat width
BLOCK_SCOOP_DEPTH_RATIO: float = 0.5
# smaller rim fillet tried when BLOCK_SCOOP_FILLET_RADIUS fails (e.g. across a socket extension)
BLOCK_SCOOP_FILLET_FALLBACK_RADIUS: float = 1.0
# rim fillet for scoops over socket extensions: larger fails where the slot edge meets the taper
SOCKET_EXTENSION_SCOOP_FILLET_RADIUS: float = 1.0
# gap between a slot scoop's rounded rim and each end of a socket extension's straight middle (mm)
SOCKET_EXTENSION_SCOOP_MARGIN: float = 1.0
# row scoop length (Y) as a fraction of the row's shortest slot
ROW_SCOOP_LENGTH_RATIO: float = 0.5
# gap kept between a row scoop's rim fillet and the block's X edges (mm)
ROW_SCOOP_EDGE_MARGIN: float = 0.5
# how close (mm) a scoop's rim must be to the top surface to be filleted
SCOOP_RIM_TOLERANCE: float = 1e-3


""" Gridfinity base """
# magnet holes in the bottom corners of every gridfinity base
BASE_MAGNET_HOLES: bool = True


""" Items """
# Orientation / Rotation values for items whose config doesn't set them
ITEM_ORIENTATION: str = 'vertical'
ITEM_ROTATION: str = 'up'


""" Labels """
# label font size for every block, row, slot and bin that doesn't set its own
FONT_SIZE: float = 6.0
# how far labels are embossed above the surface (mm)
LABEL_HEIGHT: float = 1.0
# gap between a row's slots and their labels (mm)
LABEL_SPACING: float = 1.0


""" Slots """
# with --draw-solids, vertical items sink by this fraction of their height so they show
DRAW_SOLIDS_SINK_RATIO: float = 0.5
# added to each slot's measured depth/diameter so the item fits (mm)
SLOT_DEPTH_CLEARANCE: float = 0.2
SLOT_DIAMETER_CLEARANCE: float = 0.2


""" StorageBin """
BIN_SCOOP_RADIUS: float = 15.0
# gap kept between a bin's scoop radius and its compartment depth (mm)
BIN_SCOOP_RADIUS_MARGIN: float = 0.1
# a bin's label tab needs at least this many GFU of height
BIN_LABEL_MIN_Z: int = 3


""" StorageBlock """
# StorageBlockType value for blocks whose config doesn't set one
BLOCK_TYPE: str = 'rowed'
# warn when slots in a row are closer than this (mm)
MIN_SLOT_SPACING: float = 10.0
# Y/Z size of the --draw-solids row markers (mm)
ROW_MARKER_SIZE: float = 1.0


""" yacv preview """
# gap between blocks when previewing several in yacv (mm)
PREVIEW_GAP: float = 10.0
# draw model vertices in the yacv preview
PREVIEW_VERTICES: bool = False
