import json
import logging
import math
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from build123d import (
    Align,
    Box,
    BuildSketch,
    Cylinder,
    Locations,
    Mode,
    Text,
    extrude
)

from threedpy.constants import FONT_PATH, GFU_GRID, GFU_GRID_NOMINAL, GFU_HEIGHT
from threedpy.util import DoublyLinkedList

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

logger = logging.getLogger(__name__)


class Shape(Enum):
    """
    Slot cross-section.

    --> HORIZONTAL: cylinder whose circular faces are perpendicular to the work surface.
        (e.g. a long socket laid on its side.)
    --> ROUND: cylinder whose circular faces are parallel to the work surface.
        (e.g. a short socket standing upright.)
    """

    HEXAGONAL = 'hexagonal'
    HORIZONTAL = 'horizontal'
    RECTANGLE = 'rectangle'
    ROUND = 'round'


@dataclass
class Slot:
    """
    A single cavity for storing a socket etc vertically.

    --> All measurements in mm unless otherwise stated.
    --> From a top-down view of the work surface, X is left/right and Y is up/down.
    """
    # TODO --> validation (rectangle can't have length/width 0, etc)
    # TODO --> center option for x/y. calc box_len / slot_len and offset for spacing

    label: str = ''
    shape: Shape = Shape.ROUND
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
        if self.shape in (Shape.ROUND, Shape.HORIZONTAL):
            Cylinder(
                self.scaled_radius,
                self.depth,
                rotation=(self.rotation, 0, 0),
                align=(Align.CENTER, Align.MIN),
                mode=Mode.SUBTRACT
            )
        elif self.shape == Shape.RECTANGLE:
            Box(
                self.width,
                self.length,
                self.depth,
                align=(Align.CENTER, Align.MIN),  # if the latter is CENTER, y=0
                mode=Mode.SUBTRACT
            )
        else:
            raise ValueError('[!] invalid slot shape: {}'.format(self.shape))

    def build_label(self) -> None:
        # TODO --> add default font_path to config file
        # TODO --> allow overloading font in function call
        Text(
            self.label,
            font_size=self.font_size,
            font_path=FONT_PATH,
            align=(Align.CENTER, Align.MIN)
        )

    def log_label_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING LABEL [!]')
        logging.debug('|    label: {}'.format(self.label))
        logging.debug('|   coords: x={}, y={}'.format(*coords))
        logging.debug('|    depth: {}'.format(self.depth))
        logging.debug('-'*25)

    def log_slot_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING SLOT [!]')
        logging.debug('|    label: {}'.format(self.label))
        logging.debug('|    shape: {}'.format(self.shape))
        logging.debug('|   coords: x={}, y={}, z={}'.format(*coords))
        logging.debug('|    depth: {}'.format(self.depth))
        logging.debug('| rotation: {}'.format(self.rotation))
        logging.debug('-'*25)

    @property
    def rotation(self) -> int:
        if self.shape == Shape.HORIZONTAL:
            return 90
        return 0

    @property
    def scaled_depth(self) -> float:
        return self.depth * self.scale

    @property
    def scaled_diameter(self) -> float:
        return self.diameter * self.scale

    @property
    def scaled_radius(self) -> float:
        return self.scaled_diameter / 2

    @property
    def z(self) -> float:
        # TODO --> should z_offset just be set to depth in post_init?
        # TODO --> should round-horizontal automatically offset Z + their radius?
        """ How far to offset the slot below (-Z) work surface's top face.

        --> Cylindrical (circ. faces parallel to work surface) offset by their depth.
        --> Horizontal ( "" ""  perpendicular to work surface) offset by a manually specified
            (negative) amount.
        """
        if self.shape == Shape.HORIZONTAL:
            if self.z_offset == 0.0:
                return -self.scaled_radius
            return self.z_offset
        return self.depth


