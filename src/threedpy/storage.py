import logging
import math
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml
from build123d import (
    Align,
    Axis,
    Box,
    BuildSketch,
    Cylinder,
    Locations,
    Mode,
    Select,
    Text,
    edges,
    extrude,
    fillet
)

from threedpy.constants import FONT_PATH, GFU_GRID, GFU_GRID_NOMINAL, GFU_HEIGHT
from threedpy.util import DoublyLinkedList

# repo root, two levels up from src/threedpy/
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.yaml')


def load_config() -> dict[str, Any]:
    """Read config.yaml fresh on each call -> edits apply without re-import."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


logger = logging.getLogger(__name__)


class Direction(Enum):
    """
    Direction in which the Item / resulting Slot should be rotated.

    Orientation.VERTICAL will be None
    """

    # TODO --> return rotation(X,Y,Z) ?
    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'


class Orientation(Enum):
    """
    Orientation of the Item / resulting profile of the Slot.
    """
    # TODO --> holds Direction?
    VERTICAL = 'vertical'
    HORIZONTAL = 'horizontal'


# TODO --> rename SlotShape
class Shape(Enum):
    """
    Slot cross-section.

    --> ROUND_HORZ: cylinder w/ circular faces perpendicular to Z-axis (long socket on its side)
        --> currently only rotates towards +Y
    --> ROUND_VERT: cylinder w/ circular faces parallel to Z-axis (short socket standing upright)
    """
    # TODO --> horz/vert should be combined once Item/Orientation/Direction are implemented
    # TODO --> IRREGULAR

    PRISM_HEXA = 'prism_hexa'
    PRISM_RECT = 'prism_rect'
    ROUND_HORZ = 'round_horz'
    ROUND_VERT = 'round_vert'


class StorageBlockType(Enum):
    """
    How a StorageBlock's slots are laid out.

    --> POSITIONAL: each slot is placed at the x/y given for it in the YAML config.
    --> ROWED: rows are evenly spaced along Y, and each row's slots evenly spaced along X.
    """

    POSITIONAL = 'positional'
    ROWED = 'rowed'


class Item:

    # TODO --> encapsulate the item whose dimensions are specified in the yaml
    # TODO --> import stl??

    shape: Shape
    orientation: Orientation = Orientation.VERTICAL
    direction: Direction = None


# TODO --> every class above this to item.py ??


class Scoop:
    # TODO
    pass


@dataclass
class Slot:
    """Slot

    A single storage cavity.

    --> All measurements in mm unless otherwise stated.
    --> From a top-down view of the work surface, X is left/right and Y is up/down.
    """
    # TODO SLOT REFACTOR
        # --> slot methodology should be entirely shape independent
        # --> no length/width/diameter, everything in terms of x/y/z
        # --> transformations like diameter -> depth should happen in Item w/ Orientation+Direction

    # TODO --> validation (rectangle can't have length/width 0, etc)
    # TODO --> center option for x/y. calc box_len / slot_len and offset for spacing

    # TODO --> scoops for horz

    debug: bool = False
    label: str = ''
    # TODO --> default to None
    shape: Shape = Shape.ROUND_VERT
    # None = unset, filled from the slot's Row or StorageBlock (see add_slot / add_row)
    scoops: bool | None = None
    # same as scoops; still None once built means labels are drawn
    labels: bool | None = None
    diameter: float = 0.0
    depth: float = 0.0
    font_size: float = 6.0
    length: float = 0.0
    width: float = 0.0
    scale: float = 1.01
    x: float = 0.0
    y: float = 0.0
    z_offset: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.shape, Shape):
            self.shape = Shape(self.shape)

    def build_shape(self) -> None:
        """Build the slot's shape using build123d."""
        if self.shape in (Shape.ROUND_VERT, Shape.ROUND_HORZ):
            Cylinder(
                self.scaled_radius,
                self.scaled_depth,
                rotation=self.built_rotation,
                align=(Align.CENTER, Align.CENTER),
                mode=self.built_mode
            )
        elif self.shape == Shape.PRISM_RECT:
            Box(
                # TODO --> scaled
                # TODO --> center align both axes
                self.width,
                self.length,
                self.depth,
                align=(Align.CENTER, Align.MIN),  # if the latter is CENTER, y=0
                mode=Mode.SUBTRACT
            )
        else:
            raise ValueError('[!] invalid slot shape: {}'.format(self.shape))

    def build_scoops(self) -> None:
        # TODO --> set scoop params in config.yaml
        Cylinder(
            self.scaled_radius * 1.6,
            18.0,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER),
            mode=self.built_mode
        )
        rim = edges(Select.LAST).group_by(Axis.Z)[-1]
        fillet(rim, radius=2.0)

    @property
    def draws_label(self) -> bool:
        """Whether a label is drawn: labels isn't False and there's label text."""
        return self.labels is not False and bool(self.label)

    def build_label(self) -> None:
        """
        Build an embossed label. By default, labels are placed below their slots with font size
        6 and 1mm extrusion.
        """
        Text(
            self.label,
            font_size=self.font_size,
            font_path=FONT_PATH,
            align=(Align.CENTER, Align.CENTER)
        )

    def log_label_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING LABEL [!]')
        logging.debug('|    label: {}'.format(self.label))
        logging.debug('|   coords: x={}, y={}'.format(*coords))
        logging.debug('-'*25)

    def log_scoop_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING SCOOP [!]')
        logging.debug('|   coords: x={}, y={}, z={}'.format(*coords))
        logging.debug('-'*25)

    def log_slot_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING SLOT [!]')
        logging.debug('|    label: {}'.format(self.label))
        logging.debug('|    shape: {}'.format(self.shape))
        logging.debug('|   slot_z: {}'.format(self.z))
        logging.debug('|   coords: x={}, y={}, z={}'.format(*coords))
        logging.debug('| diameter: {}'.format(self.scaled_diameter))
        logging.debug('|    depth: {}'.format(self.scaled_depth))
        logging.debug('|     mode: {}'.format(self.built_mode))
        logging.debug('| rotation: {}'.format(self.built_rotation))
        logging.debug('-'*25)

    @property
    def built_mode(self):
        if not self.debug:
            return Mode.SUBTRACT
        return Mode.ADD

    @property
    def built_radius(self):
        """Profile of slot along the X-axis."""
        return self.scaled_diameter / 2

    @property
    def built_rotation(self) -> int:
        if self.shape == Shape.ROUND_HORZ:
            return (90, 0, 0)
        return (0, 0, 0)

    @property
    def scaled_depth(self) -> float:
        return round(self.depth * self.scale, 2)

    @property
    def scaled_diameter(self) -> float:
        return round(self.diameter * self.scale, 2)

    @property
    def scaled_radius(self) -> float:
        return round(self.scaled_diameter / 2, 2)

    @property
    def y_built_height(self) -> float:
        """
        The slot's dimensions on the Y-axis depend on its orientation:
        --> ROUND_HORZ --> Y corresponds to depth
        --> ROUND_VERT --> Y corresponds to diameter
        """
        if self.shape == Shape.ROUND_HORZ:
            return self.scaled_depth + self.scaled_radius
        return self.scaled_diameter

    @property
    def z(self) -> float:
        """
        How far to offset the slot below (-Z) work surface's top face.

        --> ROUND_VERT offset by their depth.
        --> ROUND_HORZ offset by z_offset or half their scaled depth if not specified.
        """
        if self.shape == Shape.ROUND_HORZ:
            # with default 0.0 --> slot will cut -Z by half its diameter
            return self.z_offset
        if not self.debug:
            return self.scaled_depth
        # places slots above surface for debugging
        return self.scaled_depth * .5


