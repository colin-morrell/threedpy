"""
Tier 3 gridfinity tests: the real gridfinity base, built once for a block and once for a bin.

Each part is built by a module-scoped fixture and shared by every test here, so the whole module
costs two base builds (a few seconds). Deselect with -m "not slow".
"""

import pytest
from build123d import Axis, Vector

from threedpy.constants import GFU_HEIGHT, LABEL_TAB_WIDTH
from threedpy.io import load_storage_bin, load_storage_block

pytestmark = pytest.mark.slow

# gridfinity's base extends this far below Z=0, and its top sits this far below z_mm
BASE_BELOW_ZERO = 2.5
TOP_BELOW_Z_MM = 2.5


def up_faces(part):
    return [f for f in part.faces().filter_by(Axis.Z) if f.normal_at().Z > 0.99]


@pytest.fixture(scope='module')
def block():
    """Smallest gridfinity block (1x1x3) with one labeled vertical slot."""
    data = {
        'storage_block': {'x': 1, 'y': 1, 'z': 3},
        'slots': [{'shape': 'cylinder', 'diameter': 10, 'depth': 5, 'label': 'A'}],
    }
    storage_block = load_storage_block(data)
    part = storage_block.build().part
    slot = next(iter(next(iter(storage_block.rows))))
    return storage_block, part, slot


@pytest.fixture(scope='module')
def storage_bin():
    """1x1x5 gridfinity bin with a label on its tab."""
    storage_bin = load_storage_bin({'storage_bin': {'x': 1, 'y': 1, 'z': 5, 'label': 'M3'}})
    return storage_bin, storage_bin.build().part


class TestGridfinityBlock:
    def test_one_valid_solid(self, block):
        _, part, _ = block
        assert part.is_valid
        assert len(part.solids()) == 1

    def test_base_extends_below_zero(self, block):
        _, part, _ = block
        assert part.bounding_box().min.Z == pytest.approx(-BASE_BELOW_ZERO, abs=0.01)

    def test_label_sits_on_the_real_top_face(self, block):
        storage_block, part, _ = block
        top = storage_block.z_mm - TOP_BELOW_Z_MM
        assert part.bounding_box().max.Z == pytest.approx(top + 1, abs=0.01)

    def test_slot_is_cut_from_the_real_top_face(self, block):
        storage_block, part, slot = block
        top = storage_block.z_mm - TOP_BELOW_Z_MM
        # open just under the surface and just above the slot's floor, solid just below the floor
        assert not part.is_inside(Vector(slot.x, slot.y, top - 0.5))
        assert not part.is_inside(Vector(slot.x, slot.y, top - slot.z + 0.3))
        assert part.is_inside(Vector(slot.x, slot.y, top - slot.z - 0.5))


class TestGridfinityBin:
    def test_one_valid_solid(self, storage_bin):
        _, part = storage_bin
        assert part.is_valid
        assert len(part.solids()) == 1

    def test_label_stands_1mm_above_the_rim(self, storage_bin):
        b, part = storage_bin
        rim = b.z * GFU_HEIGHT - TOP_BELOW_Z_MM
        assert part.bounding_box().max.Z == pytest.approx(rim + 1, abs=0.01)

    def test_label_lands_on_the_label_tab(self, storage_bin):
        _, part = storage_bin
        faces = up_faces(part)
        label_top = max(f.center().Z for f in faces)
        # the rim is the largest upward face 1mm below the label; its hole is the cavity opening
        rim = max(
            (f for f in faces if f.center().Z == pytest.approx(label_top - 1, abs=1e-3)),
            key=lambda f: f.area,
        )
        opening = rim.inner_wires()[0].bounding_box()
        label = [f.bounding_box() for f in faces if f.center().Z == pytest.approx(label_top)]
        # the tab runs LABEL_TAB_WIDTH back (+Y) from the opening's back edge
        assert min(bb.min.Y for bb in label) >= opening.max.Y
        assert max(bb.max.Y for bb in label) <= opening.max.Y + LABEL_TAB_WIDTH
        assert min(bb.min.X for bb in label) >= opening.min.X
        assert max(bb.max.X for bb in label) <= opening.max.X
