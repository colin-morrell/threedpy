import json
from pathlib import Path

import pytest

SNAPSHOT_PATH = Path(__file__).parent / 'snapshots' / 'arrange.json'


def pytest_addoption(parser):
    parser.addoption(
        '--update-snapshots',
        action='store_true',
        help='record built volumes/solid counts as the new snapshot instead of comparing them',
    )


@pytest.fixture(scope='session')
def snapshots(request):
    """Snapshot values by config name: compared against, or recorded with --update-snapshots."""
    data = json.loads(SNAPSHOT_PATH.read_text()) if SNAPSHOT_PATH.exists() else {}
    update = request.config.getoption('--update-snapshots')
    yield data, update
    if update:
        SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(data, indent=4, sort_keys=True) + '\n')
