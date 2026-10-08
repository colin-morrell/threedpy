import logging
import math
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from typing import Any

import yaml
from build123d import (
    Align,
    BasePartObject,
    Bezier,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    Cylinder,
    Line,
    Locations,
    Mode,
    Plane,
    Text,
    extrude,
    make_face,
    mirror
)

from threedpy.constants import (
    FONT_PATH,
    GFU_GRID,
    GFU_GRID_NOMINAL,
    GFU_HEIGHT
)
from threedpy.features import (
    Label,
    Scoop,
    Shape,
    Slot,
    SCOOP_LENGTH,
    SCOOP_WALL_WIDTH
)
from threedpy.util import DoublyLinkedList

# repo root, two levels up from src/threedpy/
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.yaml')


def load_config() -> dict[str, Any]:
    """Read config.yaml fresh on each call -> edits apply without re-import."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


logger = logging.getLogger(__name__)



class StorageBlockType(Enum):
    """
    How a StorageBlock's slots are laid out.

    --> POSITIONAL: each slot is placed at the x/y given for it in the YAML config.
    --> ROWED: rows are evenly spaced along Y, and each row's slots evenly spaced along X.
    """

    POSITIONAL = 'positional'
    ROWED = 'rowed'


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
    # one scoop across the whole row: True (sized from its slots, see default_scoop), a mapping
    # overriding those dimensions, or a Scoop. Replaces the row's slot scoops.
    full_scoop: bool | dict | Scoop = False
    slots: DoublyLinkedList[Slot] = field(default_factory=DoublyLinkedList)
    width: float = 0.0
    _y: float = 0.0

    def __post_init__(self) -> None:
        Scoop.check_keys(self.full_scoop, "row '{}'".format(self.name))

    def add_slot(self, slot: Slot) -> Slot:
        slot.font_size = self.font_size
        if slot.label is not None:
            slot.label.font_size = self.font_size
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
        return 1.0

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
        """
        return self.y - self.max_radius - (self.font_size / 2) - self.font_spacing

    def built_scoop(self) -> Scoop:
        """The full-row scoop to draw (see full_scoop.)"""
        spec = None if self.full_scoop is True else self.full_scoop
        return Scoop.resolve(spec, self.default_scoop())

    def default_scoop(self) -> Scoop:
        """Scoop across the row: flat bottom spanning its slots' X extent, walls and depth from
        its largest slot radius."""
        radius = max((slot.scaled_radius for slot in self.slots), default=0.0)
        return Scoop(flat_width=self.x_scoop_span, wall_width=SCOOP_WALL_WIDTH, depth=radius)

    @property
    def x_scoop(self) -> float:
        """X-position (center) of the row's slots, for a full-row scoop."""
        left = min(slot.x - slot.scaled_radius for slot in self.slots)
        return left + self.x_scoop_span / 2

    @property
    def x_scoop_span(self) -> float:
        """X distance from the first slot's left edge to the last slot's right edge."""
        left = min(slot.x - slot.scaled_radius for slot in self.slots)
        right = max(slot.x + slot.scaled_radius for slot in self.slots)
        return right - left

    @property
    def y_scoop(self) -> float:
        """Y-position of scoops."""
        #return self.y + ((self.max_y_height + SCOOP_LENGTH / 2) / 2)
        return self.y

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

    def build_row_markers(self, surface_z: float | None = None) -> None:
        """Draw 1mm (Y) x 1mm (Z) box along each row's Y position for debugging, on top of the
        surface at surface_z (default z_mm)."""
        if surface_z is None:
            surface_z = self.z_mm
        for row in self.rows:
            coords = (
                0,
                row.y,
                surface_z
            )
            with Locations(coords):
                row.build_row_marker(self.x_mm)

    def build_slots(self, labels: bool=True, top_face=None):
        """
        Iterate through all slots of all rows and build their specified shapes (and optional
        labels.) labels=False skips every label (e.g. positional, which doesn't support them yet.)

        --> Slots and scoops are placed relative to top_face's height when given. z_mm assumes the
            body starts at Z=0, but a gridfinity base extends below it (its top is 2.5mm lower).
        """
        surface_z = top_face.center().Z if top_face is not None else self.z_mm
        if self.debug:
            self.build_row_markers(surface_z)
        for row in self.rows:
            for slot in row.slots:
                # generate slot
                coords = (
                    slot.x,
                    slot.y,
                    surface_z - slot.z
                )
                slot.log_slot_creation(coords)
                with Locations(coords):
                    slot.build()

                if labels and slot.draws_label:
                    # generate label
                    label_coords = (
                        slot.x,
                        row.y_label
                    )
                    slot.label.log_label_creation(label_coords)
                    with BuildSketch(top_face) as label:
                        with Locations(label_coords):
                            slot.label.build()
                    extrude(label.sketch, amount=1.0)

                # a full-row scoop replaces the row's slot scoops (overlapping cuts break fillets)
                if slot.scoops and not row.full_scoop:
                    # generate any individual slot scoops
                    scoop_coords = (
                        slot.x,
                        row.y_scoop,
                        surface_z
                    )
                    with Locations(scoop_coords):
                        slot.built_scoop().log_scoop_creation(scoop_coords)
                        slot.built_scoop().build(slot.built_mode)

            if row.full_scoop and len(row):
                # generate any whole-row scoops
                scoop = row.built_scoop()
                scoop_coords = (
                    row.x_scoop,
                    row.y_scoop,
                    surface_z
                )
                logger.debug('building full-row scoop {} at {}'.format(
                    scoop, tuple(round(c, 3) for c in scoop_coords)
                ))
                with Locations(scoop_coords):
                    scoop.build(Mode.ADD if self.debug else Mode.SUBTRACT)

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
        logging.debug('|           x_mm: {}'.format(round(self.x_mm, 3)))
        logging.debug('|           y_mm: {}'.format(round(self.y_mm, 3)))
        logging.debug('|           z_mm: {}'.format(round(self.z_mm, 3)))
        logging.debug('|    rows_height: {}'.format(round(self.rows_height, 3)))
        logging.debug('| y_margin_total: {}'.format(round(self.y_margin_total, 3)))
        logging.debug('|  y_row_spacing: {}'.format(round(self.y_row_spacing, 3)))
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

        This Y-value will be the center of the row.
        --> no labels: slots are centered directly on the row
        --> labels: the slot/label combined are centered on the row
        """
        cursor = self.y_mm / 2
        for row in self.rows:
            cursor -= self.y_row_spacing
            # row.y is the middle of the row's slots; any label space sits below them
            row.y = cursor - row.max_y_height / 2
            for slot in row.slots:
                slot.y = row.y
            cursor -= row.height

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
        return self.x * GFU_GRID

    @property
    def y_mm(self) -> float:
        """Length in mm (GFU_GRID spec is 42mm.)"""
        return self.y * GFU_GRID

    @property
    def z_mm(self) -> float:
        """Height in mm (GFU_HEIGHT spec is 7mm.)"""
        return self.z * GFU_HEIGHT

    @property
    def y_margin_total(self) -> float:
        """Total space between rows + top/bottom edges."""
        return self.y_mm - self.rows_height

    @property
    def y_row_spacing(self) -> float:
        """Amount of space between each row + top/bottom edges."""
        return self.y_margin_total / (self.num_rows + 1)

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
            yaml.safe_load(f),
            name=name,
            block_type=block_type,
            x=x,
            y=y,
            z=z,
            debug=debug,
            labels=labels
        )
    if not block.name:
        block.name = os.path.splitext(os.path.basename(path))[0]
    return block


def _slot_from_config(config: dict[str, Any]) -> Slot:
    """Build a Slot from its merged config, turning label text (e.g. '6' or 6) into a Label."""
    label = config.get('label')
    if label is not None and not isinstance(label, Label):
        config = {**config, 'label': Label(label_text=str(label), font_size=config['font_size'])}
    return Slot(**config)


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
        row_defaults = {
            key: value for key, value in row_data.items() if key not in ('name', 'slots', 'full_scoop')
        }
        slots = [
            _slot_from_config({**defaults, **row_defaults, **slot}) for slot in row_data['slots']
        ]
        rows.append(Row(
            font_size=max((slot.font_size for slot in slots), default=defaults['font_size']),
            name=row_data.get('name', ''),
            scoops=row_defaults.get('scoops', defaults.get('scoops')),
            labels=row_defaults.get('labels', defaults.get('labels')),
            full_scoop=row_data.get('full_scoop', False),
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
    row.add_slot(
        Slot(label=Label(label_text='M3'), shape=Shape.PRISM_HEXA, diameter=12.0, depth=20.0)
    )
    logger.info('Built {} with {} row(s)'.format(block.name, len(block)))


if __name__ == '__main__':
    main()
