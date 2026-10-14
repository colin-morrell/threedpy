import logging
import math
from collections.abc import Iterable, Iterator
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, Flag, auto

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    Locations,
    Mode,
)
from gridfinity_build123d import (
    Bin,
    Compartment,
    CompartmentsEqual,
    Scoop,
)
from gridfinity_build123d import Label as BinLabel

from threedpy.constants import (
    GFU_GRID,
    GFU_HEIGHT,
    LABEL_TAB_WIDTH,
    SLOT_SCOOP_FILLET_RADIUS,
    SLOT_SCOOP_WALL_WIDTH,
    SCOOP_RADIUS,
)
from threedpy.features import Label, LabelMode, SlotScoop, SlotScoopMode, Slot
from threedpy.util import DoublyLinkedList, build_gf_base, build_gf_box


logger = logging.getLogger(__name__)


class StorageBlockType(Enum):
    """StorageBlockType

    How a StorageBlock's slots are laid out.

    POSITIONAL: each slot is placed at the x/y given for it in the YAML config.
    ROWED: rows are evenly spaced along Y, and each row's slots are evenly spaced along X.
    """

    POSITIONAL = 'positional'
    ROWED = 'rowed'


class RoundAxis(Flag):
    """Dimensions to round up to a whole number of GFU."""

    NONE = 0
    X = auto()
    Y = auto()
    Z = auto()
    ALL = X | Y | Z


@dataclass
class BlockRow:
    """BlockRow

    An ordered collection of slots.

    Positional blocks ignore order.
    Rowed blocks draw slots and their features left-to-right along the X-axis.
    """

    debug: bool = False
    font_size: float = 6.0
    label: Label = field(default_factory=Label)
    name: str = ''
    scoop: SlotScoop = field(default_factory=SlotScoop)
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
        return any(slot.scoop.mode is SlotScoopMode.SLOT_SCOOP for slot in self.slots)

    @property
    def has_row_scoop(self) -> bool:
        """Whether the row has one scoop across all its slots."""
        return self.scoop.mode is SlotScoopMode.ROW_SCOOP

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
        left = min(slot.x - slot.x_footprint / 2 for slot in self.slots)
        return left + self.x_scoop_span / 2

    @property
    def x_scoop_span(self) -> float:
        """X distance from the first slot's left edge to the last slot's right edge."""
        left = min(slot.x - slot.x_footprint / 2 for slot in self.slots)
        right = max(slot.x + slot.x_footprint / 2 for slot in self.slots)
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
        """BlockRow's position on the Y-axis."""
        return self._y

    @y.setter
    def y(self, val: float) -> None:
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
    def z_max(self) -> float | None:
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
            align=(Align.CENTER, Align.CENTER, Align.MIN),
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
        self.scoop.log_build(coords)
        round_rim = all(slot.fillets_scoop_rim for slot in self.slots)
        if not round_rim:
            logger.warning(f"row '{self.name}' scoop spans item slots that can't be filleted; "
                           'not filleting its rim')
        with Locations(coords):
            self.scoop.build(Mode.ADD if self.debug else Mode.SUBTRACT, round_rim=round_rim)

    def default_scoop(self, x_block_width: float) -> SlotScoop:
        """Single-row scoop across its slots' X-footprint, depth of its largest slot radius."""

        radius = max((slot.x_footprint / 2 for slot in self.slots), default=0.0)
        # extend the scoop walls all the way to the edges (w/ .5 margin) on X-axis
        edge_margin = SLOT_SCOOP_FILLET_RADIUS + 0.5
        max_wall_width = (x_block_width - self.x_scoop_span) / 2 - edge_margin
        # only take default width if it doesn't touch/exceed the edges
        scoop_wall_width = min(max_wall_width, SLOT_SCOOP_WALL_WIDTH)

        return SlotScoop(
            flat_width=self.x_scoop_span,
            wall_width=scoop_wall_width,
            depth=radius,
            length=self.y_max_slot/2,
            mode=SlotScoopMode.ROW_SCOOP
        )

    def __iter__(self) -> Iterator[Slot]:
        return iter(self.slots)

    def __len__(self) -> int:
        return len(self.slots)


