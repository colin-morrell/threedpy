import contextvars
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from build123d import (
    Align,
    Axis,
    BuildPart,
    BuildSketch,
    Cone,
    Cylinder,
    GeomType,
    Locations,
    Mode,
    Part,
    RectangleRounded,
    Rot,
    extrude,
    fillet,
)

from threedpy.defaults import (
    ITEM_ORIENTATION,
    ITEM_ROTATION,
    SLOT_DEPTH_CLEARANCE,
    SLOT_DIAMETER_CLEARANCE,
    SOCKET_EXTENSION_SCOOP_MARGIN,
)

logger = logging.getLogger(__name__)


class Shape(Enum):
    """
    Slot shape, set with 'shape' at the global, row or slot level.

    --> CYLINDER / SOCKET_EXTENSION: cut to that Item's solid (see ITEM_TYPES); the slot's other
        keys that are fields of the Item (e.g. diameter, orientation) configure it
    --> PRISM_RECT / PRISM_HEXA: built by Slot from its own length/width/depth
    """

    CYLINDER = 'cylinder'
    PRISM_HEXA = 'prism_hexa'
    PRISM_RECT = 'prism_rect'
    SOCKET_EXTENSION = 'socket_extension'


class Rotation(Enum):
    """
    Top-down direction on the work surface (X/Y) an Item faces, applied after its Orientation.

    An Item faces where its top (+Z) points once HORIZONTAL, or its +Y side when VERTICAL:
     - UP    --> +Y (no turn)
     - DOWN  --> -Y
     - LEFT  --> -X
     - RIGHT --> +X
    """

    # TODO --> allow more fine-tuning. maybe CW/CCW + take a degree

    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'

    @property
    def direction(self) -> tuple[int, int]:
        """Unit X/Y direction this rotation points on the work surface."""
        match self:
            case Rotation.UP:
                return (0, 1)
            case Rotation.LEFT:
                return (-1, 0)
            case Rotation.DOWN:
                return (0, -1)
            case Rotation.RIGHT:
                return (1, 0)

    @property
    def spin(self) -> Rot:
        """Turn about Z (counter-clockwise seen from above) from UP to this direction."""
        match self:
            case Rotation.UP:
                return Rot()
            case Rotation.LEFT:
                return Rot(Z=90)
            case Rotation.DOWN:
                return Rot(Z=180)
            case Rotation.RIGHT:
                return Rot(Z=-90)


class Orientation(Enum):
    """Orientation of the Item / resulting profile of the Slot.

    Vertical: item Z matches surface Z.
    Horizontal: item Z rotates to surface Y.
    """
    VERTICAL = 'vertical'
    HORIZONTAL = 'horizontal'

    @property
    def tilt(self) -> Rot:
        """Rotation from the item as built (standing along +Z) into this orientation."""
        return Rot(X=-90) if self is Orientation.HORIZONTAL else Rot()


# enum members for the configured defaults, so dataclass fields don't call the enums
DEFAULT_ORIENTATION = Orientation(ITEM_ORIENTATION)
DEFAULT_ROTATION = Rotation(ITEM_ROTATION)


