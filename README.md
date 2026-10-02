# threedpy

Generate gridfinity bins and socket/tool holders with [build123d](https://github.com/gumyr/build123d).

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
up edits to `holder.py` / `util.py` without restarting the session:

```python
%load_ext autoreload
%autoreload 2
```

Calling `show(part)` sends a model to the [yacv](https://github.com/yeicor-3d/yet-another-cad-viewer)
viewer at <http://localhost:32323> (set `YACV_PORT` to change the port).

### CLI

```sh
poetry run threedpy --help

# holder with evenly spaced rows of slots (x/y/z in gridfinity units)
poetry run threedpy rowed src/threedpy/examples/husky-sockets-vert-mm.json -x 2 -y 3 -z 3 -o holder.stl

# holder with manually positioned slots
poetry run threedpy positional input.json -x 2 -y 3 -z 3 -o holder.stl

# test fitments for a 12.95mm diameter, 7mm deep slot at several scales
poetry run threedpy scale-test 12.95 7 -o tests/ -s 1.01 1.02 1.03
```

`--arrange` swaps the (slow) gridfinity base for a plain box while you arrange slots, and
`--no-show` skips the yacv preview.
