import sys
import math
import time
import struct
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from main import MemoryScanner, get_game_pid, get_game_base_address

# 🚨 นำเข้าฟังก์ชันจาก mul.py
from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen, 
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners, get_weapon_barrel,
    get_local_team, get_unit_status, get_unit_pos, get_unit_velocity,
    get_bullet_speed, get_bullet_mass, get_bullet_caliber, get_bullet_cd
)

SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440

COLOR_INFO_TEXT      = (255, 228, 64, 255)   
COLOR_BARREL_LINE    = (0, 255, 0, 255)      
COLOR_BOX_TARGET     = (255, 68, 0, 200)     
COLOR_TEXT_GROUND    = (0, 255, 255, 255)    
COLOR_TEXT_AIR       = (255, 222, 66, 255)   
COLOR_RELOAD_BG      = (0, 0, 0, 150)        
COLOR_RELOAD_READY   = (0, 255, 0, 200)      
COLOR_RELOAD_LOADING = (255, 165, 0, 200)    

BULLET_GRAVITY       = 9.81   

BOT_KEYWORDS = ["dummy", "bot", "ai_", "_ai", "target", "truck", "cannon", "aaa", "artillery", "infantry", "ship", "boat", "freighter", "hangar", "technic", "vent", "railway", "freight"]
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

# 🌟 THE SAFE OMEGA EXTRACTOR
def get_safe_omega(scanner, unit_ptr, is_air):
    if not is_air: return (0.0, 0.0, 0.0)
    try:
        mov_raw = scanner.read_mem(unit_ptr + 0x18, 8) 
        if not mov_raw: return None
        mov_ptr = struct.unpack("<Q", mov_raw)[0]
        if mov_ptr < 0x10000: return None
        
        omega_data = scanner.read_mem(mov_ptr + 0x3f8, 12)
        if omega_data and len(omega_data) == 12:
            wx, wy, wz = struct.unpack("<fff", omega_data)
            if math.isfinite(wx) and math.isfinite(wy) and math.isfinite(wz):
                return (wx, wy, wz)
    except: pass
    return None 

