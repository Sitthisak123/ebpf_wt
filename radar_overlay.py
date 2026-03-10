import sys
import math
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from main import MemoryScanner, get_game_pid, get_game_base_address

from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen, 
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners, get_weapon_barrel,
    get_local_team, get_unit_status, get_unit_pos
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
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        
        try:
            self.frame_count += 1
            should_log = (self.frame_count % 60 == 0)

            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.setPen(QColor(0, 255, 0, 255))
            painter.drawText(20, 40, "🟢 WTM TACTICAL RADAR: PERFECT EDITION")

            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
                
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            all_units = get_all_units(self.scanner, cgame_base)
            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            valid_targets = []
            
            # 🛡️ ระบบกรองเป้าหมายแบบสมบูรณ์แบบ
            for u_ptr in all_units:
                if u_ptr == my_unit: continue 
                
                status = get_unit_status(self.scanner, u_ptr)
                if not status: 
                    valid_targets.append((u_ptr, "UNKNOWN")) 
                    continue
                
                u_team, u_state, unit_name = status

                # 🚨 กฎข้อ 1: กรองซากรถถัง (ด้วย 0xD68)
                if u_state >= 1: continue 
                
                # 🚨 กฎข้อ 2: กรองเพื่อนร่วมทีม (ด้วย 0xDE8)
                if my_team != 0 and u_team == my_team: continue
                
                # 🚨 กฎข้อ 3: กรองขยะ/เป้าปลอม (ถ้าชื่อมีคำว่า dummy ให้ข้าม)
                if "dummy" in unit_name.lower(): continue
                
                valid_targets.append((u_ptr, unit_name))

            painter.setPen(QColor(255, 255, 0, 255))
            painter.drawText(20, 70, f"🎯 Enemies: {len(valid_targets)} | Team: {my_team}")
            has_logged_this_frame = False

            # วาด ESP
            for u_ptr, raw_name in valid_targets:
                box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                if not box_data: continue

                pos, bmin, bmax, R = box_data

                # 📍 คำนวณระยะทาง
                dist_text = ""
                if my_pos:
                    dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2)
                    dist_text = f" [{int(dist)}m]"

                # เลเซอร์ปืน
                is_logging_target = should_log and not has_logged_this_frame
                barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R, should_log=is_logging_target)
                
                if barrel_data:
                    if is_logging_target: has_logged_this_frame = True
                    p1, p2 = barrel_data
                    res_p1 = world_to_screen(view_matrix, p1[0], p1[1], p1[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    res_p2 = world_to_screen(view_matrix, p2[0], p2[1], p2[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    
                    if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                        painter.setPen(QPen(QColor(0, 255, 0, 255), 2)) 
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

                    # 🏷️ วาดข้อความ ชื่อรถถัง + ระยะทาง
                    min_y = min([p[1] for p in pts])
                    avg_x = sum([p[0] for p in pts]) / 8.0 
                    
                    # ตัดคำขยะนำหน้า
                    clean_name = raw_name
                    prefixes = ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_"]
                    for p in prefixes:
                        if clean_name.lower().startswith(p):
                            clean_name = clean_name[len(p):]
                            break
                    
                    display_text = f"{clean_name.upper()}{dist_text}" if clean_name != "UNKNOWN" else f"TARGET{dist_text}"
                    
                    painter.setPen(QColor(0, 255, 255, 255)) 
                    fm = painter.fontMetrics()
                    text_w = fm.boundingRect(display_text).width()
                    
                    painter.drawText(int(avg_x - text_w/2), int(min_y - 8), display_text)

        except Exception as e:
            pass
        finally:
            painter.end()

if __name__ == '__main__':
    print("[*] 🚀 กำลังเตรียมระบบ WTM RADAR...")
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