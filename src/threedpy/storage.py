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
    Box,
    Locations,
    Mode,
)

from threedpy.constants import (
    CONFIG_PATH,
    GFU_GRID,
    GFU_GRID_NOMINAL,
    GFU_HEIGHT,
    ROUND_KEYS,
    SCOOP_FILLET_RADIUS,
    SCOOP_WALL_WIDTH,
    STORAGE_BLOCK_KEYS,
)
from threedpy.features import Label, LabelMode, Scoop, ScoopMode, Shape, Slot
from threedpy.util import DoublyLinkedList


def load_config() -> dict[str, Any]:
    """Read config.yaml fresh on each call -> edits apply without re-import."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


logger = logging.getLogger(__name__)


class StorageBlockType(Enum):
    """StorageBlockType

    How a StorageBlock's slots are laid out.

    POSITIONAL: each slot is placed at the x/y given for it in the YAML config.
    ROWED: rows are evenly spaced along Y, and each row's slots are evenly spaced along X.
    """

    POSITIONAL = 'positional'
    ROWED = 'rowed'


@dataclass
class Row:
    """Row

    An ordered collection of slots.

    Positional blocks ignore order.
    Rowed blocks draw slots and their features left-to-right along the X-axis.
    """

    debug: bool = False
    font_size: float = 6.0
    label: Label = field(default_factory=Label)
    name: str = ''
    scoop: Scoop = field(default_factory=Scoop)
    slots: DoublyLinkedList[Slot] = field(default_factory=DoublyLinkedList)
    width: float = 0.0
    _y: float = 0.0

    @property
    def font_spacing(self) -> float:
        """Distance between bottom of slot and top of label."""
        #return self.font_size / 3
        return 1.0

    @property
    def has_labels(self) -> bool:
        """Whether the row draws any label: its own or any of its slots'."""
        return self.has_row_label or any(slot.draws_label for slot in self.slots)

    @property
    def has_row_label(self) -> bool:
        """Whether the row has one label for all its slots."""
        return self.label.mode is LabelMode.ROW_LABEL and not self.label.is_empty

    @property
    def has_slot_scoops(self) -> bool:
        """Whether any slot in the row has its own scoop."""
        return any(slot.scoop.mode is ScoopMode.SLOT_SCOOP for slot in self.slots)

    @property
    def has_row_scoop(self) -> bool:
        """Whether the row has one scoop across all its slots."""
        return self.scoop.mode is ScoopMode.ROW_SCOOP

    @property
    def height(self) -> float:
        """Total row height based on the max diameter, + font size if any slot draws a label."""
        if self.has_labels:
            return self.y_max_slot + self.font_size + self.font_spacing
        return self.y_max_slot

    @property
    def max_radius(self) -> float:
        # TODO --> rename this probably
        """Largest radius slot within the row."""
        return (self.y_max_slot / 2)

    @property
    def x_footprint(self) -> float:
        """Cumulative diameter of slots within the row. Used for width (X) spacing."""
        return sum(slot.x_footprint for slot in self.slots)

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
    def x_slot_spacing(self) -> float:
        """Space on X axis between each slot + L/R edges."""
        if self.width == 0:
            raise ValueError(f'[!] row.width: {self.width}. set width before calling.')
        return self.x_total_spacing / (len(self) + 1)

    @property
    def x_total_spacing(self) -> float:
        """Total margins (free space between slots.)"""
        return self.width - self.x_footprint

    @property
    def y(self) -> float:
        """Row's position on the Y-axis."""
        return self._y

    @y.setter
    def y(self, val: float) -> float:
        self._y = val

    @property
    def y_footprint(self) -> float:
        y_max_slot = self.y_max_slot
        if self.has_labels:
            y_max_slot += self.font_size + self.font_spacing
        return y_max_slot

    @property
    def y_label(self) -> float:
        """Y-position of slot labels. Offset -Y to sit below their respective slot."""
        # offset by the largest radius slot so the labels are aligned with each other
        return self.y - self.max_radius - (self.font_size / 2) - self.font_spacing

    @property
    def y_max_slot(self) -> float:
        """Largest slot Y-value within the row."""
        return max((slot.y_footprint for slot in self.slots), default=0.0)

    @property
    def y_min_slot(self) -> float:
        """Smallest slot Y-value within the row."""
        return min((slot.y_footprint for slot in self.slots), default=0.0)

    @property
    def y_scoop(self) -> float:
        """Y-position of scoops. Default: centered on row."""
        return self.y

    @property
    def z_max(self) -> float:
        # TODO --> max depth for vert slots
        # TODO --> max radius for horz slots
        # TODO --> will require slots to dynamically know their Z
        pass

    def add_slot(self, slot: Slot) -> Slot:
        slot.font_size = self.font_size
        slot.label.font_size = self.font_size
        slot.debug = self.debug
        if self.has_row_scoop:
            slot.scoop = self.scoop
        if self.has_row_label:
            slot.label = self.label
        self.slots.append(slot)
        return slot

    def build_row_marker(self, width: float) -> None:
        """Draw 1x1 (YxZ) box at the surface along the entire X-width of the row's Y position."""
        Box(
            width,
            1,
            1,
            align=(Align.CENTER, Align.CENTER),
            mode=Mode.ADD
        )

    def build_label(self, top_face) -> None:
        """Emboss the row label centered under the row's slots."""
        if self.has_row_label and len(self):
            self.label.build(top_face, (self.x_scoop, self.y_label))

    def build_scoop(self, coords: tuple, x_block_width: float) -> None:
        """Build the row scoop."""
        if not self.has_row_scoop or not len(self):
            return
        self.scoop.fill_unset(self.default_scoop(x_block_width))
        self.scoop.log_scoop_creation(coords)
        with Locations(coords):
            self.scoop.build(Mode.ADD if self.debug else Mode.SUBTRACT)

    def default_scoop(self, x_block_width: float) -> Scoop:
        """Single-row scoop across its slots' X-footprint, depth of its largest slot radius."""

        radius = max((slot.scaled_radius for slot in self.slots), default=0.0)
        # extend the scoop walls all the way to the edges (w/ .5 margin) on X-axis
        edge_margin = SCOOP_FILLET_RADIUS + 0.5
        max_wall_width = (x_block_width - self.x_scoop_span) / 2 - edge_margin
        # only take default width if it doesn't touch/exceed the edges
        scoop_wall_width = min(max_wall_width, SCOOP_WALL_WIDTH)

        return Scoop(
            flat_width=self.x_scoop_span,
            wall_width=scoop_wall_width,
            depth=radius,
            length=self.y_max_slot/2,
            mode=ScoopMode.ROW_SCOOP
        )

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
    def x_mm(self) -> float:
        """Width in mm (GFU_GRID spec is 42mm.)"""
        return self.x * GFU_GRID

    @property
    def x_max_footprint(self) -> float:
        """Largest row's X-footprint."""
        return max(row.x_footprint for row in self.rows)

    @property
    def y_gfu(self) -> float:
        """Number of gridfinity units along the Y axis."""
        return self.y

    @property
    def y_mm(self) -> float:
        """Length in mm (GFU_GRID spec is 42mm.)"""
        return self.y * GFU_GRID

    @property
    def y_footprint(self) -> float:
        """Combined Y footprint of all rows."""
        return sum(row.y_footprint for row in self.rows)

    @property
    def y_margin_total(self) -> float:
        """Total space between rows + top/bottom edges."""
        return self.y_mm - self.y_footprint

    @property
    def y_row_spacing(self) -> float:
        """Amount of space between each row + top/bottom edges."""
        return self.y_margin_total / (self.num_rows + 1)

    @property
    def z_gfu(self) -> float:
        """Number of gridfinity height units along the Z axis."""
        return self.z

    @property
    def z_mm(self) -> float:
        """Height in mm (GFU_HEIGHT spec is 7mm.)"""
        return self.z * GFU_HEIGHT

    def add_row(self, row: Row) -> Row:
        logger.debug(f'add_row(): {len(row)} slots')
        row.debug = self.debug
        for slot in row.slots:
            slot.debug = self.debug
            if row.has_row_scoop:
                slot.scoop = row.scoop
            if row.has_row_label:
                slot.label = row.label
        self.rows.append(row)
        return row

    def add_slots(self, slots: Iterable[Slot], name: str = '') -> Row:
        """Append slots directly as a new row."""
        return self.add_row(Row(name=name, slots=DoublyLinkedList(slots)))

    def build_row_markers(self, surface_z: float | None = None) -> None:
        """Draw 1x1 (YxZ) box at the surface along the entire X-width of each row's Y position."""
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

    def build_row_scoop(self, row: Row, surface_z: float) -> None:
        """Generate the Scoop across an entire Row, if it has one."""
        row.build_scoop((row.x_scoop, row.y_scoop, surface_z), self.x_mm)

    def build_slot_scoop(self, row: Row, slot: Slot, surface_z: float) -> None:
        """Generate a single slot's own Scoop, if it has one."""
        slot.build_scoop((slot.x, row.y_scoop, surface_z))

    def build_slot(self, slot: Slot, surface_z: float) -> None:
        """Generate a single slot."""
        coords = (
            slot.x,
            slot.y,
            surface_z - slot.z
        )
        slot.log_slot_creation(coords)
        with Locations(coords):
            slot.build()

    def build(self, labels: bool=True, top_face=None):
        """Iterate through all slots of all rows and build their specified shapes and features.

        Slots and scoops are placed relative to top_face's height when given. z_mm assumes the
        body starts at Z=0, but a gridfinity base extends below it (its top is 2.5mm lower).
        """
        self.validate()
        surface_z = top_face.center().Z if top_face is not None else self.z_mm
        if self.debug:
            self.build_row_markers(surface_z)
        for row in self.rows:
            logger.debug(f'build(): Row with x_slot_spacing {row.x_slot_spacing}')
            for slot in row.slots:
                self.build_slot(slot, surface_z)

                if labels:
                    slot.build_label(top_face, (slot.x, row.y_label))

                self.build_slot_scoop(row, slot, surface_z)

            if labels:
                row.build_label(top_face)
            self.build_row_scoop(row, surface_z)

    def build_test_surface(self, part) -> None:
        """Build mock storage block surface without expensive gf generation call.

        Useful for faster testing/fine-tuning row/slot arrangement.
        """
        Box(
            self.x_mm,
            self.y_mm,
            self.z_mm,
            align=(Align.CENTER, Align.CENTER)
        )

    def log_storage_block_creation(self) -> None:
        logger.debug('-'*25)
        logger.debug('[!] BUILDING STORAGE BLOCK [!]')
        logger.debug(f'|           type: {self.type.value}')
        logger.debug(f'|      font_size: {self.font_size}')
        logger.debug(f'|          x_gfu: {self.x_gfu}')
        logger.debug(f'|          y_gfu: {self.y_gfu}')
        logger.debug(f'|          z_gfu: {self.z_gfu}')
        logger.debug(f'|           x_mm: {round(self.x_mm, 3)}')
        logger.debug(f'|           y_mm: {round(self.y_mm, 3)}')
        logger.debug(f'|           z_mm: {round(self.z_mm, 3)}')
        logger.debug(f'|    rows_height: {round(self.rows_height, 3)}')
        logger.debug(f'| y_margin_total: {round(self.y_margin_total, 3)}')
        logger.debug(f'|  y_row_spacing: {round(self.y_row_spacing, 3)}')

    def slots(self) -> Iterator[Slot]:
        """All slots across every row, in row order."""
        for row in self.rows:
            yield from row

    def validate(self) -> None:
        self.validate_x_bounds()
        self.validate_x_spacing()
        self.validate_y_bounds()
        logger.info('[+] SurfaceBlock X/Y validation passed.')

    def validate_x_bounds(self) -> None:
        """Validate all Row's slots do not exceed the StorageBlock's width on the X-axis."""
        # TODO --> automatically account for scoop/no scoop
        # TODO --> assume a reasonable margin so slots don't overlap
        if self.x_max_footprint > self.x_mm:
            e = f'Y-BOUNDS: footprint {self.x.max_footprint} exceeds block width {self.x_mm}'
            raise ValueError(e)
        l = f'[+] SurfaceBlock X validation passed: {self.x_max_footprint} < {self.x_mm}'
        logger.debug(l)

    def validate_x_spacing(self) -> None:
        for row in self.rows:
            if row.x_slot_spacing < 10.0:
                l = f'[!] WARNING: row.x_slot_spacing {round(row.x_slot_spacing, 2)} < 10mm'
                logger.warning(l)

    def validate_y_bounds(self) -> None:
        """Check if combined rows exceed StorageBlock's height on the Y-axis."""
        # TODO --> assume a reasonable margin so slots don't overlap
        if self.y_footprint > self.y_mm:
            e = f'Y-BOUNDS: footprint {self.y_footprint} exceeds block height {self.y_mm}'
            raise ValueError(e)
        l = f'[+] SurfaceBlock Y validation passed: {self.y_footprint} < {self.y_mm}'
        logger.debug(l)

    def x_align_slots(self) -> None:
        """X-align slots from L/-X to R/+X with even spacing (per row) between slots + L/R edges."""
        for row in self.rows:
            cursor = -self.x_mm / 2
            row.width = self.x_mm
            for slot in row.slots:
                cursor += row.x_slot_spacing
                cursor += slot.x_footprint
                # slots are drawn from center: offset -X by half its X-footprint
                slot.x = cursor - (slot.x_footprint / 2)

    def y_align_rows(self) -> None:
        """Y-align rows from top/+Y to bottom/-Y with even spacing between rows + top/bottom edges."""
        cursor = self.y_mm / 2
        for row in self.rows:
            cursor -= self.y_row_spacing
            # center row based on its largest slot Y-footprint
            row.y = cursor - row.y_max_slot / 2
            for slot in row.slots:
                slot.y = row.y
            cursor -= row.height

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


