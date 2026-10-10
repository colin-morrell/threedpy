import logging
from dataclasses import dataclass, field, fields
from enum import Enum
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
    Cylinder,
    GeomType,
    Line,
    Locations,
    Mode,
    Plane,
    Select,
    Text,
    edges,
    extrude,
    fillet,
    make_face,
    mirror,
)

from threedpy.constants import (
    FONT_PATH,
    SCOOP_FILLET_RADIUS,
    SCOOP_LENGTH,
    SCOOP_WALL_WIDTH,
    SLOT_DEPTH_CLEARANCE,
    SLOT_DIAMETER_CLEARANCE,
)

logger = logging.getLogger(__name__)

"""
Physical features drawn on/removed from the surface of a storageBlock.
"""


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


class ScoopMode(Enum):
    """What a Scoop belongs to, or NONE for no scoop (Scoop.build() then does nothing.)"""

    NONE = None
    SLOT_SCOOP = 'slot_scoop'
    ROW_SCOOP = 'row_scoop'


@dataclass
class Scoop:
    """Scoop

    A finger scoop cut into the top surface to make items easier to grab.

    Args:
        flat_width (float): X-axis dimension: length of the flat bottom.
        wall_width (float): X-axis dimension: horizontal run of each parabolic wall.
        depth (float): Z-axis dimension: how far the scoop extends below the surface.
        length (float): Y-axis dimension.
        fillet_radius (float): rounds the rim where the scoop meets the surface; 0 = sharp.
        mode (ScoopMode): what the scoop belongs to; NONE = no scoop.

    Dimensions left as None are filled in by its owner (see fill_unset), e.g. a row scoop's
    flat_width/wall_width, which depend on where the row's slots end up.

    Scoop extends a straight line outward from center (X) by half the flat_width. It then follows
    a quadratic Bezier to create a parabola up (+Z) to the rim (surface). It's then mirrored across
    and extruded along the Y axis.
    """

    flat_width: float | None = None
    wall_width: float | None = None
    depth: float | None = None
    length: float | None = None
    fillet_radius: float = SCOOP_FILLET_RADIUS
    mode: ScoopMode = ScoopMode.NONE

    @property
    def width(self) -> float:
        """Total width on the X-axis at the rim (usually the block surface.)"""
        return self.flat_width + 2 * self.wall_width

    def build(self, build_mode: Mode = Mode.SUBTRACT) -> BasePartObject | None:
        """Build the scoop at the current location."""

        if self.mode is ScoopMode.NONE:
            return None
        unset = [f.name for f in fields(self) if getattr(self, f.name) is None]
        if unset:
            e = f'[!] {self.mode.value} scoop has unset dimension(s): {", ".join(unset)}'
            raise ValueError(e)

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
        if build_mode == Mode.SUBTRACT and self.fillet_radius > 0:
            self.fillet_rim(scoop)
        return scoop

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

    def fill_unset(self, default: 'Scoop') -> None:
        """Fill any unset (None) dimension(s) from default, in place."""
        for f in fields(self):
            if getattr(self, f.name) is None:
                setattr(self, f.name, getattr(default, f.name))

    def log_scoop_creation(self, coords: tuple) -> None:
        logger.debug('-'*25)
        logger.debug('[!] BUILDING SCOOP [!]')
        logger.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        logger.debug(f'|   flat_w: {round(self.flat_width, 3)}')
        logger.debug(f'|   wall_w: {round(self.wall_width, 3)}')
        logger.debug(f'|   length: {round(self.length, 3)}')

    @classmethod
    def check_keys(cls, spec: Any, owner: str) -> None:
        """Raise on mapping keys that aren't Scoop fields, so YAML typos fail at load time."""
        if isinstance(spec, dict):
            unknown = set(spec) - {f.name for f in fields(cls)}
            if unknown:
                err = '[!] {} scoop: unknown key(s): {}'.format(owner, ', '.join(sorted(unknown)))
                raise ValueError(err)


class LabelMode(Enum):
    """What a Label belongs to."""

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
    def is_empty(self) -> bool:
        return bool(not self.label_text)

    def build(self, top_face, coords: tuple) -> None:
        if self.mode is LabelMode.NO_LABEL or self.is_empty:
            return
        self.log_label_creation(coords)

        with BuildSketch(top_face) as label, Locations(coords):
            Text(
                self.label_text,
                font_size=self.font_size,
                font_path=FONT_PATH,
                align=(Align.CENTER, Align.CENTER)
            )
        extrude(label.sketch, amount=1.0)

    def log_label_creation(self, coords: tuple) -> None:
        logger.debug('[!] BUILDING LABEL @ x={} y={}'.format(*(round(c, 3) for c in coords)))


