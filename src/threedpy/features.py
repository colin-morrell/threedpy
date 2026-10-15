import contextvars
import logging
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Any, ClassVar

from build123d import (
    Align,
    Axis,
    BasePartObject,
    Bezier,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    GeomType,
    Line,
    Location,
    Locations,
    Mode,
    Part,
    Plane,
    Select,
    Text,
    Vector,
    add,
    edges,
    extrude,
    fillet,
    make_face,
    mirror,
)

from threedpy.constants import FONT_PATH
from threedpy.defaults import (
    BLOCK_SCOOP_DEPTH_RATIO,
    BLOCK_SCOOP_FILLET_FALLBACK_RADIUS,
    BLOCK_SCOOP_FILLET_RADIUS,
    BLOCK_SCOOP_FLAT_WIDTH,
    BLOCK_SCOOP_LENGTH,
    BLOCK_SCOOP_WALL_WIDTH,
    DRAW_SOLIDS_SINK_RATIO,
    FONT_SIZE,
    LABEL_HEIGHT,
    SCOOP_RIM_TOLERANCE,
    SLOT_DEPTH_CLEARANCE,
)
from threedpy.item import ITEM_TYPES, Item, Orientation, Rotation, Shape

logger = logging.getLogger(__name__)

"""
Physical features added to/subtracted from the surface of a storageBlock.
"""


class BlockScoopType(Enum):
    """What a BlockScoop belongs to, or NONE for no scoop (BlockScoop.build() then does nothing.)"""

    NONE = None
    SLOT = 'slot'
    ROW = 'row'
    MANUAL = 'manual'