# TODO --> all of this to its own file. io.py? load.py?


def _gfu_from_config(
        data: dict[str, Any],
        axis: str,
        nominal_mm: float,
        built_mm: float,
        round_up: bool
    ) -> float | None:
    """Read one storage block dimension in GFU, given as either '<axis>' (GFU) or '<axis>_mm'.

    If round_up, mm values convert using the nominal unit size (StorageBlock rounds them up.)
    Otherwise they convert using the built unit size, so <axis>_mm is drawn exactly as given.
    """

    gfu, mm = data.get(axis), data.get(axis + '_mm')
    if gfu is not None and mm is not None:
        raise ValueError(f'[!] storage_block: give {axis} or {axis}_mm, not both')
    if mm is not None:
        gfu = mm / (nominal_mm if round_up else built_mm)
        logger.info(f'storage_block: {axis}_mm={mm} -> {axis}={gfu}')
    return gfu


def load_storage_block(
        data: dict[str, Any],
        name: str = '',
        block_type: StorageBlockType | str | None = None,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
        debug: bool = False,
        no_labels: bool = False
    ) -> StorageBlock:
    """Build a StorageBlock and its Rows from a parsed YAML config."""

    block_data = data.get('storage_block', {})
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
        x=float(dims['x'] or 0.0),
        y=float(dims['y'] or 0.0),
        z=float(dims['z'] or 0.0),
        **rounding
    )
    for row in load_rows(data, font_size=block.font_size):
        if no_labels:
            # after loading, so no row/slot 'labels' setting can turn them back on
            row.label.mode = LabelMode.NO_LABEL
            for slot in row:
                slot.label.mode = LabelMode.NO_LABEL
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
        no_labels: bool = False
    ) -> StorageBlock:
    """Build StorageBlock from YAML config. Name defaults to filename if not set in config."""
    logger.info(f'loading storage block from {path}')
    with open(path) as f:
        block = load_storage_block(
            yaml.safe_load(f),
            name=name,
            block_type=block_type,
            x=x,
            y=y,
            z=z,
            debug=debug,
            no_labels=no_labels
        )
    if not block.name:
        block.name = os.path.splitext(os.path.basename(path))[0]
    return block


