"""
Reading YAML: config.yaml, and storage block / bin configs into their objects.
"""

import logging
import os
from dataclasses import fields
from typing import Any

import yaml
from threedpy.constants import (
    CONFIG_PATH,
    GFU_GRID,
    GFU_GRID_NOMINAL,
    GFU_HEIGHT,
    STORAGE_BIN_KEYS,
    STORAGE_BLOCK_KEYS,
)
from threedpy.features import Label, LabelMode, Slot, SlotScoop, SlotScoopMode
from threedpy.item import ITEM_TYPES, Item, Shape
from threedpy.storage import RoundAxis, Row, StorageBin, StorageBlock, StorageBlockType
from threedpy.util import DoublyLinkedList

logger = logging.getLogger(__name__)


def load_config() -> dict[str, Any]:
    """Read config.yaml fresh on each call -> edits apply without re-import."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _gfu_from_config(
        data: dict[str, Any],
        axis: str,
        nominal_mm: float,
        built_mm: float,
        round_up: bool
    ) -> float | None:
    """Read one storage block dimension in GFU, given as either '<axis>' (GFU) or '<axis>_mm'.

    If round_up, mm values convert using the nominal unit size (StorageBlock rounds them up.)
    Otherwise they convert using the built unit size, so <axis>_mm is drawn exactly as given.
    """

    gfu, mm = data.get(axis), data.get(axis + '_mm')
    if gfu is not None and mm is not None:
        raise ValueError(f'[!] storage_block: give {axis} or {axis}_mm, not both')
    if mm is not None:
        gfu = mm / (nominal_mm if round_up else built_mm)
        logger.info(f'storage_block: {axis}_mm={mm} -> {axis}={gfu}')
    return gfu


def _round_axes(spec: Any) -> RoundAxis:
    """The 'round_to_gfu' YAML value ('all', 'x', or a list like ['x', 'y']) as a RoundAxis."""
    flags = RoundAxis.NONE
    for name in [spec] if isinstance(spec, str) else (spec or []):
        try:
            flags |= RoundAxis[str(name).upper()]
        except KeyError:
            raise ValueError(f"[!] storage_block: round_to_gfu: unknown axis '{name}'") from None
    return flags


def load_storage_block(
        data: dict[str, Any],
        name: str = '',
        block_type: StorageBlockType | str | None = None,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
        debug: bool = False,
        no_labels: bool = False
    ) -> StorageBlock:
    """Build a StorageBlock and its Rows from a parsed YAML config."""

    block_data = data.get('storage_block', {})
    unknown = set(block_data) - set(STORAGE_BLOCK_KEYS)
    if unknown:
        raise ValueError('[!] storage_block: unknown key(s): {}'.format(', '.join(sorted(unknown))))

    round_to_gfu = _round_axes(block_data.get('round_to_gfu'))
    dims = {
        axis: _gfu_from_config(block_data, axis, nominal, built, flag in round_to_gfu)
        for axis, nominal, built, flag in (
            ('x', GFU_GRID_NOMINAL, GFU_GRID, RoundAxis.X),
            ('y', GFU_GRID_NOMINAL, GFU_GRID, RoundAxis.Y),
            ('z', GFU_HEIGHT, GFU_HEIGHT, RoundAxis.Z)
        )
    }
    for axis, override in (('x', x), ('y', y), ('z', z)):
        if override is not None:
            dims[axis] = override

    block = StorageBlock(
        debug=debug,
        no_labels=no_labels,
        name=name or block_data.get('name', ''),
        type=StorageBlockType(block_type or block_data.get('type', StorageBlockType.ROWED)),
        font_size=block_data.get('font_size', StorageBlock.font_size),
        x=float(dims['x'] or 0.0),
        y=float(dims['y'] or 0.0),
        z=float(dims['z'] or 0.0),
        round_to_gfu=round_to_gfu
    )
    for row in load_rows(data, font_size=block.font_size):
        if no_labels:
            # after loading, so no row/slot 'labels' setting can turn them back on
            row.label.mode = LabelMode.NO_LABEL
            for slot in row:
                slot.label.mode = LabelMode.NO_LABEL
        block.add_row(row)
    return block


def load_storage_block_from_path(
        path: str | os.PathLike[str],
        name: str = '',
        block_type: StorageBlockType | str | None = None,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
        debug: bool = False,
        no_labels: bool = False
    ) -> StorageBlock:
    """Build StorageBlock from YAML config. Name defaults to filename if not set in config."""
    logger.info(f'loading storage block from {path}')
    with open(path) as f:
        block = load_storage_block(
            yaml.safe_load(f),
            name=name,
            block_type=block_type,
            x=x,
            y=y,
            z=z,
            debug=debug,
            no_labels=no_labels
        )
    if not block.name:
        block.name = os.path.splitext(os.path.basename(path))[0]
    return block


def load_storage_bin(
        data: dict[str, Any],
        name: str = '',
        font_size: float = 6.0,
        x: int | None = None,
        y: int | None = None,
        z: int | None = None,
        debug: bool = False,
        no_labels: bool = False
    ) -> StorageBin:
    """Build a StorageBin from a parsed YAML config."""

    unknown = set(data) - {'storage_bin'}
    if unknown:
        raise ValueError('[!] unknown top-level key(s) with storage_bin: {}'
                         .format(', '.join(sorted(unknown))))
    bin_data = data.get('storage_bin') or {}
    unknown = set(bin_data) - set(STORAGE_BIN_KEYS)
    if unknown:
        raise ValueError('[!] storage_bin: unknown key(s): {}'.format(', '.join(sorted(unknown))))

    dims = {
        axis: bin_data.get(axis) if override is None else override
        for axis, override in (('x', x), ('y', y), ('z', z))
    }
    label = Label(
        font_size=bin_data.get('font_size', font_size),
        label_text=str(bin_data.get('label', '')),
        mode=LabelMode.NO_LABEL if no_labels else LabelMode.BIN_LABEL
    )
    return StorageBin(
        debug=debug,
        name=name,
        label=label,
        x=dims['x'] or 0,
        y=dims['y'] or 0,
        z=dims['z'] or 0
    )


def load_from_path(
        path: str | os.PathLike[str],
        name: str = '',
        block_type: StorageBlockType | str | None = None,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
        debug: bool = False,
        no_labels: bool = False
    ) -> StorageBin | StorageBlock:
    """Build a StorageBin or StorageBlock from YAML config, picked by its top-level keys. Name
    defaults to filename if not set in config.
    """
    logger.info(f'loading {path}')
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    part: StorageBin | StorageBlock
    if 'storage_bin' in data:
        part = load_storage_bin(data, name=name, x=x, y=y, z=z, debug=debug, no_labels=no_labels)
    else:
        part = load_storage_block(
            data,
            name=name,
            block_type=block_type,
            x=x,
            y=y,
            z=z,
            debug=debug,
            no_labels=no_labels
        )
    if not part.name:
        part.name = os.path.splitext(os.path.basename(path))[0]
    return part


def _slot_scoop(slot: Slot, spec: Any, owner: str) -> SlotScoop:
    """A slot's scoop from its 'slot_scoop' YAML value: false/missing -> none, true -> the slot's
    default, a mapping -> the default with those dimensions overridden.
    """
    if not spec:
        return SlotScoop()
    SlotScoop.check_keys(spec, owner)
    scoop = slot.default_scoop()
    for key, value in (spec if isinstance(spec, dict) else {}).items():
        setattr(scoop, key, value)
    return scoop


def _row_scoop(row: Row, spec: Any) -> SlotScoop:
    """A row's scoop from its 'row_scoop' YAML value: false/missing -> none, true -> defaults, a
    mapping -> those dimensions overridden.

    depth/length come from the row's slots now so validation can run before the build;
    flat_width/wall_width need the slot layout and are filled in at build time (Row.build_scoop.)
    """
    if not spec:
        return SlotScoop()
    SlotScoop.check_keys(spec, f"row '{row.name}'")
    scoop = SlotScoop(
        depth=max((slot.x_footprint / 2 for slot in row.slots), default=0.0),
        length=row.y_max_slot / 2,
        mode=SlotScoopMode.ROW_SCOOP
    )
    for key, value in (spec if isinstance(spec, dict) else {}).items():
        setattr(scoop, key, value)
    return scoop


def _slot_item(shape: Shape, config: dict[str, Any], owner: str) -> Item:
    """The Item an item shape builds, from (and popping) the merged config keys that are fields
    of its class, e.g. diameter and orientation for a cylinder.
    """
    cls = ITEM_TYPES[shape]
    spec = {f.name: config.pop(f.name) for f in fields(cls) if f.name in config}
    try:
        return cls(**spec)
    except ValueError as e:
        raise ValueError(f"[!] {owner}: {str(e).removeprefix('[!] ')}") from None


def _slot_from_config(config: dict[str, Any]) -> Slot:
    """Build a Slot from its merged config, turning label text (e.g. '6' or 6) into a Label,
    'slot_scoop' into a SlotScoop and an item shape's keys into its Item.
    """
    config = dict(config)
    scoop_spec = config.pop('slot_scoop', False)
    owner = f"slot '{config.get('label')}'"
    if 'shape' not in config:
        raise ValueError(f'[!] {owner}: no shape; set one at the global, row or slot level')
    try:
        shape = Shape(config['shape'])
    except ValueError:
        known = ', '.join(s.value for s in Shape)
        raise ValueError(f"[!] {owner}: unknown shape '{config['shape']}' ({known})") from None
    config['shape'] = shape
    slot_keys = {f.name for f in fields(Slot)}
    item_keys = {f.name for cls in ITEM_TYPES.values() for f in fields(cls)}
    unknown = set(config) - slot_keys - item_keys - {'labels'}
    if unknown:
        raise ValueError('[!] {}: unknown key(s): {}'.format(owner, ', '.join(sorted(unknown))))
    if shape in ITEM_TYPES:
        config['item'] = _slot_item(shape, config, owner)
    # labels: false (global/row/slot) turns labels off; otherwise label text gives a SLOT_LABEL
    show_labels = config.pop('labels', None) is not False
    label = config.get('label')
    if not isinstance(label, Label):
        text = '' if label is None else str(label)
        mode = LabelMode.SLOT_LABEL if text and show_labels else LabelMode.NO_LABEL
        config['label'] = Label(label_text=text, font_size=config['font_size'], mode=mode)
    # other item shapes' keys, e.g. a global 'orientation' on a prism_rect slot
    for key in set(config) - slot_keys:
        config.pop(key)
    slot = Slot(**config)
    slot.scoop = _slot_scoop(slot, scoop_spec, f"slot '{label}'")
    return slot


def load_rows(data: dict[str, Any], font_size: float = 6.0) -> list[Row]:
    """Build Rows from a parsed YAML config.

    --> Slots are grouped under 'rows', each with its own 'slots' list and an
        optional 'name'; a top-level 'slots' list is loaded as a single row.
    --> 'storage_block' 'global' keys (e.g. shape, slot_scoop) are defaults for every slot
    --> Other row-level keys are defaults for that row's slots
    --> Values set on an individual slot override both.
    --> 'slot_scoop' (global/row/slot): true, a mapping of SlotScoop dimensions, or false to opt out.
    --> 'row_scoop' (global/row): true or a mapping; one scoop across the row, shared by all its
        slots in place of their own scoops.
    --> 'shape' (global/row/slot): required; an item shape (e.g. cylinder, socket_extension) is
        configured by the slot's keys that are fields of its Item (e.g. diameter, orientation).
    --> 'label' (slot): text for the slot's own label; 'row_label' (row): text for one label
        centered under the row, shared by its slots in place of their own; 'labels: false'
        (global/row/slot) turns labels off.
    --> font_size is the default label size (e.g. the storage block's); each row reserves space
        for its largest label.
    """

    unknown = set(data) - {'storage_bin', 'storage_block', 'rows', 'slots'}
    if unknown:
        raise ValueError('[!] unknown top-level key(s): {} (slot defaults go in storage_block.global)'
                         .format(', '.join(sorted(unknown))))
    defaults = {'font_size': font_size, **data.get('storage_block', {}).get('global', {})}
    # row_scoop is a row setting, so it isn't passed down to slots
    default_row_scoop = defaults.pop('row_scoop', False)
    rows_data = data['rows'] if 'rows' in data else [{'slots': data['slots']}]
    rows = []
    for row_data in rows_data:
        row_defaults = {
            key: value for key, value in row_data.items()
            if key not in ('name', 'slots', 'row_scoop', 'row_label')
        }
        slots = [
            _slot_from_config({**defaults, **row_defaults, **slot}) for slot in row_data['slots']
        ]
        row = Row(
            font_size=max((slot.font_size for slot in slots), default=defaults['font_size']),
            name=row_data.get('name', ''),
            slots=DoublyLinkedList(slots)
        )
        row_label = row_data.get('row_label')
        if row_label is not None and row_defaults.get('labels', defaults.get('labels')) is not False:
            row.label = Label(
                label_text=str(row_label), font_size=row.font_size, mode=LabelMode.ROW_LABEL
            )
        if row.has_row_label:
            replaced = [slot for slot in slots if slot.draws_label]
            if replaced:
                logger.warning(f"row '{row.name}': row_label replaces {len(replaced)} slot label(s)")
            # share one Label, like a row scoop
            for slot in slots:
                slot.label = row.label
        row.scoop = _row_scoop(row, row_data.get('row_scoop', default_row_scoop))
        if row.has_row_scoop:
            explicit = [slot for slot, raw in zip(slots, row_data['slots']) if raw.get('slot_scoop')]
            if explicit:
                logger.warning(f"row '{row.name}': row_scoop replaces {len(explicit)} slot_scoop(s)")
            # share one SlotScoop so build-time filling reaches every slot
            for slot in slots:
                slot.scoop = row.scoop
        rows.append(row)
    return rows
