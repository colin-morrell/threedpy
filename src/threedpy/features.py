import logging
from dataclasses import dataclass, field, fields
from enum import Enum
from functools import cached_property
from typing import Any

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
    add,
    edges,
    extrude,
    fillet,
    make_face,
    mirror,
)

from threedpy.constants import (
    FONT_PATH,
    SLOT_SCOOP_FILLET_RADIUS,
    SLOT_SCOOP_LENGTH,
    SLOT_SCOOP_WALL_WIDTH,
    SLOT_DEPTH_CLEARANCE,
)
from threedpy.item import ITEM_TYPES, Item, Orientation, Shape

logger = logging.getLogger(__name__)

"""
Physical features added to/subtracted from the surface of a storageBlock.
"""


class SlotScoopMode(Enum):
    """What a SlotScoop belongs to, or NONE for no scoop (SlotScoop.build() then does nothing.)"""

    NONE = None
    SLOT_SCOOP = 'slot_scoop'
    ROW_SCOOP = 'row_scoop'


@dataclass
class SlotScoop:
    """SlotScoop

    A finger scoop cut into the top surface to make items easier to grab.

    Args:
        flat_width (float): X-axis dimension: length of the flat bottom.
        wall_width (float): X-axis dimension: horizontal run of each parabolic wall.
        depth (float): Z-axis dimension: how far the scoop extends below the surface.
        length (float): Y-axis dimension.
        fillet_radius (float): rounds the rim where the scoop meets the surface; 0 = sharp.
        mode (SlotScoopMode): what the scoop belongs to; NONE = no scoop.

    Dimensions left as None are filled in by its owner (see fill_unset), e.g. a row scoop's
    flat_width/wall_width, which depend on where the row's slots end up.

    SlotScoop extends a straight line outward from center (X) by half the flat_width. It then
    follows a quadratic Bezier to create a parabola up (+Z) to the rim (surface). It's then
    mirrored across and extruded along the Y axis.
    """

    # TODO --> allow rotation

    flat_width: float = 0
    wall_width: float = 0
    depth: float = 0
    length: float = 0
    fillet_radius: float = SLOT_SCOOP_FILLET_RADIUS
    mode: SlotScoopMode = SlotScoopMode.NONE

    @property
    def width(self) -> float:
        """Total width on the X-axis at the rim (usually the block surface.)"""
        if self.flat_width and self.wall_width:
            return self.flat_width + 2 * self.wall_width
        else:
            err = f'[!] SlotScoop.width(): flat_width: {self.flat_width}; wall_width: {self.wall_width}'
            raise ValueError(err)

    def build(self, build_mode: Mode = Mode.SUBTRACT, round_rim: bool = True) -> BasePartObject:
        """Build the scoop at the current location. round_rim=False leaves the rim sharp."""
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
        scoop = BasePartObject(part.part, mode=build_mode)
        # only a cut has a rim (--draw-solids adds the scoop as a solid)
        if build_mode == Mode.SUBTRACT and self.fillet_radius > 0 and round_rim:
            self.fillet_rim(scoop)
        return scoop

    def validate(self) -> None:
        self.validate_mode()
        self.validate_dimensions()

    def validate_mode(self) -> None:
        if self.mode is SlotScoopMode.NONE:
            raise ValueError('[!] SlotScoop.build() called with SlotScoopMode.NONE')

    def validate_dimensions(self) -> None:
        """Validate the x/y/z dimensions have been set."""
        unset = [f.name for f in fields(self) if getattr(self, f.name) == 0]
        if unset:
            e = f'[!] {self.mode.value} scoop has unset dimension(s): {", ".join(unset)}'
            raise ValueError(e)

    def fillet_rim(self, scoop: BasePartObject) -> None:
        """Round the edges where the just-cut scoop meets the top surface.

        --> First tries only the edges inside the scoop's footprint, so neighboring edges the cut
            trimmed (e.g. an overlapping slot's opening) stay sharp.
        --> That fails when the rim runs into another opening, since the fillet can't stop there;
            then the whole topmost edge group is rounded, including those neighboring edges.
        --> If both fail (e.g. radius too large for the geometry), the rim is left sharp.
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
        tolerance = 1e-3

        # TODO --> move this to util?
        def in_footprint(edge) -> bool:
            e = edge.bounding_box()
            return (
                e.min.X >= bb.min.X - tolerance and e.max.X <= bb.max.X + tolerance
                and e.min.Y >= bb.min.Y - tolerance and e.max.Y <= bb.max.Y + tolerance
            )

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
        for rim in (top.filter_by(in_footprint), top):
            try:
                fillet(rim, radius=self.fillet_radius)
                return
            except ValueError:
                continue
        logger.warning(
            f'scoop rim fillet (radius {self.fillet_radius}) failed, leaving it sharp'
        )

    def fill_unset(self, default: 'SlotScoop') -> None:
        """Fill any unset (0) dimension(s) from default, in place."""
        for f in fields(self):
            if getattr(self, f.name) == 0:
                setattr(self, f.name, getattr(default, f.name))

    def log_build(self, coords: tuple) -> None:
        logger.debug('-'*25)
        logger.debug('[!] BUILDING SLOT_SCOOP [!]')
        logger.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        logger.debug(f'|   flat_w: {round(self.flat_width, 3)}')
        logger.debug(f'|   wall_w: {round(self.wall_width, 3)}')
        logger.debug(f'|   length: {round(self.length, 3)}')

    @classmethod
    def check_keys(cls, spec: Any, owner: str) -> None:
        """Raise on mapping keys that aren't SlotScoop fields, so YAML typos fail at load time."""
        if isinstance(spec, dict):
            unknown = set(spec) - {f.name for f in fields(cls)}
            if unknown:
                err = '[!] {} scoop: unknown key(s): {}'.format(owner, ', '.join(sorted(unknown)))
                raise ValueError(err)


