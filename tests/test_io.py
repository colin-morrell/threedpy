"""
Loader tests: YAML-shaped dicts (and files) into StorageBlock / StorageBin objects, via io.py.

No geometry is built beyond the small item solids slots measure for their footprints.
"""

import logging

import pytest
from build123d import Box, BuildPart

from threedpy.constants import GFU_GRID
from threedpy.defaults import (
    BLOCK_SCOOP_DEPTH_RATIO,
    BLOCK_SCOOP_FLAT_WIDTH,
    BLOCK_SCOOP_LENGTH,
    BLOCK_SCOOP_WALL_WIDTH,
    SLOT_DEPTH_CLEARANCE,
    SLOT_DIAMETER_CLEARANCE,
)
from threedpy.features import BlockScoopType, LabelType
from threedpy.io import export_as_stl, load_from_path, load_storage_bin, load_storage_block
from threedpy.item import CylinderItem, Orientation, Rotation, Shape, SocketExtension
from threedpy.storage import RoundAxis, StorageBin, StorageBlock, StorageBlockType

# a vertical cylinder slot, the simplest valid slot
SLOT = {'shape': 'cylinder', 'diameter': 10, 'depth': 5}


def block(slots=None, rows=None, **storage_block):
    """Load a StorageBlock from slots (one row) or rows; storage_block keys default to 2x2x3."""
    data = {'storage_block': {'x': 2, 'y': 2, 'z': 3, **storage_block}}
    data.update({'rows': rows} if rows is not None else {'slots': slots or [dict(SLOT)]})
    return load_storage_block(data)


def first_slot(storage_block):
    return next(iter(next(iter(storage_block.rows))))


def all_slots(storage_block):
    return [slot for row in storage_block.rows for slot in row]


# --- storage_block


class TestStorageBlock:
    def test_dimensions_in_gfu(self):
        b = block(x=3, y=2, z=4)
        assert (b.x, b.y, b.z) == (3, 2, 4)

    def test_dimensions_in_mm_use_the_built_unit_size(self):
        b = block(x=None, x_mm=2 * GFU_GRID)
        assert b.x == pytest.approx(2)

    def test_mm_rounded_to_gfu_rounds_up(self):
        b = block(x=None, x_mm=50, round_to_gfu='x')
        assert b.x == 2

    def test_axis_and_mm_together_raise(self):
        with pytest.raises(ValueError, match='give x or x_mm, not both'):
            block(x_mm=84)

    @pytest.mark.parametrize(('spec', 'expected'), [
        (None, RoundAxis.NONE),
        ('x', RoundAxis.X),
        (['x', 'z'], RoundAxis.X | RoundAxis.Z),
        ('all', RoundAxis.ALL),
    ])
    def test_round_to_gfu_forms(self, spec, expected):
        assert block(round_to_gfu=spec).round_to_gfu == expected

    def test_round_to_gfu_unknown_axis_raises(self):
        with pytest.raises(ValueError, match="unknown axis 'w'"):
            block(round_to_gfu=['w'])

    def test_overrides_beat_the_config(self):
        data = {'storage_block': {'x': 2, 'y': 2, 'z': 3}, 'slots': [dict(SLOT)]}
        b = load_storage_block(data, x=4, z=5, block_type='positional', name='cli')
        assert (b.x, b.y, b.z) == (4, 2, 5)
        assert b.type is StorageBlockType.POSITIONAL
        assert b.name == 'cli'

    def test_type_defaults_to_rowed(self):
        assert block().type is StorageBlockType.ROWED

    def test_unknown_storage_block_key_raises(self):
        with pytest.raises(ValueError, match='storage_block: unknown key'):
            block(colour='red')

    def test_unknown_top_level_key_raises(self):
        data = {'storage_block': {'x': 2, 'y': 2, 'z': 3}, 'slots': [dict(SLOT)], 'global': {}}
        with pytest.raises(ValueError, match='unknown top-level key'):
            load_storage_block(data)

    def test_top_level_slots_load_as_one_row(self):
        b = block(slots=[dict(SLOT), dict(SLOT)])
        assert len(b.rows) == 1
        assert len(all_slots(b)) == 2


# --- slot shapes and item keys


