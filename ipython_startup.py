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