def _slot_scoop(slot: Slot, spec: Any, owner: str) -> Scoop:
    """A slot's scoop from its 'slot_scoop' YAML value: false/missing -> none, true -> the slot's
    default, a mapping -> the default with those dimensions overridden.
    """
    if not spec:
        return Scoop()
    Scoop.check_keys(spec, owner)
    scoop = slot.default_scoop()
    for key, value in (spec if isinstance(spec, dict) else {}).items():
        setattr(scoop, key, value)
    return scoop


def _row_scoop(row: Row, spec: Any) -> Scoop:
    """A row's scoop from its 'row_scoop' YAML value: false/missing -> none, true -> defaults, a
    mapping -> those dimensions overridden.

    depth/length come from the row's slots now so validation can run before the build;
    flat_width/wall_width need the slot layout and are filled in at build time (Row.build_scoop.)
    """
    if not spec:
        return Scoop()
    Scoop.check_keys(spec, f"row '{row.name}'")
    scoop = Scoop(
        depth=max((slot.scaled_radius for slot in row.slots), default=0.0),
        length=row.y_max_slot / 2,
        mode=ScoopMode.ROW_SCOOP
    )
    for key, value in (spec if isinstance(spec, dict) else {}).items():
        setattr(scoop, key, value)
    return scoop


