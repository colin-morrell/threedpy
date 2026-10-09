import argparse
import logging
import os
import sys

from build123d import (
    Align,
    Axis,
    BuildPart,
    BuildSketch,
    Location,
    Locations,
    Mode,
    Text,
    extrude,
)
from yacv_server import show

from threedpy.constants import FONT_PATH, PREVIEW_GAP
from threedpy.storage import (
    StorageBlock,
    StorageBlockType,
    load_config,
    load_storage_block_from_path,
)
from threedpy.util import build_gf_bin, build_gf_box, export_as_stl

# yacv preview colors from config.yaml; unset keys fall back to yacv's defaults
# re-read on every %run since this module is re-executed but threedpy.storage isn't
CONFIG = load_config()
SHOW_KWARGS = {key: CONFIG[key] for key in ('color_faces', 'color_edges') if CONFIG.get(key)}

logger = logging.getLogger(__name__)

# %%


def labeled_bins(txts: list):

    for l in txts:
        _bin = labeled_bin(l)
        filename = l.split()[0]
        export_path = f'/mnt/e/3dp/gf/bins/custom/bolts/{filename}.stl'
        export_as_stl(_bin, export_path)


def labeled_bin(x: int, y: int, z: int, txt: str):

    with BuildPart() as gf_bin:
        _bin = build_gf_bin(1, 1, 5)
        top_face = gf_bin.faces().sort_by(Axis.Z)[-1]

        label_x: int = 0
        label_y: int = 0

        with BuildSketch(top_face), Locations((label_x, label_y, 0)):
            Text(txt,
                 font_size=6,
                 font_path=FONT_PATH,
                 align=(Align.CENTER, Align.MIN),
                 rotation=0
                 )

        extrude(amount=1, mode=Mode.ADD)
        show(gf_bin, **SHOW_KWARGS)

        return gf_bin


def build_work_surface(block: StorageBlock, arrange: bool = False) -> None:
    """ Build the block's body: a gridfinity box, or a plain box if arranging or X/Y aren't whole
    GFU (gridfinity bases only come in whole units.)"""
    if not arrange and block.is_gridfinity:
        build_gf_box(int(block.x_gfu), int(block.y_gfu), block.z_gfu)
        return
    if not arrange:
        logger.warning(f'x/y ({block.x_gfu} x {block.y_gfu} GFU) not whole units: building a plain box, no gridfinity base'
                        )
    with Locations((0,0,0)):
        block.build_test_surface(rowed_storage_block)


def positional_storage_block(block: StorageBlock, arrange: bool=False):
    """ Generate a gridfinity box with manually-specified positions for each slot.

    --> Does not currently support labels.
    --> arrange: skips time-expensive call to build gridfinity base, good for fine-tuning
    """

    # TODO --> bounds checks

    block.log_storage_block_creation()

    with BuildPart() as part:
        build_work_surface(block, arrange=arrange)

        # TODO --> test meh
        top_face = part.faces().sort_by(Axis.Z)[-1]
        block.build(labels=False, top_face=top_face)

    return part


def rowed_storage_block(
        block: StorageBlock,
        arrange: bool = False,
        y_row_offset: float = 0.0
    ):
    """ Generate a gridfinity socket (etc) storage block with equally spaced rows of slots and
        optional corresponding labels.

    --> arrange: for fine-tuning arrangement of the slots. skips time-expensive call to build
        gridfinity base.
    --> labels: embossed below (-Y) each slot unless its labels setting is False.
    """

    if (block.x_gfu == 0 or block.y_gfu == 0 or block.z_gfu == 0):
        raise ValueError('[!] x/y/z must be > 0')

    block.log_storage_block_creation()

    with BuildPart() as part:
        build_work_surface(block, arrange=arrange)

        # determine each row's Y-position
        block.y_align_rows()

        # per row, determine each slot's X-position
        block.x_align_slots()

        # face of working surface on which label text will (optionally) be drawn + extruded
        top_face = part.faces().sort_by(Axis.Z)[-1]
        block.build(top_face=top_face)

    return part


def generate_storage_block(block: StorageBlock, arrange: bool = False):
    """ Generate a storage block using the layout given by its type.

    --> labels: only applies to rowed storage blocks (positional doesn't support labels yet.)
    """
    if block.type == StorageBlockType.POSITIONAL:
        return positional_storage_block(block, arrange=arrange)
    return rowed_storage_block(block, arrange=arrange)


