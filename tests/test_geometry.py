"""
Tier 1 geometry tests: items, slots, scoops, labels and layout, with small solids only.

Nothing here builds a gridfinity base; slots are cut into a plain box whose top sits at Z=0.
"""

import logging
import math
from dataclasses import dataclass

import pytest
from build123d import Align, Axis, Box, BuildPart, Mode, Part, Plane

from threedpy.defaults import SLOT_DEPTH_CLEARANCE, SLOT_DIAMETER_CLEARANCE
from threedpy.features import Label, LabelType, Slot, BlockScoop, BlockScoopType
from threedpy.io import load_storage_block
from threedpy.item import (
    CylinderItem,
    Drive,
    Item,
    Orientation,
    Rotation,
    Shape,
    SocketExtension,
)
from threedpy.storage import StorageBin

# surface block the slots are cut into: top face at Z=0
SURFACE = (60.0, 60.0, 20.0)


@dataclass
class Brick(Item):
    """Test item: 10 wide (X), 30 deep (Y, from the origin towards +Y), 5 tall (Z)."""

    def _build(self) -> Part:
        return Box(10, 30, 5, align=(Align.CENTER, Align.MIN, Align.MIN))


def bounds(part) -> tuple[float, ...]:
    bb = part.bounding_box()
    return (bb.min.X, bb.max.X, bb.min.Y, bb.max.Y, bb.min.Z, bb.max.Z)


def surface() -> Box:
    return Box(*SURFACE, align=(Align.CENTER, Align.CENTER, Align.MAX))


def surface_volume() -> float:
    return math.prod(SURFACE)


def cut_into_surface(slot: Slot) -> BuildPart:
    with BuildPart() as part:
        surface()
        slot.build(surface_z=0.0)
    return part


# --- items


class TestOrientedItem:
    @pytest.mark.parametrize(('rotation', 'expected'), [
        ('up', (-5, 5, 0, 30, 0, 5)),
        ('down', (-5, 5, -30, 0, 0, 5)),
        ('left', (-30, 0, -5, 5, 0, 5)),
        ('right', (0, 30, -5, 5, 0, 5)),
    ])
    def test_vertical_rotation_turns_its_plus_y_side(self, rotation, expected):
        part = Brick(orientation='vertical', rotation=rotation).oriented()
        assert bounds(part) == pytest.approx(expected, abs=1e-6)

    @pytest.mark.parametrize(('rotation', 'expected'), [
        ('up', (-5, 5, 0, 5, -30, 0)),
        ('down', (-5, 5, -5, 0, -30, 0)),
        ('left', (-5, 0, -5, 5, -30, 0)),
        ('right', (0, 5, -5, 5, -30, 0)),
    ])
    def test_horizontal_rotation_turns_its_top(self, rotation, expected):
        # lying down, its 5mm height points the rotation's way and its +Y side faces down (-Z)
        part = Brick(orientation='horizontal', rotation=rotation).oriented()
        assert bounds(part) == pytest.approx(expected, abs=1e-6)

    def test_rotation_defaults_to_up(self):
        assert Brick().rotation is Rotation.UP
        assert Brick(orientation='horizontal').rotation is Rotation.UP

    def test_yaml_strings_become_enums(self):
        item = Brick(orientation='horizontal', rotation='left')
        assert item.orientation is Orientation.HORIZONTAL
        assert item.rotation is Rotation.LEFT

    def test_building_inside_an_active_builder_does_not_add_to_it(self):
        with BuildPart() as part:
            Box(10, 10, 10)
            Brick().oriented()
            CylinderItem(diameter=5, depth=40).oriented()
        assert part.part.volume == pytest.approx(1000)