@dataclass
class Item(ABC):
    """Item

    Something a Slot holds, modeled as a solid that the Slot orients and subtracts.

    Subclasses implement build(), which returns the item in its own coordinates: standing along
    +Z, centered on the Z-axis, base at Z=0. All measurements in mm.

    Args:
        orientation (Orientation): VERTICAL stands the item up; HORIZONTAL lays it on its side.
        rotation (Rotation): top-down direction the item faces after its orientation (default UP,
            no turn).
        diameter_clearance (float): added to the item's cross-section (diameters, widths).
        depth_clearance (float): added to the item's length.

    Clearances default to the same constants as round slots, so every slot shape fits the same.
    """

    # TODO --> import stl??

    # gap kept between a slot scoop's rounded rim and each end of scoop_span()
    scoop_margin: ClassVar[float] = 0.0

    orientation: Orientation = DEFAULT_ORIENTATION
    rotation: Rotation = DEFAULT_ROTATION
    diameter_clearance: float = SLOT_DIAMETER_CLEARANCE
    depth_clearance: float = SLOT_DEPTH_CLEARANCE

    def __post_init__(self) -> None:
        if not isinstance(self.orientation, Orientation):
            self.orientation = Orientation(self.orientation)
        if not isinstance(self.rotation, Rotation):
            self.rotation = Rotation(self.rotation)

    @property
    def horizontal(self) -> bool:
        return self.orientation == Orientation.HORIZONTAL

    @property
    def vertical(self) -> bool:
        return self.orientation == Orientation.VERTICAL

    def build(self) -> Part:
        l = f'[.] {type(self).__name__}.build(): {self.orientation}, {self.rotation}'
        logger.info(l)
        return self._build()

    def scoop_span(self) -> tuple[float, float] | None:
        """Start and end (mm along the item as built, from its base) of the stretch a slot scoop
        over a HORIZONTAL item should stay within, or None to center the scoop on the slot."""
        return None

    @abstractmethod
    def _build(self) -> Part:
        """Subclasses build their solid here."""

    def oriented(self) -> Part:
        """The item's solid rotated by its orientation and rotation, about the origin."""
        # build123d objects made inside an active builder (e.g. a StorageBlock's BuildPart) add
        # themselves to it; an empty context keeps the item out of whatever is being built
        part = contextvars.Context().run(self.build)
        return self.rotation.spin * self.orientation.tilt * part


@dataclass
class CylinderItem(Item):
    """CylinderItem

    A round item, e.g. a socket: a cylinder standing along +Z.

    Args:
        diameter (float): required.
        depth (float): length along its axis; required.
    """

    diameter: float = 0.0
    depth: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.diameter or not self.depth:
            raise ValueError(
                f'[!] CylinderItem: diameter ({self.diameter}) and depth ({self.depth}) required'
            )
        self.diameter += self.diameter_clearance
        self.depth += self.depth_clearance

    def _build(self) -> Part:
        return Cylinder(
            self.diameter / 2,
            self.depth,
            align=(Align.CENTER, Align.CENTER, Align.MIN)
        )


class Drive(Enum):
    """Socket wrench drive size, which sets a SocketExtension's dimensions.

    Measurements based on Husky extensions.
    """

    NONE = None
    QUARTER_INCH = '1/4'
    THREE_EIGHTHS = '3/8'

    @property
    def dimensions(self) -> dict[str, float]:
        """SocketExtension dimensions (mm, before clearance) per drive size."""
        match self:
            case Drive.QUARTER_INCH:
                return {
                    'bot_rad': 12.3 / 2,
                    'bot_len': 13.5,
                    'bot_fillet_rad': 1.0,
                    'cone': 4.0,
                    'cone_fillet_rad': 2.0,
                    'mid_rad': 8.15 / 2,
                    'mid_top_fillet_rad': 0.5,
                    'top_width': 6.8,
                    'top_len': 9.0,
                    'top_top_fillet_rad': 0.5,
                }
            case Drive.THREE_EIGHTHS:
                return {
                    'bot_rad': 16.9 / 2,
                    'bot_len': 17.5,
                    'bot_fillet_rad': 1.0,
                    'cone': 4.0,
                    'cone_fillet_rad': 2.0,
                    'mid_rad': 12.10 / 2,
                    'mid_top_fillet_rad': 0.5,
                    'top_width': 10.15,
                    'top_len': 13.5,
                    'top_top_fillet_rad': 0.5,
                }
            case _:
                raise ValueError('Drive.NONE has no dimensions')