# TODO --> features class for common features between storage/row/slot: scoops, labels, etc

@dataclass
class Row:
    """Row

    An ordered collection of slots. For even spacing (e.g. generate.rowed_storage_block()), a
    Row's Slots are generated left-to-right along the X-axis.
    """

    debug: bool = False
    font_size: float = 6.0
    labels: bool | None = None
    name: str = ''
    scoops: bool | None = None
    slots: DoublyLinkedList[Slot] = field(default_factory=DoublyLinkedList)
    width: float = 0.0
    _y: float = 0.0

    def add_slot(self, slot: Slot) -> Slot:
        slot.font_size = self.font_size
        slot.debug = self.debug
        if slot.scoops is None:
            slot.scoops = self.scoops
        if slot.labels is None:
            slot.labels = self.labels
        self.slots.append(slot)
        return slot

    def build_row_marker(self, width: float) -> None:
        """Draw 1mm (Y) x 1mm (Z) box along the row's Y position."""
        Box(
            width,
            1,
            1,
            align=(Align.CENTER, Align.CENTER),
            mode=Mode.ADD
        )

    @property
    def font_spacing(self) -> float:
        """Distance between bottom of slot and top of label."""
        #return self.font_size / 3
        return 0.0

    @property
    def has_labels(self) -> bool:
        """Whether any slot in the row draws a label."""
        return any(slot.draws_label for slot in self.slots)

    @property
    def height(self) -> float:
        """Total row height based on the max diameter, + font size if any slot draws a label."""
        if self.has_labels:
            return self.max_y_height + self.font_size + self.font_spacing
        return self.max_y_height

    @property
    def max_y_height(self) -> float:
        """Largest y-height slot within the row."""
        return max((slot.y_built_height for slot in self.slots), default=0.0)

    @property
    def max_radius(self) -> float:
        # TODO --> rename this probably
        """Largest radius slot within the row."""
        return (self.max_y_height / 2)

    @property
    def min_y_height(self) -> float:
        """Smallest y-height slot within the row."""
        return min((slot.y_built_height for slot in self.slots), default=0.0)

    @property
    def total_diameter(self) -> float:
        """Cumulative diameter of slots within the row. Used for width (X) spacing."""
        return sum(slot.scaled_diameter for slot in self.slots)

    @property
    def x_slot_spacing(self) -> float:
        """Space on X axis between each slot + L/R edges."""
        if self.width == 0:
            raise ValueError('[!] row.width: {}. set width before calling.'.format(self.width))
        return self.x_total_spacing / (len(self) + 1)

    @property
    def x_total_spacing(self) -> float:
        return self.width - self.total_diameter

    @property
    def y(self) -> float:
        """Row's position on the Y-axis."""
        return self._y

    @y.setter
    def y(self, val: float) -> float:
        self._y = val

    @property
    def y_label(self) -> float:
        """ Y-position of slot labels.

        --> Offset downward (-Y) by font_size to sit below their respective slot.
        --> Since slots are Y-centered with each other, labels start from the row's Y position to
            stay aligned with each other.
        """
        return self.y - self.font_size

    @property
    def y_scoop(self) -> float:
        """Y-position of slot scoops."""
        # scoop depth hardcoded to 18.0 for the moment
        return self.y + ((self.max_y_height + 9.0) / 2)

    def __iter__(self) -> Iterator[Slot]:
        return iter(self.slots)

    def __len__(self) -> int:
        return len(self.slots)


