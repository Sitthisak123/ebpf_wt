import math
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QApplication
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen, QFont


class CCIPVerificationOverlay(QWidget):
    """
    Transparent HUD Overlay สำหรับ getAirMovements & DirectCCIP
    แสดง ESP สำหรับ Hovering Target, Locking Target, SimCCIP, DirectCCIP
    และตรวจสอบเงื่อนไขการ Verify เมื่อ CCIP เคลื่อนที่เข้าใกล้เป้าหมาย
    """
    verifiedSignal = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.is_running = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_update)

        # State data for rendering
        self.hover_target_info = None  # {"name": "T-34", "screen_pos": (x,y)}
        self.locked_target_info = None # {"name": "Panzer IV", "screen_pos": (x,y), "world_pos": (x,y,z)}
        self.sim_ccip_screen = None    # (x, y)
        self.direct_ccip_screen = None # (x, y)
        self.dist_ccip_to_target = 999.0
        self.dist_sim_to_direct = 999.0
        self.status_text = "รอเริ่มการทดสอบ CCIP..."
        self.is_match_verified = False

        self.current_candidate = None
        self.game_ctx = None

        self.init_ui()

    def init_ui(self):
        screen = QApplication.primaryScreen()
        if screen:
            rect = screen.geometry()
            self.setGeometry(rect)
        else:
            self.setGeometry(0, 0, 1920, 1080)

    def set_context(self, game_ctx, candidate):
        self.game_ctx = game_ctx
        self.current_candidate = candidate

    def start_overlay(self):
        self.is_running = True
        self.is_match_verified = False
        self.status_text = "🎯 กรุณาล็อกเป้าหมาย (Lock Target) ในฉากฝึกซ้อมเพื่อเริ่มตรวจจับ CCIP"
        self.show()
        self.raise_()
        self.timer.start(50) # 20 Hz update

    def stop_overlay(self):
        self.is_running = False
        self.timer.stop()
        self.hide()

    def _on_update(self):
        if not self.is_running or not self.game_ctx:
            return

        import src.utils.mul as mul

        # Read live target, camera and CCIP
        scanner = self.game_ctx.scanner
        cgame = self.game_ctx.cgame_ptr
        my_unit = self.game_ctx.my_unit_ptr

        if not scanner or not cgame:
            self.status_text = "⚠️ ยังไม่ได้เชื่อมต่อเกม หรือไม่พบ CGame"
            self.update()
            return

        cam_ptr = mul.get_camera_ptr(scanner, cgame)
        vmat = mul.get_view_matrix(scanner, cam_ptr) if cam_ptr else None

        screen_w = self.width()
        screen_h = self.height()
        center_x = screen_w / 2
        center_y = screen_h / 2

        # 1. ค้นหายูนิตเป้าหมายที่อยู่ใกล้กึ่งกลางจอ (Hovering Target)
        units = mul.get_all_units(scanner, cgame)
        best_hover = None
        best_hover_dist = 999999.0

        for u_ptr, is_air in units:
            if u_ptr == my_unit:
                continue
            pos = mul.get_unit_pos(scanner, u_ptr)
            if not pos or (abs(pos[0]) < 0.01 and abs(pos[1]) < 0.01 and abs(pos[2]) < 0.01):
                continue
            if vmat:
                scr = mul.world_to_screen(vmat, pos[0], pos[1], pos[2], screen_w, screen_h)
                if scr and scr[2] > 0:
                    d = math.hypot(scr[0] - center_x, scr[1] - center_y)
                    if d < best_hover_dist and d < 300: # ภายในระยะเล็ง
                        best_hover_dist = d
                        dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
                        tname = dna.get("short_name") or dna.get("name_key") or "EnemyUnit"
                        best_hover = {
                            "ptr": u_ptr,
                            "name": tname,
                            "screen_pos": (int(scr[0]), int(scr[1])),
                            "world_pos": pos
                        }

        self.hover_target_info = best_hover

        # จำลองการตั้ง target locked จาก target ที่ใกล้ศูนย์กลาง
        if best_hover and best_hover_dist < 150:
            self.locked_target_info = best_hover

        # 2. อ่านจุดตก Direct CCIP จาก Memory Candidate
        direct_impact = None
        if self.current_candidate and my_unit:
            off_val = self.current_candidate.get("offset", mul.OFF_CCIP_IMPACT)
            # Try reading from weapon_ptr
            weapon_ptr = 0
            raw_w = scanner.read_mem(my_unit + mul.OFF_WEAPON_PTR, 8)
            if raw_w and len(raw_w) == 8:
                import struct
                wp = struct.unpack("<Q", raw_w)[0]
                if mul.is_valid_ptr(wp):
                    weapon_ptr = wp

            target_base = weapon_ptr if weapon_ptr else cgame
            raw_impact = scanner.read_mem(target_base + off_val, 12)
            if raw_impact and len(raw_impact) == 12:
                import struct
                ix, iy, iz = struct.unpack("<fff", raw_impact)
                if math.isfinite(ix) and abs(ix) < 50000 and (ix != 0 or iy != 0 or iz != 0):
                    direct_impact = (ix, iy, iz)

        # 3. จำลองจุดตก SimCCIP
        sim_impact = None
        if self.locked_target_info:
            # คำนวณ SimCCIP เล็งไปทางเป้าหมาย
            lp = self.locked_target_info["world_pos"]
            my_pos = mul.get_unit_pos(scanner, my_unit) or (0, 0, 0)
            # จุดกระทบใกล้เคียงเป้าหมาย
            sim_impact = lp

        if vmat and direct_impact:
            d_scr = mul.world_to_screen(vmat, direct_impact[0], direct_impact[1], direct_impact[2], screen_w, screen_h)
            self.direct_ccip_screen = (int(d_scr[0]), int(d_scr[1])) if d_scr and d_scr[2] > 0 else None
        else:
            self.direct_ccip_screen = None

        if vmat and sim_impact:
            s_scr = mul.world_to_screen(vmat, sim_impact[0], sim_impact[1], sim_impact[2], screen_w, screen_h)
            self.sim_ccip_screen = (int(s_scr[0]), int(s_scr[1])) if s_scr and s_scr[2] > 0 else None
        else:
            self.sim_ccip_screen = None

        # 4. ตรวจสอบเงื่อนไข Proximity Verification
        if self.locked_target_info:
            if direct_impact and sim_impact:
                dx = direct_impact[0] - sim_impact[0]
                dy = direct_impact[1] - sim_impact[1]
                dz = direct_impact[2] - sim_impact[2]
                self.dist_sim_to_direct = math.sqrt(dx*dx + dy*dy + dz*dz)

                # ระยะระหว่าง CCIP กับเป้าหมาย
                self.dist_ccip_to_target = self.dist_sim_to_direct

                if self.dist_ccip_to_target < 25.0: # เข้าใกล้เป้าหมาย
                    if self.dist_sim_to_direct < 12.0: # ตรงกัน
                        self.is_match_verified = True
                        self.status_text = f"✅ VERIFIED! DirectCCIP ตรงกับ SimCCIP (Diff: {self.dist_sim_to_direct:.1f}m)"
                        self.verifiedSignal.emit({
                            "offset": self.current_candidate.get("offset") if self.current_candidate else 0x1CCC,
                            "delta_m": self.dist_sim_to_direct,
                            "target": self.locked_target_info["name"]
                        })
                    else:
                        self.status_text = f"⚠️ CCIP เข้าใกล้เป้าหมาย แต่จุดตกไม่ตรง (Diff: {self.dist_sim_to_direct:.1f}m)"
                else:
                    self.status_text = f"🔒 ล็อกเป้าหมายแล้ว! ก้มหัวเครื่องบินเล็งให้ CCIP เข้าใกล้เป้า (ระยะห่าง: {self.dist_ccip_to_target:.1f}m)"
            else:
                self.status_text = f"🔒 ล็อกเป้าหมาย: {self.locked_target_info['name']} | กำลังรอสัญญาณ CCIP จาก Memory..."
        else:
            self.status_text = "🎯 กรุณาเล็งและล็อกเป้าหมาย (Hover / Lock Target) ในฉากซ้อมบิน"

        self.update()

    def paintEvent(self, event):
        if not self.is_running:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1. วาดแถบสถานะด้านบนกลางจอ
        banner_w, banner_h = 750, 60
        bx = (self.width() - banner_w) // 2
        by = 40

        bg_col = QColor(26, 92, 42, 220) if self.is_match_verified else QColor(18, 20, 26, 220)
        border_col = QColor(76, 175, 80) if self.is_match_verified else QColor(60, 70, 85)

        painter.setBrush(QBrush(bg_col))
        painter.setPen(QPen(border_col, 2))
        painter.drawRoundedRect(bx, by, banner_w, banner_h, 10, 10)

        painter.setPen(QPen(Qt.white))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(bx, by, banner_w, banner_h, Qt.AlignCenter, self.status_text)

        # 2. วาด Hover Target
        if self.hover_target_info and self.hover_target_info.get("screen_pos"):
            sx, sy = self.hover_target_info["screen_pos"]
            painter.setPen(QPen(QColor(255, 215, 0, 220), 2)) # Gold
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(sx - 25, sy - 25, 50, 50)
            painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
            painter.drawText(sx - 50, sy - 30, 100, 20, Qt.AlignCenter, f"🎯 {self.hover_target_info['name']}")

        # 3. วาด Locking Target
        if self.locked_target_info and self.locked_target_info.get("screen_pos"):
            lx, ly = self.locked_target_info["screen_pos"]
            painter.setPen(QPen(QColor(244, 67, 54, 255), 2)) # Red
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(lx - 32, ly - 32, 64, 64)
            # Corner markers
            painter.drawLine(lx - 38, ly - 32, lx - 24, ly - 32)
            painter.drawLine(lx + 24, ly - 32, lx + 38, ly - 32)
            painter.drawLine(lx - 38, ly + 32, lx - 24, ly + 32)
            painter.drawLine(lx + 24, ly + 32, lx + 38, ly + 32)
            painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
            painter.drawText(lx - 80, ly + 36, 160, 22, Qt.AlignCenter, f"[🔒 LOCKED] {self.locked_target_info['name']}")

        # 4. วาด SimCCIP (สีส้ม)
        if self.sim_ccip_screen:
            sx, sy = self.sim_ccip_screen
            painter.setPen(QPen(QColor(255, 152, 0, 240), 2)) # Orange
            painter.drawEllipse(sx - 20, sy - 20, 40, 40)
            painter.drawLine(sx - 26, sy, sx + 26, sy)
            painter.drawLine(sx, sy - 26, sx, sy + 26)
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.drawText(sx + 24, sy - 10, 120, 20, Qt.AlignLeft, "SimCCIP (Physics)")

        # 5. วาด DirectCCIP (สีฟ้า Cyan)
        if self.direct_ccip_screen:
            dx, dy = self.direct_ccip_screen
            painter.setPen(QPen(QColor(0, 229, 255, 240), 2)) # Cyan
            painter.drawEllipse(dx - 16, dy - 16, 32, 32)
            painter.drawPoint(dx, dy)
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.drawText(dx + 20, dy + 5, 140, 20, Qt.AlignLeft, "DirectCCIP (Memory)")
