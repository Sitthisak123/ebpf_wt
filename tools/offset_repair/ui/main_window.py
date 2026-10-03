import os
import sys
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QStatusBar, QFrame, QDialog, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont

from tools.offset_repair.ui.styles import DARK_THEME_QSS
from tools.offset_repair.ui.split_compare_widget import SplitCompareWidget
from tools.offset_repair.core.game_connection import GameContext
from tools.offset_repair.core.snapshot_db import SnapshotDB
from tools.offset_repair.core.offset_exporter import OffsetExporter

# Import all 9 modules
from tools.offset_repair.modules.step_01_my_unit import StepMyUnitModule
from tools.offset_repair.modules.step_02_all_unit import StepAllUnitModule
from tools.offset_repair.modules.step_03_view import StepViewModule
from tools.offset_repair.modules.step_04_bbox import StepBBoxModule
from tools.offset_repair.modules.step_05_ballistics import StepBallisticsModule
from tools.offset_repair.modules.step_06_ground_mov import StepGroundMovementsModule
from tools.offset_repair.modules.step_07_air_mov_ccip import StepAirMovementsCCIPModule
from tools.offset_repair.modules.step_08_get_rockets import StepGetRocketsModule
from tools.offset_repair.modules.step_09_rocket import StepRocketStructModule


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offset Repair Tool (Standalone GUI) — War Thunder Linux")
        self.resize(1280, 850)
        self.setStyleSheet(DARK_THEME_QSS)

        # Core Components
        self.game_ctx = GameContext()
        self.snapshot_db = SnapshotDB()
        self.offset_exporter = OffsetExporter()
        self.shared_state = {}
        self.collected_offsets = {}

        # Pipeline Modules
        self.modules = [
            StepMyUnitModule(),
            StepAllUnitModule(),
            StepViewModule(),
            StepBBoxModule(),
            StepBallisticsModule(),
            StepGroundMovementsModule(),
            StepAirMovementsCCIPModule(),
            StepGetRocketsModule(),
            StepRocketStructModule(),
        ]
        self.current_step_idx = 0
        self.current_mode = "repair"  # "repair" or "snapshot"

        # UI Setup
        self._init_ui()

        # Auto refresh timer for Game Connection & Status (1 Hz)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._on_status_tick)
        self.status_timer.start(1000)

        # Run initial preflight check on step 0
        self._load_step(0)

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(10)

        # ===================================================
        # 1. Top Bar: App Title & Mode Switcher
        # ===================================================
        top_layout = QHBoxLayout()

        title_lbl = QLabel("🛠️ OFFSET REPAIR TOOL", self)
        title_lbl.setObjectName("header_title")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #61AFEF;")
        top_layout.addWidget(title_lbl)

        top_layout.addStretch()

        self.btn_view_offsets = QPushButton("📋 View Offsets (HEX)", self)
        self.btn_view_offsets.setStyleSheet("background-color: #2D3748; color: #61AFEF; font-weight: bold; padding: 6px 12px;")
        self.btn_view_offsets.clicked.connect(self._show_offsets_hex_dialog)
        top_layout.addWidget(self.btn_view_offsets)

        self.btn_mode_repair = QPushButton("🔧 Repair Mode (ค้นหา Offset)", self)
        self.btn_mode_repair.setCheckable(True)
        self.btn_mode_repair.setChecked(True)
        self.btn_mode_repair.clicked.connect(lambda: self._switch_mode("repair"))
        top_layout.addWidget(self.btn_mode_repair)

        self.btn_mode_snapshot = QPushButton("📸 Snapshot Mode (จัดการตัวอย่าง)", self)
        self.btn_mode_snapshot.setCheckable(True)
        self.btn_mode_snapshot.clicked.connect(lambda: self._switch_mode("snapshot"))
        top_layout.addWidget(self.btn_mode_snapshot)

        main_layout.addLayout(top_layout)

        # ===================================================
        # 2. Step Progress Bar / Navigation Bar (1 to 9)
        # ===================================================
        self.navbar_layout = QHBoxLayout()
        self.step_buttons = []

        step_short_names = [
            "1. MyUnit", "2. AllUnits", "3. View", "4. BBox",
            "5. Ballistics", "6. GroundMov", "7. AirMov/CCIP",
            "8. GetRockets", "9. Rocket"
        ]

        for i, sname in enumerate(step_short_names):
            btn = QPushButton(sname, self)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=i: self._on_nav_clicked(idx))
            self.navbar_layout.addWidget(btn)
            self.step_buttons.append(btn)

        main_layout.addLayout(self.navbar_layout)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #2D313B;")
        main_layout.addWidget(line)

        # ===================================================
        # 3. Central Stacked Content: Repair Mode vs Snapshot Mode
        # ===================================================
        self.stacked_widget = QStackedWidget(self)

        # 3.1 Repair View
        self.repair_widget = QWidget(self)
        repair_layout = QVBoxLayout(self.repair_widget)
        repair_layout.setContentsMargins(0, 0, 0, 0)
        repair_layout.setSpacing(8)

        # Step Header & Instruction Box
        self.lbl_step_header = QLabel("", self)
        self.lbl_step_header.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        repair_layout.addWidget(self.lbl_step_header)

        self.lbl_step_desc = QLabel("", self)
        self.lbl_step_desc.setStyleSheet("color: #9BA1A6; font-size: 12px;")
        self.lbl_step_desc.setWordWrap(True)
        repair_layout.addWidget(self.lbl_step_desc)

        self.lbl_preflight_banner = QLabel("", self)
        self.lbl_preflight_banner.setObjectName("status_banner")
        self.lbl_preflight_banner.setWordWrap(True)
        repair_layout.addWidget(self.lbl_preflight_banner)

        # Custom Step Action Container (เช่น ปุ่มเปิด Overlay)
        self.custom_action_container = QWidget(self)
        self.custom_action_layout = QHBoxLayout(self.custom_action_container)
        self.custom_action_layout.setContentsMargins(0, 0, 0, 0)
        repair_layout.addWidget(self.custom_action_container)

        # Split Compare Widget
        self.split_widget = SplitCompareWidget(self)
        self.split_widget.candidateChanged.connect(self._on_candidate_changed)
        repair_layout.addWidget(self.split_widget, 1)

        self.stacked_widget.addWidget(self.repair_widget)

        # 3.2 Snapshot Mode View
        self.snapshot_view_widget = QWidget(self)
        snap_layout = QVBoxLayout(self.snapshot_view_widget)
        snap_layout.setContentsMargins(0, 0, 0, 0)

        snap_top_btn_layout = QHBoxLayout()
        snap_title = QLabel("📸 Snapshot Manager (ตัวอย่างข้อมูลอ้างอิงสำหรับ Compare)", self)
        snap_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #61AFEF;")
        snap_top_btn_layout.addWidget(snap_title)
        snap_top_btn_layout.addStretch()

        self.btn_snap_capture = QPushButton("📸 บันทึกตัวอย่างปัจจุบัน (getDataSample)", self)
        self.btn_snap_capture.setStyleSheet("background-color: #2E7D32; color: white;")
        self.btn_snap_capture.clicked.connect(self._on_capture_snapshot)
        snap_top_btn_layout.addWidget(self.btn_snap_capture)

        self.btn_snap_delete = QPushButton("🗑️ ลบตัวอย่าง (RemoveDataSample)", self)
        self.btn_snap_delete.setStyleSheet("background-color: #C62828; color: white;")
        self.btn_snap_delete.clicked.connect(self._on_delete_snapshot)
        snap_top_btn_layout.addWidget(self.btn_snap_delete)

        snap_layout.addLayout(snap_top_btn_layout)

        # Snapshots Table
        self.table_snapshots = QTableWidget(0, 5, self)
        self.table_snapshots.setHorizontalHeaderLabels(["ID", "Snapshot Name", "Vehicle Name", "Vehicle Type", "Created At"])
        self.table_snapshots.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_snapshots.setSelectionBehavior(QTableWidget.SelectRows)
        snap_layout.addWidget(self.table_snapshots)

        self.stacked_widget.addWidget(self.snapshot_view_widget)

        main_layout.addWidget(self.stacked_widget, 1)

        # ===================================================
        # 4. Bottom Action Bar (Back, Rescan, Confirm & Next, Save)
        # ===================================================
        bottom_layout = QHBoxLayout()

        self.btn_back = QPushButton("⬅️ ย้อนกลับ (Back)", self)
        self.btn_back.clicked.connect(self._on_back_clicked)
        bottom_layout.addWidget(self.btn_back)

        self.btn_rescan = QPushButton("🔄 เริ่มสแกนใหม่ (Rescan)", self)
        self.btn_rescan.setObjectName("btn_scan")
        self.btn_rescan.clicked.connect(self._on_rescan_clicked)
        bottom_layout.addWidget(self.btn_rescan)

        bottom_layout.addStretch()

        self.btn_export_all = QPushButton("💾 บันทึก Offset ทั้งหมด (Save All)", self)
        self.btn_export_all.setStyleSheet("background-color: #455A64; color: white;")
        self.btn_export_all.clicked.connect(self._on_save_all_clicked)
        bottom_layout.addWidget(self.btn_export_all)

        self.btn_next = QPushButton("✅ ยืนยัน & ไปต่อ (Confirm & Next) ➡️", self)
        self.btn_next.setObjectName("btn_next")
        self.btn_next.clicked.connect(self._on_next_clicked)
        bottom_layout.addWidget(self.btn_next)

        main_layout.addLayout(bottom_layout)

        # Status Bar
        self.statusBar = QStatusBar(self)
        self.setStatusBar(self.statusBar)
        self.lbl_game_status = QLabel("กำลังตรวจจับเกม 'aces'...", self)
        self.statusBar.addWidget(self.lbl_game_status)

    def _switch_mode(self, mode):
        self.current_mode = mode
        if mode == "repair":
            self.btn_mode_repair.setChecked(True)
            self.btn_mode_snapshot.setChecked(False)
            self.stacked_widget.setCurrentWidget(self.repair_widget)
            self._load_step(self.current_step_idx)
        else:
            self.btn_mode_repair.setChecked(False)
            self.btn_mode_snapshot.setChecked(True)
            self.stacked_widget.setCurrentWidget(self.snapshot_view_widget)
            self._refresh_snapshots_table()

    def _on_nav_clicked(self, step_idx):
        if 0 <= step_idx < len(self.modules):
            self._load_step(step_idx)

    def _load_step(self, step_idx):
        self.current_step_idx = step_idx
        mod = self.modules[step_idx]

        # Update Navbar active tab
        for i, btn in enumerate(self.step_buttons):
            btn.setChecked(i == step_idx)

        # Header Info
        self.lbl_step_header.setText(mod.step_title)
        self.lbl_step_desc.setText(f"{mod.step_desc}\n{mod.preflight_instructions}")

        # Check Preflight Guard
        self.game_ctx.refresh()
        ok, msg = mod.check_preflight(self.game_ctx, self.snapshot_db)

        if ok:
            self.lbl_preflight_banner.setText(f"✅ สถานะพร้อม: {msg}")
            self.lbl_preflight_banner.setStyleSheet("background-color: #1E3A24; color: #98C379; border: 1px solid #2E7D32;")
            self.btn_rescan.setEnabled(True)
            self.btn_next.setEnabled(True)
        else:
            self.lbl_preflight_banner.setText(f"⚠️ เงื่อนไขยังไม่พร้อม: {msg}")
            self.lbl_preflight_banner.setStyleSheet("background-color: #3D2323; color: #E06C75; border: 1px solid #C62828;")
            self.btn_rescan.setEnabled(False)
            self.btn_next.setEnabled(False)

        # Back button state
        self.btn_back.setEnabled(step_idx > 0)

        # Setup custom widget
        for i in reversed(range(self.custom_action_layout.count())):
            w = self.custom_action_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        custom_w = mod.build_custom_widget(self.custom_action_container, controller=self)
        if custom_w:
            self.custom_action_layout.addWidget(custom_w)

        # If already scanned, populate UI
        if mod.candidates:
            self.split_widget.set_candidates(mod.candidates)
            self.split_widget.set_comparison_data(mod.comparison_data)
        elif ok:
            # Auto scan once if ready
            self._run_scan_for_current_step()

    def _run_scan_for_current_step(self):
        mod = self.modules[self.current_step_idx]
        candidates = mod.scan(self.game_ctx, self.snapshot_db, self.shared_state)
        self.split_widget.set_candidates(candidates)

        selected = self.split_widget.get_selected_candidate()
        mod.selected_candidate = selected
        diffs = mod.compare(self.game_ctx, self.snapshot_db, selected, self.shared_state)
        self.split_widget.set_comparison_data(diffs)

        # ปรับสถานะปุ่ม Next และ Banner สำหรับ Step 1 ตามการ Verify (Auto vs Manual)
        if self.current_step_idx == 0:
            if getattr(mod, "is_verified", False):
                self.btn_next.setEnabled(True)
                self.lbl_preflight_banner.setText(getattr(mod, "verified_message", "✅ ยืนยันสำเร็จ"))
                self.lbl_preflight_banner.setStyleSheet("background-color: #1E3A24; color: #98C379; border: 1px solid #2E7D32;")
            else:
                self.btn_next.setEnabled(False)
                self.lbl_preflight_banner.setText(getattr(mod, "verified_message", "⚠️ ยังไม่พบ Snapshot"))
                self.lbl_preflight_banner.setStyleSheet("background-color: #3D3523; color: #E5C07B; border: 1px solid #C68228;")

    def _on_candidate_changed(self, candidate):
        mod = self.modules[self.current_step_idx]
        mod.selected_candidate = candidate
        diffs = mod.compare(self.game_ctx, self.snapshot_db, candidate, self.shared_state)
        self.split_widget.set_comparison_data(diffs)

        if self.current_step_idx == 0:
            if getattr(mod, "is_verified", False):
                self.btn_next.setEnabled(True)
                self.lbl_preflight_banner.setText(getattr(mod, "verified_message", "✅ ยืนยันสำเร็จ"))
                self.lbl_preflight_banner.setStyleSheet("background-color: #1E3A24; color: #98C379; border: 1px solid #2E7D32;")
            else:
                self.btn_next.setEnabled(False)
                self.lbl_preflight_banner.setText(getattr(mod, "verified_message", "⚠️ ยังไม่พบ Snapshot"))
                self.lbl_preflight_banner.setStyleSheet("background-color: #3D3523; color: #E5C07B; border: 1px solid #C68228;")

    def _on_rescan_clicked(self):
        self._run_scan_for_current_step()

    def _on_back_clicked(self):
        if self.current_step_idx > 0:
            self._load_step(self.current_step_idx - 1)

    def _on_next_clicked(self):
        mod = self.modules[self.current_step_idx]
        selected = self.split_widget.get_selected_candidate()

        # Run verify
        is_valid, reason = mod.verify(self.game_ctx, selected, self.shared_state)
        if not is_valid:
            QMessageBox.warning(self, "ยังไม่ผ่านการ Verify", f"ขั้นตอน {mod.step_title} ยังไม่ผ่านเงื่อนไข:\n{reason}")
            return

        # Export step offsets
        exported = mod.export_offsets(selected, self.shared_state)
        self.collected_offsets.update(exported)

        # Move to next step or finish
        if self.current_step_idx < len(self.modules) - 1:
            self._load_step(self.current_step_idx + 1)
        else:
            # Reached end of pipeline!
            ret = QMessageBox.question(
                self,
                "🎉 สแกนครบทุกขั้นตอนแล้ว!",
                "ท่านต้องการบันทึก Offset ทั้งหมดลง config/offsets.json และอัปเดตระบบเลยหรือไม่?",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret == QMessageBox.Yes:
                self._on_save_all_clicked()

    def _on_save_all_clicked(self):
        # รวบรวมจากทุกโมดูล
        for mod in self.modules:
            cand = mod.selected_candidate or (mod.candidates[0] if mod.candidates else {})
            exp = mod.export_offsets(cand, self.shared_state)
            self.collected_offsets.update(exp)

        success = self.offset_exporter.export_offsets(self.collected_offsets, dual_export=True)
        if success:
            QMessageBox.information(
                self,
                "💾 บันทึกสำเร็จ!",
                f"บันทึก Offset จำนวน {len(self.collected_offsets)} รายการลง config/offsets.json เรียบร้อยแล้ว!\n"
                "(และได้ทำการ Dual-Export อัปเดต persistence files เดิมควบคู่กันเรียบร้อย)"
            )
        else:
            QMessageBox.critical(self, "ข้อผิดพลาด", "ไม่สามารถบันทึกไฟล์ config/offsets.json ได้")

    def _show_offsets_hex_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("📋 Current Offsets (HEX)")
        dialog.resize(720, 520)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(15, 15, 15, 15)

        title = QLabel("📑 รายการ Struct Offsets ทั้งหมด (Hexadecimal Format)", dialog)
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #61AFEF; margin-bottom: 5px;")
        dlg_layout.addWidget(title)

        offsets_data = self.offset_exporter.load_existing_offsets()
        hex_map = offsets_data.get("offsets_hex", {})

        table = QTableWidget(0, 3, dialog)
        table.setHorizontalHeaderLabels(["Offset Name", "HEX Value", "Decimal / Raw"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        for k, v in offsets_data.items():
            if k in ("updated_at", "build_fingerprint", "offsets_hex"):
                continue
            row = table.rowCount()
            table.insertRow(row)

            hex_val = hex_map.get(k)
            if hex_val is None:
                if isinstance(v, int) and not isinstance(v, bool):
                    hex_val = hex(v)
                elif isinstance(v, (list, tuple)):
                    hex_val = str([hex(x) if isinstance(x, int) and not isinstance(x, bool) else x for x in v])
                else:
                    hex_val = str(v)
            else:
                hex_val = str(hex_val)

            item_k = QTableWidgetItem(str(k))
            item_h = QTableWidgetItem(hex_val)
            item_h.setForeground(QColor("#98C379"))
            item_h.setFont(QFont("Consolas", 10, QFont.Bold))
            item_v = QTableWidgetItem(str(v))

            table.setItem(row, 0, item_k)
            table.setItem(row, 1, item_h)
            table.setItem(row, 2, item_v)

        dlg_layout.addWidget(table)
        btns = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
        btns.accepted.connect(dialog.accept)
        dlg_layout.addWidget(btns)
        dialog.exec_()

    def _on_status_tick(self):
        self.game_ctx.refresh()
        self.lbl_game_status.setText(f"🎮 สถานะเกม: {self.game_ctx.cached_status}")

        # Update preflight button states if in repair mode
        if self.current_mode == "repair":
            mod = self.modules[self.current_step_idx]
            ok, msg = mod.check_preflight(self.game_ctx, self.snapshot_db)
            self.btn_rescan.setEnabled(ok)
            self.btn_next.setEnabled(ok)
            if ok:
                self.lbl_preflight_banner.setText(f"✅ สถานะพร้อม: {msg}")
                self.lbl_preflight_banner.setStyleSheet("background-color: #1E3A24; color: #98C379; border: 1px solid #2E7D32;")
            else:
                self.lbl_preflight_banner.setText(f"⚠️ เงื่อนไขยังไม่พร้อม: {msg}")
                self.lbl_preflight_banner.setStyleSheet("background-color: #3D2323; color: #E06C75; border: 1px solid #C62828;")

    # ===================================================
    # Snapshot Mode Methods
    # ===================================================
    def _refresh_snapshots_table(self):
        snaps = self.snapshot_db.list_snapshots()
        self.table_snapshots.setRowCount(0)

        for s in snaps:
            row = self.table_snapshots.rowCount()
            self.table_snapshots.insertRow(row)
            self.table_snapshots.setItem(row, 0, QTableWidgetItem(str(s["id"])))
            self.table_snapshots.setItem(row, 1, QTableWidgetItem(s["name"]))
            self.table_snapshots.setItem(row, 2, QTableWidgetItem(s["vehicle_name"]))
            self.table_snapshots.setItem(row, 3, QTableWidgetItem(s["vehicle_type"].upper()))
            self.table_snapshots.setItem(row, 4, QTableWidgetItem(s["created_at"]))

    def _on_capture_snapshot(self):
        self.game_ctx.refresh(force=True)
        if not self.game_ctx.is_connected or not self.game_ctx.my_unit_ptr:
            QMessageBox.warning(self, "คำเตือน", "กรุณาเปิดเกมและเข้า Test Drive ก่อนกดบันทึก Snapshot")
            return

        vname = self.game_ctx.current_unit_name
        vtype = self.game_ctx.current_unit_type
        snap_name = f"snapshot_{vname}_{len(self.snapshot_db.list_snapshots()) + 1}"

        import src.utils.mul as mul
        scanner = self.game_ctx.scanner
        cgame = self.game_ctx.cgame_ptr

        live_units_data = []
        if scanner and cgame:
            units = mul.get_all_units(scanner, cgame)
            for u_ptr, is_air in units:
                dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
                pos = mul.get_unit_pos(scanner, u_ptr) if not is_air else [0, 0, 0]
                live_units_data.append({
                    "short_name": dna.get("short_name", ""),
                    "unit_id": 1,
                    "state": 0,
                    "team": 1,
                    "pos": pos,
                    "is_ground": not is_air
                })

        data_dict = {
            "my_unit": {
                "short_name": vname,
                "unit_id": 1,
                "state": 0,
                "team": 1,
            },
            "all_units": live_units_data,
            "ballistics": {
                "speed": 795.0,
                "mass": 9.2,
                "caliber": 0.085,
                "cx": 0.32,
            },
            "bbox": {
                "units": [
                    {
                        "short_name": vname,
                        "dim": [3.0, 2.5, 6.0]
                    }
                ]
            }
        }

        self.snapshot_db.save_snapshot(
            name=snap_name,
            vehicle_name=vname,
            vehicle_type=vtype,
            data_dict=data_dict
        )
        self._refresh_snapshots_table()
        QMessageBox.information(self, "สำเร็จ", f"บันทึก Snapshot '{snap_name}' สำหรับยูนิต '{vname}' เรียบร้อยแล้ว!")

    def _on_delete_snapshot(self):
        selected_rows = self.table_snapshots.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "คำเตือน", "กรุณาเลือก Snapshot ที่ต้องการลบในตาราง")
            return

        row_idx = selected_rows[0].row()
        snap_id = int(self.table_snapshots.item(row_idx, 0).text())
        snap_name = self.table_snapshots.item(row_idx, 1).text()

        ret = QMessageBox.question(self, "ยืนยันการลบ", f"ต้องการลบ Snapshot '{snap_name}' ใช่หรือไม่?", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.snapshot_db.delete_snapshot(snap_id)
            self._refresh_snapshots_table()