@dataclass
class Row:
    """An ordered collection of slots."""

    font_size: float = 6.0
    name: str = ''
    slots: DoublyLinkedList[Slot] = field(default_factory=DoublyLinkedList)
    width: float = 0.0
    _y: float = 0.0

    def add_slot(self, slot: Slot) -> Slot:
        slot.font_size = self.font_size
        self.slots.append(slot)
        return slot

    @property
    def font_spacing(self) -> float:
        """Distance between bottom of slot and top of label."""
        #return self.font_size / 3
        return 0.0

    @property
    def height(self) -> float:
        """Total row height based on the max diameter + font size."""
        return self.max_diameter + self.font_size + self.font_spacing

    @property
    def max_diameter(self) -> float:
        """Largest diameter slot within the row."""
        return max((slot.scaled_diameter for slot in self.slots), default=0.0)

    @property
    def max_radius(self) -> float:
        """Largest radius slot within the row."""
        return (self.max_diameter / 2)

    @property
    def min_diameter(self) -> float:
        """Smallest diameter slot within the row."""
        return min((slot.scaled_diameter for slot in self.slots), default=0.0)

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

        --> Offset downward/below slots (-Y) by font_size.
        --> Since slots are Y-centered with each other, labels start from the row's Y position to
            stay aligned with each other."""
        return self.y - self.font_size

    def __iter__(self) -> Iterator[Slot]:
        return iter(self.slots)

    def __len__(self) -> int:
        return len(self.slots)


@dataclass
class Holder:
    """ A gridfinity holder, structured as a collection of rows, which are ordered collections of
    slots."""

    # TODO --> auto allocate slots given # rows
    # TODO --> auto allocate slots/rows given GFU
    # TODO --> font_size

    name: str = ''
    rows: DoublyLinkedList[Row] = field(default_factory=DoublyLinkedList)
    x: int = 0
    y: int = 0
    z: float = 0.0

    def add_row(self, row: Row) -> Row:
        logger.debug('add_row(): {} slots'.format(len(row)))
        self.rows.append(row)
        return row

    def add_slots(self, slots: Iterable[Slot], name: str = '') -> Row:
        """
        Add slots (e.g. from load_slots) as a new row. With no existing
        rows this becomes the first row; otherwise it is appended after them.
        """
        return self.add_row(Row(name=name, slots=DoublyLinkedList(slots)))

    def build_slots(self, labels: bool=True, top_face=None):
        for row in self.rows:
            for slot in row.slots:
                # generate slot
                coords = (
                    slot.x,
                    slot.y,
                    self.z_mm - slot.z
                )
                slot.log_slot_creation(coords)
                with Locations(coords):
                    slot.build_shape()

                if labels and slot.label:
                    # generate label
                    label_coords = (
                        slot.x,
                        row.y_label
                    )
                    slot.log_label_creation(label_coords)
                    with BuildSketch(top_face) as label:
                        with Locations(label_coords):
                            slot.build_label()
                    extrude(label.sketch, amount=1.0)

    def build_test_surface(self, part) -> None:
        """ Build mock holder surface without expensive gf generation call. Useful for faster
            testing/fine-tuning row/slot arrangement."""
        Box(
            self.x_mm,
            self.y_mm,
            self.z_mm,
            align=(Align.CENTER, Align.CENTER)
        )

    def log_holder_creation(self) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING HOLDER [!]')
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

        --> First slot initially aligns with min X / left edge (0-(x_mm*.5), since 0 is center.)
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

        --> First row initially aligns with max Y / top edge  (y_mm*.5, since 0 is center.)
        --> Other rows initially align with the previous row.

        --> All rows then offset downward (-Y) by self.y_row_spacing
        --> All rows then offset again by their own height."""

        for row in self.rows.nodes():
            if not row.prev:
                row.value.y = 0 + (self.y_mm / 2)
            else:
                row.value.y = row.prev.value.y
                row.value.y -= self.y_row_spacing
            row.value.y -= row.value.height
            for slot in row.value.slots:
                slot.y = row.value.y
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
    def x_gfu(self) -> int:
        """Number of gridfinity units along the X axis."""
        return self.x

    @property
    def y_gfu(self) -> int:
        """Number of gridfinity units along the Y axis."""
        return self.y

    @property
    def z_gfu(self) -> float:
        """Number of gridfinity height units along the Z axis."""
        return self.z

    @property
    def x_mm(self) -> int:
        """Width in mm (GFU_GRID spec is 42mm.)"""
        return self.x * GFU_GRID

    @property
    def y_mm(self) -> int:
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
        return self.y_margin_total / (self.num_rows + 2)

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


HOLDER_KEYS = ('name', 'x', 'y', 'z', 'x_mm', 'y_mm', 'z_mm')


def _gfu_from_json(data: dict[str, Any], axis: str, unit_mm: float, whole: bool) -> float | None:
    """ Read one holder dimension in GFU, given as either '<axis>' (GFU) or '<axis>_mm'.

    --> mm values are converted using the nominal unit size, and rounded up to whole units if
        whole is set (gridfinity X/Y must be whole units).
    --> Returns None if the dimension isn't given."""

    gfu, mm = data.get(axis), data.get(axis + '_mm')
    if gfu is not None and mm is not None:
        raise ValueError('[!] holder: give {0} or {0}_mm, not both'.format(axis))
    if mm is not None:
        gfu = mm / unit_mm
        if whole:
            # round() first so float error (e.g. 84 / 42 = 2.0000000001) doesn't add a unit
            gfu = math.ceil(round(gfu, 6))
        logger.info('holder: {}_mm={} -> {}={}'.format(axis, mm, axis, gfu))
    if gfu is not None and whole and not float(gfu).is_integer():
        raise ValueError('[!] holder: {} must be a whole number of units, got {}'.format(axis, gfu))
    return gfu


