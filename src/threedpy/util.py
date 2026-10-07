import logging
import os
from collections.abc import Iterable, Iterator
from build123d import (
    Align,
    Axis,
    BuildPart,
    BuildSketch,
    Circle,
    Locations,
    Mode,
    RegularPolygon,
    Text,
    extrude
)
from build123d.exporters3d import export_stl
from gridfinity_build123d import (
    Bin,
    BaseEqual,
    BottomCorners,
    Compartment,
    CompartmentsEqual,
    GridfinityRefinedMagnetHolePressfit as MagHole,
    Label,
    Scoop,
)
from gridfinity_build123d.constants import gridfinity_standard

logger = logging.getLogger(__name__)


# %%


class Node[T]:
    """A doubly linked list node holding a value and links to its neighbors."""

    def __init__(self, value: T) -> None:
        self.value = value
        self.prev: Node[T] | None = None
        self.next: Node[T] | None = None

    def __repr__(self) -> str:
        return 'Node({!r})'.format(self.value)


class DoublyLinkedList[T]:
    """A doubly linked list. Iterating yields values; nodes() yields Nodes."""

    def __init__(self, values: Iterable[T] = ()) -> None:
        self.head: Node[T] | None = None
        self.tail: Node[T] | None = None
        self._len = 0
        for value in values:
            self.append(value)

    def append(self, value: T) -> Node[T]:
        """Add value to the end of the list."""
        if self.tail is None:
            return self._insert_first(value)
        return self.insert_after(self.tail, value)

    def prepend(self, value: T) -> Node[T]:
        """Add value to the start of the list."""
        if self.head is None:
            return self._insert_first(value)
        return self.insert_before(self.head, value)

    def insert_after(self, node: Node[T], value: T) -> Node[T]:
        """Insert value directly after node."""
        new = Node(value)
        new.prev = node
        new.next = node.next
        if node.next is None:
            self.tail = new
        else:
            node.next.prev = new
        node.next = new
        self._len += 1
        return new

    def insert_before(self, node: Node[T], value: T) -> Node[T]:
        """Insert value directly before node."""
        new = Node(value)
        new.next = node
        new.prev = node.prev
        if node.prev is None:
            self.head = new
        else:
            node.prev.next = new
        node.prev = new
        self._len += 1
        return new

    def remove(self, node: Node[T]) -> T:
        """Unlink node from the list and return its value."""
        if node.prev is None:
            self.head = node.next
        else:
            node.prev.next = node.next
        if node.next is None:
            self.tail = node.prev
        else:
            node.next.prev = node.prev
        node.prev = node.next = None
        self._len -= 1
        return node.value

    def _insert_first(self, value: T) -> Node[T]:
        node = Node(value)
        self.head = self.tail = node
        self._len = 1
        return node

    def nodes(self) -> Iterator[Node[T]]:
        node = self.head
        while node is not None:
            yield node
            node = node.next

    def __iter__(self) -> Iterator[T]:
        return (node.value for node in self.nodes())

    def __reversed__(self) -> Iterator[T]:
        node = self.tail
        while node is not None:
            yield node.value
            node = node.prev

    def __len__(self) -> int:
        return self._len

    def __repr__(self) -> str:
        return 'DoublyLinkedList({!r})'.format(list(self))


def build_gf_base(grid_x: int, grid_y: int):
    base = BaseEqual(
        grid_x,
        grid_y,
        [MagHole(BottomCorners())]
    )
    return base


def build_gf_bin(grid_x: int, grid_y: int, z: int):
    """Generate gridfinity bin with scoop+label given x/y/z. All in gf units."""

    base = build_gf_base(grid_x, grid_y)
    gf_bin = Bin(
        base,
        compartments=CompartmentsEqual(
            div_x=grid_x,
            compartment_list=Compartment(features=[Label(), Scoop(radius=15)]),
        ),
        height_in_units=z
    )
    return gf_bin

def build_gf_box(grid_x: int, grid_y: int, grid_z: int):
    """Generate solid gridfinity box given x/y/z. All in gf units."""

    base = build_gf_base(grid_x, grid_y)
    gf_box = Bin(
        base,
        height_in_units=grid_z
    )

    return gf_box


def export_as_stl(part, path: str | os.PathLike[str]) -> None:
    """Export a BuildPart's part to an STL file, validating the path first.

    --> ValueError: path is empty, is a directory, or doesn't end in .stl
    --> FileNotFoundError: path's parent directory doesn't exist
    --> PermissionError: path (or its parent directory) isn't writable
    --> OSError: the export itself failed
    """
    path = os.path.expanduser(os.fspath(path))
    if not path:
        raise ValueError('[!] export path is empty')
    if os.path.isdir(path):
        raise ValueError('[!] export path is a directory: {}'.format(path))
    if os.path.splitext(path)[1].lower() != '.stl':
        raise ValueError('[!] export path must end in .stl: {}'.format(path))

    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise FileNotFoundError('[!] export directory does not exist: {}'.format(parent))
    if os.path.exists(path):
        if not os.access(path, os.W_OK):
            raise PermissionError('[!] export path is not writable: {}'.format(path))
        logger.warning('overwriting existing file: {}'.format(path))
    elif not os.access(parent, os.W_OK):
        raise PermissionError('[!] export directory is not writable: {}'.format(parent))

    if not export_stl(part.part, path):
        raise OSError('[!] failed to export STL: {}'.format(path))
    logger.info('exported STL to {}'.format(path))


# %%
