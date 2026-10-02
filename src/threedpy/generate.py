import argparse
import logging
import os
import sys

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Locations,
    Rectangle,
    RegularPolygon,
    Mode,
    Text,
    extrude
)
from gridfinity_build123d import (
    Bin
)
from gridfinity_build123d.constants import gridfinity_standard
from threedpy.constants import FONT_PATH, GFU_GRID, GFU_HEIGHT
from threedpy.holder import (
    Holder,
    Row,
    Shape,
    Slot,
    load_rows_from_path,
    load_slots_from_path
)
from threedpy.util import (
    build_gf_bin,
    build_gf_box,
    export_as_stl
)
from yacv_server import show


# %%


def labeled_bins(txts: list):

    for l in txts:
        _bin = labeled_bin(l)
        filename = l.split()[0]
        export_path = '/mnt/e/3dp/gf/bins/custom/bolts/{}.stl'.format(filename)
        export_as_stl(_bin, export_path)


def labeled_bin(x: int, y: int, z: int, txt: str):

    with BuildPart() as gf_bin:
        _bin = build_gf_bin(1, 1, 5)
        top_face = gf_bin.faces().sort_by(Axis.Z)[-1]

        label_x: int = 0
        label_y: int = 0

        with BuildSketch(top_face) as label:
            with Locations((label_x, label_y, 0)):
                Text(txt,
                     font_size=6,
                     font_path=FONT_PATH,
                     align=(Align.CENTER, Align.MIN),
                     rotation=0
                     )

        extrude(amount=1, mode=Mode.ADD)
        show(gf_bin)

        return gf_bin


def positional_holder(holder: Holder, arrange: bool=False):
    """ Generate a gridfinity box with manually-specified positions for each slot.

    --> Does not currently support labels.
    --> arrange: for fine-tuning arrangement of the slots. skips time-expensive call to build
        gridfinity base. """

    # TODO --> bounds checks

    holder.log_holder_creation()

    with BuildPart() as part:
        # establish our work surface
        if not arrange:
            gf_box = build_gf_box(holder.x_gfu, holder.y_gfu, holder.z_gfu)
        else:
            with Locations((0,0,0)):
                holder.build_test_surface(rowed_holder)

        for slot in holder.slots():
            coords = (
                slot.x,
                slot.y,
                holder.z_mm - slot.z
            )
            with Locations(coords):
                slot.log_slot_creation(coords)
                slot.build_shape()

    return part


def rowed_holder(
        holder: Holder,
        arrange: bool = False,
        font_size: float = 6.0,
        labels: bool = True,
        y_row_offset: float = 0.0
    ):
    """ Generate a gridfinity socket (etc) holder box with equally spaced rows of slots and
        optional corresponding labels.

    --> arrange: for fine-tuning arrangement of the slots. skips time-expensive call to build
        gridfinity base.
    --> labels: whether to emboss slots' labels. defaults to below (-Y) slot.
    """

    # TODO --> support horizontal

    if (holder.x_gfu == 0 or holder.y_gfu == 0 or holder.z_gfu == 0):
        raise ValueError('[!] x/y/z must be > 0')

    with BuildPart() as part:

        # establish work surface
        if not arrange:
            gf_box = build_gf_box(holder.x_gfu, holder.y_gfu, holder.z_gfu)
        else:
            with Locations((0,0,0)):
                holder.build_test_surface(rowed_holder)

        # determine each rows' Y-position
        holder.y_align_rows()

        # determine each slots' X-position (per row)
        holder.x_align_slots()

        # face of working surface on which label text will (optionally) be drawn + extruded
        top_face = part.faces().sort_by(Axis.Z)[-1]

        holder.build_slots(labels=labels, top_face=top_face)

    return part


def scale_test(
        diameter: float,
        depth: float,
        path: str,
        scales: list[float] = [1.01, 1.02, 1.03],
        preview: bool = True,
    ):
    """Generate test fitments for a given diameter using provided scale(s)."""

    width = diameter + 3
    length = width

    for scale in scales:

        scaled_diameter = diameter * scale
        scaled_radius = scaled_diameter / 2

        with BuildPart() as scale_test:
            with BuildSketch() as box:
                with Locations((0, 0, 0)):
                    Rectangle(
                        width,
                        length,
                        align=(Align.CENTER, Align.MIN)
                    )

            extrude(amount=depth)

            faces = scale_test.faces().sort_by(Axis.Z)
            top_face = faces[-1]

            y = 0 - (width / 2)
            with BuildSketch(top_face) as slot:
                with Locations((0, 0, 0)):
                    Circle(
                        radius=scaled_radius,
                        align=(Align.CENTER, Align.CENTER)
                    )
            extrude(amount=-depth, mode=Mode.SUBTRACT)

        if preview:
            show(scale_test)
        str_scale = str(scale).replace('.', '')
        str_diameter = str(diameter)
        filename = 'test-{}-{}.stl'.format(str_scale, str_diameter)
        export_path = os.path.join(path, filename)
        export_as_stl(scale_test, export_path)

    return None


def load_holder(args: argparse.Namespace) -> Holder:
    """Build a Holder from the input JSON and x/y/z dimensions given on the command line."""
    name = args.name or os.path.splitext(os.path.basename(args.in_path))[0]
    holder = Holder(name, x=args.x, y=args.y, z=args.z)
    for row in load_rows_from_path(args.in_path):
        holder.add_row(row)
    return holder


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate gridfinity holders and fitment tests.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # arguments shared by both holder types
    holder_args = argparse.ArgumentParser(add_help=False)
    holder_args.add_argument(
        '-i', '--in',
        dest='in_path',
        metavar='PATH',
        required=True,
        help='path to slot/row JSON file'
    )
    holder_args.add_argument('-x', type=int, required=True, help='width in gridfinity units')
    holder_args.add_argument('-y', type=int, required=True, help='depth in gridfinity units')
    holder_args.add_argument('-z', type=float, required=True, help='height in gridfinity units')
    holder_args.add_argument(
        '-o', '--out',
        dest='out_path',
        metavar='PATH',
        help='STL export path (not exported if omitted)'
    )
    holder_args.add_argument('-n', '--name', help='holder name (default: input filename)')
    holder_args.add_argument(
        '--arrange',
        action='store_true',
        help='use a plain box instead of the (slow) gridfinity base, for arranging slots'
    )
    holder_args.add_argument('--no-show', action='store_true', help='skip the yacv preview')

    subparsers.add_parser(
        'positional',
        parents=[holder_args],
        help='holder with manually positioned slots'
    )

    rowed = subparsers.add_parser(
        'rowed',
        parents=[holder_args],
        help='holder with evenly spaced rows of slots'
    )
    rowed.add_argument('--no-labels', action='store_true', help='skip embossed slot labels')

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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command == 'scale-test':
        os.makedirs(args.out_path, exist_ok=True)
        scale_test(args.diameter, args.depth, args.out_path, args.scales, preview=not args.no_show)
        return

    holder = load_holder(args)
    if args.command == 'positional':
        part = positional_holder(holder, arrange=args.arrange)
    else:
        holder.log_holder_creation()
        part = rowed_holder(holder, arrange=args.arrange, labels=not args.no_labels)

    if not args.no_show:
        show(part)
    if args.out_path:
        export_as_stl(part, args.out_path)

# %%

if __name__ == '__main__':
    main()