class TestItemDimensions:
    def test_cylinder_includes_its_clearances(self):
        item = CylinderItem(diameter=10, depth=40)
        size = item.oriented().bounding_box().size
        assert size.X == pytest.approx(10 + SLOT_DIAMETER_CLEARANCE)
        assert size.Z == pytest.approx(40 + SLOT_DEPTH_CLEARANCE)

    def test_cylinder_needs_diameter_and_depth(self):
        with pytest.raises(ValueError, match='diameter.*depth'):
            CylinderItem(diameter=10)

    def test_socket_extension_size(self):
        item = SocketExtension(drive='1/4', total_length=50.7)
        size = item.oriented().bounding_box().size
        assert size.X == pytest.approx(12.3 + SLOT_DIAMETER_CLEARANCE, abs=1e-4)
        assert size.Z == pytest.approx(50.7 + SLOT_DEPTH_CLEARANCE, abs=1e-4)

    def test_socket_extension_needs_total_length(self):
        with pytest.raises(ValueError, match='total_length'):
            SocketExtension(drive='1/4')

    def test_socket_extension_needs_a_drive(self):
        with pytest.raises(ValueError, match='drive not specified'):
            SocketExtension(total_length=50.7)

    def test_three_eighths_drive_uses_its_dimensions(self):
        item = SocketExtension(drive='3/8', total_length=76.3)
        expected = Drive.THREE_EIGHTHS.dimensions['bot_rad'] + SLOT_DIAMETER_CLEARANCE / 2
        assert item.bot_rad == pytest.approx(expected)

    def test_drive_fills_only_unset_dimensions(self):
        item = SocketExtension(drive='1/4', total_length=50.7, bot_len=20)
        assert item.drive is Drive.QUARTER_INCH
        assert item.bot_len == 20
        assert item.top_len == Drive.QUARTER_INCH.dimensions['top_len']

    def test_socket_extension_square_end_corners_sit_on_the_shaft(self):
        item = SocketExtension(drive='1/4', total_length=50.7)
        part = item.oriented()
        # section through the square end, below its top fillet
        z = item.total_length - item.top_len / 2
        section = part.intersect(Plane.XY.offset(z) * Box(30, 30, 0.001))
        reach = max(
            math.hypot(p.X, p.Y) for edge in section.edges() for p in edge.positions([0, 0.5, 1])
        )
        assert reach == pytest.approx(item.mid_rad, abs=1e-3)


# --- slots


class TestSlotMeasurements:
    def test_vertical_cylinder(self):
        slot = Slot(shape='cylinder', item=CylinderItem(diameter=10, depth=8))
        assert slot.x_footprint == pytest.approx(10 + SLOT_DIAMETER_CLEARANCE)
        assert slot.y_footprint == pytest.approx(10 + SLOT_DIAMETER_CLEARANCE)
        assert slot.z == pytest.approx(8 + SLOT_DEPTH_CLEARANCE)

    def test_vertical_cylinder_debug_sinks_halfway(self):
        slot = Slot(shape='cylinder', item=CylinderItem(diameter=10, depth=8), debug=True)
        assert slot.z == pytest.approx((8 + SLOT_DEPTH_CLEARANCE) / 2)

    def test_horizontal_cylinder(self):
        item = CylinderItem(diameter=10, depth=40, orientation='horizontal')
        slot = Slot(shape='cylinder', item=item)
        assert slot.x_footprint == pytest.approx(10 + SLOT_DIAMETER_CLEARANCE)
        assert slot.y_footprint == pytest.approx(40 + SLOT_DEPTH_CLEARANCE)
        assert slot.z == pytest.approx((10 + SLOT_DIAMETER_CLEARANCE) / 2)

    def test_horizontal_z_offset_sinks_further(self):
        item = CylinderItem(diameter=10, depth=40, orientation='horizontal')
        slot = Slot(shape='cylinder', item=item, z_offset=2)
        assert slot.z == pytest.approx((10 + SLOT_DIAMETER_CLEARANCE) / 2 + 2)

    def test_prism_rect(self):
        slot = Slot(shape='prism_rect', width=10, length=20, depth=5)
        assert (slot.x_footprint, slot.y_footprint) == (10, 20)
        assert slot.z == pytest.approx(5 + SLOT_DEPTH_CLEARANCE)

    @pytest.mark.parametrize(('rotation', 'expected'), [
        ('up', 0), ('down', 0), ('left', 90), ('right', 90),
    ])
    def test_scoops_turn_with_the_item(self, rotation, expected):
        item = SocketExtension(drive='1/4', total_length=50.7, orientation='horizontal',
                               rotation=rotation)
        assert Slot(shape='socket_extension', item=item).scoop_rotation == expected

    @pytest.mark.parametrize('rotation', ['up', 'right'])
    def test_scoop_width_is_the_shaft_either_way(self, rotation):
        item = SocketExtension(drive='1/4', total_length=50.7, orientation='horizontal',
                               rotation=rotation)
        slot = Slot(shape='socket_extension', item=item)
        assert slot.scoop_width == pytest.approx(2 * item.mid_rad, abs=1e-3)

    def test_item_solid_is_centered_with_its_bottom_at_zero(self):
        item = CylinderItem(diameter=10, depth=40, orientation='horizontal')
        slot = Slot(shape='cylinder', item=item)
        bb = slot.item_solid.bounding_box()
        assert (bb.center().X, bb.center().Y, bb.min.Z) == pytest.approx((0, 0, 0), abs=1e-6)

    def test_shape_is_required(self):
        with pytest.raises(ValueError, match='no shape'):
            Slot()

    def test_item_shape_needs_its_item(self):
        with pytest.raises(ValueError, match='needs a CylinderItem'):
            Slot(shape='cylinder')

    def test_prism_takes_no_item(self):
        with pytest.raises(ValueError, match='takes no item'):
            Slot(shape=Shape.PRISM_RECT, item=CylinderItem(diameter=10, depth=5))


