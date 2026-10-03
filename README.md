# threedpy

Generate gridfinity bins and socket/tool storage blocks with [build123d](https://github.com/gumyr/build123d).

## Setup

Requires Python 3.12 and [Poetry](https://python-poetry.org/docs/#installation) 2.x.

```sh
# create the venv with Python 3.12
poetry env use python3.12

# install dependencies + threedpy itself (editable)
poetry install

# confirm which venv is in use
poetry env info --path
```

To activate the venv in your current shell (so `poetry run` can be dropped from the commands
below):

```sh
eval $(poetry env activate)
```

Slot labels are drawn in IBM Plex Mono Bold, bundled in `src/threedpy/fonts/` (licensed under the SIL
Open Font License; see `src/threedpy/fonts/OFL.txt`).

## Usage

### IPython (recommended)

The modules are split into cells with `# %%` markers. Running them cell by cell in an IPython
session keeps models in memory between runs, so you can tweak and rebuild a part without
re-running everything, and inspect intermediate objects as you go.

```sh
poetry run ipython
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
poetry run threedpy --help

# storage block laid out and sized by the JSON's "storage_block" object
poetry run threedpy build src/threedpy/examples/husky-sockets-vert-mm.json -o block.stl

# override the JSON's layout type and size
poetry run threedpy build input.json -t positional -x 2 -y 3 -z 3 -o block.stl

# test fitments for a 12.95mm diameter, 7mm deep slot at several scales
poetry run threedpy scale-test 12.95 7 -o tests/ -s 1.01 1.02 1.03
```

`-t`, `-x`/`-y`/`-z` (gridfinity units) and `-n` override the JSON's storage block settings. `--arrange`
swaps the (slow) gridfinity base for a plain box while you arrange slots, and `--no-show` skips
the yacv preview.

### Storage block JSON

```json
{
    "storage_block": {"name": "my-block", "type": "rowed", "font_size": 6.0, "x": 2, "y": 3, "z": 3},
    "shape": "round",
    "rows": [
        {"slots": [{"label": "10", "diameter": 14.2, "depth": 14.0}]}
    ]
}
```

`storage_block` sets the name, layout and size of the storage block. `type` is `rowed` (rows
evenly spaced along Y, slots evenly spaced along X; the default) or `positional` (each slot at its
own `x`/`y`). `font_size` is the default label size; rows and slots can set their own. Give each
dimension in gridfinity units (`x`, `y`, `z`) or in mm (`x_mm`, `y_mm`, `z_mm`), not both. X/Y in
mm round up to whole units (42mm each); Z in mm is converted to (possibly fractional) 7mm height
units. The name defaults to the filename.

Other top-level keys are defaults for every slot, row-level keys are defaults for that row's slots,
and values on a slot override both. A top-level `slots` list can be used instead of `rows` for a
single row.