class TestSlotShape:
    def test_missing_shape_raises(self):
        with pytest.raises(ValueError, match='no shape'):
            block(slots=[{'diameter': 10, 'depth': 5, 'label': 'A'}])

    def test_unknown_shape_lists_the_valid_ones(self):
        with pytest.raises(ValueError, match="unknown shape 'round_vert'.*cylinder"):
            block(slots=[{**SLOT, 'shape': 'round_vert'}])

    def test_typo_key_is_reported_as_unknown(self):
        slot = {'shape': 'cylinder', 'diameter': 10, 'depht': 5, 'label': 'A'}
        with pytest.raises(ValueError, match="slot 'A': unknown key.*depht"):
            block(slots=[slot])

    def test_item_errors_name_the_slot(self):
        with pytest.raises(ValueError, match="slot 'A'.*diameter.*depth"):
            block(slots=[{'shape': 'cylinder', 'diameter': 10, 'label': 'A'}])

    def test_cylinder_keys_build_its_item(self):
        slot = first_slot(block(slots=[{**SLOT, 'orientation': 'horizontal'}]))
        assert slot.shape is Shape.CYLINDER
        assert isinstance(slot.item, CylinderItem)
        assert slot.item.orientation is Orientation.HORIZONTAL
        assert slot.item.rotation is Rotation.UP
        assert slot.item.diameter == pytest.approx(10 + SLOT_DIAMETER_CLEARANCE)
        assert slot.item.depth == pytest.approx(5 + SLOT_DEPTH_CLEARANCE)

    def test_socket_extension_keys_build_its_item(self):
        slot = {
            'shape': 'socket_extension', 'drive': '1/4', 'total_length': 50.7, 'rotation': 'down'
        }
        item = first_slot(block(slots=[slot])).item
        assert isinstance(item, SocketExtension)
        assert item.rotation is Rotation.DOWN
        assert item.total_length == pytest.approx(50.7 + SLOT_DEPTH_CLEARANCE)

    def test_defaults_cascade_global_row_slot(self):
        b = block(
            rows=[{'diameter': 12, 'slots': [{}, {'diameter': 14}]}],
            **{'global': {'shape': 'cylinder', 'diameter': 10, 'depth': 5}},
        )
        diameters = [slot.item.diameter - SLOT_DIAMETER_CLEARANCE for slot in all_slots(b)]
        assert diameters == pytest.approx([12, 14])

    def test_other_shapes_keys_are_dropped(self):
        prism = {'shape': 'prism_rect', 'width': 10, 'length': 20, 'depth': 5}
        slot = first_slot(block(slots=[prism], **{'global': {'orientation': 'horizontal'}}))
        assert slot.shape is Shape.PRISM_RECT
        assert slot.item is None


# --- labels


class TestLabels:
    def test_slot_label_text(self):
        slot = first_slot(block(slots=[{**SLOT, 'label': 10}]))
        assert slot.label.type is LabelType.SLOT
        assert slot.label.label_text == '10'

    def test_no_label_text_means_no_label(self):
        assert first_slot(block()).label.type is LabelType.NONE

    def test_labels_false_turns_them_off(self):
        slot = first_slot(block(slots=[{**SLOT, 'label': 'A', 'labels': False}]))
        assert slot.label.type is LabelType.NONE

    def test_row_label_is_shared_by_its_slots(self, caplog):
        rows = [{'row_label': 'R', 'slots': [{**SLOT, 'label': 'A'}, dict(SLOT)]}]
        with caplog.at_level(logging.WARNING):
            b = block(rows=rows)
        row = next(iter(b.rows))
        assert row.label.type is LabelType.ROW
        assert all(slot.label is row.label for slot in row)
        assert 'row_label replaces 1 slot label' in caplog.text

    def test_no_labels_overrides_row_and_slot_labels(self):
        data = {
            'storage_block': {'x': 2, 'y': 2, 'z': 3},
            'rows': [{'row_label': 'R', 'slots': [{**SLOT, 'label': 'A'}]}],
        }
        b = load_storage_block(data, no_labels=True)
        row = next(iter(b.rows))
        assert row.label.type is LabelType.NONE
        assert all(slot.label.type is LabelType.NONE for slot in row)


# --- scoops