class TestSlotBuild:
    def test_horizontal_item_is_cut_halfway_at_its_x_y(self):
        item = CylinderItem(diameter=10, depth=40, orientation='horizontal')
        slot = Slot(shape='cylinder', item=item, x=5, y=-3)
        part = cut_into_surface(slot).part
        assert surface_volume() - part.volume == pytest.approx(slot.item_solid.volume / 2, rel=1e-4)
        cut = surface() - part
        bb = cut.bounding_box()
        assert (bb.center().X, bb.center().Y, bb.max.Z) == pytest.approx((5, -3, 0), abs=1e-4)

    def test_vertical_item_is_cut_fully_below_the_surface(self):
        slot = Slot(shape='cylinder', item=CylinderItem(diameter=10, depth=8))
        part = cut_into_surface(slot).part
        assert surface_volume() - part.volume == pytest.approx(slot.item_solid.volume, rel=1e-4)
        bb = (surface() - part).bounding_box()
        assert (bb.min.Z, bb.max.Z) == pytest.approx((-slot.z, 0), abs=1e-4)

    def test_debug_adds_the_solid_half_above_the_surface(self):
        slot = Slot(shape='cylinder', item=CylinderItem(diameter=10, depth=8), debug=True)
        part = cut_into_surface(slot).part
        assert part.volume - surface_volume() == pytest.approx(slot.item_solid.volume / 2, rel=1e-4)

    @pytest.mark.xfail(strict=True, reason="PRISM_RECT's box isn't scaled (TODO in Slot.build), "
                       'so its top sits SLOT_DEPTH_CLEARANCE below the surface')
    def test_prism_rect_is_cut_from_the_surface(self):
        slot = Slot(shape='prism_rect', width=10, length=20, depth=5)
        bb = (surface() - cut_into_surface(slot).part).bounding_box()
        assert bb.max.Z == pytest.approx(0, abs=1e-4)


# --- scoops and labels


class TestBlockScoop:
    def scoop(self, **kwargs) -> BlockScoop:
        dims = {'flat_width': 10, 'wall_width': 5, 'depth': 4, 'length': 20, 'fillet_radius': 2.5}
        return BlockScoop(**{**dims, 'type': BlockScoopType.SLOT, **kwargs})

    def test_size_comes_from_its_fields(self):
        with BuildPart() as part:
            self.scoop().build(Mode.ADD)
        assert bounds(part.part) == pytest.approx((-10, 10, -10, 10, -4, 0), abs=1e-6)

    def test_rotation_turns_it_about_z(self):
        with BuildPart() as part:
            self.scoop(length=30).build(Mode.ADD, rotation=90)
        assert bounds(part.part) == pytest.approx((-15, 15, -10, 10, -4, 0), abs=1e-6)

    def test_width(self):
        assert self.scoop().width == 20

    def test_width_needs_flat_and_wall_width(self):
        with pytest.raises(ValueError, match='width'):
            _ = self.scoop(wall_width=0).width

    def test_type_none_raises(self):
        with pytest.raises(ValueError, match='NONE'):
            self.scoop(type=BlockScoopType.NONE).build()

    def test_unset_dimension_raises(self):
        with pytest.raises(ValueError, match='unset dimension.*depth'):
            self.scoop(depth=0).build()

    def test_fill_unset_fills_only_zeros(self):
        scoop = self.scoop(depth=0, length=0)
        scoop.fill_unset(BlockScoop(flat_width=99, wall_width=99, depth=7, length=30))
        assert (scoop.flat_width, scoop.wall_width, scoop.depth, scoop.length) == (10, 5, 7, 30)


class TestManualScoop:
    def build(self, scoops):
        data = {
            'storage_block': {'x': 2, 'y': 3, 'z': 3, 'manual_scoops': scoops},
            'slots': [{'shape': 'cylinder', 'diameter': 10, 'depth': 5}],
        }
        return load_storage_block(data).build(arrange=True).part

    def test_cut_at_its_position_and_rotation(self):
        plain = self.build([])
        spec = {'x': 20, 'y': 35, 'rotation': 90, 'length': 30, 'flat_width': 10, 'depth': 4}
        cut = (plain - self.build([spec])).bounding_box()
        # rim fillets widen the cut by up to fillet_radius on each side
        assert (cut.center().X, cut.center().Y) == pytest.approx((20, 35), abs=1e-3)
        # turned 90: length along X, width (10 + 2 x 7.5 walls) along Y
        assert 30 <= cut.size.X <= 30 + 2 * 2.5 + 1e-3
        assert 25 <= cut.size.Y <= 25 + 2 * 2.5 + 1e-3
        assert cut.min.Z == pytest.approx(3 * 7 - 4, abs=1e-3)

    def test_past_the_block_edge_raises(self):
        with pytest.raises(ValueError, match='scoop 1 .* extends past the block'):
            self.build([{'x': 30, 'y': 0, 'rotation': 45}])