def _slot_from_config(config: dict[str, Any]) -> Slot:
    """Build a Slot from its merged config, turning label text (e.g. '6' or 6) into a Label and
    'slot_scoop' into a Scoop.
    """
    config = dict(config)
    scoop_spec = config.pop('slot_scoop', False)
    # labels: false (global/row/slot) turns labels off; otherwise label text gives a SLOT_LABEL
    show_labels = config.pop('labels', None) is not False
    label = config.get('label')
    if not isinstance(label, Label):
        text = '' if label is None else str(label)
        mode = LabelMode.SLOT_LABEL if text and show_labels else LabelMode.NO_LABEL
        config['label'] = Label(label_text=text, font_size=config['font_size'], mode=mode)
    slot = Slot(**config)
    slot.scoop = _slot_scoop(slot, scoop_spec, f"slot '{label}'")
    return slot


def load_rows(data: dict[str, Any], font_size: float = 6.0) -> list[Row]:
    """Build Rows from a parsed YAML config.

    --> Slots are grouped under 'rows', each with its own 'slots' list and an
        optional 'name'; a top-level 'slots' list is loaded as a single row.
    --> 'storage_block' 'global' keys (e.g. shape, slot_scoop) are defaults for every slot
    --> Other row-level keys are defaults for that row's slots
    --> Values set on an individual slot override both.
    --> 'slot_scoop' (global/row/slot): true, a mapping of Scoop dimensions, or false to opt out.
    --> 'row_scoop' (global/row): true or a mapping; one scoop across the row, shared by all its
        slots in place of their own scoops.
    --> 'label' (slot): text for the slot's own label; 'row_label' (row): text for one label
        centered under the row, shared by its slots in place of their own; 'labels: false'
        (global/row/slot) turns labels off.
    --> font_size is the default label size (e.g. the storage block's); each row reserves space
        for its largest label.
    """

    unknown = set(data) - {'storage_block', 'rows', 'slots'}
    if unknown:
        raise ValueError('[!] unknown top-level key(s): {} (slot defaults go in storage_block.global)'
                         .format(', '.join(sorted(unknown))))
    defaults = {'font_size': font_size, **data.get('storage_block', {}).get('global', {})}
    # row_scoop is a row setting, so it isn't passed down to slots
    default_row_scoop = defaults.pop('row_scoop', False)
    rows_data = data['rows'] if 'rows' in data else [{'slots': data['slots']}]
    rows = []
    for row_data in rows_data:
        row_defaults = {
            key: value for key, value in row_data.items()
            if key not in ('name', 'slots', 'row_scoop', 'row_label')
        }
        slots = [
            _slot_from_config({**defaults, **row_defaults, **slot}) for slot in row_data['slots']
        ]
        row = Row(
            font_size=max((slot.font_size for slot in slots), default=defaults['font_size']),
            name=row_data.get('name', ''),
            slots=DoublyLinkedList(slots)
        )
        row_label = row_data.get('row_label')
        if row_label is not None and row_defaults.get('labels', defaults.get('labels')) is not False:
            row.label = Label(
                label_text=str(row_label), font_size=row.font_size, mode=LabelMode.ROW_LABEL
            )
        if row.has_row_label:
            replaced = [slot for slot in slots if slot.draws_label]
            if replaced:
                logger.warning(f"row '{row.name}': row_label replaces {len(replaced)} slot label(s)")
            # share one Label, like a row scoop
            for slot in slots:
                slot.label = row.label
        row.scoop = _row_scoop(row, row_data.get('row_scoop', default_row_scoop))
        if row.has_row_scoop:
            explicit = [slot for slot, raw in zip(slots, row_data['slots']) if raw.get('slot_scoop')]
            if explicit:
                logger.warning(f"row '{row.name}': row_scoop replaces {len(explicit)} slot_scoop(s)")
            # share one Scoop so build-time filling reaches every slot
            for slot in slots:
                slot.scoop = row.scoop
        rows.append(row)
    return rows


def load_rows_from_path(path: str | os.PathLike[str]) -> list[Row]:
    """Build Rows from a YAML file."""
    logger.info(f'loading rows from {path}')
    with open(path) as f:
        return load_rows(yaml.safe_load(f))


def load_slots(data: dict[str, Any]) -> list[Slot]:
    """Build Slots from a parsed YAML config, ignoring any row grouping."""
    return [slot for row in load_rows(data) for slot in row]


def load_slots_from_path(path: str | os.PathLike[str]) -> list[Slot]:
    """Build Slots from a YAML file, ignoring any row grouping."""
    logger.info(f'loading slots from {path}')
    with open(path) as f:
        return load_slots(yaml.safe_load(f))


def main() -> None:
    pass


if __name__ == '__main__':
    main()