class TestScoops:
    def test_no_slot_scoop_by_default(self):
        assert first_slot(block()).scoop.type is BlockScoopType.NONE

    def test_slot_scoop_true_uses_the_slot_default(self):
        slot = first_slot(block(slots=[{**SLOT, 'slot_scoop': True}]))
        assert slot.scoop.type is BlockScoopType.SLOT
        assert slot.scoop.flat_width == pytest.approx(slot.x_footprint)
        assert slot.scoop.depth == pytest.approx(slot.x_footprint / 2)
        assert slot.scoop.wall_width == BLOCK_SCOOP_WALL_WIDTH
        assert slot.scoop.length == BLOCK_SCOOP_LENGTH

    def test_slot_scoop_mapping_overrides_dimensions(self):
        slot = first_slot(block(slots=[{**SLOT, 'slot_scoop': {'length': 15}}]))
        assert slot.scoop.type is BlockScoopType.SLOT
        assert slot.scoop.length == 15

    def test_max_depth_flag_loads(self):
        slot = first_slot(block(slots=[{**SLOT, 'slot_scoop': {'max_depth': True}}]))
        assert slot.scoop.max_depth is True
        rows = [{'row_scoop': {'max_depth': True}, 'slots': [dict(SLOT)]}]
        row = next(iter(block(rows=rows).rows))
        assert row.scoop.max_depth is True
        assert block(manual_scoops=[{'max_depth': True}]).manual_scoops[0].max_depth is True

    @pytest.mark.parametrize('spec', [
        {'slots': [{**SLOT, 'slot_scoop': {'depth': 4, 'max_depth': True}}]},
        {'rows': [{'row_scoop': {'depth': 4, 'max_depth': True}, 'slots': [dict(SLOT)]}]},
        {'manual_scoops': [{'depth': 4, 'max_depth': True}]},
    ], ids=['slot', 'row', 'manual'])
    def test_depth_and_max_depth_together_raise(self, spec):
        with pytest.raises(ValueError, match='give depth or max_depth, not both'):
            block(**spec)

    def test_max_width_flag_loads_for_row_and_manual_scoops(self):
        rows = [{'row_scoop': {'max_width': True}, 'slots': [dict(SLOT)]}]
        assert next(iter(block(rows=rows).rows)).scoop.max_width is True
        assert block(manual_scoops=[{'max_width': True}]).manual_scoops[0].max_width is True

    def test_max_width_on_a_slot_scoop_raises(self):
        with pytest.raises(ValueError, match="max_width isn't supported for slot scoops"):
            block(slots=[{**SLOT, 'slot_scoop': {'max_width': True}}])

    @pytest.mark.parametrize('spec', [
        {'rows': [{'row_scoop': {'wall_width': 4, 'max_width': True}, 'slots': [dict(SLOT)]}]},
        {'manual_scoops': [{'wall_width': 4, 'max_width': True}]},
    ], ids=['row', 'manual'])
    def test_wall_width_and_max_width_together_raise(self, spec):
        with pytest.raises(ValueError, match='give wall_width or max_width, not both'):
            block(**spec)

    def test_unknown_scoop_key_raises(self):
        with pytest.raises(ValueError, match='scoop: unknown key.*lenght'):
            block(slots=[{**SLOT, 'slot_scoop': {'lenght': 15}}])

    def test_row_scoop_is_shared_and_replaces_slot_scoops(self, caplog):
        rows = [{'row_scoop': True, 'slots': [{**SLOT, 'slot_scoop': True}, dict(SLOT)]}]
        with caplog.at_level(logging.WARNING):
            b = block(rows=rows)
        row = next(iter(b.rows))
        assert row.scoop.type is BlockScoopType.ROW
        assert all(slot.scoop is row.scoop for slot in row)
        assert 'row_scoop replaces 1 slot_scoop' in caplog.text

    def test_row_scoop_over_left_right_slots_raises(self):
        with pytest.raises(ValueError, match="row_scoop doesn't support left/right"):
            block(rows=[{'row_scoop': True, 'slots': [{**SLOT, 'rotation': 'right',
                                                        'orientation': 'horizontal'}]}])

    def test_global_row_scoop_applies_to_every_row(self):
        rows = [{'slots': [dict(SLOT)]}, {'slots': [dict(SLOT)]}]
        b = block(rows=rows, **{'global': {'row_scoop': True}})
        assert all(row.scoop.type is BlockScoopType.ROW for row in b.rows)


# --- manual scoops


class TestManualScoops:
    def test_defaults(self):
        scoop = block(manual_scoops=[{'x': 10, 'y': -5}]).manual_scoops[0]
        assert scoop.type is BlockScoopType.MANUAL
        assert (scoop.x, scoop.y, scoop.rotation) == (10, -5, 0)
        assert scoop.flat_width == BLOCK_SCOOP_FLAT_WIDTH
        assert scoop.depth == BLOCK_SCOOP_FLAT_WIDTH * BLOCK_SCOOP_DEPTH_RATIO
        assert (scoop.wall_width, scoop.length) == (BLOCK_SCOOP_WALL_WIDTH, BLOCK_SCOOP_LENGTH)

    def test_given_values(self):
        spec = {'x': 1, 'y': 2, 'rotation': 90, 'length': 30, 'flat_width': 8, 'depth': 3}
        scoop = block(manual_scoops=[spec]).manual_scoops[0]
        assert (scoop.rotation, scoop.length, scoop.flat_width, scoop.depth) == (90, 30, 8, 3)

    def test_depth_defaults_to_half_the_given_flat_width(self):
        assert block(manual_scoops=[{'flat_width': 12}]).manual_scoops[0].depth == 6

    def test_no_scoops_by_default(self):
        assert block().manual_scoops == []

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match='scoop 1 scoop: unknown key.*rotate'):
            block(manual_scoops=[{'x': 0, 'rotate': 90}])

    def test_must_be_a_list_of_mappings(self):
        with pytest.raises(ValueError, match='manual_scoops must be a list of mappings'):
            block(manual_scoops={'x': 0})

    def test_slot_scoops_take_no_position(self):
        with pytest.raises(ValueError, match='scoop: unknown key.*x'):
            block(slots=[{**SLOT, 'slot_scoop': {'x': 5}}])


