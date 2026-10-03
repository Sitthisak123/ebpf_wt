import struct
import math
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton
from tools.offset_repair.core.base_module import BaseStepModule
from tools.offset_repair.ui.ccip_overlay import CCIPVerificationOverlay
import src.utils.mul as mul


class StepAirMovementsCCIPModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_air_movements_ccip",
            step_index=7,
            step_title="7. getAirMovements & DirectCCIP (สแกน Movement & ยืนยัน CCIP จุดตกกระทบ)",
            step_desc="สแกนหา OFF_AIR_MOVEMENT, OFF_AIR_VEL และ OFF_CCIP_IMPACT โดยใช้ Overlay แสดง ESP เป้าหมายและตรวจสอบความสอดคล้องระหว่าง SimCCIP กับ DirectCCIP"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้า Test Drive ด้วยเครื่องบินหรือเฮลิคอปเตอร์ที่มีระบบอาวุธทิ้งระเบิดหรือจรวด (CCIP)\n"
            "2. กดปุ่ม [🎯 เปิด Overlay ทดสอบ CCIP] เพื่อเล็งและล็อกเป้าหมาย (Lock Target) บนหน้าจอเกม\n"
            "3. เล็งให้จุดตก CCIP เข้าใกล้เป้าหมายจนระบบขึ้น Verified สีเขียว"
        )
        self.ccip_overlay = None

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        ok, msg = super().check_preflight(game_ctx, snapshot_db)
        if not ok:
            return False, msg

        cur_name = game_ctx.current_unit_name
        all_snaps = snapshot_db.get_all_snapshots()
        has_snap = any(s.get("vehicle_name") == cur_name or cur_name in s.get("vehicle_name", "") for s in all_snaps)
        if not has_snap:
            return False, f"⚠️ ยูนิตปัจจุบัน '{cur_name}' ยังไม่มี Snapshot ในระบบ"

        return True, "พร้อมทดสอบ Air Movements และ DirectCCIP"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        candidates = []
        # Candidate 1: ค่ามาตรฐานจาก mul.py
        candidates.append({
            "offset": mul.OFF_CCIP_IMPACT,
            "label": f"Primary CCIP (Impact {hex(mul.OFF_CCIP_IMPACT)}, AirVel {hex(mul.OFF_AIR_VEL)})",
            "score": 96.0,
            "is_default": True,
            "ccip_off": mul.OFF_CCIP_IMPACT,
            "air_mov_off": mul.OFF_AIR_MOVEMENT,
            "air_vel_off": mul.OFF_AIR_VEL
        })

        # Alternative offsets สำหรับ CCIP ใน Dagor Engine
        for alt_ccip in [0x1CBC, 0x117C, 0x114C, 0x111C, 0x10EC, 0x1C9C]:
            candidates.append({
                "offset": alt_ccip,
                "label": f"Alternative Pylon CCIP ({hex(alt_ccip)})",
                "score": 82.0,
                "is_default": False,
                "ccip_off": alt_ccip,
                "air_mov_off": mul.OFF_AIR_MOVEMENT,
                "air_vel_off": mul.OFF_AIR_VEL
            })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        my_unit = game_ctx.my_unit_ptr or shared_state.get("my_unit_ptr", 0)

        ccip_off = selected_candidate.get("ccip_off", mul.OFF_CCIP_IMPACT) if selected_candidate else mul.OFF_CCIP_IMPACT
        air_mov_off = selected_candidate.get("air_mov_off", mul.OFF_AIR_MOVEMENT) if selected_candidate else mul.OFF_AIR_MOVEMENT
        air_vel_off = selected_candidate.get("air_vel_off", mul.OFF_AIR_VEL) if selected_candidate else mul.OFF_AIR_VEL

        # 1. Air Movement Pointer
        mov_ptr = 0
        if scanner and my_unit:
            raw_m = scanner.read_mem(my_unit + air_mov_off, 8)
            if raw_m and len(raw_m) == 8:
                mov_ptr = struct.unpack("<Q", raw_m)[0]

        diffs.append({
            "field": f"Air Movement Pointer ({hex(air_mov_off)})",
            "live_val": hex(mov_ptr) if mov_ptr else "Null / Ground Mode",
            "snap_val": hex(mul.OFF_AIR_MOVEMENT),
            "status": "match" if mul.is_valid_ptr(mov_ptr) else "warn",
            "notes": "ชี้ไปยังโครงสร้างจลนศาสตร์การบิน"
        })

        # 2. Air Velocity
        vel_str = "N/A"
        if scanner and my_unit:
            raw_v = scanner.read_mem(my_unit + air_vel_off, 12)
            if raw_v and len(raw_v) == 12:
                vx, vy, vz = struct.unpack("<fff", raw_v)
                if math.isfinite(vx) and abs(vx) < 2000.0:
                    spd = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6
                    vel_str = f"({vx:.1f}, {vy:.1f}, {vz:.1f}) | {spd:.1f} km/h"

        diffs.append({
            "field": f"Air Velocity ({hex(air_vel_off)})",
            "live_val": vel_str,
            "snap_val": "Finite Vec3 Velocity",
            "status": "match" if vel_str != "N/A" else "warn",
            "notes": "เวกเตอร์ความเร็วเครื่องบิน 12-byte float"
        })

        # 3. DirectCCIP Impact Offset
        diffs.append({
            "field": f"DirectCCIP Impact Offset ({hex(ccip_off)})",
            "live_val": "พร้อมทดสอบความตรงกันผ่าน Overlay",
            "snap_val": hex(mul.OFF_CCIP_IMPACT),
            "status": "match" if self.is_verified else "warn",
            "notes": "เวกเตอร์จุดตกกระทบของระเบิด/จรวด"
        })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        if not self.is_verified:
            return False, "ยังไม่ผ่านการ Verify: กรุณากดเปิด Overlay เพื่อเล็งเป้าหมายและรอให้ CCIP เคลื่อนที่เข้าใกล้เป้าหมายจน SimCCIP และ DirectCCIP ตรงกัน"
        return True, "ยืนยันค่า DirectCCIP ผ่านการทดสอบกับเป้าหมายจริงสำเร็จ!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        return {
            "OFF_AIR_MOVEMENT": selected_candidate.get("air_mov_off", mul.OFF_AIR_MOVEMENT),
            "OFF_AIR_VEL": selected_candidate.get("air_vel_off", mul.OFF_AIR_VEL),
            "OFF_CCIP_IMPACT": selected_candidate.get("ccip_off", mul.OFF_CCIP_IMPACT),
        }

    def build_custom_widget(self, parent_widget, controller=None):
        widget = QWidget(parent_widget)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 5)

        btn_overlay = QPushButton("🎯 เปิด Overlay แสดง ESP & ทดสอบ DirectCCIP", widget)
        btn_overlay.setStyleSheet("background-color: #E65100; color: white; font-weight: bold; padding: 8px 16px;")

        def _on_click():
            if self.ccip_overlay is None:
                self.ccip_overlay = CCIPVerificationOverlay()
                self.ccip_overlay.verifiedSignal.connect(self._on_ccip_verified)
            cand = self.selected_candidate or (self.candidates[0] if self.candidates else {})
            self.ccip_overlay.set_context(controller.game_ctx if controller else None, cand)
            self.ccip_overlay.start_overlay()

        btn_overlay.clicked.connect(_on_click)
        layout.addWidget(btn_overlay)
        layout.addStretch()
        return widget

    def _on_ccip_verified(self, data):
        self.is_verified = True
        self.verified_message = f"Verified! Diff: {data.get('delta_m', 0):.1f}m with {data.get('target', '')}"