@dataclass
class SocketExtension(Item):
    """SocketExtension

    A socket wrench extension: round drive end (bot), tapered into a thinner shaft (mid), ending
    in a square drive (top). Lengths are along the extension, from the round end.

    Args:
        drive (Drive): drive size; required. Sets every dimension left at 0.
        total_length (float): overall length; required.
    """

    scoop_margin: ClassVar[float] = SOCKET_EXTENSION_SCOOP_MARGIN

    drive: Drive = Drive.NONE
    bot_rad: float = 0.0
    bot_len: float = 0.0
    bot_fillet_rad: float = 0.0
    cone: float = 0.0
    cone_fillet_rad: float = 0.0
    mid_rad: float = 0.0
    mid_top_fillet_rad: float = 0.0
    top_width: float = 0.0
    top_len: float = 0.0
    top_top_fillet_rad: float = 0.0
    total_length: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.drive, Drive):
            self.drive = Drive(self.drive)
        if self.drive is Drive.NONE:
            known = ', '.join(d.value for d in Drive if d is not Drive.NONE)
            raise ValueError(f'[!] SocketExtension: drive not specified ({known})')
        for name, value in self.drive.dimensions.items():
            if getattr(self, name) == 0:
                setattr(self, name, value)
        unmeasured = [name for name in self.drive.dimensions if getattr(self, name) == 0]
        if unmeasured:
            raise ValueError(
                f'[!] SocketExtension: {self.drive.value} drive has unmeasured dimension(s): '
                + ', '.join(unmeasured)
            )
        if self.total_length == 0.0:
            raise ValueError('[!] SocketExtension: total_length not specified')
        self.bot_rad += self.diameter_clearance / 2
        self.mid_rad += self.diameter_clearance / 2
        self.top_width += self.diameter_clearance
        self.bot_len += self.depth_clearance
        self.cone += self.depth_clearance
        self.top_len += self.depth_clearance
        self.total_length += self.depth_clearance

    def scoop_span(self) -> tuple[float, float]:
        """The middle's straight stretch: past the cone's fillet at the bottom end and the
        middle's top fillet at the top end."""
        # a fillet of radius r between faces at angle a blends r * tan(a / 2) into each face
        cone_angle = math.atan((self.bot_rad - self.mid_rad) / self.cone)
        cone_blend = self.cone_fillet_rad * math.tan(cone_angle / 2)
        start = self.bot_len + self.cone + cone_blend
        end = self.total_length - self.top_len - self.mid_top_fillet_rad
        if end - start <= 2 * self.scoop_margin:
            raise ValueError(
                f'[!] SocketExtension: middle ({end - start:.2f}mm) too short for a slot scoop'
            )
        return start, end

    @property
    def top_fillet_rad(self) -> float:
        """Rounds the box's vertical edges so its corners sit on the mid cylinder's surface."""
        return (self.top_width / 2 * math.sqrt(2) - self.mid_rad) / (math.sqrt(2) - 1)

    def _build(self) -> Part:
        #logger.info('[.] building')
        with BuildPart() as part:
            # bottom
            Cylinder(
                self.bot_rad,
                self.bot_len,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
                mode=Mode.ADD
            )
            fillet(part.edges().sort_by(Axis.Z)[0], radius=self.bot_fillet_rad)
            # transition
            with Locations(part.faces().sort_by(Axis.Z)[-1]):
                Cone(
                    self.bot_rad,
                    self.mid_rad,
                    self.cone,
                    align=(Align.CENTER, Align.CENTER, Align.MIN),
                    mode=Mode.ADD
                )
            # middle
            with Locations(part.faces().sort_by(Axis.Z)[-1]):
                Cylinder(
                    self.mid_rad,
                    self.total_length-self.top_len-self.bot_len-self.cone,
                    align=(Align.CENTER, Align.CENTER, Align.MIN),
                    mode=Mode.ADD
                )
            # round both ends of the taper, where it meets each cylinder
            taper_edges = part.edges().filter_by(GeomType.CIRCLE).filter_by_position(
                Axis.Z, self.bot_len, self.bot_len + self.cone
            )
            fillet(taper_edges, radius=self.cone_fillet_rad)
            # before the square end is added: its corners meet this edge, so filleting after fails
            fillet(part.edges().sort_by(Axis.Z)[-1], radius=self.mid_top_fillet_rad)
            # top
            # extruded bc filleting the box after fusing fails where its corners meet the cylinder
            with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):
                RectangleRounded(self.top_width, self.top_width, self.top_fillet_rad)
            extrude(amount=self.top_len)
            fillet(part.faces().sort_by(Axis.Z)[-1].edges(), radius=self.top_top_fillet_rad)

        return part.part


# the Item class each item Shape builds
ITEM_TYPES: dict[Shape, type[Item]] = {
    Shape.CYLINDER: CylinderItem,
    Shape.SOCKET_EXTENSION: SocketExtension,
}
