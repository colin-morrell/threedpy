import logging

"""
Suppress debug logging messages from asyncio, build123d, yacv_server.

By default, they add a lot of noise to ipython output. Suppressing them allows us to better
see our own debug logging.
"""

# third-party loggers inherit DEBUG from the root logger (set in 10-logging-colors.py)
for name in ('yacv_server', 'build123d', 'asyncio'):
    logging.getLogger(name).setLevel(logging.WARNING)

# print only DEBUG records, i.e. threedpy's own debug output
logging.getLogger().handlers[0].addFilter(lambda record: record.levelno == logging.DEBUG)

"""
Re-import threedpy from scratch after any of its files change.

autoreload patches classes in place, which can't apply dataclass field changes (dataclass builds
__init__ and the field list once). Dropping threedpy from sys.modules makes the next import rebuild
everything. Other modules (e.g. yacv_server and its running server) are left alone.
"""

import os
import sys

from IPython import get_ipython

THREEDPY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'threedpy')


def _threedpy_mtime() -> float:
    return max(
        os.path.getmtime(os.path.join(THREEDPY_DIR, f))
        for f in os.listdir(THREEDPY_DIR) if f.endswith('.py')
    )


_threedpy_loaded = [_threedpy_mtime()]


def _reimport_changed_threedpy(*_) -> None:
    latest = _threedpy_mtime()
    if latest > _threedpy_loaded[0]:
        for name in [n for n in sys.modules if n == 'threedpy' or n.startswith('threedpy.')]:
            del sys.modules[name]
        _threedpy_loaded[0] = latest


get_ipython().events.register('pre_run_cell', _reimport_changed_threedpy)