@dataclass
class Storage(ABC):
    """Storage

    A printable gridfinity organizer: StorageBin/StorageBlock, sized in gridfinity units (GFU).

    Args:
        debug (bool): draw debug geometry.
        name (str, optional): defaults to the YAML filename.
        font_size (float): label font size.
        x (float): dimensions along the X-axis in GFU.
        y (float): dimensions along the Y-axis in GFU.
        z (float): height in GFU.
        round_to_gfu (RoundAxis): dimensions to round up to whole GFU number.
    """

    debug: bool = False
    name: str = ''
    font_size: float = 6.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    round_to_gfu: RoundAxis = RoundAxis.NONE

    def __post_init__(self) -> None:
        for axis, flag in (('x', RoundAxis.X), ('y', RoundAxis.Y), ('z', RoundAxis.Z)):
            if flag in self.round_to_gfu:
                # round() first so float error doesn't add a unit
                setattr(self, axis, math.ceil(round(getattr(self, axis), 6)))

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

    def build(self, arrange: bool = False) -> BuildPart:
        """Build the part. arrange swaps a slow gridfinity base for a plain box, where supported."""
        logger.info(f'[.] {type(self).__name__}.build()')
        return self._build(arrange)

    @abstractmethod
    def _build(self, arrange: bool = False) -> BuildPart:
        """Subclasses build their solid here."""

    def build_base(self, arrange: bool = False):
        logger.info(f'[.] {type(self).__name__}.build_base()')
        self._build_base(arrange)

    @abstractmethod
    def _build_base(self, arrange: bool = False):
        """Subclasses build their bases here."""

    def validate(self) -> None:
        """Raise ValueError if the configuration can't be built."""
        logger.info(f'[.] {type(self).__name__}.validate()')
        self._validate()
        logger.info(f'[+] {type(self).__name__}.validate() passed.')

    @abstractmethod
    def _validate(self) -> None:
        """Subclasses run their validation checks here."""


@dataclass
class StorageBin(Storage):
    """StorageBin"""

    # TODO --> support scoop/noscoop
    # TODO --> support labeltab/nolabeltab

    label: BinLabel = field(default_factory=BinLabel)
    scoop_radius: float = SCOOP_RADIUS

    def _build(self, arrange: bool = False) -> BuildPart:  # noqa: ARG002
        """Iterate through all slots of all rows and build their specified shapes and features.

        Slots and scoops are placed relative to top_face's height when given. z_mm assumes the
        body starts at Z=0, but a gridfinity base extends below it (its top is 2.5mm lower).
        """
        with BuildPart() as part:
            self.log_build()
            self.validate()
            self.build_base()

            top_face = part.faces().sort_by(Axis.Z)[-1]
            self.label.build(top_face, self.label_tab_center(top_face))

            return part

    def _build_base(self):
        base = build_gf_base(int(self.x), int(self.y))
        _bin = Bin(
            base,
            compartments=CompartmentsEqual(
                #div_x=self.x,
                #div_y=self.y,
                compartment_list=Compartment(
                    features=[BinLabel(), Scoop(radius=self.scoop_radius)]
                ),
            ),
            height_in_units=int(self.z)
        )

    @staticmethod
    def label_tab_center(top_face) -> tuple[float, float]:
        opening = top_face.inner_wires()[0].bounding_box()
        return ((opening.min.X + opening.max.X) / 2, opening.max.Y + LABEL_TAB_WIDTH / 2)

    def log_build(self) -> None:
        # TODO
        pass

    def _validate(self) -> None:
        # TODO --> label text bounds check on X/Y
        self.validate_gfu()
        self.validate_label_z()
        self.validate_scoop_radius()

    def validate_gfu(self) -> None:
        partial = [axis for axis in ('x', 'y', 'z') if not float(getattr(self, axis)).is_integer()]
        if partial:
            raise ValueError(
                '[!] storage_bin {}: {} must be whole GFU'.format(self.name, '/'.join(partial))
            )

    def validate_label_z(self) -> None:
        if self.label.mode is not LabelMode.NO_LABEL and self.z < 3:
            raise ValueError(f'[!] storage_bin {self.name}: label tab requires Z > 2')

    def validate_scoop_radius(self) -> None:
        z_top: float = 7 * self.z - 2.5
        depth: float = z_top - 5.3
        max_rad: float = depth - 0.1

        if self.scoop_radius > max_rad:
            logger.warning(
                f'[!] compartment depth > requested scoop rad, falling back to max_rad: {max_rad}'
            )
            self.scoop_radius = max_rad