def load_holder(
        data: dict[str, Any],
        name: str = '',
        x: int | None = None,
        y: int | None = None,
        z: float | None = None
    ) -> Holder:
    """ Build a Holder (and its Rows) from a parsed JSON object.

    --> Holder settings live under an optional top-level 'holder' object: 'name', and each
        dimension as either GFU ('x', 'y', 'z') or mm ('x_mm', 'y_mm', 'z_mm').
    --> X/Y given in mm are rounded up to whole units; Z may be fractional.
    --> name/x/y/z arguments (e.g. from the CLI) override the JSON values.
    --> Missing dimensions are left at 0."""

    holder_data = data.get('holder', {})
    unknown = set(holder_data) - set(HOLDER_KEYS)
    if unknown:
        raise ValueError('[!] holder: unknown key(s): {}'.format(', '.join(sorted(unknown))))

    dims = {
        'x': _gfu_from_json(holder_data, 'x', GFU_GRID_NOMINAL, whole=True),
        'y': _gfu_from_json(holder_data, 'y', GFU_GRID_NOMINAL, whole=True),
        'z': _gfu_from_json(holder_data, 'z', GFU_HEIGHT, whole=False),
    }
    for axis, override in (('x', x), ('y', y), ('z', z)):
        if override is not None:
            dims[axis] = override

    holder = Holder(
        name=name or holder_data.get('name', ''),
        x=int(dims['x'] or 0),
        y=int(dims['y'] or 0),
        z=float(dims['z'] or 0.0)
    )
    for row in load_rows(data):
        holder.add_row(row)
    return holder


def load_holder_from_path(
        path: str | os.PathLike[str],
        name: str = '',
        x: int | None = None,
        y: int | None = None,
        z: float | None = None
    ) -> Holder:
    """Build a Holder from a JSON file. The name defaults to the filename if not set in the JSON."""
    logger.info('loading holder from {}'.format(path))
    with open(path) as f:
        holder = load_holder(json.load(f), name=name, x=x, y=y, z=z)
    if not holder.name:
        holder.name = os.path.splitext(os.path.basename(path))[0]
    return holder


def load_rows(data: dict[str, Any]) -> list[Row]:
    """ Build Rows from parsed JSON object.

    --> Slots are grouped under 'rows', each with its own 'slots' list and an
        optional 'name'; a top-level 'slots' list is loaded as a single row.
    --> Top-level keys (e.g. shape, scale) are defaults for every slot, except 'holder'
        (see load_holder)
    --> Other row-level keys are defaults for that row's slots
    --> Values set on an individual slot override both."""

    defaults = {key: value for key, value in data.items() if key not in ('holder', 'rows', 'slots')}
    rows_data = data['rows'] if 'rows' in data else [{'slots': data['slots']}]
    rows = []
    for row_data in rows_data:
        row_defaults = {key: value for key, value in row_data.items() if key not in ('name', 'slots')}
        slots = [Slot(**{**defaults, **row_defaults, **slot}) for slot in row_data['slots']]
        rows.append(Row(name=row_data.get('name', ''), slots=DoublyLinkedList(slots)))
    return rows


def load_rows_from_path(path: str | os.PathLike[str]) -> list[Row]:
    """Build Rows from a JSON file."""
    logger.info('loading rows from {}'.format(path))
    with open(path) as f:
        return load_rows(json.load(f))


def load_slots(data: dict[str, Any]) -> list[Slot]:
    """Build Slots from a parsed JSON object, ignoring any row grouping."""
    return [slot for row in load_rows(data) for slot in row]


def load_slots_from_path(path: str | os.PathLike[str]) -> list[Slot]:
    """Build Slots from a JSON file, ignoring any row grouping."""
    logger.info('loading slots from {}'.format(path))
    with open(path) as f:
        return load_slots(json.load(f))


def main() -> None:
    logger.info('Starting')
    holder = Holder(name='holder-1')
    row = holder.add_row(Row(name='row-1'))
    row.add_slot(Slot(label='M3', shape=Shape.HEXAGONAL, diameter=12.0, depth=20.0))
    logger.info('Built {} with {} row(s)'.format(holder.name, len(holder)))


if __name__ == '__main__':
    main()
