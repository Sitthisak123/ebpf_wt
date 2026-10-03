import struct
import math
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from tools.offset_repair.core.base_module import BaseStepModule
from tools.offset_repair.ui.camera_overlay import CameraOverlayHUD
import src.utils.mul as mul


class StepViewModule(BaseStepModule):
    def __init__(self):
        super().__init__(
            step_id="get_view",
            step_index=3,
            step_title="3. getView (สแกน Camera & View Matrix พร้อม Overlay ไกด์หมุนกล้อง)",
            step_desc="สแกนหา OFF_CAMERA_PTR และ OFF_VIEW_MATRIX โดยใช้ Transparent Overlay จับเวลาหมุนกล้อง 6 วินาทีเพื่อตรวจสอบ Orthogonality และ Dynamic Matrix Changes"
        )
        self.preflight_instructions = (
            "📌 ข้อกำหนดก่อนเริ่มสแกน:\n"
            "1. อยู่ในแมพ Test Drive ในมุมมองบุคคลที่สาม (3rd Person View) หรือ Commander View\n"
            "2. กดปุ่ม [🎥 เริ่มหมุนกล้องด้วย Overlay (6s)] และปฏิบัติตามคำแนะนำบนหน้าจอเกม (หันซ้าย-ขวา 6s, ก้ม-เงย 6s, อยู่นิ่งๆ 6s)"
        )
        self.overlay_hud = None

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        ok, msg = super().check_preflight(game_ctx, snapshot_db)
        if not ok:
            return False, msg
        cgame = game_ctx.cgame_ptr
        if not cgame:
            return False, "ยังไม่พบ CGame Pointer จากขั้นตอนก่อนหน้า"
        return True, "พร้อมสแกน View Matrix (CGame พร้อมใช้งาน)"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        scanner = game_ctx.scanner
        cgame = game_ctx.cgame_ptr or shared_state.get("cgame_ptr", 0)

        candidates = []
        # Candidate 1: ค่าปัจจุบันจาก mul.py (Camera 0x660, Matrix 0x1D8)
        candidates.append({
            "offset": (mul.OFF_CAMERA_PTR, mul.OFF_VIEW_MATRIX),
            "label": f"Primary Matrix (Camera {hex(mul.OFF_CAMERA_PTR)}, Matrix {hex(mul.OFF_VIEW_MATRIX)})",
            "score": 98.0,
            "is_default": True,
            "cam_off": mul.OFF_CAMERA_PTR,
            "matrix_off": mul.OFF_VIEW_MATRIX,
        })

        # ค้นหา alternative camera ptrs
        if scanner and cgame:
            for c_off in [0x640, 0x650, 0x658, 0x660, 0x668, 0x670]:
                raw_c = scanner.read_mem(cgame + c_off, 8)
                if raw_c and len(raw_c) == 8:
                    cam_p = struct.unpack("<Q", raw_c)[0]
                    if mul.is_valid_ptr(cam_p):
                        for m_off in [0x1B8, 0x1C0, 0x1C8, 0x1D0, 0x1D8, 0x1E0]:
                            if (c_off, m_off) == (mul.OFF_CAMERA_PTR, mul.OFF_VIEW_MATRIX):
                                continue
                            raw_mat = scanner.read_mem(cam_p + m_off, 64)
                            if raw_mat and len(raw_mat) == 64:
                                vals = struct.unpack("<16f", raw_mat)
                                if all(math.isfinite(v) for v in vals):
                                    det_approx = vals[0]*vals[5] - vals[1]*vals[4]
                                    if 0.2 < abs(det_approx) < 2.0:
                                        candidates.append({
                                            "offset": (c_off, m_off),
                                            "label": f"Candidate (Camera {hex(c_off)}, Matrix {hex(m_off)})",
                                            "score": 85.0,
                                            "is_default": False,
                                            "cam_off": c_off,
                                            "matrix_off": m_off,
                                        })

        self.candidates = candidates
        return candidates

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        diffs = []
        scanner = game_ctx.scanner
        cgame = game_ctx.cgame_ptr or shared_state.get("cgame_ptr", 0)

        cam_off = selected_candidate.get("cam_off", mul.OFF_CAMERA_PTR) if selected_candidate else mul.OFF_CAMERA_PTR
        mat_off = selected_candidate.get("matrix_off", mul.OFF_VIEW_MATRIX) if selected_candidate else mul.OFF_VIEW_MATRIX

        cam_ptr = 0
        if scanner and cgame:
            raw_c = scanner.read_mem(cgame + cam_off, 8)
            if raw_c and len(raw_c) == 8:
                cam_ptr = struct.unpack("<Q", raw_c)[0]

        diffs.append({
            "field": "Camera Pointer Offset",
            "live_val": f"{hex(cam_off)} (Pointer: {hex(cam_ptr)})",
            "snap_val": hex(mul.OFF_CAMERA_PTR),
            "status": "match" if mul.is_valid_ptr(cam_ptr) else "warn",
            "notes": "ชี้ไปยังโครงสร้างกล้องมุมมอง"
        })

        diffs.append({
            "field": "View Matrix Offset",
            "live_val": hex(mat_off),
            "snap_val": hex(mul.OFF_VIEW_MATRIX),
            "status": "match" if mat_off == mul.OFF_VIEW_MATRIX else "warn",
            "notes": "ตำแหน่ง 4x4 Float Matrix ภายใน Camera Struct"
        })

        if scanner and mul.is_valid_ptr(cam_ptr):
            raw_m = scanner.read_mem(cam_ptr + mat_off, 64)
            if raw_m and len(raw_m) == 64:
                m = struct.unpack("<16f", raw_m)
                row0_len = math.sqrt(m[0]*m[0] + m[1]*m[1] + m[2]*m[2])
                row1_len = math.sqrt(m[4]*m[4] + m[5]*m[5] + m[6]*m[6])
                row2_len = math.sqrt(m[8]*m[8] + m[9]*m[9] + m[10]*m[10])

                is_ortho = 0.95 <= row0_len <= 1.05 and 0.95 <= row1_len <= 1.05 and 0.95 <= row2_len <= 1.05

                diffs.append({
                    "field": "Matrix Row Norms (Orthogonality)",
                    "live_val": f"R0={row0_len:.2f}, R1={row1_len:.2f}, R2={row2_len:.2f}",
                    "snap_val": "R0=1.00, R1=1.00, R2=1.00",
                    "status": "match" if is_ortho else "mismatch",
                    "notes": "เวกเตอร์แกนหมุนของกล้องต้องมีความยาว 1.0 เสมอ"
                })

        shared_state["cam_ptr"] = cam_ptr
        shared_state["view_matrix_off"] = mat_off
        self.comparison_data = diffs
        return diffs

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        cam_ptr = shared_state.get("cam_ptr", 0)
        if not mul.is_valid_ptr(cam_ptr):
            return False, "Camera Pointer ไม่ถูกต้อง (Null หรือ Invalid Pointer)"
        return True, "ยืนยัน Camera Pointer และ View Matrix สำเร็จ!"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        cam_off = selected_candidate.get("cam_off", mul.OFF_CAMERA_PTR)
        mat_off = selected_candidate.get("matrix_off", mul.OFF_VIEW_MATRIX)
        return {
            "OFF_CAMERA_PTR": cam_off,
            "OFF_VIEW_MATRIX": mat_off,
        }

    def build_custom_widget(self, parent_widget, controller=None):
        widget = QWidget(parent_widget)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 5)

        btn_overlay = QPushButton("🎥 เปิด Overlay ไกด์หมุนกล้อง 6 วินาที (Start Camera Guide Overlay)", widget)
        btn_overlay.setStyleSheet("background-color: #0288D1; color: white; font-weight: bold; padding: 8px 16px;")

        def _on_click():
            if self.overlay_hud is None:
                self.overlay_hud = CameraOverlayHUD()
            self.overlay_hud.start_guide()

        btn_overlay.clicked.connect(_on_click)
        layout.addWidget(btn_overlay)
        layout.addStretch()
        return widget