@dataclass
class Slot:
    """Slot

    A single storage cavity. All measurements in mm unless otherwise stated.
    From a top-down view of the work surface, X is left/right and Y is up/down.
    """
    # TODO SLOT REFACTOR
        # --> slot methodology should be entirely shape independent
        # --> no length/width/diameter, everything in terms of x/y/z
        # --> transformations like diameter -> depth should happen in Item w/ Orientation+Direction

    debug: bool = False
    label: Label = field(default_factory=Label)
    shape: Shape = Shape.ROUND_VERT  # TODO --> default to None
    scoop: Scoop = field(default_factory=Scoop)
    diameter: float = 0.0
    depth: float = 0.0
    font_size: float = 6.0
    length: float = 0.0
    width: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z_offset: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.shape, Shape):
            self.shape = Shape(self.shape)

    @property
    def draws_label(self) -> bool:
        """Whether the slot draws its own label."""
        return self.label.mode is LabelMode.SLOT_LABEL and not self.label.is_empty

    @property
    def built_align(self):
        if self.shape == Shape.ROUND_HORZ:
            # also center along socket's length so slot.y is its middle
            return (Align.CENTER, Align.CENTER, Align.CENTER)
        return (Align.CENTER, Align.CENTER)

    @property
    def built_mode(self):
        if not self.debug:
            return Mode.SUBTRACT
        return Mode.ADD

    @property
    def built_rotation(self) -> int:
        if self.shape == Shape.ROUND_HORZ:
            return (90, 0, 0)
        return (0, 0, 0)

    @property
    def scaled_depth(self) -> float:
        return self.depth + SLOT_DEPTH_CLEARANCE

    @property
    def scaled_diameter(self) -> float:
        return self.diameter + SLOT_DIAMETER_CLEARANCE

    @property
    def scaled_radius(self) -> float:
        return self.scaled_diameter / 2

    @property
    def x_footprint(self):
        """Slot's profile along the X-axis."""
        return self.scaled_diameter

    @property
    def y_footprint(self) -> float:
        if self.shape == Shape.ROUND_HORZ:
            return self.scaled_depth
        return self.scaled_diameter

    @property
    def z(self) -> float:
        """
        How far to offset the slot below (-Z) work surface's top face.

        --> ROUND_VERT offset by their depth.
        --> ROUND_HORZ offset by z_offset or half their scaled depth if not specified.
        """
        if self.shape == Shape.ROUND_HORZ:
            # default 0.0 --> slot will cut -Z by half its diameter
            return self.z_offset
        if not self.debug:
            return self.scaled_depth
        # places slots above surface for debugging
        return self.scaled_depth * .5

    def build(self) -> None:
        """Build the slot's shape using build123d."""
        if self.shape in (Shape.ROUND_VERT, Shape.ROUND_HORZ):
            Cylinder(
                self.scaled_radius,
                self.scaled_depth,
                rotation=self.built_rotation,
                align=self.built_align,
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
            raise ValueError(f'[!] invalid slot shape: {self.shape}')

    def build_label(self, top_face, coords: tuple) -> None:
        if self.label.mode is LabelMode.SLOT_LABEL:
            self.label.build(top_face, coords)

    def build_scoop(self, coords: tuple) -> None:
        if self.scoop.mode is not ScoopMode.SLOT_SCOOP:
            return
        self.scoop.log_scoop_creation(coords)
        with Locations(coords):
            self.scoop.build(self.built_mode)

    def default_scoop(self) -> Scoop:
        """Single-slot scoop: flat bottom width of slot, as deep as its radius."""
        return Scoop(
            flat_width=self.scaled_diameter,
            wall_width=SCOOP_WALL_WIDTH,
            depth=self.scaled_radius,
            length=SCOOP_LENGTH,
            mode=ScoopMode.SLOT_SCOOP
        )

    def log_slot_creation(self, coords: tuple) -> None:
        logger.debug('-'*25)
        logger.debug('[!] BUILDING SLOT [!]')
        logger.debug(f'|    label: {self.label if self.draws_label else None}')
        logger.debug(f'|    shape: {self.shape}')
        logger.debug(f'|   slot_z: {round(self.z, 3)}')
        logger.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        logger.debug(f'| diameter: {round(self.scaled_diameter, 3)}')
        logger.debug(f'|    depth: {round(self.scaled_depth, 3)}')
        logger.debug(f'|     mode: {self.built_mode}')
        logger.debug(f'| rotation: {self.built_rotation}')


