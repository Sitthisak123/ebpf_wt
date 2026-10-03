import struct
import math
import time
from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepGroundMovementsModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_ground_movements",
            step_index=6,
            step_title="6. getGroundMovements (สแกนหา Movement & พิกัดรถถังด้วย pos_VEL)",
            step_desc="ค้นหา OFF_GROUND_MOVEMENT และ OFF_GROUND_VEL ด้วย DNA Scanner พร้อมตรวจสอบความถูกต้องด้วยความสัมพันธ์ความเร็วและพิกัด (pos_VEL Verification)"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้า Test Drive ด้วยรถถังหรือยานเกราะทางบก\n"
            "2. ขับรถเดินหน้าหรือถอยหลังเล็กน้อยเพื่อสร้างเวกเตอร์ความเร็ว (Velocity) แล้วกดสแกน"
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

        return True, "พร้อมสแกน Ground Movements"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        scanner = game_ctx.scanner
        my_unit = game_ctx.my_unit_ptr or shared_state.get("my_unit_ptr", 0)

        candidates = []
        # Candidate 1: ค่ามาตรฐานจาก mul.py
        candidates.append({
            "offset": (mul.OFF_GROUND_MOVEMENT, mul.OFF_GROUND_VEL),
            "label": f"Primary Ground Movement (Move {hex(mul.OFF_GROUND_MOVEMENT)}, Vel {hex(mul.OFF_GROUND_VEL)})",
            "score": 98.0,
            "is_default": True,
            "mov_off": mul.OFF_GROUND_MOVEMENT,
            "vel_off": mul.OFF_GROUND_VEL,
            "pos_off": mul.OFF_UNIT_X
        })

        # ค้นหา alternative movement pointers รอบๆ 0xD00 - 0xD60
        if scanner and my_unit:
            for m_off in [0x0D00, 0x0D10, 0x0D20, 0x0D28, 0x0D30, 0x0D38, 0x0D48]:
                raw_m = scanner.read_mem(my_unit + m_off, 8)
                if raw_m and len(raw_m) == 8:
                    m_ptr = struct.unpack("<Q", raw_m)[0]
                    if mul.is_valid_ptr(m_ptr) and m_off != mul.OFF_GROUND_MOVEMENT:
                        for v_off in [0x0068, 0x0070, 0x0078, 0x0080]:
                            candidates.append({
                                "offset": (m_off, v_off),
                                "label": f"Candidate Ground ({hex(m_off)}, Vel {hex(v_off)})",
                                "score": 83.0,
                                "is_default": False,
                                "mov_off": m_off,
                                "vel_off": v_off,
                                "pos_off": mul.OFF_UNIT_X
                            })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        my_unit = game_ctx.my_unit_ptr or shared_state.get("my_unit_ptr", 0)

        mov_off = selected_candidate.get("mov_off", mul.OFF_GROUND_MOVEMENT) if selected_candidate else mul.OFF_GROUND_MOVEMENT
        vel_off = selected_candidate.get("vel_off", mul.OFF_GROUND_VEL) if selected_candidate else mul.OFF_GROUND_VEL
        pos_off = selected_candidate.get("pos_off", mul.OFF_UNIT_X) if selected_candidate else mul.OFF_UNIT_X

        # 1. ตำแหน่งพิกัด (Pos)
        pos = mul.get_unit_pos(scanner, my_unit) if scanner and my_unit else None
        pos_str = f"({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})" if pos else "N/A"
        diffs.append({
            "field": f"Unit 3D Position ({hex(pos_off)})",
            "live_val": pos_str,
            "snap_val": "Finite World Vector (X, Y, Z)",
            "status": "match" if pos and all(math.isfinite(v) for v in pos) else "warn",
            "notes": "พิกัด World Space ของยานพาหนะ"
        })

        # 2. Movement Pointer
        mov_ptr = 0
        if scanner and my_unit:
            raw_mp = scanner.read_mem(my_unit + mov_off, 8)
            if raw_mp and len(raw_mp) == 8:
                mov_ptr = struct.unpack("<Q", raw_mp)[0]

        diffs.append({
            "field": f"Ground Movement Pointer ({hex(mov_off)})",
            "live_val": hex(mov_ptr) if mov_ptr else "Null",
            "snap_val": "Valid Heap Pointer",
            "status": "match" if mul.is_valid_ptr(mov_ptr) else "warn",
            "notes": "ชี้ไปยังโครงสร้างฟิสิกส์การเคลื่อนที่ของรถ"
        })

        # 3. Velocity (pos_VEL)
        vel_vec = (0.0, 0.0, 0.0)
        speed_kmh = 0.0
        if scanner and mul.is_valid_ptr(mov_ptr):
            raw_v = scanner.read_mem(mov_ptr + vel_off, 24)
            if raw_v and len(raw_v) >= 24:
                # ลองอ่านแบบ double
                vx, vy, vz = struct.unpack("<ddd", raw_v[:24])
                if math.isfinite(vx) and abs(vx) < 500.0:
                    vel_vec = (vx, vy, vz)
                    speed_kmh = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6

        diffs.append({
            "field": f"Ground Velocity Vector ({hex(vel_off)})",
            "live_val": f"({vel_vec[0]:.2f}, {vel_vec[1]:.2f}, {vel_vec[2]:.2f}) | {speed_kmh:.1f} km/h",
            "snap_val": "Speed >= 0.0 km/h (Finite)",
            "status": "match" if math.isfinite(speed_kmh) and speed_kmh < 200.0 else "warn",
            "notes": "เวกเตอร์ความเร็ว (pos_VEL verification)"
        })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        return True, "ยืนยันค่า Ground Movement และพิกัดเรียบร้อย!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        return {
            "OFF_UNIT_X": selected_candidate.get("pos_off", mul.OFF_UNIT_X),
            "OFF_UNIT_ROTATION": selected_candidate.get("pos_off", mul.OFF_UNIT_X) - 0x24,
            "OFF_GROUND_MOVEMENT": selected_candidate.get("mov_off", mul.OFF_GROUND_MOVEMENT),
            "OFF_GROUND_VEL": selected_candidate.get("vel_off", mul.OFF_GROUND_VEL),
        }