@dataclass
class StorageBlock:
    """StorageBlock

    A gridfinity storage block for holding tools, sockets, etc. A StorageBlock is structured as a
    collection of Rows, which themselves are ordered collections of Slots. By default these rows
    and their slots will be spaced evenly along their respective axes.

    For manual positional placement, specific x/y/z coordinates can also be assigned at the
    slot level in the .yaml config. Rows are irrelevant for this configuration.

    Dimensions are primarily intended to fit the gridfinity standard (https://gridfinity.xyz/)
    using gridfinity units (GFU), but dimensions can also be given in mm and built as given. If X/Y
    aren't whole GFU, a plain box is built instead of the gridfinity base (see is_gridfinity.)

    GFU grid (X/Y) specifications are 42mm per unit (not including tolerances.)
    GFU height (Z) specification is 7mm per unit (not including tolerances.)

    Args:
        name (str, optional): storage block name. Defaults to inputted YAML filename.
        type (StorageBlockType): slot layout, rowed (default) or positional.
        font_size (float): default label font size for every row/slot.
        scoops (bool, optional): default for rows/slots that don't set their own.
        labels (bool, optional): same as scoops; labels are drawn if nothing sets it.
        x (float): storage block dimensions along the X-axis in GFU.
        y (float): storage block dimensions along the Y-axis in GFU.
        z (float): storage block height in GFU.
        round_to_gfu_x/y/z (bool): round that dimension up to a whole number of GFU. Otherwise
            it's built as given (a gridfinity base needs whole X/Y; see is_gridfinity.)
        round_to_gfu_all (bool): sets all three round_to_gfu_* options.
    """

    # TODO --> auto allocate slots given # rows
    # TODO --> auto allocate slots/rows given GFU

    debug: bool = False
    name: str = ''
    type: StorageBlockType = StorageBlockType.ROWED
    font_size: float = 6.0
    scoops: bool | None = None
    labels: bool | None = None
    rows: DoublyLinkedList[Row] = field(default_factory=DoublyLinkedList)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    round_to_gfu_x: bool = False
    round_to_gfu_y: bool = False
    round_to_gfu_z: bool = False
    round_to_gfu_all: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.type, StorageBlockType):
            self.type = StorageBlockType(self.type)
        if self.round_to_gfu_all:
            self.round_to_gfu_x = self.round_to_gfu_y = self.round_to_gfu_z = True
        for axis in ('x', 'y', 'z'):
            if getattr(self, 'round_to_gfu_' + axis):
                # round() first so float error (e.g. 84 / 42 = 2.0000000001) doesn't add a unit
                setattr(self, axis, math.ceil(round(getattr(self, axis), 6)))

    def add_row(self, row: Row) -> Row:
        logger.debug('add_row(): {} slots'.format(len(row)))
        row.debug = self.debug
        if row.scoops is None:
            row.scoops = self.scoops
        if row.labels is None:
            row.labels = self.labels
        for slot in row.slots:
            slot.debug = self.debug
            if slot.scoops is None:
                slot.scoops = row.scoops
            if slot.labels is None:
                slot.labels = row.labels
        self.rows.append(row)
        return row

    def add_slots(self, slots: Iterable[Slot], name: str = '') -> Row:
        """
        Add slots (e.g. from load_slots) as a new row. With no existing
        rows this becomes the first row; otherwise it is appended after them.
        """
        return self.add_row(Row(name=name, slots=DoublyLinkedList(slots)))

    def build_row_markers(self) -> None:
        """Draw 1mm (Y) x 1mm (Z) box along each row's Y position for debugging."""
        for row in self.rows:
            coords = (
                0,
                row.y,
                self.z_mm
            )
            with Locations(coords):
                row.build_row_marker(self.x_mm)

    def build_slots(self, labels: bool=True, top_face=None):
        """
        Iterate through all slots of all rows and build their specified shapes (and optional
        labels.) labels=False skips every label (e.g. positional, which doesn't support them yet.)
        """
        if self.debug:
            self.build_row_markers()
        for row in self.rows:
            for slot in row.slots:
                # generate slot
                coords = (
                    round(slot.x, 3),
                    round(slot.y, 3),
                    round(self.z_mm - slot.z, 3)
                )
                slot.log_slot_creation(coords)
                with Locations(coords):
                    slot.build_shape()

                if labels and slot.draws_label:
                    # generate label
                    label_coords = (
                        round(slot.x, 3),
                        round(row.y_label, 3)
                    )
                    slot.log_label_creation(label_coords)
                    with BuildSketch(top_face) as label:
                        with Locations(label_coords):
                            slot.build_label()
                    extrude(label.sketch, amount=1.0)

                if slot.scoops:
                    scoop_coords = (
                        round(slot.x, 3),
                        round(row.y_scoop, 3),
                        round(self.z_mm, 3)
                    )
                    slot.log_scoop_creation(scoop_coords)
                    with Locations(scoop_coords):
                        slot.build_scoops()

    def build_test_surface(self, part) -> None:
        """
        Build mock storage block surface without expensive gf generation call. Useful for faster
        testing/fine-tuning row/slot arrangement.
        """
        Box(
            self.x_mm,
            self.y_mm,
            self.z_mm,
            align=(Align.CENTER, Align.CENTER)
        )

    def log_storage_block_creation(self) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING STORAGE BLOCK [!]')
        logging.debug('|           type: {}'.format(self.type.value))
        logging.debug('|      font_size: {}'.format(self.font_size))
        logging.debug('|          x_gfu: {}'.format(self.x_gfu))
        logging.debug('|          y_gfu: {}'.format(self.y_gfu))
        logging.debug('|          z_gfu: {}'.format(self.z_gfu))
        logging.debug('|           x_mm: {}'.format(self.x_mm))
        logging.debug('|           y_mm: {}'.format(self.y_mm))
        logging.debug('|           z_mm: {}'.format(self.z_mm))
        logging.debug('|    rows_height: {}'.format(self.rows_height))
        logging.debug('| y_margin_total: {}'.format(self.y_margin_total))
        logging.debug('|  y_row_spacing: {}'.format(self.y_row_spacing))
        logging.debug('-'*25)

    def slots(self) -> Iterator[Slot]:
        """All slots across every row, in row order."""
        for row in self.rows:
            yield from row

    def x_align_slots(self) -> None:
        """X-align each slot, leaving even spacing (per row) between slots + left/right edges.

        --> First slot initially aligns with left edge (min X, or (0-(x_mm*.5), since 0 is center.)
        --> Other slots initially align with the rightward edge of the previous slot.

        --> All slots then offset rightward (+X) by their row's x_slot_spacing
            + their own radius."""

        for row in self.rows:
            row.width = self.x_mm
            for slot in row.slots.nodes():
                if not slot.prev:
                    slot.value.x = 0 - (self.x_mm / 2)
                else:
                    slot.value.x = slot.prev.value.x
                    slot.value.x += slot.prev.value.scaled_radius
                slot.value.x += row.x_slot_spacing
                slot.value.x += slot.value.scaled_radius

    def y_align_rows(self) -> None:
        """Y-align each row, leaving even spacing between rows + top/bottom edges.

        --> with (Align.CENTER, Align.CENTER), row Y-position is at the bottom of the slot??

        --> First row initially aligns with top edge (max Y value, or y_mm*.5, since 0 is center.)
        --> Other rows initially align with the previous row.

        --> All rows then offset downward (-Y) by self.y_row_spacing
        --> All rows then offset again by their own height."""

        # TODO --> y spacing isn't quite right for round_horz

        for row in self.rows.nodes():
            if not row.prev:
                row.value.y = 0 + (self.y_mm / 2)
            else:
                row.value.y = row.prev.value.y
                row.value.y -= self.y_row_spacing
            row.value.y -= row.value.height
            for slot in row.value.slots:
                # (Align.CENTER, Align.MIN) --> slot.y = row.value.y
                # (Align.CENTER, Align.CENTER) --> +offset by half slot Y height
                slot.y = (row.value.y + (slot.y_built_height / 2))
                # center each slot along their row's Y
                slot.y += (row.value.max_radius - slot.scaled_radius)

    @property
    def num_rows(self) -> int:
        return len(self)

    @property
    def rows_height(self) -> float:
        """Combined height of every row (based on each row's largest diameter slot)."""
        ht = 0.0
        for row in self.rows:
            ht += row.height
        return ht

    @property
    def is_gridfinity(self) -> bool:
        """Whether X/Y are whole GFU, which a gridfinity base needs."""
        return float(self.x).is_integer() and float(self.y).is_integer()

    @property
    def x_gfu(self) -> float:
        """Number of gridfinity units along the X axis."""
        return self.x

    @property
    def y_gfu(self) -> float:
        """Number of gridfinity units along the Y axis."""
        return self.y

    @property
    def z_gfu(self) -> float:
        """Number of gridfinity height units along the Z axis."""
        return self.z

    @property
    def x_mm(self) -> float:
        """Width in mm (GFU_GRID spec is 42mm.)"""
        return round(self.x * GFU_GRID, 3)

    @property
    def y_mm(self) -> float:
        """Length in mm (GFU_GRID spec is 42mm.)"""
        return round(self.y * GFU_GRID, 3)

    @property
    def z_mm(self) -> float:
        """Height in mm (GFU_HEIGHT spec is 7mm.)"""
        return round(self.z * GFU_HEIGHT, 3)

    @property
    def y_margin_total(self) -> float:
        """Total space between rows + top/bottom edges."""
        return round(self.y_mm - self.rows_height, 2)

    @property
    def y_row_spacing(self) -> float:
        """Amount of space between each row + top/bottom edges."""
        return round(self.y_margin_total / (self.num_rows + 2), 2)

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


