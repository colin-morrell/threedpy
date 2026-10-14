"""
Tier 2 build tests: every tests/*.yaml block built in arrange mode (plain box, no gridfinity base).

Volumes and solid counts are compared against tests/snapshots/arrange.json; after an intended
geometry change, rerun with --update-snapshots and review the JSON diff.
"""

from pathlib import Path

import pytest

from threedpy.io import load_from_path, load_storage_block

TESTS_DIR = Path(__file__).parent
CONFIGS = sorted(TESTS_DIR.glob('*.yaml'))
# OCCT volumes vary slightly between versions; real geometry changes are far bigger
VOLUME_TOLERANCE = 1e-5


@pytest.fixture(scope='module')
def built():
    """Build each config once, however many tests check it: path -> (block, part)."""
    cache = {}

    def build(path):
        if path not in cache:
            block = load_from_path(path)
            cache[path] = (block, block.build(arrange=True).part)
        return cache[path]

    return build


@pytest.mark.parametrize('path', CONFIGS, ids=lambda path: path.stem)
class TestArrangeBuild:
    def test_one_valid_solid(self, path, built):
        _, part = built(path)
        assert part.is_valid
        assert len(part.solids()) == 1

    def test_top_is_the_surface_plus_labels(self, path, built):
        block, part = built(path)
        has_labels = any(row.has_labels for row in block.rows)
        expected = block.z_mm + (1 if has_labels and not block.no_labels else 0)
        assert part.bounding_box().max.Z == pytest.approx(expected, abs=1e-4)

    def test_matches_snapshot(self, path, built, snapshots):
        _, part = built(path)
        data, update = snapshots
        actual = {'volume': round(part.volume, 3), 'solids': len(part.solids())}
        if update:
            data[path.name] = actual
            return
        assert path.name in data, f'no snapshot for {path.name}; run with --update-snapshots'
        assert actual['solids'] == data[path.name]['solids']
        assert actual['volume'] == pytest.approx(data[path.name]['volume'], rel=VOLUME_TOLERANCE)


@pytest.mark.xfail(strict=True, reason='validate_x_spacing() reads row.x_slot_spacing, which '
                   'raises for positional rows: only rowed layout sets row.width')
def test_positional_block_builds():
    data = {
        'storage_block': {
            'type': 'positional', 'x': 2, 'y': 2, 'z': 3,
            'global': {'shape': 'cylinder', 'depth': 5},
        },
        'slots': [{'diameter': 10, 'x': -15, 'y': 10}, {'diameter': 14, 'x': 12, 'y': -8}],
    }
    part = load_storage_block(data).build(arrange=True).part
    assert part.is_valid
    assert len(part.solids()) == 1