@dataclass
class BlockScoop:
    """BlockScoop

    A finger scoop cut into the top surface to make items easier to grab.

    Args:
        flat_width (float): X-axis dimension: length of the flat bottom.
        wall_width (float): X-axis dimension: horizontal run of each parabolic wall.
        depth (float): Z-axis dimension: how far the scoop extends below the surface.
        length (float): Y-axis dimension.
        fillet_radius (float): rounds the rim where the scoop meets the surface.
        type (BlockScoopType): what the scoop belongs to; NONE = no scoop.
        x (float): MANUAL scoops: X position of its center on the block (mm, block-centered).
        y (float): MANUAL scoops: Y position of its center on the block (mm, block-centered).
        rotation (float): MANUAL scoops: degrees about Z; 0 runs its length along Y.

    Dimensions left at 0 are filled in by its owner (see fill_unset), e.g. a row scoop's, which
    depend on where the row's slots end up.

    BlockScoop extends a straight line outward from center (X) by half the flat_width. It then
    follows a quadratic Bezier to create a parabola up (+Z) to the rim (surface). It's then
    mirrored across and extruded along the Y axis.
    """

    # dimensions that 0 marks as unset; position/rotation can legitimately be 0
    DIMENSIONS: ClassVar[tuple[str, ...]] = (
        'flat_width', 'wall_width', 'depth', 'length', 'fillet_radius'
    )
    PLACEMENT: ClassVar[tuple[str, ...]] = ('x', 'y', 'rotation')

    flat_width: float = 0
    wall_width: float = 0
    depth: float = 0
    length: float = 0
    fillet_radius: float = 0
    type: BlockScoopType = BlockScoopType.NONE
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0

    @property
    def width(self) -> float:
        """Total width on the X-axis at the rim (usually the block surface.)"""
        if self.flat_width and self.wall_width:
            return self.flat_width + 2 * self.wall_width
        else:
            err = f'[!] BlockScoop.width(): flat_width: {self.flat_width}; wall_width: {self.wall_width}'
            raise ValueError(err)

    def build(self, build_mode: Mode = Mode.SUBTRACT, rotation: float = 0.0) -> BasePartObject:
        """Build the scoop at the current location."""
        logger.info(f'[.] {type(self).__name__}.build(): {self.type}, {self.length}')
        self.validate()

        half_flat = self.flat_width / 2
        floor = -self.depth
        rim = (-half_flat - self.wall_width, 0)
        with BuildPart() as part:
            with BuildSketch(Plane.XZ):
                with BuildLine():
                    if half_flat > 0:
                        Line((0, floor), (-half_flat, floor))
                    Bezier((-half_flat, floor), (-half_flat - self.wall_width / 2, floor), rim)
                    Line(rim, (0, 0))
                    Line((0, 0), (0, floor))
                make_face()
                mirror(about=Plane.YZ)
            extrude(amount=self.length / 2, both=True)
        scoop = BasePartObject(part.part, rotation=(0, 0, rotation), mode=build_mode)
        # only a cut has a rim (--draw-solids adds the scoop as a solid)
        if build_mode == Mode.SUBTRACT and self.fillet_radius > 0:
            self.fillet_rim(scoop)
        return scoop

    def validate(self) -> None:
        self.validate_type()
        self.validate_dimensions()

    def validate_type(self) -> None:
        if self.type is BlockScoopType.NONE:
            raise ValueError('[!] BlockScoop.build() called with BlockScoopType.NONE')

    def validate_dimensions(self) -> None:
        """Validate the x/y/z dimensions have been set."""
        unset = [name for name in self.DIMENSIONS if getattr(self, name) == 0]
        if unset:
            e = f'[!] {self.type.value} scoop has unset dimension(s): {", ".join(unset)}'
            raise ValueError(e)

    def fillet_rim(self, scoop: BasePartObject) -> None:
        """Round the edges where the just-cut scoop meets the top surface.

        --> Rounds the whole topmost edge group the cut made: the rim plus the slot-opening edges
            it crosses. Filleting only the rim crashes OCCT where it stops against an item's
            curved surface (e.g. a socket extension's taper).
        --> Tries fillet_radius, then BLOCK_SCOOP_FILLET_FALLBACK_RADIUS; if both fail, the rim is
            left sharp.
        --> Skipped (rim left sharp) when the walls are narrower than the fillet, or the rim isn't
            at the surface or has BSPLINE edges; each can crash OCCT outright rather than raise."""

        # TODO --> clean up this mess

        # the fillet spreads fillet_radius across the surface, past a narrow wall into the slots
        if self.wall_width < self.fillet_radius:
            logger.warning(
                f'scoop wall ({self.wall_width:.2f}mm) narrower than fillet radius '
                f'({self.fillet_radius}mm); not filleting'
            )
            return
        bb = scoop.bounding_box()
        tolerance = SCOOP_RIM_TOLERANCE

        top = edges(Select.LAST).group_by(Axis.Z)[-1]
        # a rim off the surface leaves curved wall/surface intersections, which can crash OCCT
        if abs(top[0].center().Z - bb.max.Z) > tolerance:
            logger.warning(
                f'scoop rim (z={bb.max.Z:.2f}) not at top surface '
                f'(z={top[0].center().Z:.2f}); not filleting'
            )
            return
        # a fresh rim on a flat surface is lines (+ arcs at round openings)
        # BSPLINEs are leftovers of an overlapping scoop's fillet, e.g. neighboring slot scoops
        if any(e.geom_type == GeomType.BSPLINE for e in top):
            logger.warning('scoop rim overlaps another scoop\'s fillet; not filleting')
            return
        radii = [self.fillet_radius]
        if BLOCK_SCOOP_FILLET_FALLBACK_RADIUS < self.fillet_radius:
            radii.append(BLOCK_SCOOP_FILLET_FALLBACK_RADIUS)
        for radius in radii:
            try:
                fillet(top, radius=radius)
            except ValueError:
                continue
            if radius != self.fillet_radius:
                logger.warning(
                    f'[!] scoop rim fillet (radius {self.fillet_radius}) failed, used {radius}'
                )
            return
        logger.warning(
            f"[!] scoop rim fillet (radius {', '.join(map(str, radii))}) failed, leaving it sharp"
        )

    def fill_manual_defaults(self) -> None:
        """Fill a MANUAL scoop's unset (0) dimensions; depth follows its (possibly given) flat width."""
        self.fill_unset(BlockScoop(
            flat_width=BLOCK_SCOOP_FLAT_WIDTH,
            wall_width=BLOCK_SCOOP_WALL_WIDTH,
            length=BLOCK_SCOOP_LENGTH,
            fillet_radius=BLOCK_SCOOP_FILLET_RADIUS,
        ))
        if self.depth == 0:
            self.depth = self.flat_width * BLOCK_SCOOP_DEPTH_RATIO

    def fill_unset(self, default: 'BlockScoop') -> None:
        """Fill any unset (0) dimension(s) from default, in place."""
        for name in self.DIMENSIONS:
            if getattr(self, name) == 0:
                setattr(self, name, getattr(default, name))

    def log_build(self, coords: tuple) -> None:
        logger.debug('-'*25)
        logger.debug(f'[!] BUILDING {self.type.name} SCOOP [!]')
        logger.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        logger.debug(f'|   flat_w: {round(self.flat_width, 3)}')
        logger.debug(f'|   wall_w: {round(self.wall_width, 3)}')
        logger.debug(f'|   length: {round(self.length, 3)}')

    @classmethod
    def check_keys(cls, spec: Any, owner: str, placement: bool = False) -> None:
        """Raise on mapping keys that aren't BlockScoop dimensions (plus x/y/rotation when placement),
        so YAML typos fail at load time."""
        if isinstance(spec, dict):
            unknown = set(spec) - set(cls.DIMENSIONS) - set(cls.PLACEMENT if placement else ())
            if unknown:
                err = '[!] {} scoop: unknown key(s): {}'.format(owner, ', '.join(sorted(unknown)))
                raise ValueError(err)