ROUND_KEYS = ('round_to_gfu_x', 'round_to_gfu_y', 'round_to_gfu_z', 'round_to_gfu_all')
STORAGE_BLOCK_KEYS = (
    'name', 'type', 'font_size', 'x', 'y', 'z', 'x_mm', 'y_mm', 'z_mm', 'global', *ROUND_KEYS
)


def _gfu_from_config(
        data: dict[str, Any],
        axis: str,
        nominal_mm: float,
        built_mm: float,
        round_up: bool
    ) -> float | None:
    """ Read one storage block dimension in GFU, given as either '<axis>' (GFU) or '<axis>_mm'.

    --> If round_up, mm values convert using the nominal unit size (StorageBlock rounds them up.)
    --> Otherwise they convert using the built unit size, so <axis>_mm is drawn exactly as given.
    --> Returns None if the dimension isn't given."""

    gfu, mm = data.get(axis), data.get(axis + '_mm')
    if gfu is not None and mm is not None:
        raise ValueError('[!] storage_block: give {0} or {0}_mm, not both'.format(axis))
    if mm is not None:
        gfu = mm / (nominal_mm if round_up else built_mm)
        logger.info('storage_block: {}_mm={} -> {}={}'.format(axis, mm, axis, gfu))
    return gfu


def load_storage_block(
        data: dict[str, Any],
        name: str = '',
        block_type: StorageBlockType | str | None = None,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
        debug: bool = False,
        labels: bool | None = None
    ) -> StorageBlock:
    """ Build a StorageBlock (and its Rows) from a parsed YAML config.

    --> Storage block settings live under an optional top-level 'storage_block' object: 'name',
        'type' ('rowed' or 'positional', default rowed), 'font_size' (default label size for
        every row/slot), each dimension as either GFU ('x', 'y', 'z') or mm ('x_mm', 'y_mm',
        'z_mm'), and 'global' (defaults for every slot, see load_rows).
    --> 'round_to_gfu_x'/'_y'/'_z' round that dimension up to whole units ('round_to_gfu_all' sets
        all three); unrounded dimensions are built exactly as given.
    --> name/block_type/x/y/z arguments (e.g. from the CLI) override the YAML values.
    --> debug is passed down to every Row and Slot.
    --> labels (e.g. False from --no-labels) overrides the 'global' labels value; rows/slots that
        set their own still win.
    --> Missing dimensions are left at 0."""

    block_data = data.get('storage_block', {})
    if labels is not None:
        # override 'global' so load_rows applies it to slots too
        block_data = {**block_data, 'global': {**block_data.get('global', {}), 'labels': labels}}
        data = {**data, 'storage_block': block_data}
    unknown = set(block_data) - set(STORAGE_BLOCK_KEYS)
    if unknown:
        raise ValueError('[!] storage_block: unknown key(s): {}'.format(', '.join(sorted(unknown))))

    rounding = {key: bool(block_data.get(key, False)) for key in ROUND_KEYS}
    round_all = rounding['round_to_gfu_all']
    dims = {
        axis: _gfu_from_config(
            block_data, axis, nominal, built, round_all or rounding['round_to_gfu_' + axis]
        )
        for axis, nominal, built in (
            ('x', GFU_GRID_NOMINAL, GFU_GRID),
            ('y', GFU_GRID_NOMINAL, GFU_GRID),
            ('z', GFU_HEIGHT, GFU_HEIGHT)
        )
    }
    for axis, override in (('x', x), ('y', y), ('z', z)):
        if override is not None:
            dims[axis] = override

    block = StorageBlock(
        debug=debug,
        name=name or block_data.get('name', ''),
        type=block_type or block_data.get('type', StorageBlockType.ROWED),
        font_size=block_data.get('font_size', StorageBlock.font_size),
        scoops=block_data.get('global', {}).get('scoops'),
        labels=block_data.get('global', {}).get('labels'),
        x=float(dims['x'] or 0.0),
        y=float(dims['y'] or 0.0),
        z=float(dims['z'] or 0.0),
        **rounding
    )
    for row in load_rows(data, font_size=block.font_size):
        block.add_row(row)
    return block


