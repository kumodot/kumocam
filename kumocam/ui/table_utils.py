"""Shared table helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt


def apply_check_to_selection(table, items, source_row: int, new_state: bool,
                             guard=None) -> None:
    """When the user toggles a checkbox on a row that is part of a Ctrl/Shift
    multi-row selection, apply the same check state to every selected row.

    `items` are the backing objects with a `selected` attribute, indexed by
    table row. Signals are blocked while updating so the itemChanged handler
    does not re-enter.
    """
    sel_model = table.selectionModel()
    if sel_model is None:
        return
    sel_rows = {index.row() for index in sel_model.selectedRows()}
    if source_row not in sel_rows or len(sel_rows) < 2:
        return

    table.blockSignals(True)
    try:
        for row in sel_rows:
            if 0 <= row < len(items):
                items[row].selected = new_state
                cell = table.item(row, 0)
                if cell is not None:
                    cell.setCheckState(Qt.Checked if new_state else Qt.Unchecked)
    finally:
        table.blockSignals(False)