class LabelMode(Enum):
    """What a Label belongs to."""

    BIN_LABEL = 'bin_label'
    SLOT_LABEL = 'slot_label'
    ROW_LABEL = 'row_label'
    NO_LABEL = None


@dataclass
class Label:
    """Label.

    Embossed label, 1mm tall, centered on its Slot or Row.
    """

    font_path = FONT_PATH
    font_size: float = 6.0
    label_text: str = ''
    mode: LabelMode = LabelMode.NO_LABEL

    @property
    def alignment(self) -> tuple:
        match self.mode:
            case LabelMode.BIN_LABEL:
                return (Align.CENTER, Align.CENTER)
            case LabelMode.ROW_LABEL | LabelMode.SLOT_LABEL:
                return (Align.CENTER, Align.CENTER)
            case _:
                raise ValueError(f'label.alignment() called with LabelMode={self.mode}')

    @property
    def is_empty(self) -> bool:
        return bool(not self.label_text)

    def build(self, top_face, coords: tuple) -> None:
        if self.mode is LabelMode.NO_LABEL or self.is_empty:
            return
        self.log_build(coords)

        with BuildSketch(Plane.XY.offset(top_face.center().Z)) as label, Locations(coords):
            Text(
                self.label_text,
                font_size=self.font_size,
                font_path=FONT_PATH,
                align=self.alignment
            )
        extrude(label.sketch, amount=1.0)

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
    scoop: SlotScoop = field(default_factory=SlotScoop)
    depth: float = 0.0
    font_size: float = 6.0
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
        return self.label.mode is LabelMode.SLOT_LABEL and not self.label.is_empty

    @property
    def built_mode(self):
        if not self.debug:
            return Mode.SUBTRACT
        return Mode.ADD

    @property
    def fillets_scoop_rim(self) -> bool:
        """Whether a scoop's rim can be filleted where it crosses this slot."""
        return self.item is None or self.item.fillet_scoop_rim

    @cached_property
    def item_solid(self) -> Part:
        """The item's oriented solid, centered on X/Y with its bottom at Z=0. Built once, since
        layout reads the footprint many times."""
        if self.item is None:
            raise ValueError(f'[!] item_solid: {self.shape} slot has no item')
        solid = self.item.oriented()
        bb = solid.bounding_box()
        return solid.moved(Location((-bb.center().X, -bb.center().Y, -bb.min.Z)))

    @property
    def scaled_depth(self) -> float:
        return self.depth + SLOT_DEPTH_CLEARANCE

    @property
    def x_footprint(self) -> float:
        """Slot's profile along the X-axis."""
        if self.item is not None:
            return self.item_solid.bounding_box().size.X
        return self.width

    @property
    def y_footprint(self) -> float:
        """Slot's profile along the Y-axis."""
        if self.item is not None:
            return self.item_solid.bounding_box().size.Y
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
            height = self.item_solid.bounding_box().size.Z
            if self.item.orientation is Orientation.HORIZONTAL:
                return height / 2 + self.z_offset
            return height if not self.debug else height * .5
        return self.scaled_depth

    def build(self) -> None:
        """Build the slot's shape using build123d."""
        if self.item is not None:
            add(self.item_solid, mode=self.built_mode)
        elif self.shape == Shape.PRISM_RECT:
            Box(
                # TODO --> scaled
                self.width,
                self.length,
                self.depth,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
                mode=Mode.SUBTRACT
            )
        else:
            raise ValueError(f'[!] invalid slot shape: {self.shape}')

    def build_label(self, top_face, coords: tuple) -> None:
        if self.label.mode is LabelMode.SLOT_LABEL:
            self.label.build(top_face, coords)

    def build_scoop(self, coords: tuple) -> None:
        if self.scoop.mode is not SlotScoopMode.SLOT_SCOOP:
            return
        self.scoop.log_build(coords)
        if not self.fillets_scoop_rim:
            logger.warning(f'scoop on a {type(self.item).__name__} slot; not filleting its rim')
        with Locations(coords):
            self.scoop.build(self.built_mode, round_rim=self.fillets_scoop_rim)

    def default_scoop(self) -> SlotScoop:
        """Single-slot scoop: flat bottom width of slot, as deep as half that width."""
        return SlotScoop(
            flat_width=self.x_footprint,
            wall_width=SLOT_SCOOP_WALL_WIDTH,
            depth=self.x_footprint / 2,
            length=SLOT_SCOOP_LENGTH,
            mode=SlotScoopMode.SLOT_SCOOP,
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