def load_storage_block_from_path(
        path: str | os.PathLike[str],
        name: str = '',
        block_type: StorageBlockType | str | None = None,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
        debug: bool = False,
        labels: bool | None = None
    ) -> StorageBlock:
    """Build a StorageBlock from a YAML file. The name defaults to the filename if not set in the
    YAML."""
    logger.info('loading storage block from {}'.format(path))
    with open(path) as f:
        block = load_storage_block(
            yaml.safe_load(f), name=name, block_type=block_type, x=x, y=y, z=z, debug=debug,
            labels=labels
        )
    if not block.name:
        block.name = os.path.splitext(os.path.basename(path))[0]
    return block


def load_rows(data: dict[str, Any], font_size: float = 6.0) -> list[Row]:
    """ Build Rows from a parsed YAML config.

    --> Slots are grouped under 'rows', each with its own 'slots' list and an
        optional 'name'; a top-level 'slots' list is loaded as a single row.
    --> 'storage_block' 'global' keys (e.g. shape, scale) are defaults for every slot
    --> Other row-level keys are defaults for that row's slots
    --> Values set on an individual slot override both.
    --> font_size is the default label size (e.g. the storage block's); each row reserves space
        for its largest label."""

    unknown = set(data) - {'storage_block', 'rows', 'slots'}
    if unknown:
        raise ValueError('[!] unknown top-level key(s): {} (slot defaults go in storage_block.global)'
                         .format(', '.join(sorted(unknown))))
    defaults = {'font_size': font_size, **data.get('storage_block', {}).get('global', {})}
    rows_data = data['rows'] if 'rows' in data else [{'slots': data['slots']}]
    rows = []
    for row_data in rows_data:
        row_defaults = {key: value for key, value in row_data.items() if key not in ('name', 'slots')}
        slots = [Slot(**{**defaults, **row_defaults, **slot}) for slot in row_data['slots']]
        rows.append(Row(
            font_size=max((slot.font_size for slot in slots), default=defaults['font_size']),
            name=row_data.get('name', ''),
            scoops=row_defaults.get('scoops', defaults.get('scoops')),
            labels=row_defaults.get('labels', defaults.get('labels')),
            slots=DoublyLinkedList(slots)
        ))
    return rows


def load_rows_from_path(path: str | os.PathLike[str]) -> list[Row]:
    """Build Rows from a YAML file."""
    logger.info('loading rows from {}'.format(path))
    with open(path) as f:
        return load_rows(yaml.safe_load(f))


def load_slots(data: dict[str, Any]) -> list[Slot]:
    """Build Slots from a parsed YAML config, ignoring any row grouping."""
    return [slot for row in load_rows(data) for slot in row]


def load_slots_from_path(path: str | os.PathLike[str]) -> list[Slot]:
    """Build Slots from a YAML file, ignoring any row grouping."""
    logger.info('loading slots from {}'.format(path))
    with open(path) as f:
        return load_slots(yaml.safe_load(f))


def main() -> None:
    logger.info('Starting')
    block = StorageBlock(name='block-1')
    row = block.add_row(Row(name='row-1'))
    row.add_slot(Slot(label='M3', shape=Shape.PRISM_HEXA, diameter=12.0, depth=20.0))
    logger.info('Built {} with {} row(s)'.format(block.name, len(block)))


if __name__ == '__main__':
    main()
