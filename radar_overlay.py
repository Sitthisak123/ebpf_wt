import sys
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen, 
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners, get_weapon_barrel
)

SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440

class ESPOverlay(QWidget):
    def __init__(self, scanner, base_address):
        super().__init__()
        self.scanner = scanner
        self.base_address = base_address
        self.frame_count = 0
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def paintEvent(self, event):
        try:
            self.frame_count += 1
            should_log = (self.frame_count % 60 == 0)
            
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            # 🟢 วาดสถานะก่อนเลยเป็นอันดับแรก จะได้รู้ว่าโปรแกรมทำงานอยู่!
            painter.setFont(QFont("Arial", 14, QFont.Bold))
            painter.setPen(QColor(0, 255, 0, 255))
            painter.drawText(20, 40, "🟢 DYNAMIC WTM BONE TRACKER: ACTIVE")

            cgame_base = get_cgame_base(self.scanner, self.base_address)
            
            # ถ้าหาเกมไม่เจอ หรืออยู่หน้าล็อบบี้ ให้แจ้งเตือนแล้วข้ามไป
            if cgame_base == 0: 
                painter.setPen(QColor(255, 0, 0, 255))
                painter.drawText(20, 70, "❌ Status: รอเข้าแมตช์ / ไม่พบเรดาร์...")
                return
                
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            all_units = get_all_units(self.scanner, cgame_base)
            
            # แสดงจำนวนศัตรูบนจอ
            painter.setPen(QColor(255, 255, 0, 255))
            painter.drawText(20, 70, f"🎯 Targets in Match: {len(all_units)} Units")

            has_logged_this_frame = False

            for u_ptr in all_units:
                box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                if not box_data: continue
                
                pos, bmin, bmax, R = box_data

                # -----------------------------------------------------
                # 🔫 วาด เลเซอร์ป้อมปืน (สีเขียว)
                # -----------------------------------------------------
                is_logging_target = should_log and not has_logged_this_frame
                barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R, should_log=is_logging_target)
                
                if barrel_data:
                    if is_logging_target: has_logged_this_frame = True
                    p1, p2 = barrel_data
                    
                    res_p1 = world_to_screen(view_matrix, p1[0], p1[1], p1[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    res_p2 = world_to_screen(view_matrix, p2[0], p2[1], p2[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    
                    if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                        painter.setPen(QPen(QColor(0, 255, 0, 255), 3)) 
                        painter.drawLine(int(res_p1[0]), int(res_p1[1]), int(res_p2[0]), int(res_p2[1]))

                # -----------------------------------------------------
                # 📦 วาดกล่อง 3D Box (สีแดง)
                # -----------------------------------------------------
                corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
                pts = []
                for c in corners_3d:
                    res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    if res and res[2] >= 0.001:
                        pts.append((res[0], res[1]))
                        
                if len(pts) == 8:
                    painter.setPen(QPen(QColor(255, 0, 0, 200), 2))
                    edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]
                    for e1, e2 in edges:
                        painter.drawLine(int(pts[e1][0]), int(pts[e1][1]), int(pts[e2][0]), int(pts[e2][1]))

        except Exception as e:
            pass

if __name__ == '__main__':
    print("[*] กำลังเตรียมระบบ WTM Bone Tracker...")
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        print(f"[+] เจอ War Thunder PID: {pid} | Base: {hex(base_addr)}")
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)

    print("[+] เปิด Overlay แล้ว! (ถ้าจอใส ให้ดูข้อความสีเขียวที่มุมซ้ายบนหน้าจอหลัก)")
    app = QApplication(sys.argv)
    overlay = ESPOverlay(scanner, base_addr)
    overlay.show()
    sys.exit(app.exec_())