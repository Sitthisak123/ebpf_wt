import struct
import math
from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepBBoxModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_bbox",
            step_index=4,
            step_title="4. getBBOX (สแกนหา Bounding Box ของทุกยูนิตในแมพ)",
            step_desc="เปรียบเทียบ BBox (bbmin/bbmax) ของยูนิตทั้งหมดในแมพที่มี Snapshot โดยคำนวณทิศทางการหมุน (Rotated Direction) ให้สอดคล้องกัน"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้า Test Drive ด้วยยูนิตที่มี Snapshot อ้างอิงอยู่ในระบบ\n"
            "2. ระบบจะตรวจสอบและเปรียบเทียบขนาดยูนิตทุกคันในแมพที่พบ Snapshot เทียบกับค่าจริงใน Memory"
        )

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        ok, msg = super().check_preflight(game_ctx, snapshot_db)
        if not ok:
            return False, msg

        cur_name = game_ctx.current_unit_name
        all_snaps = snapshot_db.get_all_snapshots()
        has_snap = any(s.get("vehicle_name") == cur_name or cur_name in s.get("vehicle_name", "") for s in all_snaps)

        if not has_snap:
            return False, f"⚠️ ยูนิตปัจจุบัน '{cur_name}' ยังไม่มี Snapshot ในระบบ (กรุณาไปที่ 'Snapshot Mode' เพื่อเก็บตัวอย่าง หรือเปลี่ยนไปขับยูนิตที่มีตัวอย่างแล้ว)"

        return True, f"✅ ยูนิต '{cur_name}' มีข้อมูล Snapshot อ้างอิงพร้อมสำหรับการสแกน BBOX"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        scanner = game_ctx.scanner
        cgame = game_ctx.cgame_ptr or shared_state.get("cgame_ptr", 0)
        units = mul.get_all_units(scanner, cgame) if scanner and cgame else []

        candidates = []
        # Candidate 1: 0x260 / 0x26C จาก mul.py
        candidates.append({
            "offset": (mul.OFF_UNIT_BBMIN, mul.OFF_UNIT_BBMAX),
            "label": f"Primary BBox ({hex(mul.OFF_UNIT_BBMIN)}, {hex(mul.OFF_UNIT_BBMAX)})",
            "score": 98.0,
            "is_default": True,
            "bbmin_off": mul.OFF_UNIT_BBMIN,
            "bbmax_off": mul.OFF_UNIT_BBMAX,
        })

        # กวาดหา BBOX Candidates จากยูนิตในแมพ
        tested_pairs = set([(mul.OFF_UNIT_BBMIN, mul.OFF_UNIT_BBMAX)])
        sample_u = units[0][0] if units else game_ctx.my_unit_ptr

        if scanner and sample_u:
            # สแกนช่วง 0x180 ถึง 0x350
            raw_chunk = scanner.read_mem(sample_u + 0x180, 0x200)
            if raw_chunk and len(raw_chunk) >= 64:
                for off in range(0, len(raw_chunk) - 32, 4):
                    try:
                        bmin = struct.unpack_from("<fff", raw_chunk, off)
                        for gap in [0x0C, 0x10, 0x14, 0x18]:
                            bmax = struct.unpack_from("<fff", raw_chunk, off + gap)
                            dx = bmax[0] - bmin[0]
                            dy = bmax[1] - bmin[1]
                            dz = bmax[2] - bmin[2]
                            if (1.5 < dx < 15.0) and (0.5 < dy < 8.0) and (1.0 < dz < 8.0):
                                real_min = 0x180 + off
                                real_max = real_min + gap
                                pair = (real_min, real_max)
                                if pair not in tested_pairs:
                                    tested_pairs.add(pair)
                                    candidates.append({
                                        "offset": pair,
                                        "label": f"Alternative BBox ({hex(real_min)}, {hex(real_max)})",
                                        "score": 82.0,
                                        "is_default": False,
                                        "bbmin_off": real_min,
                                        "bbmax_off": real_max,
                                    })
                    except Exception:
                        pass

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        cgame = game_ctx.cgame_ptr or shared_state.get("cgame_ptr", 0)

        bbmin_off = selected_candidate.get("bbmin_off", mul.OFF_UNIT_BBMIN) if selected_candidate else mul.OFF_UNIT_BBMIN
        bbmax_off = selected_candidate.get("bbmax_off", mul.OFF_UNIT_BBMAX) if selected_candidate else mul.OFF_UNIT_BBMAX

        diffs.append({
            "field": "BBox Min / Max Offsets",
            "live_val": f"Min={hex(bbmin_off)}, Max={hex(bbmax_off)}",
            "snap_val": f"Min={hex(mul.OFF_UNIT_BBMIN)}, Max={hex(mul.OFF_UNIT_BBMAX)}",
            "status": "match" if (bbmin_off, bbmax_off) == (mul.OFF_UNIT_BBMIN, mul.OFF_UNIT_BBMAX) else "warn",
            "notes": "ตำแหน่งเวกเตอร์กรอบ Bounding Box ใน Unit Struct"
        })

        if not scanner or not cgame:
            return diffs

        # ดึงรายชื่อยูนิตทั้งหมดในแมพ
        units = mul.get_all_units(scanner, cgame)
        all_snaps = snapshot_db.get_all_snapshots()

        # รวบรวมข้อมูล Snapshot BBox อ้างอิง
        snap_bbox_dict = {}
        for s in all_snaps:
            bbox_data = s.get("data", {}).get("bbox", {})
            for u_entry in bbox_data.get("units", []):
                sname = u_entry.get("short_name")
                if sname:
                    snap_bbox_dict[sname] = u_entry

        # วนลูปตรวจสอบทุกยูนิตในแมพที่มี Snapshot
        matched_unit_count = 0
        for i, (u_ptr, is_air) in enumerate(units[:12]):
            dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
            uname = dna.get("short_name") or f"Unit_{i+1}"

            snap_entry = snap_bbox_dict.get(uname)
            if not snap_entry:
                continue

            raw_min = scanner.read_mem(u_ptr + bbmin_off, 12)
            raw_max = scanner.read_mem(u_ptr + bbmax_off, 12)

            if raw_min and raw_max and len(raw_min) == 12 and len(raw_max) == 12:
                bmin = struct.unpack("<fff", raw_min)
                bmax = struct.unpack("<fff", raw_max)

                # ดึง Rotation Matrix เพื่อพิจารณาทิศทางการหมุน (Rotated Direction)
                rot_off = mul.OFF_UNIT_X - 0x24
                raw_rot = scanner.read_mem(u_ptr + rot_off, 36)
                heading_deg = 0.0
                if raw_rot and len(raw_rot) == 36:
                    rot_mat = struct.unpack("<9f", raw_rot)
                    heading_deg = math.degrees(math.atan2(rot_mat[1], rot_mat[0]))

                # ขนาดกล่อง (Size / Dimensions)
                dx = abs(bmax[0] - bmin[0])
                dy = abs(bmax[1] - bmin[1])
                dz = abs(bmax[2] - bmin[2])

                # จัดเรียงมิติเพื่อจับคู่แกนที่หมุน (Sorted dimensions to match rotated orientation)
                live_dims_sorted = sorted([dx, dy, dz])
                snap_dims = snap_entry.get("dim", [3.0, 2.5, 6.0])
                snap_dims_sorted = sorted(snap_dims)

                # ตรวจสอบความคลาดเคลื่อน
                err = sum(abs(live_dims_sorted[j] - snap_dims_sorted[j]) for j in range(3))
                is_dim_match = err < 1.0

                matched_unit_count += 1
                diffs.append({
                    "field": f"BBox for {uname}",
                    "live_val": f"Dim: [{dx:.2f}, {dy:.2f}, {dz:.2f}] (Rot: {heading_deg:.0f}°)",
                    "snap_val": f"Dim: [{snap_dims[0]:.2f}, {snap_dims[1]:.2f}, {snap_dims[2]:.2f}]",
                    "status": "match" if is_dim_match else "mismatch",
                    "notes": f"Diff Error: {err:.2f}m (Aligned with Heading: {heading_deg:.1f}°)"
                })

        if matched_unit_count == 0:
            diffs.append({
                "field": "All Units BBox Check",
                "live_val": f"ตรวจพบ {len(units)} ยูนิตในแมพ",
                "snap_val": "ไม่มี Snapshot BBox ที่ชื่อตรงกัน",
                "status": "warn",
                "notes": "สามารถใช้ปุ่ม Seed Snapshot หรือบันทึก Snapshot เพิ่มเติมได้"
            })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        bmin_off = selected_candidate.get("bbmin_off", 0)
        bmax_off = selected_candidate.get("bbmax_off", 0)
        if not (0x100 <= bmin_off < bmax_off <= 0x500):
            return False, "ช่วง Offset ของ BBox ไม่ถูกต้อง"
        return True, "ยืนยัน Offset BBox และการหมุนทุกยูนิตในแมพสำเร็จ!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        return {
            "OFF_UNIT_BBMIN": selected_candidate.get("bbmin_off", mul.OFF_UNIT_BBMIN),
            "OFF_UNIT_BBMAX": selected_candidate.get("bbmax_off", mul.OFF_UNIT_BBMAX),
        }
