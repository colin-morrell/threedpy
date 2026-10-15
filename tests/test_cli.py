"""
CLI tests for cli.py: argument parsing, names, overrides, preview layout and STL export.

yacv's show() is replaced with a recorder, and config.yaml's out_dir with a temp directory, so no
viewer is driven and nothing is written outside pytest's tmp_path.
"""

import pytest

from threedpy import cli
from threedpy.defaults import PREVIEW_GAP

BLOCK_YAML = """\
storage_block:
    x: 1
    y: 1
    z: 2
slots:
    - {shape: 'cylinder', diameter: 10, depth: 5}
"""


def write_block(directory, name='block', text=BLOCK_YAML):
    path = directory / f'{name}.yaml'
    path.write_text(text)
    return str(path)


@pytest.fixture
def shown(monkeypatch):
    """Record show() calls as (parts, names) instead of sending them to yacv."""
    calls = []
    monkeypatch.setattr(cli, 'show', lambda *parts, names, **_: calls.append((parts, names)))
    return calls


@pytest.fixture
def out_dir(monkeypatch, tmp_path):
    out = tmp_path / 'out'
    monkeypatch.setattr(cli, 'CONFIG', {'out_dir': str(out)})
    return out


class TestParseArgs:
    def test_defaults(self):
        args = cli.parse_args(['build', 'a.yaml'])
        assert args.command == 'build'
        assert args.in_paths == ['a.yaml']
        assert (args.type, args.x, args.y, args.z) == (None, None, None, None)
        assert not (args.out or args.arrange or args.no_show or args.row or args.column)

    def test_overrides_are_typed(self):
        args = cli.parse_args(['build', 'a.yaml', '-t', 'positional', '-x', '3', '-z', '2.5'])
        assert args.type == 'positional'
        assert args.x == 3
        assert args.z == 2.5

    @pytest.mark.parametrize('argv', [
        [],
        ['build'],
        ['build', 'a.yaml', '--row', '--column'],
        ['build', 'a.yaml', '-t', 'diagonal'],
        ['build', 'a.yaml', '-x', '1.5'],
    ], ids=['no command', 'no path', 'row and column', 'bad type', 'partial x'])
    def test_bad_arguments_exit(self, argv):
        with pytest.raises(SystemExit):
            cli.parse_args(argv)


class TestBlockNames:
    def test_names_are_file_names_without_extensions(self):
        assert cli.block_names(['a/one.yaml', 'b/two.yml']) == ['one', 'two']

    def test_duplicate_names_raise(self):
        with pytest.raises(ValueError, match='duplicate file names'):
            cli.block_names(['a/one.yaml', 'b/one.yaml'])


class TestPartFromArgs:
    def test_cli_overrides_reach_the_loader(self, tmp_path):
        args = cli.parse_args(['build', 'x.yaml', '-x', '2', '--no-labels'])
        part = cli.part_from_args(args, write_block(tmp_path))
        assert (part.x, part.y, part.z) == (2, 1, 2)
        assert part.no_labels

    def test_missing_dimensions_raise(self, tmp_path):
        path = write_block(tmp_path, text=BLOCK_YAML.replace('    z: 2\n', ''))
        args = cli.parse_args(['build', path])
        with pytest.raises(ValueError, match='missing z dimension'):
            cli.part_from_args(args, path)


class TestMain:
    def test_shows_every_part_once_named_by_file(self, tmp_path, shown):
        paths = [write_block(tmp_path, 'one'), write_block(tmp_path, 'two')]
        cli.main(['build', *paths, '--arrange'])
        assert len(shown) == 1
        parts, names = shown[0]
        assert names == ['one', 'two']
        assert len(parts) == 2

    def test_column_stacks_parts_along_y(self, tmp_path, shown):
        paths = [write_block(tmp_path, 'one'), write_block(tmp_path, 'two')]
        cli.main(['build', *paths, '--arrange'])
        first, second = (part.bounding_box() for part in shown[0][0])
        assert second.min.Y == pytest.approx(first.max.Y + PREVIEW_GAP, abs=1e-4)
        assert second.min.X == pytest.approx(first.min.X, abs=1e-4)

    def test_row_lines_parts_up_along_x(self, tmp_path, shown):
        paths = [write_block(tmp_path, 'one'), write_block(tmp_path, 'two')]
        cli.main(['build', *paths, '--arrange', '--row'])
        first, second = (part.bounding_box() for part in shown[0][0])
        assert second.min.X == pytest.approx(first.max.X + PREVIEW_GAP, abs=1e-4)
        assert second.min.Y == pytest.approx(first.min.Y, abs=1e-4)

    def test_no_show_skips_the_preview(self, tmp_path, shown):
        cli.main(['build', write_block(tmp_path), '--arrange', '--no-show'])
        assert shown == []

    @pytest.mark.usefixtures('shown')
    def test_out_exports_each_part_to_out_dir(self, tmp_path, out_dir):
        paths = [write_block(tmp_path, 'one'), write_block(tmp_path, 'two')]
        cli.main(['build', *paths, '--arrange', '--no-show', '-o'])
        stls = sorted(path.name for path in out_dir.iterdir())
        assert stls == ['one.stl', 'two.stl']
        assert all((out_dir / name).stat().st_size > 0 for name in stls)

    @pytest.mark.usefixtures('shown')
    def test_out_needs_out_dir_in_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, 'CONFIG', {})
        with pytest.raises(SystemExit, match='out_dir'):
            cli.main(['build', write_block(tmp_path), '--arrange', '--no-show', '-o'])

    @pytest.mark.usefixtures('shown')
    def test_duplicate_names_raise_before_building(self, tmp_path, monkeypatch):
        (tmp_path / 'a').mkdir()
        (tmp_path / 'b').mkdir()
        paths = [write_block(tmp_path / 'a'), write_block(tmp_path / 'b')]
        monkeypatch.setattr(cli, 'build_part', lambda *_, **__: pytest.fail('built'))
        with pytest.raises(ValueError, match='duplicate file names'):
            cli.main(['build', *paths, '--arrange'])
