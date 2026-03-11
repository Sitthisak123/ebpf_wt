import sys
import math
import time
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

# ⚡ [OPTIMIZED & HANGAR FILTER]: เพิ่มคำกรองขยะหน้าเมนูหลักและช่างซ่อมบำรุง
# ⚡ [OPTIMIZED & HANGAR FILTER]: เพิ่มคำกรองขยะหน้าเมนูหลัก, ช่างซ่อมบำรุง และวัตถุประกอบฉาก
BOT_KEYWORDS = [
    "dummy", "bot", "ai_", "_ai", "target", "truck", "cannon", 
    "aaa", "artillery", "infantry", "ship", "boat", "freighter",
    "hangar", "technic", "vent", "railway", "freight"  # <--- เพิ่มตู้รถไฟและขยะประกอบฉากล่าสุด!
]
NAME_PREFIXES = ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_"]

def is_aiming_at(barrel_base, barrel_tip, target_pos, threshold_degrees=6.0):
    dx = barrel_tip[0] - barrel_base[0]
    dy = barrel_tip[1] - barrel_base[1]
    dz = barrel_tip[2] - barrel_base[2]
    
    tx = target_pos[0] - barrel_base[0]
    ty = target_pos[1] - barrel_base[1]
    tz = target_pos[2] - barrel_base[2]
    
    len_d = math.sqrt(dx*dx + dy*dy + dz*dz)
    len_t = math.sqrt(tx*tx + ty*ty + tz*tz)
    
    if len_d < 0.001 or len_t < 0.001: return False
    dot_prod = (dx*tx + dy*ty + dz*tz) / (len_d * len_t)
    dot_prod = max(-1.0, min(1.0, dot_prod)) 
    angle = math.degrees(math.acos(dot_prod))
    return angle <= threshold_degrees

