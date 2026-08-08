from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHeaderView,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)

from app.core.models import PixelCondition
from app.core.screen_capture import CapturedPixel


class ConditionTableWidget(QTableWidget):
    changed = Signal()

    OP_COL = 0
    POINTER_COL = 1
    X_COL = 2
    Y_COL = 3
    R_COL = 4
    G_COL = 5
    B_COL = 6
    MATCH_COL = 7
    TOLERANCE_COL = 8
    ID_COL = 9

    HEADERS = [
        "Op",
        "Use Pointer",
        "X",
        "Y",
        "R",
        "G",
        "B",
        "Match Type",
        "Tolerance",
        "Condition ID",
    ]

    def __init__(self) -> None:
        super().__init__(0, len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(self.POINTER_COL, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self.ID_COL, QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)

    def load_conditions(self, expression: list[dict]) -> None:
        self.blockSignals(True)
        self.setRowCount(0)
        next_operator = ""
        for item in expression:
            if "operator" in item:
                next_operator = str(item["operator"]).upper()
                continue
            condition = PixelCondition.from_dict(item)
            self._append_row(condition, next_operator)
            next_operator = "AND"
        self.blockSignals(False)

    def add_condition(self, operator: str = "AND") -> None:
        op = "" if self.rowCount() == 0 else operator.upper()
        self._append_row(PixelCondition(), op)
        self.selectRow(self.rowCount() - 1)
        self.changed.emit()

    def remove_selected_condition(self) -> None:
        row = self.currentRow()
        if row < 0:
            return
        self.removeRow(row)
        if self.rowCount() > 0:
            self._operator_combo(0).setCurrentText("")
        self.changed.emit()

    def selected_condition_id(self) -> str | None:
        row = self.currentRow()
        if row < 0:
            return None
        item = self.item(row, self.ID_COL)
        return item.text() if item else None

    def selected_uses_pointer(self) -> bool:
        row = self.currentRow()
        if row < 0:
            return False
        return self._pointer_checkbox(row).isChecked()

    def apply_capture_to_selected(self, capture: CapturedPixel) -> bool:
        row = self.currentRow()
        if row < 0:
            return False
        if self._pointer_checkbox(row).isChecked():
            self._spin(row, self.X_COL).setValue(0)
            self._spin(row, self.Y_COL).setValue(0)
        else:
            self._spin(row, self.X_COL).setValue(capture.x)
            self._spin(row, self.Y_COL).setValue(capture.y)
        self._spin(row, self.R_COL).setValue(capture.rgb[0])
        self._spin(row, self.G_COL).setValue(capture.rgb[1])
        self._spin(row, self.B_COL).setValue(capture.rgb[2])
        self.changed.emit()
        return True

    def apply_offset_capture_to_selected(
        self,
        reference_x: int,
        reference_y: int,
        capture: CapturedPixel,
    ) -> bool:
        row = self.currentRow()
        if row < 0 or not self._pointer_checkbox(row).isChecked():
            return False
        self._spin(row, self.X_COL).setValue(capture.x - reference_x)
        self._spin(row, self.Y_COL).setValue(capture.y - reference_y)
        self._spin(row, self.R_COL).setValue(capture.rgb[0])
        self._spin(row, self.G_COL).setValue(capture.rgb[1])
        self._spin(row, self.B_COL).setValue(capture.rgb[2])
        self.changed.emit()
        return True

    def to_expression(self) -> list[dict]:
        expression: list[dict] = []
        for row in range(self.rowCount()):
            operator = self._operator_combo(row).currentText()
            if row > 0:
                expression.append({"operator": operator if operator in {"AND", "OR"} else "AND"})
            condition = PixelCondition(
                condition_id=self.item(row, self.ID_COL).text(),
                x=self._spin(row, self.X_COL).value(),
                y=self._spin(row, self.Y_COL).value(),
                rgb=(
                    self._spin(row, self.R_COL).value(),
                    self._spin(row, self.G_COL).value(),
                    self._spin(row, self.B_COL).value(),
                ),
                match_type="unmatch"
                if self._match_combo(row).currentText() == "Unmatch Color"
                else "match",
                tolerance=self._spin(row, self.TOLERANCE_COL).value(),
                use_cursor_position=self._pointer_checkbox(row).isChecked(),
            )
            expression.append(condition.to_dict())
        return expression

    def _append_row(self, condition: PixelCondition, operator: str) -> None:
        row = self.rowCount()
        self.insertRow(row)
        op_combo = QComboBox()
        op_combo.addItems(["", "AND", "OR"])
        op_combo.setCurrentText("" if row == 0 else operator or "AND")
        op_combo.setEnabled(row > 0)
        op_combo.currentTextChanged.connect(lambda _value: self.changed.emit())
        self.setCellWidget(row, self.OP_COL, op_combo)

        pointer_check = QCheckBox()
        pointer_check.setChecked(condition.use_cursor_position)
        pointer_check.setToolTip("When enabled, X/Y are offsets from the current mouse pointer. X=0, Y=0 samples directly under the pointer.")
        pointer_check.stateChanged.connect(lambda _value: self.changed.emit())
        self.setCellWidget(row, self.POINTER_COL, pointer_check)

        for col, value, maximum in [
            (self.X_COL, condition.x, 100000),
            (self.Y_COL, condition.y, 100000),
            (self.R_COL, condition.rgb[0], 255),
            (self.G_COL, condition.rgb[1], 255),
            (self.B_COL, condition.rgb[2], 255),
            (self.TOLERANCE_COL, condition.tolerance, 255),
        ]:
            spin = QSpinBox()
            minimum = -maximum if col in {self.X_COL, self.Y_COL} else 0
            spin.setRange(minimum, maximum)
            spin.setValue(int(value))
            spin.valueChanged.connect(lambda _value: self.changed.emit())
            self.setCellWidget(row, col, spin)

        match_combo = QComboBox()
        match_combo.addItems(["Match Color", "Unmatch Color"])
        match_combo.setCurrentText("Unmatch Color" if condition.match_type == "unmatch" else "Match Color")
        match_combo.currentTextChanged.connect(lambda _value: self.changed.emit())
        self.setCellWidget(row, self.MATCH_COL, match_combo)

        id_item = QTableWidgetItem(condition.condition_id)
        self.setItem(row, self.ID_COL, id_item)

    def _operator_combo(self, row: int) -> QComboBox:
        return self.cellWidget(row, self.OP_COL)  # type: ignore[return-value]

    def _pointer_checkbox(self, row: int) -> QCheckBox:
        return self.cellWidget(row, self.POINTER_COL)  # type: ignore[return-value]

    def _match_combo(self, row: int) -> QComboBox:
        return self.cellWidget(row, self.MATCH_COL)  # type: ignore[return-value]

    def _spin(self, row: int, col: int) -> QSpinBox:
        return self.cellWidget(row, col)  # type: ignore[return-value]
