# threedpy

Generate gridfinity bins and socket/tool storage blocks with [build123d](https://github.com/gumyr/build123d).

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/), which also installs Python
3.12 if it's missing.

```sh
# create .venv and install dependencies + threedpy itself (editable)
uv sync
```

`uv run <command>` runs a command in the venv, syncing it first if `pyproject.toml` or `uv.lock`
changed. To activate the venv in your current shell instead (so `uv run` can be dropped from the
commands below):

```sh
source .venv/bin/activate
```

Add dependencies with `uv add <package>` (`uv add --dev <package>` for dev tools), which updates
`pyproject.toml` and `uv.lock` together.

Slot labels are drawn in IBM Plex Mono Bold, bundled in `src/threedpy/fonts/` (licensed under the SIL
Open Font License; see `src/threedpy/fonts/OFL.txt`).

### Linting and formatting

[ruff](https://docs.astral.sh/ruff/) is a dev dependency, configured in `pyproject.toml`
(100-column lines, single quotes):

```sh
uv run ruff check src
uv run ruff format src
```

## Usage

### IPython (recommended)

The modules are split into cells with `# %%` markers. Running them cell by cell in an IPython
session keeps models in memory between runs, so you can tweak and rebuild a part without
re-running everything, and inspect intermediate objects as you go.

```sh
uv run ipython
```

Send cells to the session from your editor (e.g. vim-ipython-cell / vim-slime, or VS Code's
Interactive Window), or load them by hand with `%load` / `%run`. Turning on autoreload picks
up edits to `storage.py` / `util.py` without restarting the session:

```python
%load_ext autoreload
%autoreload 2
```

Calling `show(part)` sends a model to the [yacv](https://github.com/yeicor-3d/yet-another-cad-viewer)
viewer at <http://localhost:32323> (set `YACV_PORT` to change the port).

### CLI

```sh
uv run threedpy --help

# storage block laid out and sized by the YAML's "storage_block" mapping
uv run threedpy build src/threedpy/examples/husky-sockets-vert-mm.yaml -o block.stl

# override the YAML's layout type and size
uv run threedpy build input.yaml -t positional -x 2 -y 3 -z 3 -o block.stl

# test fitments for a 12.95mm diameter, 7mm deep slot at several scales
uv run threedpy scale-test 12.95 7 -o tests/ -s 1.01 1.02 1.03
```

`-t`, `-x`/`-y`/`-z` (gridfinity units) and `-n` override the YAML's storage block settings. `--arrange`
swaps the (slow) gridfinity base for a plain box while you arrange slots, and `--no-show` skips
the yacv preview.

### Storage block YAML

```yaml
storage_block:
    name: 'my-block'
    type: 'rowed'
    font_size: 6.0
    x: 2
    y: 3
    z: 3
    global:
        shape: 'round_vert'
rows:
    - slots:
        - {diameter: 14.2, depth: 14.0, label: '10'}
```

`storage_block` sets the name, layout, size and slot defaults of the storage block. `type` is
`rowed` (rows evenly spaced along Y, slots evenly spaced along X; the default) or `positional` (each
slot at its own `x`/`y`). `font_size` is the default label size; rows and slots can set their own.
Give each dimension in gridfinity units (`x`, `y`, `z`) or in mm (`x_mm`, `y_mm`, `z_mm`), not both.
Dimensions are built as given unless `round_to_gfu_x`, `round_to_gfu_y` or `round_to_gfu_z` is
`true`, which rounds that dimension up to whole units (42mm for X/Y, 7mm for Z); `round_to_gfu_all`
sets all three. The gridfinity base needs whole X/Y units, so otherwise a plain box is built. The
name defaults to the filename.

`global` keys are defaults for every slot, row-level keys are defaults for that row's slots, and
values on a slot override both. A top-level `slots` list can be used instead of `rows` for a
single row. Quote labels that look like numbers (`'10'`), or YAML reads them as numbers.