class ESPOverlay(QWidget):
    def __init__(self, scanner, base_address):
        super().__init__()
        self.scanner = scanner
        self.base_address = base_address
        self.last_my_unit = 0
        self.max_reload_cache = {}
        
        self.center_x = SCREEN_WIDTH / 2
        self.center_y = SCREEN_HEIGHT / 2
        
        self.seen_names = set() # ไว้สอดแนมชื่อใหม่ๆ
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16) # ~60 FPS

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.setPen(QColor(0, 255, 0, 255))
            painter.drawText(20, 40, "🟢 WTM TACTICAL RADAR: PRO UI V3")

            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            all_units_data = get_all_units(self.scanner, cgame_base) 
            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            if my_unit != self.last_my_unit:
                if hasattr(self.scanner, "bone_cache"):
                    self.scanner.bone_cache = {} 
                self.max_reload_cache = {} 
                self.last_my_unit = my_unit

            valid_targets = []
            
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit: continue 
                status = get_unit_status(self.scanner, u_ptr)
                if not status: continue
                
                u_team, u_state, unit_name, reload_val = status 

                if u_state >= 1: continue 
                if my_team != 0 and u_team == my_team: continue
                
                if unit_name not in self.seen_names and unit_name != "UNKNOWN":
                    print(f"[*] 🔍 พบโมเดลเป้าหมายในแมพ: '{unit_name}'")
                    self.seen_names.add(unit_name)
                
                unit_name_lower = unit_name.lower()
                if any(kw in unit_name_lower for kw in BOT_KEYWORDS): continue
                
                valid_targets.append((u_ptr, unit_name, reload_val, is_air))

            painter.setPen(QColor(255, 255, 0, 255))
            painter.drawText(20, 70, f"🎯 Real Players: {len(valid_targets)} | Team: {my_team}")

            for u_ptr, raw_name, reload_val, is_air_target in valid_targets:
                box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                if not box_data: continue
                pos, bmin, bmax, R = box_data
                
                dist = 0
                if my_pos:
                    dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2)

                barrel_base_2d = None
                barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R)
                if barrel_data:
                    p1, p2 = barrel_data
                    res_p1 = world_to_screen(view_matrix, p1[0], p1[1], p1[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    res_p2 = world_to_screen(view_matrix, p2[0], p2[1], p2[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                        painter.setPen(QPen(QColor(0, 255, 0, 255), 2)) 
                        painter.drawLine(int(res_p1[0]), int(res_p1[1]), int(res_p2[0]), int(res_p2[1]))
                        barrel_base_2d = res_p1 

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
                    avg_y = sum([p[1] for p in pts]) / 8.0  
                    
                    clean_name = raw_name
                    for p in NAME_PREFIXES:
                        if clean_name.lower().startswith(p):
                            clean_name = clean_name[len(p):]; break
                            
                    if is_air_target and my_pos:
                        if abs(pos[2] - my_pos[2]) < 50:
                            is_air_target = False
                            
                    has_reload_bar = (not is_air_target and (0 <= reload_val < 500))
                    
                    # -----------------------------------------------------
                    # 🥷 ลอจิกซ่อนชื่อ Stealth Mode (อัปเดตตามคำสั่งนายพล!)
                    # -----------------------------------------------------
                    hide_name = False
                    if not is_air_target:
                        dist_to_crosshair = math.hypot(avg_x - self.center_x, avg_y - self.center_y)
                        if dist_to_crosshair < 350:
                            # เล็งอยู่ -> โชว์ชื่อ
                            hide_name = False
                        else:
                            # ไม่ได้เล็ง และอยู่ไกลเกิน 550m -> ซ่อนชื่อ
                            if dist > 550:
                                hide_name = True

                    if hide_name:
                        display_text = f"-{int(dist)}m-"
                    else:
                        display_text = f"{clean_name.upper()} [{int(dist)}m]"
                        
                    fm = painter.fontMetrics()
                    text_w = fm.boundingRect(display_text).width()
                    text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)

                    # =====================================================
                    # 🚨 Threat Alert (Dot & Snapline)
                    # =====================================================
                    aiming_me = False
                    if my_pos and barrel_data:
                        aiming_me = is_aiming_at(barrel_data[0], barrel_data[1], my_pos, threshold_degrees=6.0)

                    if aiming_me:
                        dot_text = "●"
                        dot_w = fm.boundingRect(dot_text).width()
                        dot_x = int(avg_x - dot_w / 2) 
                        dot_y = text_y - 14 
                        
                        t = (math.sin(time.time() * 15.0) + 1.0) / 2.0
                        r = int(t * 255)
                        g = int(255 - (t * 90))
                        
                        painter.setPen(QColor(r, g, 0, 50))
                        for ox, oy in [(-1,-1), (1,-1), (-1,1), (1,1), (0,-2), (0,2), (-2,0), (2,0)]:
                            painter.drawText(dot_x + ox, dot_y + oy, dot_text)
                            
                        painter.setPen(QColor(r, g, 0, 255))
                        painter.drawText(dot_x, dot_y, dot_text)

                        line_dest_x = barrel_base_2d[0] if barrel_base_2d else avg_x
                        line_dest_y = barrel_base_2d[1] if barrel_base_2d else avg_y
                        glow_thickness = max(3, int(t * 6))
                        painter.setPen(QPen(QColor(r, g, 0, 80), glow_thickness))
                        painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))
                        
                        painter.setPen(QPen(QColor(r, g, 0, 255), 2))
                        painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))

                    # =====================================================
                    
                    painter.setPen(QColor(0, 255, 255, 255))
                    painter.drawText(int(avg_x - text_w/2), text_y, display_text)

                    if has_reload_bar:
                        if u_ptr not in self.max_reload_cache:
                            self.max_reload_cache[u_ptr] = reload_val
                        if reload_val > self.max_reload_cache[u_ptr]:
                            self.max_reload_cache[u_ptr] = reload_val
                            
                        max_val = self.max_reload_cache[u_ptr]
                        if reload_val == 0 or max_val == 0:
                            progress = 1.0 
                        else:
                            progress = 1.0 - (float(reload_val) / float(max_val))
                            
                        bar_w = 40
                        bar_h = 4
                        bar_x = int(avg_x - bar_w / 2)
                        bar_y = int(min_y - 8)
                        
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QColor(0, 0, 0, 150))
                        painter.drawRect(bar_x, bar_y, bar_w, bar_h)
                        
                        fill_w = int(bar_w * progress)
                        if progress >= 0.99:
                            painter.setBrush(QColor(0, 255, 0, 200))   
                        else:
                            painter.setBrush(QColor(255, 165, 0, 200)) 
                        
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