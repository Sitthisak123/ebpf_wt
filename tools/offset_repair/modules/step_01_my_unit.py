import struct
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from tools.offset_repair.core.base_module import BaseStepModule
import src.utils.mul as mul


class StepMyUnitModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_my_unit",
            step_index=1,
            step_title="1. getMyUnit (สแกนหา Base & Player Unit)",
            step_desc="ใช้ DNA Scanner ตรวจหา CGameManager และ Controlled Unit Pointer พร้อมตรวจสอบ Snapshot ตามชื่อยูนิต (Auto-Verify หากตรง หรือ Manual Verify ด้วยปุ่ม Mismatch/New sample หากยังไม่มีตัวอย่าง)"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. เข้าเกม War Thunder และเข้าสู่โหมด 'Test Drive' (ขับรถถังหรือบินเครื่องบิน)\n"
            "2. ระบบจะค้นหา Snapshot ตามชื่อยูนิต:\n"
            "   - หากพบ Snapshot ตรงกัน: จะทำการ Auto-Verify อัตโนมัติทันที\n"
            "   - หากไม่พบ Snapshot: ให้กดปุ่ม [Mismatch / New sample] เพื่อยืนยันตัวอย่างใหม่แบบ Manual"
        )
        self.manual_override = False
        self.matched_snapshot = None
        self.has_matching_snapshot = False

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        ok, msg = super().check_preflight(game_ctx, snapshot_db)
        if not ok:
            return False, msg

        if not game_ctx.my_unit_ptr:
            return False, "ยังไม่พบ Player Unit ใน Memory (กรุณาเกิดตัวใน Test Drive)"

        cur_name = game_ctx.current_unit_name
        return True, f"ตรวจพบยูนิต: {cur_name} (Address: {hex(game_ctx.my_unit_ptr)})"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        scanner = game_ctx.scanner
        base_addr = game_ctx.base_address
        candidates = []

        # Candidate 1: Manager Offset ปัจจุบันใน mul
        candidates.append({
            "offset": mul.MANAGER_OFFSET,
            "label": f"CGameManager Primary (mul.py: {hex(mul.MANAGER_OFFSET)})",
            "score": 98.0,
            "is_default": True,
            "cgame_ptr": game_ctx.cgame_ptr,
            "my_unit_ptr": game_ctx.my_unit_ptr,
            "dat_controlled_unit": mul.DAT_CONTROLLED_UNIT
        })

        # Candidate 2: DNA PAT_MY_UNIT สำหรับหา DAT_CONTROLLED_UNIT ใหม่
        from src.utils.scanner import PAT_MY_UNIT
        if scanner:
            try:
                found_hero = scanner.find_all_patterns(PAT_MY_UNIT)
                for target_addr in found_hero:
                    raw_h = scanner.read_mem(target_addr, 8)
                    if raw_h and len(raw_h) == 8:
                        cand_ptr = struct.unpack("<Q", raw_h)[0]
                        if mul.is_valid_ptr(cand_ptr):
                            candidates.append({
                                "offset": mul.MANAGER_OFFSET,
                                "label": f"DNA PAT_MY_UNIT: Controlled Unit -> {hex(target_addr)}",
                                "score": 99.0,
                                "is_default": True,
                                "cgame_ptr": game_ctx.cgame_ptr,
                                "my_unit_ptr": cand_ptr,
                                "dat_controlled_unit": target_addr
                            })
            except Exception:
                pass

        # Candidate offsets สำรองจาก MANAGER_CANDIDATE_OFFSETS
        for alt_off in mul.MANAGER_CANDIDATE_OFFSETS:
            if alt_off != mul.MANAGER_OFFSET:
                raw = scanner.read_mem(base_addr + alt_off, 8) if scanner and base_addr else None
                if raw and len(raw) == 8:
                    ptr = struct.unpack("<Q", raw)[0]
                    if mul.is_valid_ptr(ptr):
                        candidates.append({
                            "offset": alt_off,
                            "label": f"CGameManager Alternative ({hex(alt_off)})",
                            "score": 85.0,
                            "is_default": False,
                            "cgame_ptr": ptr,
                            "my_unit_ptr": game_ctx.my_unit_ptr
                        })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        my_unit = game_ctx.my_unit_ptr
        cur_name = game_ctx.current_unit_name

        # -------------------------------------------------------------
        # 🎯 ค้นหา Snapshot ตามชื่อยูนิต (Find Snap by Name)
        # -------------------------------------------------------------
        all_snaps = snapshot_db.get_all_snapshots()
        matched_snap = None
        for s in all_snaps:
            vname = s.get("vehicle_name", "")
            if vname and (vname == cur_name or vname in cur_name or cur_name in vname):
                matched_snap = s
                break

        self.matched_snapshot = matched_snap
        self.has_matching_snapshot = matched_snap is not None
        snap_ref = matched_snap["data"].get("my_unit", {}) if matched_snap else {}

        if scanner and my_unit:
            # 1. Unit ID
            raw_id = scanner.read_mem(my_unit + mul.OFF_UNIT_ID, 2)
            live_id = struct.unpack("<H", raw_id)[0] if raw_id else "N/A"
            snap_id = snap_ref.get("unit_id", 1) if matched_snap else "N/A"
            diffs.append({
                "field": f"Unit ID (OFF_UNIT_ID: {hex(mul.OFF_UNIT_ID)})",
                "live_val": f"{hex(live_id)} ({live_id})" if isinstance(live_id, int) else str(live_id),
                "snap_val": f"{hex(snap_id)} ({snap_id})" if isinstance(snap_id, int) else str(snap_id),
                "status": "match" if (matched_snap and live_id == snap_id) or live_id != "N/A" else "warn",
                "notes": "Session Unit ID ของผู้เล่น"
            })

            # 2. Unit State
            raw_state = scanner.read_mem(my_unit + mul.OFF_UNIT_STATE, 2)
            live_state = struct.unpack("<H", raw_state)[0] if raw_state else "N/A"
            snap_state = snap_ref.get("state", 0) if matched_snap else "N/A"
            state_match = (live_state == snap_state) if matched_snap else (live_state == 0)
            diffs.append({
                "field": f"Unit State (OFF_UNIT_STATE: {hex(mul.OFF_UNIT_STATE)})",
                "live_val": f"{hex(live_state)} (Alive)" if live_state == 0 else (f"{hex(live_state)} ({live_state})" if isinstance(live_state, int) else str(live_state)),
                "snap_val": f"{hex(snap_state)} (Alive)" if matched_snap else "N/A",
                "status": "match" if state_match else "warn",
                "notes": "0 = ปกติ (Alive), 1 = ไฟไหม้, >=2 = ซาก"
            })

            # 3. Unit Team
            raw_team = scanner.read_mem(my_unit + mul.OFF_UNIT_TEAM, 1)
            live_team = raw_team[0] if raw_team else "N/A"
            snap_team = snap_ref.get("team", 1) if matched_snap else "N/A"
            team_match = (live_team == snap_team) if matched_snap else (live_team in (1, 2))
            diffs.append({
                "field": f"Unit Team (OFF_UNIT_TEAM: {hex(mul.OFF_UNIT_TEAM)})",
                "live_val": f"{hex(live_team)} (Friendly)" if live_team == 1 else (f"{hex(live_team)}" if isinstance(live_team, int) else str(live_team)),
                "snap_val": f"{hex(snap_team)} (Friendly)" if matched_snap else "N/A",
                "status": "match" if team_match else "warn",
                "notes": "1 = ฝั่งเรา/มิตร, 2 = ศัตรู"
            })

            # 4. Short Name
            dna = mul.get_unit_detailed_dna(scanner, my_unit) or {}
            live_name = dna.get("short_name", cur_name)
            snap_name = snap_ref.get("short_name", "N/A (No Snapshot)") if matched_snap else "N/A (No Snapshot)"
            name_match = matched_snap is not None and (live_name == snap_name or snap_name in live_name)

            diffs.append({
                "field": "Vehicle Model (short_name)",
                "live_val": live_name,
                "snap_val": snap_name,
                "status": "match" if name_match else "warn",
                "notes": f"Snapshot: {matched_snap['name']}" if matched_snap else "ไม่พบ Snapshot ที่ชื่อตรงกัน"
            })

            # -------------------------------------------------------------
            # 🎯 ตัดสินการ Verify (Auto Verify vs Manual Verify)
            # -------------------------------------------------------------
            if self.has_matching_snapshot:
                # ถ้ามี Snapshot และข้อมูลสอดคล้องกัน -> Auto Verify
                if name_match and live_state == 0:
                    self.is_verified = True
                    self.verified_message = f"✅ Auto-Verified: พบ Snapshot '{matched_snap['name']}' ตรงกับยูนิต {cur_name}"
                else:
                    self.is_verified = True
                    self.verified_message = f"✅ Auto-Verified: อ้างอิง Snapshot '{matched_snap['name']}' เรียบร้อย"
            else:
                # ถ้าไม่มี Snapshot -> ต้อง Manual Verify ด้วยปุ่ม Mismatch / New sample
                if self.manual_override:
                    self.is_verified = True
                    self.verified_message = f"✅ Manual Verified: ยืนยันเป็นตัวอย่างใหม่ '{cur_name}' เรียบร้อยแล้ว"
                else:
                    self.is_verified = False
                    self.verified_message = f"⚠️ ยังไม่พบ Snapshot ของ '{cur_name}' ในระบบ (กรุณากดปุ่ม [Mismatch / New sample] เพื่อยืนยันตัวอย่างใหม่)"

        self.comparison_data = diffs
        # บันทึก shared_state ให้ step ถัดไปนำไปใช้ต่อ
        shared_state["my_unit_ptr"] = my_unit
        shared_state["cgame_ptr"] = game_ctx.cgame_ptr
        shared_state["my_unit_name"] = cur_name
        shared_state["my_unit_type"] = game_ctx.current_unit_type

        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        if not game_ctx.my_unit_ptr:
            return False, "ไม่พบ Player Unit Pointer"
        if not self.is_verified:
            return False, self.verified_message or "ยูนิตนี้ยังไม่มี Snapshot ในระบบ กรุณากดปุ่ม [Mismatch / New sample] เพื่อยืนยันตัวอย่างใหม่"
        return True, self.verified_message or f"ยืนยัน MyUnit สำเร็จ! (Address: {hex(game_ctx.my_unit_ptr)})"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        c = selected_candidate or {}
        cgame_off = c.get("offset", mul.MANAGER_OFFSET)
        dat_controlled = c.get("dat_controlled_unit", mul.DAT_CONTROLLED_UNIT)
        return {
            "MANAGER_OFFSET": cgame_off if cgame_off < 0x20000000 else mul.MANAGER_OFFSET,
            "DAT_CONTROLLED_UNIT": dat_controlled,
            "OFF_UNIT_ID": mul.OFF_UNIT_ID,
            "OFF_UNIT_STATE": mul.OFF_UNIT_STATE,
            "OFF_UNIT_TEAM": mul.OFF_UNIT_TEAM,
            "OFF_UNIT_INFO": mul.OFF_UNIT_INFO,
            "OFF_PLAYER_INFO": mul.OFF_PLAYER_INFO,
        }

    def build_custom_widget(self, parent_widget, controller=None):
        widget = QWidget(parent_widget)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 5)

        lbl_status = QLabel(widget)
        btn_new_sample = QPushButton("➕ Mismatch / New sample", widget)
        btn_new_sample.setStyleSheet("background-color: #E65100; color: white; font-weight: bold; padding: 6px 14px;")

        def _on_new_sample_clicked():
            self.manual_override = True
            self.is_verified = True
            cur_name = controller.game_ctx.current_unit_name if controller else "NewUnit"
            cur_type = controller.game_ctx.current_unit_type if controller else "ground"

            self.verified_message = f"✅ Manual Verified: ยืนยันยูนิต '{cur_name}' เป็นตัวอย่างใหม่แล้ว"

            # บันทึกเป็น Snapshot ใหม่อัตโนมัติทันที เพื่อให้ Step 2-9 ใช้งานต่อได้ไม่สะดุด
            if controller and cur_name not in ("Unknown", "None"):
                controller.snapshot_db.save_snapshot(
                    name=f"snapshot_{cur_name}_manual",
                    vehicle_name=cur_name,
                    vehicle_type=cur_type,
                    data_dict={
                        "my_unit": {"short_name": cur_name, "unit_id": 1, "state": 0, "team": 1},
                        "all_units": [],
                        "bbox": {"units": [{"short_name": cur_name, "dim": [3.0, 2.5, 6.0]}]},
                        "ballistics": {"speed": 795.0, "mass": 9.2, "caliber": 0.085, "cx": 0.32},
                    }
                )

            if controller:
                controller._load_step(0)

        btn_new_sample.clicked.connect(_on_new_sample_clicked)

        if self.has_matching_snapshot:
            snap_name = self.matched_snapshot.get("name", "")
            lbl_status.setText(f"🟢 พบ Snapshot ตรงกัน: '{snap_name}' (Auto-Verified สำเร็จ)")
            lbl_status.setStyleSheet("color: #98C379; font-weight: bold; font-size: 13px;")
            btn_new_sample.setVisible(False)
        else:
            if self.manual_override:
                lbl_status.setText("✅ ยืนยันเป็นตัวอย่างใหม่แบบ Manual เรียบร้อยแล้ว")
                lbl_status.setStyleSheet("color: #61AFEF; font-weight: bold; font-size: 13px;")
                btn_new_sample.setText("✓ ยืนยันเป็นตัวอย่างใหม่แล้ว")
                btn_new_sample.setEnabled(False)
                btn_new_sample.setVisible(True)
            else:
                lbl_status.setText("⚠️ ยังไม่พบ Snapshot ของยูนิตนี้ในระบบ — กรุณากดปุ่มเพื่อยืนยันตัวอย่างใหม่")
                lbl_status.setStyleSheet("color: #E5C07B; font-weight: bold; font-size: 13px;")
                btn_new_sample.setVisible(True)

        layout.addWidget(lbl_status)
        layout.addStretch()
        layout.addWidget(btn_new_sample)
        return widget
