import sys
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from main import MemoryScanner, get_game_pid, get_game_base_address

from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen, 
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners, get_weapon_barrel,
    get_local_team, get_unit_status, LinuxOffsets
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
        # 🚨 แก้บั๊ก RAM รั่ว! ต้องเปิด Painter อย่างปลอดภัย และใช้ finally ปิดเสมอ
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)

        try:
            self.frame_count += 1
            should_log = (self.frame_count % 60 == 0)

            painter.setFont(QFont("Arial", 14, QFont.Bold))
            painter.setPen(QColor(0, 255, 0, 255))
            painter.drawText(20, 40, "🟢 WTM RADAR: MASTER MERGE BUILD")

            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
                
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            all_units = get_all_units(self.scanner, cgame_base)
            
            # ดึงข้อมูลตัวเราเอง
            my_unit, my_data = get_local_team(self.scanner, self.base_address)

            valid_targets = []
            
            # ==================================================
            # 🛡️ ระบบกรองเป้าหมายแบบคลายกฎ (ป้องกันศัตรูหาย 100%)
            # ==================================================
            for u_ptr in all_units:
                if u_ptr == my_unit: continue 
                
                status = get_unit_status(self.scanner, u_ptr, my_unit, my_data)
                if not status: 
                    valid_targets.append(u_ptr) # กันศัตรูหาย
                    continue
                
                my_team, u_team, u_family, u_state = status

                # 🚨 กฎข้อ 1: กรองซากรถถังที่พังแล้ว (ด้วย Offset 0xD68)
                if u_state >= 1: continue
                
                # 🚨 กฎข้อ 2: กรองเพื่อนร่วมทีม
                # สังเกตว่าเราไม่ได้ใช้ u_team == 0 อีกต่อไป! เพราะรถเกิดใหม่อาจจะเป็นทีม 0 ชั่วคราว
                if my_team != 0 and u_team == my_team: continue
                
                # 🚨 กฎข้อ 3: เอาเฉพาะยานเกราะ (อนุญาต 99 ไว้กันบั๊กอ่าน Family ไม่ทัน)
                if LinuxOffsets.info_offset != -1: 
                    if u_family not in [3, 4, 5, 6, 99]: continue
                
                valid_targets.append(u_ptr)

            painter.setPen(QColor(255, 255, 0, 255))
            painter.drawText(20, 70, f"🎯 Detected Enemies: {len(valid_targets)} Units")
            has_logged_this_frame = False

            # วาด ESP
            for u_ptr in valid_targets:
                box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                if not box_data: continue

                pos, bmin, bmax, R = box_data

                # เลเซอร์ปืน!
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

                # 3D Box
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
        finally:
            painter.end() # 🚨 ไม่ว่าเกิดอะไรขึ้น ต้องคืน RAM ให้ระบบ!

if __name__ == '__main__':
    print("[*] กำลังเตรียมระบบ WTM RADAR...")
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
    except Exception as e:
        sys.exit(1)

    app = QApplication(sys.argv)
    overlay = ESPOverlay(scanner, base_addr)
    overlay.show()
    sys.exit(app.exec_())