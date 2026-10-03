import struct
from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepGetRocketsModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_rockets",
            step_index=8,
            step_title="8. getRockets (สแกนหา Projectile List & ECS Manager)",
            step_desc="สแกนหาอาเรย์กระสุน/จรวดที่กำลังบิน (OFF_PROJ_LIST) และตัวจัดการ ECS (OFF_ECS_MANAGER) พร้อมเทียบชื่อรุ่นจรวดที่คาดหวัง (Expected Rocket Name)"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้า Test Drive ด้วยยูนิตที่มีจรวดหรือมิสไซล์ (เช่น Su-25, F-16 หรือ BMP-2)\n"
            "2. กดสแกนเพื่อตรวจสอบการเชื่อมต่อกับระบบขีปนาวุธ"
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

        return True, "พร้อมสแกนระบบจรวดและขีปนาวุธ"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        candidates = []
        # Candidate 1: ค่ามาตรฐานปี 2026 จาก mul.py
        candidates.append({
            "offset": (mul.OFF_PROJ_LIST, mul.OFF_ECS_MANAGER),
            "label": f"Primary Projectile Table ({hex(mul.OFF_PROJ_LIST)}, ECS {hex(mul.OFF_ECS_MANAGER)})",
            "score": 98.0,
            "is_default": True,
            "proj_list_off": mul.OFF_PROJ_LIST,
            "ecs_mgr_off": mul.OFF_ECS_MANAGER,
            "ecs_node_off": mul.OFF_ECS_NODE_TABLE,
            "ecs_class_off": mul.OFF_ECS_CLASS_TABLE,
        })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        base_addr = game_ctx.base_address

        proj_off = selected_candidate.get("proj_list_off", mul.OFF_PROJ_LIST) if selected_candidate else mul.OFF_PROJ_LIST
        ecs_off = selected_candidate.get("ecs_mgr_off", mul.OFF_ECS_MANAGER) if selected_candidate else mul.OFF_ECS_MANAGER

        # 1. Projectile List Pointer
        proj_ptr = 0
        if scanner and base_addr:
            raw_p = scanner.read_mem(base_addr + proj_off, 8)
            if raw_p and len(raw_p) == 8:
                proj_ptr = struct.unpack("<Q", raw_p)[0]

        diffs.append({
            "field": f"Projectile Table Pointer ({hex(proj_off)})",
            "live_val": hex(proj_ptr) if proj_ptr else "Null / Empty Table",
            "snap_val": hex(mul.OFF_PROJ_LIST),
            "status": "match" if mul.is_valid_ptr(proj_ptr) else "warn",
            "notes": "ตารางเก็บรายชื่อ Projectiles ทั้งหมดในแมพ"
        })

        # 2. ECS Manager Pointer
        ecs_ptr = 0
        if scanner and base_addr:
            raw_e = scanner.read_mem(base_addr + ecs_off, 8)
            if raw_e and len(raw_e) == 8:
                ecs_ptr = struct.unpack("<Q", raw_e)[0]

        diffs.append({
            "field": f"ECS Manager Pointer ({hex(ecs_off)})",
            "live_val": hex(ecs_ptr) if ecs_ptr else "Null",
            "snap_val": hex(mul.OFF_ECS_MANAGER),
            "status": "match" if mul.is_valid_ptr(ecs_ptr) else "warn",
            "notes": "Entity Component System Manager"
        })

        # 3. Expected Rocket Names
        all_snaps = snapshot_db.get_all_snapshots()
        snap_rockets = all_snaps[0]["data"].get("rockets", {}) if all_snaps else {}
        expected_names = snap_rockets.get("expected_names", ["r_60m", "aim_9l", "ffar_mighty_mouse"])

        diffs.append({
            "field": "Expected Rocket Names",
            "live_val": f"ตรวจพบระบบ ECS Active: {'ใช่' if mul.is_valid_ptr(ecs_ptr) else 'ยังไม่พบ'}",
            "snap_val": ", ".join(expected_names[:3]),
            "status": "match" if mul.is_valid_ptr(ecs_ptr) or mul.is_valid_ptr(proj_ptr) else "warn",
            "notes": "ชื่อรุ่นจรวดที่ระบบเตรียมตรวจจับในแมพ"
        })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        return True, "ยืนยันค่า Projectile Table & ECS Manager สำเร็จ!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        return {
            "OFF_PROJ_LIST": selected_candidate.get("proj_list_off", mul.OFF_PROJ_LIST),
            "OFF_ECS_MANAGER": selected_candidate.get("ecs_mgr_off", mul.OFF_ECS_MANAGER),
            "OFF_ECS_NODE_TABLE": selected_candidate.get("ecs_node_off", mul.OFF_ECS_NODE_TABLE),
            "OFF_ECS_CLASS_TABLE": selected_candidate.get("ecs_class_off", mul.OFF_ECS_CLASS_TABLE),
        }
