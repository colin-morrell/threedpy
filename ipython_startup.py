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
Re-import threedpy and the test helpers that import it after any of their files change.

autoreload patches classes in place, which can't apply dataclass field changes (dataclass builds
__init__ and the field list once). Dropping the repo's modules from sys.modules makes the next
import rebuild everything. Helpers like tests/render_grid.py must go too, or they keep calling
the old threedpy functions they imported. Other modules (e.g. yacv_server and its server) stay.
"""

import os
import sys

from IPython import get_ipython

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHED_DIRS = [os.path.join(REPO_DIR, 'src', 'threedpy'), os.path.join(REPO_DIR, 'tests')]


def _watched_mtime() -> float:
    return max(
        os.path.getmtime(os.path.join(d, f))
        for d in WATCHED_DIRS for f in os.listdir(d) if f.endswith('.py')
    )


def _is_repo_module(module) -> bool:
    path = getattr(module, '__file__', None) or ''
    return any(os.path.abspath(path).startswith(d + os.sep) for d in WATCHED_DIRS)


_watched_loaded = [_watched_mtime()]


def _reimport_changed_modules(*_) -> None:
    latest = _watched_mtime()
    if latest > _watched_loaded[0]:
        for name in [n for n, m in list(sys.modules.items()) if _is_repo_module(m)]:
            del sys.modules[name]
        _watched_loaded[0] = latest


get_ipython().events.register('pre_run_cell', _reimport_changed_modules)
