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
        self.last_my_unit = 0
        self.max_reload_cache = {} # 🚨 เพิ่มหน่วยความจำจดจำความจุกระสุนสูงสุดของศัตรูแต่ละคัน
        
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
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.setPen(QColor(0, 255, 0, 255))
            painter.drawText(20, 40, "🟢 WTM TACTICAL RADAR: VISUAL PROGRESS BAR")

            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            all_units = get_all_units(self.scanner, cgame_base)
            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            # 🚨 ถ้ารถถังเราเปลี่ยน (เริ่มแมตช์ใหม่) ให้ล้าง Cache ทั้งหมดทิ้ง!
            if my_unit != self.last_my_unit:
                if hasattr(self.scanner, "bone_cache"):
                    self.scanner.bone_cache = {} 
                self.max_reload_cache = {} 
                self.last_my_unit = my_unit

            valid_targets = []
            for u_ptr in all_units:
                if u_ptr == my_unit: continue 
                status = get_unit_status(self.scanner, u_ptr)
                if not status: continue
                u_team, u_state, unit_name, reload_val = status 

                if u_state >= 1: continue 
                if my_team != 0 and u_team == my_team: continue
                if "dummy" in unit_name.lower(): continue
                
                valid_targets.append((u_ptr, unit_name, reload_val))

            painter.setPen(QColor(255, 255, 0, 255))
            painter.drawText(20, 70, f"🎯 Targets: {len(valid_targets)} | Team: {my_team}")

            for u_ptr, raw_name, reload_val in valid_targets:
                box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                if not box_data: continue
                pos, bmin, bmax, R = box_data
                
                dist_text = ""
                if my_pos:
                    dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2)
                    dist_text = f" [{int(dist)}m]"

                barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R)
                if barrel_data:
                    p1, p2 = barrel_data
                    res_p1 = world_to_screen(view_matrix, p1[0], p1[1], p1[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    res_p2 = world_to_screen(view_matrix, p2[0], p2[1], p2[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                        painter.setPen(QPen(QColor(0, 255, 0, 255), 2)) 
                        painter.drawLine(int(res_p1[0]), int(res_p1[1]), int(res_p2[0]), int(res_p2[1]))

                corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
                pts = []
                for c in corners_3d:
                    res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    if res and res[2] >= 0.001: pts.append((res[0], res[1]))
                
                if len(pts) == 8:
                    painter.setPen(QPen(QColor(255, 0, 0, 200), 2))
                    edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]
                    for e1, e2 in edges: painter.drawLine(int(pts[e1][0]), int(pts[e1][1]), int(pts[e2][0]), int(pts[e2][1]))
                    
                    min_y = min([p[1] for p in pts])
                    avg_x = sum([p[0] for p in pts]) / 8.0 
                    clean_name = raw_name
                    for p in ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_"]:
                        if clean_name.lower().startswith(p):
                            clean_name = clean_name[len(p):]; break
                    
                    # 🏷️ 1. วาดข้อความชื่อและระยะทาง (ดันขึ้นไปนิดนึงเพื่อเว้นที่ให้หลอดกระสุน)
                    display_text = f"{clean_name.upper()}{dist_text}"
                    painter.setPen(QColor(0, 255, 255, 255)) 
                    text_w = painter.fontMetrics().boundingRect(display_text).width()
                    painter.drawText(int(avg_x - text_w/2), int(min_y - 12), display_text)
                    
                    # 🔫 2. คำนวณและวาดหลอด Reload Progress (กว้าง 40px)
                    if 0 <= reload_val < 500: # กรองค่าขยะ
                        # อัปเดตค่า Max กระสุนของคันนี้
                        if u_ptr not in self.max_reload_cache:
                            self.max_reload_cache[u_ptr] = reload_val
                        if reload_val > self.max_reload_cache[u_ptr]:
                            self.max_reload_cache[u_ptr] = reload_val
                            
                        max_val = self.max_reload_cache[u_ptr]
                        
                        # คำนวณเปอร์เซ็นต์หลอด (0 = เต็ม, max_val = หมด)
                        if reload_val == 0 or max_val == 0:
                            progress = 1.0 # 100%
                        else:
                            progress = 1.0 - (float(reload_val) / float(max_val))
                            
                        # วาดกล่องพื้นหลังหลอด (สีดำโปร่งแสง)
                        bar_w = 40
                        bar_h = 4
                        bar_x = int(avg_x - bar_w / 2)
                        bar_y = int(min_y - 8)
                        
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QColor(0, 0, 0, 150))
                        painter.drawRect(bar_x, bar_y, bar_w, bar_h)
                        
                        # วาดความคืบหน้าของหลอด
                        fill_w = int(bar_w * progress)
                        if progress >= 0.99:
                            painter.setBrush(QColor(0, 255, 0, 200))   # สีเขียว: พร้อมยิง
                        else:
                            painter.setBrush(QColor(255, 165, 0, 200)) # สีส้ม: กำลังรีโหลด
                        
                        painter.drawRect(bar_x, bar_y, fill_w, bar_h)

        except Exception: pass
        finally: painter.end()

if __name__ == '__main__':
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        app = QApplication(sys.argv)
        overlay = ESPOverlay(scanner, base_addr)
        overlay.show()
        sys.exit(app.exec_())
    except: sys.exit(1)