class LabelType(Enum):
    """What a Label belongs to."""

    BIN = 'bin'
    SLOT = 'slot'
    ROW = 'row'
    NONE = None


@dataclass
class Label:
    """Label.

    Embossed label, 1mm tall, centered on its Slot or BlockRow.
    """

    font_path = FONT_PATH
    font_size: float = FONT_SIZE
    label_text: str = ''
    type: LabelType = LabelType.NONE

    @property
    def alignment(self) -> tuple:
        match self.type:
            case LabelType.BIN:
                return (Align.CENTER, Align.CENTER)
            case LabelType.ROW | LabelType.SLOT:
                return (Align.CENTER, Align.CENTER)
            case _:
                raise ValueError(f'label.alignment() called with LabelType={self.type}')

    @property
    def is_empty(self) -> bool:
        return bool(not self.label_text)

    def build(self, top_face, coords: tuple) -> None:
        if self.type is LabelType.NONE or self.is_empty:
            return
        self.log_build(coords)

        with BuildSketch(Plane.XY.offset(top_face.center().Z)) as label, Locations(coords):
            Text(
                self.label_text,
                font_size=self.font_size,
                font_path=FONT_PATH,
                align=self.alignment
            )
        extrude(label.sketch, amount=LABEL_HEIGHT)

    def log_build(self, coords: tuple) -> None:
        logger.debug('[!] BUILDING LABEL @ x={} y={}'.format(*(round(c, 3) for c in coords)))