class ESPOverlay(QWidget):
    def __init__(self, scanner, base_address):
        super().__init__()
        self.scanner = scanner
        self.base_address = base_address
        self.max_reload_cache = {}
        self.smooth_cache = {} 
        
        self.center_x = SCREEN_WIDTH / 2
        self.center_y = SCREEN_HEIGHT / 2
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(0) 

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        
        seen_targets_this_frame = set()
        
        try:
            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            current_bullet_speed = get_bullet_speed(self.scanner, cgame_base)
            current_bullet_mass = get_bullet_mass(self.scanner, cgame_base)
            current_bullet_caliber = get_bullet_caliber(self.scanner, cgame_base)
            current_bullet_cd = get_bullet_cd(self.scanner, cgame_base)
            
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.setPen(QColor(*COLOR_INFO_TEXT))
            painter.drawText(20, 30, f"🔫 WTM AXIS DEBUGGER (6 PERMUTATIONS)")
            painter.drawText(20, 50, f"🔴 RED     = W x V (Standard)")
            painter.drawText(20, 70, f"🟢 GREEN   = V x W (Reversed)")
            painter.drawText(20, 90, f"🔵 BLUE    = Swap W(X,Y)")
            painter.drawText(20, 110, f"🟡 YELLOW  = Swap W(Y,Z)")
            painter.drawText(20, 130, f"🟣 MAGENTA = Swap W(X,Z)")
            painter.drawText(20, 150, f"⚪ WHITE   = Linear Only (No Curve)")

            all_units_data = get_all_units(self.scanner, cgame_base) 
            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            my_is_air = False
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit:
                    my_is_air = is_air
                    break
            
            my_vel = get_unit_velocity(self.scanner, my_unit, my_is_air) if my_unit else (0.0, 0.0, 0.0)
            if not my_vel: my_vel = (0.0, 0.0, 0.0)
            my_vx, my_vy, my_vz = my_vel

            valid_targets = []
            for u_ptr, is_air in all_units_data:
                status = get_unit_status(self.scanner, u_ptr)
                if not status: continue
                u_team, u_state, unit_name, reload_val = status 
                if u_state >= 1: continue 
                
                if my_team != 0 and u_team == my_team and u_ptr != my_unit: continue
                
                unit_name_lower = unit_name.lower()
                if any(kw in unit_name_lower for kw in BOT_KEYWORDS): continue
                valid_targets.append((u_ptr, unit_name, reload_val, is_air))

            for u_ptr, raw_name, reload_val, is_air_target in valid_targets:
                seen_targets_this_frame.add(u_ptr)
                try:
                    box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                    if not box_data: continue
                    pos, bmin, bmax, R = box_data
                    
                    dist = 0
                    if my_pos:
                        dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2)

                    corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
                    pts = []
                    for c in corners_3d:
                        res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        if res and res[2] >= 0.001: pts.append((res[0], res[1]))
                    
                    if len(pts) == 8:
                        painter.setPen(QPen(QColor(*COLOR_BOX_TARGET), 2))
                        edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]
                        for e1, e2 in edges: painter.drawLine(int(pts[e1][0]), int(pts[e1][1]), int(pts[e2][0]), int(pts[e2][1]))
                        
                        min_y = min([p[1] for p in pts])
                        avg_x = sum([p[0] for p in pts]) / 8.0 
                        avg_y = sum([p[1] for p in pts]) / 8.0  
                        
                        # -----------------------------------------------------
                        # 🚀 THE MULTIVERSE LEAD MARKER (หาแกนที่ใช่!)
                        # -----------------------------------------------------
                        raw_vel = get_unit_velocity(self.scanner, u_ptr, is_air_target)
                        raw_omega = get_safe_omega(self.scanner, u_ptr, is_air_target) 
                        
                        if raw_vel and my_pos and dist > 10.0:
                            
                            # TRIPLE-BUFFER FALLBACK
                            if raw_omega is None:
                                if u_ptr in self.smooth_cache: raw_omega = self.smooth_cache[u_ptr]['w']
                                else: raw_omega = (0.0, 0.0, 0.0)
                            
                            if u_ptr not in self.smooth_cache:
                                self.smooth_cache[u_ptr] = {'v': raw_vel, 'w': raw_omega}
                                vx, vy, vz = raw_vel
                                wx, wy, wz = raw_omega
                            else:
                                old_v = self.smooth_cache[u_ptr]['v']
                                old_w = self.smooth_cache[u_ptr]['w']
                                alpha = 0.4
                                vx = old_v[0] + alpha * (raw_vel[0] - old_v[0])
                                vy = old_v[1] + alpha * (raw_vel[1] - old_v[1])
                                vz = old_v[2] + alpha * (raw_vel[2] - old_v[2])
                                wx = old_w[0] + alpha * (raw_omega[0] - old_w[0])
                                wy = old_w[1] + alpha * (raw_omega[1] - old_w[1])
                                wz = old_w[2] + alpha * (raw_omega[2] - old_w[2])
                                self.smooth_cache[u_ptr] = {'v': (vx, vy, vz), 'w': (wx, wy, wz)}

                            if is_air_target:
                                t_x, t_y, t_z = pos[0], pos[1], pos[2] 
                            else:
                                t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                            # 💨 คำนวณแรงต้านอากาศ (Drag)
                            if current_bullet_mass > 0.001 and current_bullet_caliber > 0.001:
                                Cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                                rho = 1.225
                                area = math.pi * ((current_bullet_caliber / 2.0) ** 2)
                                k = (0.5 * rho * Cd * area) / current_bullet_mass
                            else:
                                k = 0.0001
                                
                            # 🧠 1. คำนวณเวลา (Time of Flight) เพียงครั้งเดียว! 
                            # (เพื่อเป้าทุกสีจะได้ใช้เวลาเดียวกัน ไม่บานออกห่างกัน)
                            t = 0.0
                            pred_x, pred_y, pred_z = t_x, t_y, t_z
                            for i in range(5):
                                dx = pred_x - my_pos[0]
                                dy = pred_y - (my_pos[1] + 1.5)  
                                dz = pred_z - my_pos[2]         
                                current_dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                                
                                if current_bullet_speed > 0:
                                    if k > 0.000001:
                                        kx = min(k * current_dist, 5.0)
                                        new_t = (math.exp(kx) - 1.0) / (k * current_bullet_speed)
                                    else:
                                        new_t = current_dist / current_bullet_speed
                                else: new_t = 0
                                    
                                if i > 0: t = (t + new_t) / 2.0
                                else: t = new_t
                                    
                                pred_x = t_x + ((vx - my_vx) * t)
                                pred_y = t_y + ((vy - my_vy) * t)
                                pred_z = t_z + ((vz - my_vz) * t)
                                
                            drop = 0.5 * BULLET_GRAVITY * (t * t)
                            accel_t = min(t, 1.2) 

                            # 🎯 2. สร้างชุดการสลับแกน (Axis Shuffle Permutations)
                            # (ชื่อ, Wx, Wy, Wz, สี RGB)
                            w_permutations = [
                                ("🔴 WxV",  wx,  wy,  wz, (255, 50, 50)),     # Red
                                ("🟢 VxW", -wx, -wy, -wz, (50, 255, 50)),     # Green (Negative Omega)
                                ("🔵 SWAP(XY)", wy, wx, wz, (50, 150, 255)),  # Blue
                                ("🟡 SWAP(YZ)", wx, wz, wy, (255, 255, 50)),  # Yellow
                                ("🟣 SWAP(XZ)", wz, wy, wx, (255, 50, 255)),  # Magenta
                                ("⚪ LINEAR", 0.0, 0.0, 0.0, (255, 255, 255)) # White (Baseline: ไม่เลี้ยวเลย)
                            ]

                            # หาจุดเริ่มต้นวาดเส้นชี้เป้า (เอามาจากกลางเครื่องบิน)
                            draw_start_x, draw_start_y = avg_x, avg_y
                            pos_screen = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                            if pos_screen and pos_screen[2] > 0:
                                draw_start_x, draw_start_y = pos_screen[0], pos_screen[1]

                            # 🎯 3. วนลูปวาดเป้าหมายทั้ง 6 แบบ
                            for name, twx, twy, twz, color in w_permutations:
                                if is_air_target:
                                    ax = twy * vz - twz * vy
                                    ay = twz * vx - twx * vz
                                    az = twx * vy - twy * vx
                                    
                                    a_mag = math.sqrt(ax**2 + ay**2 + az**2)
                                    if a_mag > 150.0:
                                        ax = (ax / a_mag) * 150.0
                                        ay = (ay / a_mag) * 150.0
                                        az = (az / a_mag) * 150.0
                                else:
                                    ax, ay, az = 0.0, 0.0, 0.0

                                # คำนวณสมการ Kinematics ของแต่ละสี
                                final_x = t_x + ((vx - my_vx) * t) + (0.5 * ax * accel_t * accel_t)
                                final_y = t_y + ((vy - my_vy) * t) + (0.5 * ay * accel_t * accel_t) + drop 
                                final_z = t_z + ((vz - my_vz) * t) + (0.5 * az * accel_t * accel_t)             
                                
                                pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, SCREEN_WIDTH, SCREEN_HEIGHT)
                                
                                if pred_screen and pred_screen[2] > 0:
                                    # วาดเส้นประโยงไปยังจุดต่างๆ
                                    painter.setPen(QPen(QColor(color[0], color[1], color[2], 100), 1, Qt.DashLine))
                                    painter.drawLine(int(draw_start_x), int(draw_start_y), int(pred_screen[0]), int(pred_screen[1]))
                                    
                                    # วาดวงกลมเป้าหมาย
                                    painter.setPen(QPen(QColor(*color), 2))
                                    painter.drawEllipse(int(pred_screen[0]) - 5, int(pred_screen[1]) - 5, 10, 10)
                                    painter.setBrush(QColor(*color))
                                    painter.drawEllipse(int(pred_screen[0]) - 1, int(pred_screen[1]) - 1, 2, 2)
                                    painter.setBrush(Qt.NoBrush)
                                    
                                    # วาดตัวหนังสือบอกว่าสีนี้คือสูตรอะไร
                                    painter.setFont(QFont("Arial", 9, QFont.Bold))
                                    painter.setPen(QColor(*color))
                                    painter.drawText(int(pred_screen[0]) + 8, int(pred_screen[1]) + 4, name)
                        # -----------------------------------------------------
                        
                        clean_name = raw_name
                        for p in NAME_PREFIXES:
                            if clean_name.lower().startswith(p): clean_name = clean_name[len(p):]; break
                        
                        if is_air_target and my_pos:
                            if abs(pos[1] - my_pos[1]) < 50: is_air_target = False
                                
                        has_reload_bar = (not is_air_target and (0 <= reload_val < 500))
                        hide_name = False
                        if not is_air_target:
                            dist_to_crosshair = math.hypot(avg_x - self.center_x, avg_y - self.center_y)
                            if dist_to_crosshair < 350: hide_name = False
                            else: hide_name = True if dist > 550 else False

                        if hide_name: display_text = f"-{int(dist)}m-"
                        else: display_text = f"{clean_name.upper()} [{int(dist)}m]"
                            
                        fm = painter.fontMetrics()
                        text_w = fm.boundingRect(display_text).width()
                        text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)

                        painter.setFont(QFont("Arial", 12, QFont.Bold))
                        if is_air_target: painter.setPen(QColor(*COLOR_TEXT_AIR))
                        else: painter.setPen(QColor(*COLOR_TEXT_GROUND))
                        painter.drawText(int(avg_x - text_w/2), text_y, display_text)

                except Exception:
                    pass

            dead_targets = [ptr for ptr in self.smooth_cache if ptr not in seen_targets_this_frame]
            for ptr in dead_targets:
                del self.smooth_cache[ptr]

        except Exception: 
            pass
        finally: 
            painter.end()

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