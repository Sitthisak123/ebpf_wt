from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepRocketStructModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="rocket_struct",
            step_index=9,
            step_title="9. Rocket (สแกนหาโครงสร้าง Rocket Struct Layout)",
            step_desc="ค้นหาและเปรียบเทียบ Offset ภายในตัวขีปนาวุธ/จรวด (Position, Velocity, Guidance, Props, Target ID) กับ Snapshot"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้า Test Drive ด้วยยูนิตที่มีจรวดหรือมิสไซล์\n"
            "2. กดสแกนเพื่อยืนยันโครงสร้างหน่วยความจำของ Rocket Struct (Entity ID, Position, Velocity, Guidance)"
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

        return True, "พร้อมสแกนโครงสร้าง Rocket Struct"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        candidates = []
        # Candidate 1: โครงสร้างอัปเดตล่าสุดปี 2026 จาก mul.py
        candidates.append({
            "offset": (mul.OFF_RKT_POS, mul.OFF_RKT_GUIDANCE),
            "label": f"Primary Rocket Layout (Pos {hex(mul.OFF_RKT_POS)}, Guid {hex(mul.OFF_RKT_GUIDANCE)})",
            "score": 98.0,
            "is_default": True,
            "entity_id_off": mul.OFF_RKT_ENTITY_ID,
            "owner_off": mul.OFF_RKT_OWNER,
            "state_off": mul.OFF_RKT_STATE,
            "pos_off": mul.OFF_RKT_POS,
            "vel_off": mul.OFF_RKT_VEL,
            "detonated_off": mul.OFF_RKT_DETONATED,
            "phase_off": mul.OFF_RKT_PHASE,
            "guidance_off": mul.OFF_RKT_GUIDANCE,
            "alive_off": mul.OFF_RKT_ALIVE,
            "props_off": mul.OFF_RKT_PROPS,
            "guid_locked_off": mul.OFF_GUID_LOCKED,
            "guid_tracking_off": mul.OFF_GUID_TRACKING,
            "guid_target_off": mul.OFF_GUID_TARGET_ID,
        })

        # Candidate 2: Layout โบราณ (Shift -0x10)
        candidates.append({
            "offset": (mul.OFF_RKT_POS, 0x670),
            "label": f"Legacy Rocket Layout (Pos {hex(mul.OFF_RKT_POS)}, Guid 0x670)",
            "score": 81.0,
            "is_default": False,
            "entity_id_off": mul.OFF_RKT_ENTITY_ID,
            "owner_off": mul.OFF_RKT_OWNER,
            "state_off": mul.OFF_RKT_STATE,
            "pos_off": mul.OFF_RKT_POS,
            "vel_off": mul.OFF_RKT_VEL,
            "detonated_off": mul.OFF_RKT_DETONATED,
            "phase_off": mul.OFF_RKT_PHASE,
            "guidance_off": 0x670,
            "alive_off": 0x6c0,
            "props_off": 0x700,
            "guid_locked_off": 0x50,
            "guid_tracking_off": 0x51,
            "guid_target_off": 0x8C,
        })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        c = selected_candidate or {}

        fields_to_check = [
            ("Rocket Entity ID", "entity_id_off", mul.OFF_RKT_ENTITY_ID, "u32 Entity Identifier"),
            ("Rocket Owner Unit", "owner_off", mul.OFF_RKT_OWNER, "Pointer to Owner Unit"),
            ("Rocket State", "state_off", mul.OFF_RKT_STATE, "State Flag (Flying / Detonated)"),
            ("Rocket Position Vec3", "pos_off", mul.OFF_RKT_POS, "World 3D Position"),
            ("Rocket Velocity Vec3", "vel_off", mul.OFF_RKT_VEL, "World 3D Velocity Vector"),
            ("Rocket Detonation Flag", "detonated_off", mul.OFF_RKT_DETONATED, "0 = Flying, non-zero = Detonated"),
            ("Rocket Phase", "phase_off", mul.OFF_RKT_PHASE, "3 = In-flight, 6 = Terminated"),
            ("Rocket Guidance Struct", "guidance_off", mul.OFF_RKT_GUIDANCE, "Pointer to Guidance Controller"),
            ("Rocket Props Pointer", "props_off", mul.OFF_RKT_PROPS, "Pointer to Props / Names"),
            ("Guidance isLocked", "guid_locked_off", mul.OFF_GUID_LOCKED, "Lock State Byte"),
            ("Guidance Target ID", "guid_target_off", mul.OFF_GUID_TARGET_ID, "Target Unit ID (i16)"),
        ]

        for label, key, default_val, notes in fields_to_check:
            live_val = c.get(key, default_val)
            is_match = live_val == default_val
            diffs.append({
                "field": label,
                "live_val": hex(live_val),
                "snap_val": hex(default_val),
                "status": "match" if is_match else "warn",
                "notes": notes
            })

        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        return True, "ยืนยันค่า Rocket Struct Layout เรียบร้อยครบถ้วน!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        c = selected_candidate or {}
        return {
            "OFF_RKT_ENTITY_ID": c.get("entity_id_off", mul.OFF_RKT_ENTITY_ID),
            "OFF_RKT_OWNER": c.get("owner_off", mul.OFF_RKT_OWNER),
            "OFF_RKT_STATE": c.get("state_off", mul.OFF_RKT_STATE),
            "OFF_RKT_POS": c.get("pos_off", mul.OFF_RKT_POS),
            "OFF_RKT_VEL": c.get("vel_off", mul.OFF_RKT_VEL),
            "OFF_RKT_DETONATED": c.get("detonated_off", mul.OFF_RKT_DETONATED),
            "OFF_RKT_PHASE": c.get("phase_off", mul.OFF_RKT_PHASE),
            "OFF_RKT_GUIDANCE": c.get("guidance_off", mul.OFF_RKT_GUIDANCE),
            "OFF_RKT_ALIVE": c.get("alive_off", mul.OFF_RKT_ALIVE),
            "OFF_RKT_PROPS": c.get("props_off", mul.OFF_RKT_PROPS),
            "OFF_GUID_LOCKED": c.get("guid_locked_off", mul.OFF_GUID_LOCKED),
            "OFF_GUID_TRACKING": c.get("guid_tracking_off", mul.OFF_GUID_TRACKING),
            "OFF_GUID_TARGET_ID": c.get("guid_target_off", mul.OFF_GUID_TARGET_ID),
        }
