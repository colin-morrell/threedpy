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
    mirror
)

from threedpy.constants import (
    FONT_PATH,
    GFU_GRID,
    GFU_GRID_NOMINAL,
    GFU_HEIGHT
)
from threedpy.util import DoublyLinkedList
"""
Physical features drawn on the surface of a storageBlock.
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


# defaults along X
SCOOP_FLAT_WIDTH: float = 10.0
SCOOP_WALL_WIDTH: float = 7.5
# default scoop length along Y
SCOOP_LENGTH: float = 20.0
# rounds the rim where a scoop meets the top surface; 0 = sharp
SCOOP_FILLET_RADIUS: float = 2.5


@dataclass
class Scoop:
    """Scoop

    A finger scoop cut into the top surface: a flat bottom between two parabolic walls, extruded
    along Y. Built with its rim at Z=0 and its floor at -depth, centered on X and Y.

    Args:
        flat_width (float): X-axis dimension: length of the flat bottom.
        wall_width (float): X-axis dimension: horizontal run of each parabolic wall.
        depth (float): Z-axis dimension: how far the scoop extends below the surface.
        width (float): Y-axis dimension.
    """

    flat_width: float = SCOOP_FLAT_WIDTH
    wall_width: float = SCOOP_WALL_WIDTH
    depth: float = None
    length: float = SCOOP_LENGTH
    fillet_radius: float = SCOOP_FILLET_RADIUS

    @property
    def width(self) -> float:
        """Total length (X) at the rim."""
        return self.flat_width + 2 * self.wall_width

    def build(self, mode: Mode = Mode.SUBTRACT) -> BasePartObject:
        """Build the scoop at the current location(s)."""
        half_flat = self.flat_width / 2
        floor = -self.depth
        rim = (-half_flat - self.wall_width, 0)
        with BuildPart() as part:
            # XZ plane so the profile stands upright (sketch Y -> world Z) and extrudes along Y
            with BuildSketch(Plane.XZ):
                # half profile from the middle out, closed along the rim and centerline
                with BuildLine():
                    if half_flat > 0:
                        Line((0, floor), (-half_flat, floor))
                    # a quadratic Bezier is an exact parabola; from the vertex, the middle
                    # control point is where the end tangents meet: halfway along the wall
                    Bezier((-half_flat, floor), (-half_flat - self.wall_width / 2, floor), rim)
                    Line(rim, (0, 0))
                    Line((0, 0), (0, floor))
                make_face()
                mirror(about=Plane.YZ)
            extrude(amount=self.length / 2, both=True)
        scoop = BasePartObject(part.part, mode=mode)
        # only a cut has a rim (debug mode adds the scoop as a solid)
        if mode == Mode.SUBTRACT and self.fillet_radius > 0:
            self.fillet_rim(scoop)
        return scoop

    def fillet_rim(self, scoop: BasePartObject) -> None:
        """Round the edges where the just-cut scoop meets the top surface.

        --> First tries only the edges inside the scoop's footprint, so neighboring edges the cut
            trimmed (e.g. an overlapping slot's opening) stay sharp.
        --> That fails when the rim runs into another opening, since the fillet can't stop there;
            then the whole topmost edge group is rounded, including those neighboring edges.
        --> If both fail (e.g. radius too large for the geometry), the rim is left sharp.
        --> Skipped (rim left sharp) when the rim isn't at the surface or has BSPLINE edges, both
            of which can crash OCCT outright rather than raise."""
        bb = scoop.bounding_box()
        tolerance = 1e-3

        def in_footprint(edge) -> bool:
            e = edge.bounding_box()
            return (
                e.min.X >= bb.min.X - tolerance and e.max.X <= bb.max.X + tolerance
                and e.min.Y >= bb.min.Y - tolerance and e.max.Y <= bb.max.Y + tolerance
            )

        top = edges(Select.LAST).group_by(Axis.Z)[-1]
        # a rim off the surface leaves curved wall/surface intersections, which can crash OCCT
        if abs(top[0].center().Z - bb.max.Z) > tolerance:
            logging.warning(
                'scoop rim (z={:.2f}) is not at the top surface (z={:.2f}); not filleting'
                .format(bb.max.Z, top[0].center().Z)
            )
            return
        # a fresh rim on a flat surface is lines (+ arcs at round openings); BSPLINEs are leftovers
        # of an overlapping scoop's fillet, e.g. neighboring slot scoops
        if any(e.geom_type == GeomType.BSPLINE for e in top):
            logging.warning('scoop rim overlaps another scoop\'s fillet; not filleting')
            return
        for rim in (top.filter_by(in_footprint), top):
            try:
                fillet(rim, radius=self.fillet_radius)
                return
            except ValueError:
                continue
        logging.warning(
            'scoop rim fillet (radius {}) failed, leaving it sharp'.format(self.fillet_radius)
        )

    def log_scoop_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING SCOOP [!]')
        logging.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        logging.debug('|   flat_w: {}'.format(round(self.flat_width, 3)))
        logging.debug('|   wall_w: {}'.format(round(self.wall_width, 3)))
        logging.debug('|   length: {}'.format(round(self.length, 3)))

    @classmethod
    def resolve(cls, spec: 'Scoop | dict | None', default: 'Scoop') -> 'Scoop':
        """A Scoop as given, or default with a mapping's keys (e.g. from YAML) overriding it."""
        if isinstance(spec, Scoop):
            return spec
        return replace(default, **(spec or {}))

    @classmethod
    def check_keys(cls, spec: Any, owner: str) -> None:
        """Raise on mapping keys that aren't Scoop fields, so YAML typos fail at load time."""
        if isinstance(spec, dict):
            unknown = set(spec) - {f.name for f in fields(cls)}
            if unknown:
                err = '[!] {} scoop: unknown key(s): {}'.format(owner, ', '.join(sorted(unknown)))
                raise ValueError(err)


class ScoopMode(Enum):

    SLOT_SCOOP = 'slot_scoop'
    ROW_SCOOP = 'row_scoop'
    NO_SCOOP = None


@dataclass
class Label:
    """Label.

    Embossed label for a single slot. By default, placed below slot with font size 6 and 1mm
    extrusion.
    """
    # TODO --> per-row label (center on row, excludes/overwrites other slot labels)

    font_path = FONT_PATH
    font_size: float = 6.0
    label_text: str = ''

    def build(self) -> None:
        Text(
            self.label_text,
            font_size=self.font_size,
            font_path=FONT_PATH,
            align=(Align.CENTER, Align.CENTER)
        )

    def log_label_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING LABEL [!]')
        logging.debug('|    label: {}'.format(self.label_text))
        logging.debug('|   coords: x={}, y={}'.format(*(round(c, 3) for c in coords)))

    @property
    def is_empty(self) -> bool:
        if not self.label_text:
            return True
        return False


class LabelMode(Enum):

    SLOT_LABEL = 'slot_label'
    ROW_LABEL = 'row_label'
    NO_LABEL = None


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
    label: Label | None = None
    shape: Shape = Shape.ROUND_VERT  # TODO --> default to None
    # None = unset, filled from the slot's Row or StorageBlock (see add_slot / add_row)
    scoops: bool | None = None  # TODO --> move to Enum
    # drawn when scoops is set: a Scoop, or a mapping overriding default_scoop's dimensions
    scoop: Scoop | dict | None = None
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
        Scoop.check_keys(self.scoop, "slot '{}'".format(self.label))

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
            raise ValueError('[!] invalid slot shape: {}'.format(self.shape))

    def built_scoop(self) -> Scoop:
        """The scoop to draw: scoop if it's a Scoop, else default_scoop with scoop's overrides."""
        return Scoop.resolve(self.scoop, self.default_scoop())

    def default_scoop(self) -> Scoop:
        """Scoop sized from the slot: flat bottom as wide as the slot, each wall half its width,
        as deep as its radius."""
        return Scoop(
            flat_width=self.scaled_diameter,
            wall_width=SCOOP_WALL_WIDTH,
            depth=self.scaled_radius
        )

    @property
    def draws_label(self) -> bool:
        """Whether a label is drawn: labels isn't False and there's label text."""
        return self.labels is not False and self.label is not None and bool(self.label.label_text)

    def log_slot_creation(self, coords: tuple) -> None:
        logging.debug('-'*25)
        logging.debug('[!] BUILDING SLOT [!]')
        logging.debug('|    label: {}'.format(self.label))
        logging.debug('|    shape: {}'.format(self.shape))
        logging.debug('|   slot_z: {}'.format(round(self.z, 3)))
        logging.debug('|   coords: x={}, y={}, z={}'.format(*(round(c, 3) for c in coords)))
        logging.debug('| diameter: {}'.format(round(self.scaled_diameter, 3)))
        logging.debug('|    depth: {}'.format(round(self.scaled_depth, 3)))
        logging.debug('|     mode: {}'.format(self.built_mode))
        logging.debug('| rotation: {}'.format(self.built_rotation))

    @property
    def built_align(self):
        # also center along socket's length so slot.y is its middle
        if self.shape == Shape.ROUND_HORZ:
            return (Align.CENTER, Align.CENTER, Align.CENTER)
        return (Align.CENTER, Align.CENTER)

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
        #return self.depth * self.scale
        return self.depth + 0.5

    @property
    def scaled_diameter(self) -> float:
        #return self.diameter * self.scale
        return self.diameter + 0.5

    @property
    def scaled_radius(self) -> float:
        return self.scaled_diameter / 2

    @property
    def y_built_height(self) -> float:
        """
        The slot's dimensions on the Y-axis depend on its orientation:
        --> ROUND_HORZ --> Y corresponds to depth
        --> ROUND_VERT --> Y corresponds to diameter
        """
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
            # with default 0.0 --> slot will cut -Z by half its diameter
            return self.z_offset
        if not self.debug:
            return self.scaled_depth
        # places slots above surface for debugging
        return self.scaled_depth * .5


