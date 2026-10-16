import argparse
import logging
import os
import sys

from build123d import (
    Location,
)
from yacv_server import show

from threedpy.defaults import PREVIEW_GAP, PREVIEW_VERTICES
from threedpy.io import export_as_stl, load_config, load_from_path
from threedpy.storage import Storage, StorageBlockType

# yacv preview colors from config.yaml; unset keys fall back to yacv's defaults
# re-read on every %run since this module is re-executed but threedpy.io isn't
CONFIG = load_config()
SHOW_KWARGS = {
    'vertices': PREVIEW_VERTICES,
    **{key: CONFIG[key] for key in ('color_faces', 'color_edges') if CONFIG.get(key)}
}

logger = logging.getLogger(__name__)

# %%


def build_part(part: Storage, arrange: bool = False):
    return part.build(arrange)


def part_from_args(args: argparse.Namespace, in_path: str) -> Storage:
    """Build a StorageBin or StorageBlock from the input YAML. CLI args override YAML settings."""
    logger.info('[.] part_from_args()')
    part = load_from_path(
        in_path,
        block_type=args.type,
        x=args.x,
        y=args.y,
        z=args.z,
        debug=args.draw_solids,
        no_labels=args.no_labels
    )
    missing = [axis for axis in ('x', 'y', 'z') if not getattr(part, axis)]
    if missing:
        err = '[!] {}: missing {} dimension(s)'.format(in_path, '/'.join(missing))
        raise ValueError(err)
    return part


def block_names(in_paths: list[str]) -> list[str]:
    """yacv object and STL names: each input's file name minus its extension."""
    names = [os.path.splitext(os.path.basename(path))[0] for path in in_paths]
    unique = set(names)
    if len(names) > len(unique):
        # yacv would replace one with the other, and their STLs would overwrite each other
        err = '[!] input contains duplicate file names:\n\t{}'.format('\n\t'.join(in_paths))
        raise ValueError(err)
    return names


def show_in_column(parts: list, names: list[str]) -> None:
    """Show generated parts in a column (Y). Uses one call so auto_clear refreshes old objects."""
    shown, y = [], 0.0
    for part in parts:
        bb = part.part.bounding_box()
        # moved copies for the preview; exports stay at the origin
        shown.append(part.part.moved(Location((0, y - bb.min.Y, 0))))
        y += bb.size.Y + PREVIEW_GAP
    show(*shown, names=names, **SHOW_KWARGS)


def show_in_row(parts: list, names: list[str]) -> None:
    """Show generated parts in a row (X). Uses one call so auto_clear refreshes old objects."""
    shown, x = [], 0.0
    for part in parts:
        bb = part.part.bounding_box()
        # moved copies for the preview; exports stay at the origin
        shown.append(part.part.moved(Location((x - bb.min.X, 0, 0))))
        x += bb.size.X + PREVIEW_GAP
    show(*shown, names=names, **SHOW_KWARGS)


def export_parts(parts: list, names: list[str], out_dir: str) -> None:
    """Export each part to <out_dir>/<name>.stl."""
    os.makedirs(out_dir, exist_ok=True)
    for part, name in zip(parts, names):
        export_as_stl(part, os.path.abspath(os.path.join(out_dir, name + '.stl')))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Generate gridfinity StorageBlocks and StorageBins.'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    build = subparsers.add_parser(
        'build',
        help='StorageBlock or StorageBin from its YAML config'
    )
    build.add_argument(
        'in_paths', nargs='+', metavar='PATH',
        help='storage_block or storage_bin YAML file(s); several are built and shown in a row'
    )
    build.add_argument(
        '-t', '--type',
        choices=[block_type.value for block_type in StorageBlockType],
        help='storage block slot layout (overrides YAML; default: rowed)'
    )
    build.add_argument('-x', type=int, help='width in gridfinity units (overrides YAML)')
    build.add_argument('-y', type=int, help='depth in gridfinity units (overrides YAML)')
    build.add_argument('-z', type=float, help='height in gridfinity units (overrides YAML)')
    build.add_argument(
        '-o', '--out',
        action='store_true',
        help="export each block to config.yaml's out_dir as <yaml file name>.stl"
    )
    build.add_argument(
        '--arrange',
        action='store_true',
        help='use a plain box instead of the (slow) gridfinity base, for arranging slots'
    )
    build.add_argument('--no-show', action='store_true', help='skip the yacv preview')
    arrangement = build.add_mutually_exclusive_group()
    arrangement.add_argument(
        '--row', action='store_true', help='preview blocks in a row along X (default)'
    )
    arrangement.add_argument(
        '--column', action='store_true', help='preview blocks in a column along Y'
    )
    build.add_argument(
        '--draw-solids',
        action='store_true',
        help='draw slots as solids raised above the surface, plus row markers'
    )
    build.add_argument('--debug', action='store_true', help='show DEBUG log messages')
    build.add_argument(
        '--no-labels',
        action='store_true',
        help='skip embossed labels'
    )

    return parser.parse_args(argv)


def configure_logging(debug: bool) -> None:
    """Show threedpy's INFO and above, plus DEBUG with --debug. Other libraries stay at WARNING."""
    # CLI runs have no log handler yet; 3dipy's startup scripts already add one
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING)
    level = logging.DEBUG if debug else logging.INFO
    # '__main__' is cli.py itself when run directly or with %run
    for name in ('threedpy', '__main__'):
        logging.getLogger(name).setLevel(level)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(getattr(args, 'debug', False))

    logger.info('[.] init')

    names = block_names(args.in_paths)
    storage = [part_from_args(args, path) for path in args.in_paths]
    parts = [build_part(part, arrange=args.arrange) for part in storage]

    if not args.no_show:
        (show_in_column if args.column else show_in_row)(parts, names)
    if args.out:
        out_dir = CONFIG.get('out_dir')
        if not out_dir:
            sys.exit('[!] -o needs out_dir set in config.yaml')
        export_parts(parts, names, out_dir)

    logger.info('[+] done.')

# %%

if __name__ == '__main__':
    main()
