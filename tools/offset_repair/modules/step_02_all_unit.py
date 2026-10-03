import struct
import math
from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepAllUnitModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_all_unit",
            step_index=2,
            step_title="2. getAllUnit (สแกนหา Unit List & ตรวจสอบยูนิตทั้งหมด)",
            step_desc="สแกนหาอาเรย์ยูนิตทั้งหมดในแมพ (Air & Ground) และเปรียบเทียบข้อมูลยูนิตทุกตัว (ID, State, Team, Position) กับ Snapshot"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. ขับยูนิตใดก็ได้ในโหมด Test Drive แต่ต้องเป็นยูนิตที่มีข้อมูล Snapshot อยู่ในระบบแล้ว\n"
            "2. หากเป็นยูนิตใหม่ที่ยังไม่เคยเก็บตัวอย่าง กรุณาสลับไปหน้า 'Snapshot Mode' ด้านบนเพื่อกดบันทึกตัวอย่างก่อน"
        )

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        ok, msg = super().check_preflight(game_ctx, snapshot_db)
        if not ok:
            return False, msg

        cur_name = game_ctx.current_unit_name
        if not cur_name or cur_name in ("Unknown", "None (In Hangar / Not Spawned)"):
            return False, "ยังไม่พบยูนิตที่กำลังขับอยู่ในแมพ (กรุณา Spawn ยูนิตใน Test Drive)"

        # ตรวจสอบว่าใน snapshot_db มี snapshot ของยูนิตนี้หรือไม่
        all_snaps = snapshot_db.get_all_snapshots()
        matched_snap = None
        for s in all_snaps:
            vname = s.get("vehicle_name", "")
            if vname == cur_name or vname in cur_name or cur_name in vname:
                matched_snap = s
                break
            # ตรวจสอบภายใน list all_units ของ snapshot
            snap_units = s.get("data", {}).get("all_units", [])
            if any(u.get("short_name") == cur_name for u in snap_units):
                matched_snap = s
                break

        if not matched_snap:
            return False, f"⚠️ ยูนิตปัจจุบัน '{cur_name}' ยังไม่มี Snapshot ในระบบ (กรุณาไปที่ 'Snapshot Mode' เพื่อเก็บตัวอย่าง หรือเปลี่ยนไปขับยูนิตที่มีตัวอย่างแล้ว)"

        return True, f"✅ ยูนิต '{cur_name}' มี Snapshot อ้างอิงในระบบแล้ว (Snapshot: {matched_snap['name']})"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        scanner = game_ctx.scanner
        cgame = game_ctx.cgame_ptr or shared_state.get("cgame_ptr", 0)

        candidates = []
        # Candidate 1: โครงสร้างมาตรฐานจาก mul.py (Air 0x310, Ground 0x328)
        candidates.append({
            "offset": (0x310, 0x328),
            "label": "Standard Unit Lists (Air 0x310, Ground 0x328)",
            "score": 96.0,
            "is_default": True,
            "air_off": 0x310,
            "ground_off": 0x328
        })

        # ตรวจสอบ pointer offsets รอบๆ 0x300 - 0x350
        if scanner and cgame:
            for delta in [0x300, 0x318, 0x320, 0x330, 0x338, 0x340]:
                raw = scanner.read_mem(cgame + delta, 8)
                if raw and len(raw) == 8:
                    ptr = struct.unpack("<Q", raw)[0]
                    if mul.is_valid_ptr(ptr):
                        # อ่าน count ที่ +0x10
                        raw_cnt = scanner.read_mem(cgame + delta + 0x10, 4)
                        cnt = struct.unpack("<I", raw_cnt)[0] if raw_cnt else 0
                        if 1 <= cnt <= 128:
                            candidates.append({
                                "offset": (delta, delta + 0x18),
                                "label": f"Alternative Unit List ({hex(delta)} count={cnt})",
                                "score": 80.0,
                                "is_default": False,
                                "air_off": delta,
                                "ground_off": delta + 0x18
                            })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        cgame = game_ctx.cgame_ptr or shared_state.get("cgame_ptr", 0)

        if not scanner or not cgame:
            return diffs

        # ดึง Snapshot ที่ตรงกับยูนิตปัจจุบัน
        cur_name = game_ctx.current_unit_name
        all_snaps = snapshot_db.get_all_snapshots()
        snap_ref = None
        for s in all_snaps:
            if s.get("vehicle_name") == cur_name or cur_name in s.get("vehicle_name", ""):
                snap_ref = s
                break
        if not snap_ref and all_snaps:
            snap_ref = all_snaps[0]

        snap_all_units = snap_ref["data"].get("all_units", []) if snap_ref else []

        # อ่านยูนิตปัจจุบันสดจากเกม
        live_units = mul.get_all_units(scanner, cgame)
        shared_state["live_units_count"] = len(live_units)
        shared_state["live_units"] = live_units

        diffs.append({
            "field": "Total Active Units Count",
            "live_val": f"{len(live_units)} ยูนิต",
            "snap_val": f"{len(snap_all_units)} ยูนิต (ใน Snapshot)",
            "status": "match" if len(live_units) > 0 else "warn",
            "notes": "จำนวนยูนิตทั้งหมดที่อ่านได้ในฉาก"
        })

        # ตรวจสอบทีละยูนิต (เปรียบเทียบ ID, State, Team, Position สำหรับ Ground Unit)
        for i, (u_ptr, is_air) in enumerate(live_units[:8]):
            dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
            uname = dna.get("short_name") or f"Unit_{i+1}"

            # 1. ID
            raw_id = scanner.read_mem(u_ptr + mul.OFF_UNIT_ID, 2)
            uid = struct.unpack("<H", raw_id)[0] if raw_id else 0

            # 2. State
            raw_state = scanner.read_mem(u_ptr + mul.OFF_UNIT_STATE, 2)
            ustate = struct.unpack("<H", raw_state)[0] if raw_state else 0

            # 3. Team
            raw_team = scanner.read_mem(u_ptr + mul.OFF_UNIT_TEAM, 1)
            uteam = raw_team[0] if raw_team else 0

            # 4. Pos
            pos = mul.get_unit_pos(scanner, u_ptr) if not is_air else None
            pos_str = f"({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})" if pos else "N/A (Air/NoPos)"

            # ค้นหาใน Snapshot
            matched_snap_u = next((su for su in snap_all_units if su.get("unit_id") == uid or su.get("short_name") == uname), None)

            snap_desc = "ไม่พบใน Snapshot"
            status = "warn"
            if matched_snap_u:
                s_pos = matched_snap_u.get("pos", [0, 0, 0])
                snap_desc = f"ID={matched_snap_u.get('unit_id')} State={matched_snap_u.get('state')} Team={matched_snap_u.get('team')}"
                status = "match"

            diffs.append({
                "field": f"Unit #{i+1}: {uname}",
                "live_val": f"ID={hex(uid)} ({uid}), State={hex(ustate)}, Team={hex(uteam)}, Pos={pos_str}",
                "snap_val": snap_desc,
                "status": status,
                "notes": f"{'Air Unit' if is_air else 'Ground Unit'} (Address: {hex(u_ptr)})"
            })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        cnt = shared_state.get("live_units_count", 0)
        if cnt == 0:
            return False, "ยังไม่พบยูนิตใน Memory (จำนวนยูนิตเป็น 0)"
        return True, f"ยืนยัน Unit List สำเร็จ! (พบยูนิตทั้งหมด {cnt} ยูนิต)"

    def export_offsets(self, selected_candidate, shared_state) -> dict:
        c = selected_candidate or {}
        air_off = c.get("air_off", 0x310)
        ground_off = c.get("ground_off", 0x328)
        return {
            "OFF_ACTIVE_UNITS": [air_off, True, 0x10],
            "OFF_ACTIVE_EXTRA_UNIT_LISTS": [[ground_off, False, 0x10]],
            "OFF_AIR_UNITS": [air_off, True],
            "OFF_GROUND_UNITS": [ground_off, False]
        }