# --- storage_bin


class TestStorageBin:
    def test_dimensions_label_and_font_size(self):
        data = {'storage_bin': {'x': 2, 'y': 1, 'z': 4, 'font_size': 8.0, 'label': 'M3'}}
        b = load_storage_bin(data)
        assert (b.x, b.y, b.z) == (2, 1, 4)
        assert b.label.label_text == 'M3'
        assert b.label.font_size == 8.0
        assert b.label.type is LabelType.BIN

    def test_no_labels(self):
        data = {'storage_bin': {'x': 1, 'y': 1, 'z': 4, 'label': 'M3'}}
        b = load_storage_bin(data, no_labels=True)
        assert b.label.type is LabelType.NONE

    def test_overrides_beat_the_config(self):
        b = load_storage_bin({'storage_bin': {'x': 1, 'y': 1, 'z': 4}}, y=2, z=5)
        assert (b.x, b.y, b.z) == (1, 2, 5)

    def test_unknown_bin_key_raises(self):
        with pytest.raises(ValueError, match='storage_bin: unknown key'):
            load_storage_bin({'storage_bin': {'x': 1, 'y': 1, 'z': 4, 'colour': 'red'}})

    def test_other_top_level_keys_raise(self):
        with pytest.raises(ValueError, match='unknown top-level key'):
            load_storage_bin({'storage_bin': {'x': 1, 'y': 1, 'z': 4}, 'slots': []})


# --- files


class TestLoadFromPath:
    def test_picks_a_bin_by_its_top_level_key(self, tmp_path):
        path = tmp_path / 'm3-bin.yaml'
        path.write_text("storage_bin:\n    x: 1\n    y: 1\n    z: 4\n")
        b = load_from_path(path)
        assert isinstance(b, StorageBin)
        assert b.name == 'm3-bin'

    def test_loads_a_block_otherwise(self, tmp_path):
        path = tmp_path / 'sockets.yaml'
        path.write_text(
            "storage_block:\n    x: 2\n    y: 2\n    z: 3\n"
            "slots:\n    - {shape: 'cylinder', diameter: 10, depth: 5}\n"
        )
        b = load_from_path(path)
        assert isinstance(b, StorageBlock)
        assert b.name == 'sockets'

    def test_config_name_beats_the_file_name(self, tmp_path):
        path = tmp_path / 'sockets.yaml'
        path.write_text(
            "storage_block:\n    name: 'mine'\n    x: 2\n    y: 2\n    z: 3\n"
            "slots:\n    - {shape: 'cylinder', diameter: 10, depth: 5}\n"
        )
        assert load_from_path(path).name == 'mine'


# --- STL export


@pytest.fixture
def small_part():
    with BuildPart() as part:
        Box(10, 10, 10)
    return part


class TestExportAsStl:
    def test_writes_the_file(self, tmp_path, small_part):
        path = tmp_path / 'cube.stl'
        export_as_stl(small_part, path)
        assert path.stat().st_size > 0

    def test_overwriting_warns(self, tmp_path, small_part, caplog):
        path = tmp_path / 'cube.stl'
        export_as_stl(small_part, path)
        with caplog.at_level(logging.WARNING):
            export_as_stl(small_part, path)
        assert 'overwriting' in caplog.text

    @pytest.mark.parametrize(('name', 'error', 'match'), [
        ('', ValueError, 'empty'),
        ('.', ValueError, 'is a directory'),
        ('cube.step', ValueError, 'must end in .stl'),
        ('missing/cube.stl', FileNotFoundError, 'does not exist'),
    ], ids=['empty', 'directory', 'extension', 'missing parent'])
    def test_bad_paths_raise(self, tmp_path, small_part, name, error, match):
        path = str(tmp_path / name) if name else ''
        with pytest.raises(error, match=match):
            export_as_stl(small_part, path)