@dataclass
class StorageBlock(Storage):
    """StorageBlock

    A gridfinity storage block for holding tools, sockets, etc. A StorageBlock is structured as a
    collection of Rows, which themselves are ordered collections of Slots. By default these rows
    and their slots will be spaced evenly along their respective axes.

    For manual positional placement, specific x/y/z coordinates can also be assigned at the
    slot level in the .yaml config. Rows are irrelevant for this configuration.

    Dimensions are primarily intended to fit the gridfinity standard (https://gridfinity.xyz/)
    using gridfinity units (GFU), but dimensions can also be given in mm and built as given. If X/Y
    aren't whole GFU, a plain box is built instead of the gridfinity base.

    GFU grid (X/Y) specifications are 42mm per unit (not including tolerances.)
    GFU height (Z) specification is 7mm per unit (not including tolerances.)

    Args:
        name (str, optional): storage block name. Defaults to inputted YAML filename.
        type (StorageBlockType): slot layout, rowed (default) or positional.
        font_size (float): default label font size for every row/slot.
        x (float): storage block dimensions along the X-axis in GFU.
        y (float): storage block dimensions along the Y-axis in GFU.
        z (float): storage block height in GFU.
        round_to_gfu (RoundAxis): dimensions to round up to whole GFU number.
    """

    # TODO --> auto allocate slots given # rows
    # TODO --> auto allocate slots/rows given GFU

    no_labels: bool = False
    type: StorageBlockType = StorageBlockType.ROWED
    rows: DoublyLinkedList[BlockRow] = field(default_factory=DoublyLinkedList)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.type, StorageBlockType):
            self.type = StorageBlockType(self.type)

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
    def x_max_footprint(self) -> float:
        """Largest row's X-footprint."""
        return max(row.x_footprint for row in self.rows)

    @property
    def y_gfu(self) -> float:
        """Number of gridfinity units along the Y axis."""
        return self.y

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

    def add_row(self, row: BlockRow) -> BlockRow:
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

    def add_slots(self, slots: Iterable[Slot], name: str = '') -> BlockRow:
        """Append slots directly as a new row."""
        return self.add_row(BlockRow(name=name, slots=DoublyLinkedList(slots)))

    def _build(self, arrange: bool=False):
        """Iterate through all slots of all rows and build their specified shapes and features.

        Slots and scoops are placed relative to top_face's height when given. z_mm assumes the
        body starts at Z=0, but a gridfinity base extends below it (its top is 2.5mm lower).
        """
        with BuildPart() as part:
            self.log_build()
            self.build_base(arrange)
            top_face = part.faces().sort_by(Axis.Z)[-1]

            if self.type == StorageBlockType.ROWED:
                self.y_align_rows()
                self.x_align_slots()

            self.validate()
            surface_z = top_face.center().Z if top_face is not None else self.z_mm
            if self.debug:
                self.build_row_markers(surface_z)

            for row in self.rows:
                logger.debug(f'build(): BlockRow with x_slot_spacing {row.x_slot_spacing}')
                for slot in row.slots:
                    slot.build(surface_z)

                    if not self.no_labels:
                        slot.build_label(top_face, (slot.x, row.y_label))

                    self.build_slot_scoop(row, slot, surface_z)

                if not self.no_labels:
                    row.build_label(top_face)
                self.build_row_scoop(row, surface_z)

            return part

    def _build_base(self, arrange: bool = False):
        if not arrange:
            self._build_base_gfu()
            return
        with Locations((0,0,0)):
            self._build_base_plain()

    def _build_base_gfu(self) -> None:
        if self.is_gridfinity:
            build_gf_box(int(self.x_gfu), int(self.y_gfu), int(self.z_gfu))
            return
        raise ValueError(f'{self.x_gfu}x{self.y_gfu} is_gridfinity() failed')

    def _build_base_plain(self) -> None:
        """Build mock storage block surface without expensive gf generation call.

        Useful for faster testing/fine-tuning row/slot arrangement.
        """
        Box(
            self.x_mm,
            self.y_mm,
            self.z_mm,
            align=(Align.CENTER, Align.CENTER, Align.MIN)
        )

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

    def build_row_scoop(self, row: BlockRow, surface_z: float) -> None:
        """Generate the SlotScoop across an entire BlockRow, if it has one."""
        row.build_scoop((row.x_scoop, row.y_scoop, surface_z), self.x_mm)

    def build_slot_scoop(self, row: BlockRow, slot: Slot, surface_z: float) -> None:
        """Generate a single slot's own SlotScoop, if it has one."""
        slot.build_scoop((slot.x, row.y_scoop, surface_z))

    def log_build(self) -> None:
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

    def _validate(self) -> None:
        self.validate_x_bounds()
        self.validate_x_spacing()
        self.validate_y_bounds()

    def validate_x_bounds(self) -> None:
        """Validate all BlockRow's slots do not exceed the StorageBlock's width on the X-axis."""
        # TODO --> automatically account for scoop/no scoop
        # TODO --> assume a reasonable margin so slots don't overlap
        if self.x_max_footprint > self.x_mm:
            e = f'Y-BOUNDS: footprint {self.x_max_footprint} exceeds block width {self.x_mm}'
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
        logger.info('[.] x_align_slots()')
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
        logger.info('[.] y_align_rows()')
        cursor = self.y_mm / 2
        for row in self.rows:
            cursor -= self.y_row_spacing
            # center row based on its largest slot Y-footprint
            row.y = cursor - row.y_max_slot / 2
            for slot in row.slots:
                slot.y = row.y
            cursor -= row.height

    def __iter__(self) -> Iterator[BlockRow]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)