def storage_block_from_args(args: argparse.Namespace, in_path: str) -> StorageBlock:
    """Build a StorageBlock from the input YAML, with any type/x/y/z given on the command
    line overriding the YAML's 'storage_block' settings."""
    block = load_storage_block_from_path(
        in_path,
        block_type=args.type,
        x=args.x,
        y=args.y,
        z=args.z,
        debug=args.draw_solids,
        labels=False if args.no_labels else None
    )
    missing = [axis for axis in ('x', 'y', 'z') if not getattr(block, axis)]
    if missing:
        sys.exit('[!] {}: no {} dimension(s) in the YAML "storage_block" mapping or on the command line'
                 .format(in_path, '/'.join(missing)))
    return block


def block_names(in_paths: list[str]) -> list[str]:
    """yacv object and STL names: each input's file name minus its extension."""
    names = [os.path.splitext(os.path.basename(path))[0] for path in in_paths]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        # yacv would replace one with the other, and their STLs would overwrite each other
        sys.exit('[!] input files share a name: {}'.format(', '.join(duplicates)))
    return names


def show_in_column(parts: list, names: list[str]) -> None:
    """Show the parts in a column along Y (first in front) in one call, so auto_clear
    (default) removes everything shown earlier."""
    shown, y = [], 0.0
    for part in parts:
        bb = part.part.bounding_box()
        # moved copies for the preview; exports stay at the origin
        shown.append(part.part.moved(Location((0, y - bb.min.Y, 0))))
        y += bb.size.Y + PREVIEW_GAP
    show(*shown, names=names, **SHOW_KWARGS)


def export_parts(parts: list, names: list[str], out_dir: str) -> None:
    """Export each part to <out_dir>/<name>.stl."""
    os.makedirs(out_dir, exist_ok=True)
    for part, name in zip(parts, names):
        export_as_stl(part, os.path.abspath(os.path.join(out_dir, name + '.stl')))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate gridfinity storage blocks and fitment tests.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    build = subparsers.add_parser(
        'build',
        help='storage block laid out by its YAML config (rowed or positional)'
    )
    build.add_argument(
        'in_paths', nargs='+', metavar='PATH',
        help='slot/row YAML file(s); several are built and shown in a column'
    )
    build.add_argument(
        '-t', '--type',
        choices=[block_type.value for block_type in StorageBlockType],
        help='slot layout (overrides YAML; default: rowed)'
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
    build.add_argument(
        '--draw-solids',
        action='store_true',
        help='draw slots as solids raised above the surface, plus row markers'
    )
    build.add_argument('--debug', action='store_true', help='show DEBUG log messages')
    build.add_argument(
        '--no-labels',
        action='store_true',
        help='skip embossed slot labels, except rows/slots that set labels: true (rowed only)'
    )

    scale = subparsers.add_parser('scale-test', help='test fitments for a diameter at several scales')
    scale.add_argument('diameter', type=float, help='slot diameter (mm)')
    scale.add_argument('depth', type=float, help='slot depth (mm)')
    scale.add_argument(
        '-o', '--out',
        dest='out_path',
        metavar='DIR',
        required=True,
        help='directory to export STLs into'
    )
    scale.add_argument(
        '-s', '--scales',
        type=float,
        nargs='+',
        default=[1.01, 1.02, 1.03],
        help='scale factors to test (default: 1.01 1.02 1.03)'
    )
    scale.add_argument('--no-show', action='store_true', help='skip the yacv preview')

    return parser.parse_args(argv)


def configure_logging(debug: bool) -> None:
    """Show threedpy's INFO and above, plus DEBUG with --debug. Other libraries stay at WARNING."""
    # CLI runs have no log handler yet; 3dipy's startup scripts already add one
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING)
    level = logging.DEBUG if debug else logging.INFO
    # '__main__' is generate.py itself when run directly or with %run
    for name in ('threedpy', '__main__'):
        logging.getLogger(name).setLevel(level)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(getattr(args, 'debug', False))

    """
    if args.command == 'scale-test':
        os.makedirs(args.out_path, exist_ok=True)
        scale_test(args.diameter, args.depth, args.out_path, args.scales, preview=not args.no_show)
        return
    """

    names = block_names(args.in_paths)
    blocks = [storage_block_from_args(args, path) for path in args.in_paths]
    parts = [generate_storage_block(block, arrange=args.arrange) for block in blocks]

    if not args.no_show:
        show_in_column(parts, names)
    if args.out:
        out_dir = CONFIG.get('out_dir')
        if not out_dir:
            sys.exit('[!] -o needs out_dir set in config.yaml')
        export_parts(parts, names, out_dir)

# %%

if __name__ == '__main__':
    main()
