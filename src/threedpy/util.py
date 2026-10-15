import logging
from collections.abc import Iterable, Iterator

from gridfinity_build123d import (
    BaseEqual,
    Bin,
    BottomCorners,
)
from gridfinity_build123d import (
    GridfinityRefinedMagnetHolePressfit as MagHole,
)

from threedpy.defaults import BASE_MAGNET_HOLES

logger = logging.getLogger(__name__)


# %%


class Node[T]:
    """A doubly linked list node holding a value and links to its neighbors."""

    def __init__(self, value: T) -> None:
        self.value = value
        self.prev: Node[T] | None = None
        self.next: Node[T] | None = None

    def __repr__(self) -> str:
        return f'Node({self.value!r})'


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
        return f'DoublyLinkedList({list(self)!r})'


def build_gf_base(grid_x: int, grid_y: int):
    logger.info(f'[.] build_gf_base(): x={grid_x} y={grid_y}')
    base = BaseEqual(
        grid_x,
        grid_y,
        [MagHole(BottomCorners())] if BASE_MAGNET_HOLES else []
    )
    return base


def build_gf_box(grid_x: int, grid_y: int, grid_z: int):
    """Generate solid gridfinity box given x/y/z. All in gf units."""
    base = build_gf_base(grid_x, grid_y)

    logger.info(f'[.] build_gf_box():  x={grid_x} y={grid_y} z={grid_z}')
    gf_box = Bin(
        base,
        height_in_units=grid_z
    )

    return gf_box


# %%