class TestLabel:
    def emboss(self, label: Label) -> BuildPart:
        with BuildPart() as part:
            surface()
            label.build(part.faces().sort_by(Axis.Z)[-1], (5, 0))
        return part

    def test_embossed_1mm_at_its_coordinates(self):
        part = self.emboss(Label(label_text='A', type=LabelType.SLOT)).part
        assert part.bounding_box().max.Z == pytest.approx(1)
        raised = part - surface()
        assert raised.bounding_box().center().X == pytest.approx(5, abs=0.5)

    @pytest.mark.parametrize('label', [
        Label(label_text='A', type=LabelType.NONE),
        Label(label_text='', type=LabelType.SLOT),
    ])
    def test_no_label_or_empty_text_adds_nothing(self, label):
        assert self.emboss(label).part.volume == pytest.approx(surface_volume())

    def test_alignment_needs_a_label_type(self):
        with pytest.raises(ValueError, match='NONE'):
            _ = Label().alignment


# --- layout and validation, no building


def block(rows, x=2, y=2):
    data = {
        'storage_block': {'x': x, 'y': y, 'z': 3, 'global': {'shape': 'cylinder', 'depth': 5}},
        'rows': [{'slots': [{'diameter': d} for d in diameters]} for diameters in rows],
    }
    return load_storage_block(data)


class TestLayout:
    def test_slots_are_evenly_spaced_left_to_right(self):
        b = block([[10, 14, 12]])
        b.x_align_slots()
        row = next(iter(b.rows))
        edges = [-b.x_mm / 2]
        for slot in row:
            edges += [slot.x - slot.x_footprint / 2, slot.x + slot.x_footprint / 2]
        edges.append(b.x_mm / 2)
        gaps = [right - left for left, right in zip(edges[::2], edges[1::2])]
        assert gaps == pytest.approx([row.x_slot_spacing] * 4)

    def test_rows_are_evenly_spaced_top_to_bottom(self):
        b = block([[10], [20], [14]])
        b.y_align_rows()
        rows = list(b.rows)
        assert [row.y for row in rows] == sorted((row.y for row in rows), reverse=True)
        top = b.y_mm / 2 - (rows[0].y + rows[0].y_max_slot / 2)
        assert top == pytest.approx(b.y_row_spacing)
        assert all(slot.y == row.y for row in rows for slot in row)

    def test_slot_spacing_needs_the_row_width(self):
        with pytest.raises(ValueError, match='row.width'):
            _ = next(iter(block([[10]]).rows)).x_slot_spacing

    def test_too_wide_a_row_fails_validation(self):
        with pytest.raises(ValueError, match='exceeds block width'):
            block([[20] * 3], x=1).validate_x_bounds()

    def test_too_many_rows_fail_validation(self):
        with pytest.raises(ValueError, match='exceeds block height'):
            block([[20]] * 3, y=1).validate_y_bounds()

    def test_tight_slot_spacing_warns(self, caplog):
        b = block([[20] * 3], x=2)
        b.x_align_slots()
        with caplog.at_level(logging.WARNING):
            b.validate_x_spacing()
        assert 'x_slot_spacing' in caplog.text


class TestBinValidation:
    def labeled(self, label_type=LabelType.BIN) -> Label:
        return Label(label_text='M3', type=label_type)

    def test_partial_gfu_raises(self):
        with pytest.raises(ValueError, match='x must be whole GFU'):
            StorageBin(x=1.5, y=1, z=4, label=self.labeled()).validate_gfu()

    def test_label_tab_needs_z_of_3(self):
        with pytest.raises(ValueError, match='label tab requires'):
            StorageBin(x=1, y=1, z=2, label=self.labeled()).validate_label_z()

    def test_scoop_radius_falls_back_to_the_compartment_depth(self, caplog):
        b = StorageBin(x=1, y=1, z=3, label=self.labeled(), scoop_radius=15)
        with caplog.at_level(logging.WARNING):
            b.validate_scoop_radius()
        # 7 * z - 2.5 (top) - 5.3 (floor) - 0.1
        assert b.scoop_radius == pytest.approx(13.1)
        assert 'falling back' in caplog.text

    def test_scoop_radius_kept_when_it_fits(self):
        b = StorageBin(x=1, y=1, z=4, label=self.labeled(), scoop_radius=15)
        b.validate_scoop_radius()
        assert b.scoop_radius == 15