@dataclass
class Slot:
    """Slot

    A single storage cavity. All measurements in mm unless otherwise stated.
    From a top-down view of the work surface, X is left/right and Y is up/down.
    """
    # TODO --> move PRISM_RECT/PRISM_HEXA onto items too; their length/width/depth live here

    debug: bool = False
    label: Label = field(default_factory=Label)
    shape: Shape | None = None
    item: Item | None = None
    scoop: BlockScoop = field(default_factory=BlockScoop)
    depth: float = 0.0
    font_size: float = FONT_SIZE
    length: float = 0.0
    width: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z_offset: float = 0.0

    def __post_init__(self) -> None:
        if self.shape is None:
            raise ValueError('[!] slot has no shape')
        if not isinstance(self.shape, Shape):
            self.shape = Shape(self.shape)
        item_type = ITEM_TYPES.get(self.shape)
        if item_type is not None and not isinstance(self.item, item_type):
            raise ValueError(f'[!] {self.shape.value} slot needs a {item_type.__name__} item')
        if item_type is None and self.item is not None:
            raise ValueError(f'[!] {self.shape.value} slot takes no item')

    @property
    def draws_label(self) -> bool:
        """Whether the slot draws its own label."""
        return self.label.type is LabelType.SLOT and not self.label.is_empty

    @property
    def built_mode(self):
        if not self.debug:
            return Mode.SUBTRACT
        return Mode.ADD

    @cached_property
    def _placed_item(self) -> tuple[Part, Vector]:
        """The item's oriented solid, centered on X/Y with its bottom at Z=0, and its size. Both
        are computed once: layout reads them many times, and an exact bounding box of a filleted
        item takes OCCT a noticeable fraction of a second."""
        if self.item is None:
            raise ValueError(f'[!] item_solid: {self.shape} slot has no item')
        solid = self.item.oriented()
        bb = solid.bounding_box()
        return solid.moved(Location((-bb.center().X, -bb.center().Y, -bb.min.Z))), bb.size

    @property
    def item_solid(self) -> Part:
        """The item's oriented solid, centered on X/Y with its bottom at Z=0."""
        return self._placed_item[0]

    @property
    def item_size(self) -> Vector:
        """X/Y/Z size of item_solid."""
        return self._placed_item[1]

    @property
    def scaled_depth(self) -> float:
        return self.depth + SLOT_DEPTH_CLEARANCE

    @property
    def scoop_fillet_radius(self) -> float:
        """Rim fillet radius for scoops over this slot."""
        if self.item is None:
            return BLOCK_SCOOP_FILLET_RADIUS
        return self.item.scoop_fillet_radius

    @property
    def scoop_span(self) -> tuple[float, float] | None:
        """The item's scoop_span() for a HORIZONTAL item, or None to center scoops on the slot."""
        if self.item is None or self.item.orientation is not Orientation.HORIZONTAL:
            return None
        return self.item.scoop_span()

    @property
    def scoop_offset(self) -> tuple[float, float]:
        """X/Y shift from the slot's center to the center of its item's scoop_span(), along the
        item's length; (0, 0) when the item has no span."""
        span = self.scoop_span
        if span is None or self.item is None:
            return (0.0, 0.0)
        dx, dy = self.item.rotation.direction
        size = self.item_size
        # item_solid is centered on X/Y, so its base sits half its length back from the center
        along = (span[0] + span[1]) / 2 - (size.X if dx else size.Y) / 2
        return (dx * along, dy * along)

    @property
    def scoop_rotation(self) -> float:
        """Degrees about Z for scoops over this slot: 90 when its item points left/right, so the
        scoop runs along the item like it does for up/down."""
        if self.item is not None and self.item.rotation in (Rotation.LEFT, Rotation.RIGHT):
            return 90.0
        return 0.0

    @cached_property
    def scoop_width(self) -> float:
        """X width of the slot's opening across its center, which its scoops are sized from.

        Scoops are centered on the slot, so this is the opening they actually cross: e.g. a socket
        extension's shaft rather than its wider round end.
        """
        if self.item is None:
            return self.x_footprint if self.scoop_rotation == 0 else self.y_footprint
        # thin slab through the slot's center, across the scoop (X, or Y when turned 90) and Z;
        # made in an empty context so it doesn't add itself to a StorageBlock's active BuildPart
        if self.scoop_rotation == 0:
            slab = contextvars.Context().run(Box, 1000, 0.001, 1000)
            return (self.item_solid & slab).bounding_box().size.X
        slab = contextvars.Context().run(Box, 0.001, 1000, 1000)
        return (self.item_solid & slab).bounding_box().size.Y

    @property
    def x_footprint(self) -> float:
        """Slot's profile along the X-axis."""
        if self.item is not None:
            return self.item_size.X
        return self.width

    @property
    def y_footprint(self) -> float:
        """Slot's profile along the Y-axis."""
        if self.item is not None:
            return self.item_size.Y
        return self.length

    @property
    def z(self) -> float:
        """
        How far to offset the slot below (-Z) work surface's top face.

        --> HORIZONTAL items sink by half their height, so they're cut halfway; z_offset moves
            them further down.
        --> VERTICAL items sink by their full height (half with --draw-solids, to show them).
        --> PRISM_RECT sinks by its scaled depth.
        """
        if self.item is not None:
            height = self.item_size.Z
            if self.item.orientation is Orientation.HORIZONTAL:
                return height / 2 + self.z_offset
            return height if not self.debug else height * DRAW_SOLIDS_SINK_RATIO
        return self.scaled_depth

    def build(self, surface_z: float) -> None:
        """Build the slot's shape using build123d, sunk z below the work surface at surface_z."""
        l = f'[.] {type(self).__name__}.build(): {type(self.item).__name__}, x={self.x}, y={self.y}'
        logger.info(l)
        coords = (self.x, self.y, surface_z - self.z)
        self.log_build(coords)
        with Locations(coords):
            if self.item is not None:
                add(self.item_solid, mode=self.built_mode)
            elif self.shape == Shape.PRISM_RECT:
                Box(
                    self.width,
                    self.length,
                    self.depth,
                    align=(Align.CENTER, Align.CENTER, Align.MIN),
                    mode=Mode.SUBTRACT
                )
            else:
                raise ValueError(f'[!] invalid slot shape: {self.shape}')

    def build_label(self, top_face, coords: tuple) -> None:
        if self.label.type is LabelType.SLOT:
            self.label.build(top_face, coords)

    def build_scoop(self, coords: tuple) -> None:
        if self.scoop.type is not BlockScoopType.SLOT:
            return
        self.check_scoop_length()
        dx, dy = self.scoop_offset
        coords = (coords[0] + dx, coords[1] + dy, *coords[2:])
        self.scoop.log_build(coords)
        with Locations(coords):
            self.scoop.build(self.built_mode, rotation=self.scoop_rotation)

    def check_scoop_length(self) -> None:
        """Warn when the slot scoop, rounded rim included, reaches the ends of its item's
        scoop_span()."""
        span = self.scoop_span
        reach = self.scoop.length + 2 * self.scoop.fillet_radius
        if span is not None and reach >= span[1] - span[0]:
            logger.warning(
                f"slot '{self.label.label_text}': scoop ({reach:.2f}mm with its rim) reaches the "
                f'ends of its {type(self.item).__name__} span ({span[1] - span[0]:.2f}mm)'
            )

    def default_scoop(self) -> BlockScoop:
        """Single-slot scoop: flat bottom width of slot, as deep as half that width, and as long as
        its item's scoop_span() less its rim fillet and the item's margin at each end (or the
        default length)."""
        span = self.scoop_span
        if span is None or self.item is None:
            length = BLOCK_SCOOP_LENGTH
        else:
            # the rim fillet rounds past each end of the scoop, so keep it off the span's ends too
            reserve = self.scoop_fillet_radius + self.item.scoop_margin
            length = span[1] - span[0] - 2 * reserve
        return BlockScoop(
            flat_width=self.scoop_width,
            wall_width=BLOCK_SCOOP_WALL_WIDTH,
            depth=self.scoop_width * BLOCK_SCOOP_DEPTH_RATIO,
            length=length,
            fillet_radius=self.scoop_fillet_radius,
            type=BlockScoopType.SLOT,
        )

    def log_build(self, coords: tuple) -> None:
        logger.debug('-'*25)
        logger.debug('[!] BUILDING SLOT [!]')
        logger.debug(f'|    label: {self.label if self.draws_label else None}')
        logger.debug(f'|    shape: {self.shape}')
        logger.debug(f'|   slot_z: {round(self.z, 3)}')
        logger.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        if self.item is not None:
            logger.debug(f'|     item: {self.item}')
        else:
            logger.debug(f'|     size: {self.width} x {self.length} x {round(self.scaled_depth, 3)}')
        logger.debug(f'|     mode: {self.built_mode}')


