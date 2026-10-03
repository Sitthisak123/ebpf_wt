from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QComboBox,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont


class SplitCompareWidget(QWidget):
    """
    Split-View Widget สำหรับแสดงผลข้อมูลในแต่ละขั้นตอน:
    - ซ้ายมือ: รายการ Candidate Offsets + Score (%) + Dropdown เลือกค่า
    - ขวามือ: ตารางเปรียบเทียบ Field-by-Field ของ Live Unit vs Snapshot (ไฮไลต์ สีเขียว/แดง)
    """
    candidateChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.candidates = []
        self.comparison_data = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # ===================================================
        # ฝั่งซ้าย: Candidate Offsets & Manual Dropdown Selector
        # ===================================================
        left_group = QGroupBox("🔍 Candidate Offsets (ผลการสแกน)")
        left_layout = QVBoxLayout(left_group)
        left_layout.setContentsMargins(10, 15, 10, 10)

        dropdown_layout = QHBoxLayout()
        lbl_select = QLabel("เลือก Offset:", self)
        lbl_select.setStyleSheet("font-weight: bold; color: #61AFEF;")
        self.combo_candidates = QComboBox(self)
        self.combo_candidates.currentIndexChanged.connect(self._on_combo_changed)
        dropdown_layout.addWidget(lbl_select)
        dropdown_layout.addWidget(self.combo_candidates, 1)
        left_layout.addLayout(dropdown_layout)

        # ตาราง Candidate
        self.table_candidates = QTableWidget(0, 3, self)
        self.table_candidates.setHorizontalHeaderLabels(["Offset", "Match Score", "สถานะ"])
        self.table_candidates.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_candidates.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_candidates.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_candidates.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_candidates.itemSelectionChanged.connect(self._on_table_row_selected)
        left_layout.addWidget(self.table_candidates)

        # ข้อมูลสรุปของ Candidate ที่เลือก
        self.lbl_candidate_desc = QLabel("ยังไม่ได้เลือก Candidate", self)
        self.lbl_candidate_desc.setStyleSheet("color: #ABB2BF; font-size: 11px;")
        self.lbl_candidate_desc.setWordWrap(True)
        left_layout.addWidget(self.lbl_candidate_desc)

        # ===================================================
        # ฝั่งขวา: Field-by-Field Comparison Table
        # ===================================================
        right_group = QGroupBox("📊 Snapshot Comparison (เปรียบเทียบข้อมูลยูนิต)")
        right_layout = QVBoxLayout(right_group)
        right_layout.setContentsMargins(10, 15, 10, 10)

        # ตาราง Comparison
        self.table_diff = QTableWidget(0, 5, self)
        self.table_diff.setHorizontalHeaderLabels(["Field Name", "Live Value (ในเกม)", "Snapshot Value", "สถานะ", "หมายเหตุ"])
        self.table_diff.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_diff.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_diff.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_diff.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_diff.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        right_layout.addWidget(self.table_diff)

        # สรุปคะแนนการเทียบ
        self.lbl_diff_summary = QLabel("พร้อมแสดงข้อมูลการเปรียบเทียบ", self)
        self.lbl_diff_summary.setStyleSheet("font-weight: bold; color: #98C379;")
        right_layout.addWidget(self.lbl_diff_summary)

        # Add to splitter
        splitter.addWidget(left_group)
        splitter.addWidget(right_group)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        main_layout.addWidget(splitter)

    def set_candidates(self, candidates: list[dict]):
        self.candidates = candidates or []
        self.combo_candidates.blockSignals(True)
        self.combo_candidates.clear()
        self.table_candidates.setRowCount(0)

        default_idx = 0
        for i, c in enumerate(self.candidates):
            off_str = hex(c.get("offset", 0)) if isinstance(c.get("offset"), int) else str(c.get("offset"))
            score = c.get("score", 0.0)
            is_def = c.get("is_default", False)
            if is_def:
                default_idx = i

            label = f"{off_str} ({score:.0f}%)" + (" [Default]" if is_def else "")
            self.combo_candidates.addItem(label, c)

            row = self.table_candidates.rowCount()
            self.table_candidates.insertRow(row)

            item_off = QTableWidgetItem(off_str)
            item_score = QTableWidgetItem(f"{score:.1f}%")
            item_status = QTableWidgetItem("⭐ Recommended" if is_def else "Alternative")

            if is_def:
                item_status.setForeground(QColor("#98C379")) # Green
            else:
                item_status.setForeground(QColor("#61AFEF")) # Blue

            self.table_candidates.setItem(row, 0, item_off)
            self.table_candidates.setItem(row, 1, item_score)
            self.table_candidates.setItem(row, 2, item_status)

        self.combo_candidates.blockSignals(False)

        if self.candidates:
            self.combo_candidates.setCurrentIndex(default_idx)
            self._select_table_row(default_idx)
        else:
            self.lbl_candidate_desc.setText("⚠️ ไม่พบ Candidate สำหรับขั้นตอนนี้")

    def _select_table_row(self, row_idx):
        if 0 <= row_idx < self.table_candidates.rowCount():
            self.table_candidates.blockSignals(True)
            self.table_candidates.selectRow(row_idx)
            self.table_candidates.blockSignals(False)
            c = self.candidates[row_idx]
            off_hex = hex(c.get("offset", 0)) if isinstance(c.get("offset"), int) else str(c.get("offset"))
            self.lbl_candidate_desc.setText(f"Offset: {off_hex} | Score: {c.get('score', 0):.1f}% | {c.get('label', '')}")

    def _on_combo_changed(self, idx):
        if 0 <= idx < len(self.candidates):
            self._select_table_row(idx)
            self.candidateChanged.emit(self.candidates[idx])

    def _on_table_row_selected(self):
        selected_rows = self.table_candidates.selectionModel().selectedRows()
        if selected_rows:
            idx = selected_rows[0].row()
            if 0 <= idx < self.combo_candidates.count():
                self.combo_candidates.blockSignals(True)
                self.combo_candidates.setCurrentIndex(idx)
                self.combo_candidates.blockSignals(False)
                c = self.candidates[idx]
                off_hex = hex(c.get("offset", 0)) if isinstance(c.get("offset"), int) else str(c.get("offset"))
                self.lbl_candidate_desc.setText(f"Offset: {off_hex} | Score: {c.get('score', 0):.1f}% | {c.get('label', '')}")
                self.candidateChanged.emit(c)

    def set_comparison_data(self, diff_rows: list[dict]):
        self.comparison_data = diff_rows or []
        self.table_diff.setRowCount(0)

        match_count = 0
        total_count = len(self.comparison_data)

        for row_data in self.comparison_data:
            row = self.table_diff.rowCount()
            self.table_diff.insertRow(row)

            field = str(row_data.get("field", ""))
            live_val = str(row_data.get("live_val", ""))
            snap_val = str(row_data.get("snap_val", ""))
            status = row_data.get("status", "match").lower()
            notes = str(row_data.get("notes", ""))

            if status == "match":
                match_count += 1
                status_text = "✅ Match"
                fg_color = QColor("#98C379") # Green
            elif status == "mismatch":
                status_text = "❌ Mismatch"
                fg_color = QColor("#E06C75") # Red
            else:
                status_text = "⚠️ Warning"
                fg_color = QColor("#E5C07B") # Yellow

            item_field = QTableWidgetItem(field)
            item_live = QTableWidgetItem(live_val)
            item_snap = QTableWidgetItem(snap_val)
            item_status = QTableWidgetItem(status_text)
            item_notes = QTableWidgetItem(notes)

            item_status.setForeground(fg_color)
            item_status.setFont(QFont("Segoe UI", 9, QFont.Bold))

            self.table_diff.setItem(row, 0, item_field)
            self.table_diff.setItem(row, 1, item_live)
            self.table_diff.setItem(row, 2, item_snap)
            self.table_diff.setItem(row, 3, item_status)
            self.table_diff.setItem(row, 4, item_notes)

        if total_count > 0:
            rate = (match_count / total_count) * 100.0
            color_str = "#98C379" if rate >= 80 else ("#E5C07B" if rate >= 50 else "#E06C75")
            self.lbl_diff_summary.setText(f"ผลการเทียบ: ตรงกัน {match_count}/{total_count} รายการ ({rate:.1f}%)")
            self.lbl_diff_summary.setStyleSheet(f"font-weight: bold; color: {color_str};")
        else:
            self.lbl_diff_summary.setText("ไม่มีข้อมูลสำหรับการเปรียบเทียบ")
            self.lbl_diff_summary.setStyleSheet("font-weight: bold; color: #ABB2BF;")

    def get_selected_candidate(self):
        idx = self.combo_candidates.currentIndex()
        if 0 <= idx < len(self.candidates):
            return self.candidates[idx]
        return None
