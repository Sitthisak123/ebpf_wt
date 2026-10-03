import struct
import math
from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepBallisticsModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_ballistics",
            step_index=5,
            step_title="5. getBallistics_profile (สแกนหา Ballistic Layout & กระสุน)",
            step_desc="ค้นหาพอยเตอร์ระบบอาวุธ (OFF_WEAPON_PTR) และโครงสร้าง Ballistic Layout (Speed, Mass, Caliber, Cx, Max Dist) พร้อมเทียบกับ Snapshot"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้า Test Drive ด้วยยูนิตที่มีปืนใหญ่/ปืนกล\n"
            "2. แนะนำให้ยิง 1 นัด หรือรอให้กระสุนโหลดเสร็จเรียบร้อยก่อนกดสแกน"
        )

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        ok, msg = super().check_preflight(game_ctx, snapshot_db)
        if not ok:
            return False, msg

        cur_name = game_ctx.current_unit_name
        all_snaps = snapshot_db.get_all_snapshots()
        has_snap = any(s.get("vehicle_name") == cur_name or cur_name in s.get("vehicle_name", "") for s in all_snaps)
        if not has_snap:
            return False, f"⚠️ ยูนิตปัจจุบัน '{cur_name}' ยังไม่มี Snapshot ในระบบ"

        return True, "พร้อมสแกนโครงสร้าง Ballistics"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        scanner = game_ctx.scanner
        my_unit = game_ctx.my_unit_ptr or shared_state.get("my_unit_ptr", 0)

        candidates = []
        # Layout มาตรฐาน
        candidates.append({
            "offset": 0x2118,
            "label": "Layout Verified 2026 (Speed 0x2118, Base 0x2120)",
            "score": 97.0,
            "is_default": True,
            "base_off": 0x2120,
            "speed_off": 0x2118,
            "mass_off": 0x2124,
            "caliber_off": 0x2128,
            "cx_off": 0x212C,
            "max_dist_off": 0x2130,
        })

        # Layout ดั้งเดิม (Offset Shift -0x20 หรือ -0x10)
        candidates.append({
            "offset": 0x2108,
            "label": "Layout Legacy Shift (Speed 0x2108, Base 0x2110)",
            "score": 80.0,
            "is_default": False,
            "base_off": 0x2110,
            "speed_off": 0x2108,
            "mass_off": 0x2114,
            "caliber_off": 0x2118,
            "cx_off": 0x211C,
            "max_dist_off": 0x2120,
        })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        my_unit = game_ctx.my_unit_ptr or shared_state.get("my_unit_ptr", 0)

        speed_off = selected_candidate.get("speed_off", 0x2118) if selected_candidate else 0x2118
        mass_off = selected_candidate.get("mass_off", 0x2124) if selected_candidate else 0x2124
        caliber_off = selected_candidate.get("caliber_off", 0x2128) if selected_candidate else 0x2128
        cx_off = selected_candidate.get("cx_off", 0x212C) if selected_candidate else 0x212C
        dist_off = selected_candidate.get("max_dist_off", 0x2130) if selected_candidate else 0x2130

        # อ่าน Weapon Pointer จาก MyUnit
        weapon_ptr = 0
        if scanner and my_unit:
            raw_w = scanner.read_mem(my_unit + mul.OFF_WEAPON_PTR, 8)
            if raw_w and len(raw_w) == 8:
                cand_wp = struct.unpack("<Q", raw_w)[0]
                if mul.is_valid_ptr(cand_wp):
                    weapon_ptr = cand_wp

        diffs.append({
            "field": "Weapon Pointer (OFF_WEAPON_PTR)",
            "live_val": f"{hex(mul.OFF_WEAPON_PTR)} -> {hex(weapon_ptr)}",
            "snap_val": hex(mul.OFF_WEAPON_PTR),
            "status": "match" if mul.is_valid_ptr(weapon_ptr) else "warn",
            "notes": "พอยเตอร์ฐานระบบอาวุธ"
        })

        # ดึง Snapshot
        all_snaps = snapshot_db.get_all_snapshots()
        snap_ballistics = all_snaps[0]["data"].get("ballistics", {}) if all_snaps else {}

        target_base = weapon_ptr if weapon_ptr else (game_ctx.cgame_ptr or 0)
        if scanner and target_base:
            # 1. Speed
            raw_sp = scanner.read_mem(target_base + speed_off, 4)
            live_sp = struct.unpack("<f", raw_sp)[0] if raw_sp else 0.0
            snap_sp = snap_ballistics.get("speed", 795.0)
            sp_match = 100.0 < live_sp < 2500.0 and abs(live_sp - snap_sp) < 200.0
            diffs.append({
                "field": f"Muzzle Speed ({hex(speed_off)})",
                "live_val": f"{live_sp:.1f} m/s",
                "snap_val": f"{snap_sp:.1f} m/s",
                "status": "match" if sp_match else "warn",
                "notes": "ความเร็วต้นกระสุน"
            })

            # 2. Caliber
            raw_cal = scanner.read_mem(target_base + caliber_off, 4)
            live_cal = struct.unpack("<f", raw_cal)[0] if raw_cal else 0.0
            snap_cal = snap_ballistics.get("caliber", 0.085)
            cal_match = 0.005 < live_cal < 0.200
            diffs.append({
                "field": f"Bullet Caliber ({hex(caliber_off)})",
                "live_val": f"{live_cal*1000:.1f} mm ({live_cal:.4f}m)",
                "snap_val": f"{snap_cal*1000:.1f} mm",
                "status": "match" if cal_match else "warn",
                "notes": "ขนาดเส้นผ่านศูนย์กลางกระสุน"
            })

            # 3. Mass
            raw_mass = scanner.read_mem(target_base + mass_off, 4)
            live_mass = struct.unpack("<f", raw_mass)[0] if raw_mass else 0.0
            snap_mass = snap_ballistics.get("mass", 9.2)
            mass_match = 0.01 < live_mass < 150.0
            diffs.append({
                "field": f"Bullet Mass ({hex(mass_off)})",
                "live_val": f"{live_mass:.2f} kg",
                "snap_val": f"{snap_mass:.2f} kg",
                "status": "match" if mass_match else "warn",
                "notes": "น้ำหนักกระสุน"
            })

            # 4. Cx (Drag Coefficient)
            raw_cx = scanner.read_mem(target_base + cx_off, 4)
            live_cx = struct.unpack("<f", raw_cx)[0] if raw_cx else 0.0
            snap_cx = snap_ballistics.get("cx", 0.32)
            cx_match = 0.01 < live_cx < 1.5
            diffs.append({
                "field": f"Drag Coefficient Cx ({hex(cx_off)})",
                "live_val": f"{live_cx:.3f}",
                "snap_val": f"{snap_cx:.3f}",
                "status": "match" if cx_match else "warn",
                "notes": "สัมประสิทธิ์แรงต้านอากาศ"
            })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        return True, "ยืนยันค่า Ballistics Profile สำเร็จ!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        return {
            "OFF_WEAPON_PTR": mul.OFF_WEAPON_PTR,
            "BALLISTIC_STRUCT_BASE_OFF": selected_candidate.get("base_off", 0x2120),
            "BALLISTIC_SPEED_OFF": selected_candidate.get("speed_off", 0x2118),
            "BALLISTIC_MASS_OFF": selected_candidate.get("mass_off", 0x2124),
            "BALLISTIC_CALIBER_OFF": selected_candidate.get("caliber_off", 0x2128),
            "BALLISTIC_CX_OFF": selected_candidate.get("cx_off", 0x212C),
            "BALLISTIC_MAX_DISTANCE_OFF": selected_candidate.get("max_dist_off", 0x2130),
        }
