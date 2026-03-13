import sys
import math
import time
import struct
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from main import MemoryScanner, get_game_pid, get_game_base_address

# 🚨 นำเข้าฟังก์ชันทั้งหมด รวมถึง Dynamic Zeroing
from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen, 
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners, get_weapon_barrel,
    get_local_team, get_unit_status, get_unit_pos, get_unit_velocity,
    get_bullet_speed, get_bullet_mass, get_bullet_caliber, get_bullet_cd,
    get_sight_compensation_factor
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
COLOR_PREDICTION     = (255, 40, 40, 255)    # 🔴 สีเป้าดักหน้า (แดงสดสุดๆ)
COLOR_FPS_GOOD       = (0, 255, 0, 255)      

BULLET_GRAVITY       = 9.81   

BOT_KEYWORDS = ["speaker","water", "panzerzug","windmill","dummy", "bot", "ai_", "_ai", "target", "truck", "cannon", "aaa", "artillery", "infantry", "ship", "boat", "freighter", "hangar", "technic", "vent", "railway", "freight"]
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
        self.max_reload_cache = {}
        
        self.last_my_unit = 0 
        self.vel_window = {} 
        
        self.last_frame_time = time.time()
        self.current_fps = 0.0
        
        self.center_x = SCREEN_WIDTH / 2
        self.center_y = SCREEN_HEIGHT / 2
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(12) 

    def paintEvent(self, event):
        now = time.time()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        if dt > 0:
            fps = 1.0 / dt
            self.current_fps = (self.current_fps * 0.9) + (fps * 0.1) 
            
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        
        seen_targets_this_frame = set()
        curr_t = time.time()
        
        try:
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            current_bullet_speed = get_bullet_speed(self.scanner, cgame_base)
            current_zeroing = get_sight_compensation_factor(self.scanner, self.base_address)
            current_bullet_mass = get_bullet_mass(self.scanner, cgame_base)
            current_bullet_caliber = get_bullet_caliber(self.scanner, cgame_base)
            current_bullet_cd = get_bullet_cd(self.scanner, cgame_base)
            
            # painter.setPen(QColor(*COLOR_INFO_TEXT))
            # painter.drawText(20, 30, f"🔫 WTM ABSOLUTE RAYMARCHING")
            # painter.drawText(20, 50, f"⚡ VELOCITY : {current_bullet_speed:.0f} m/s")
            # painter.drawText(20, 70, f"🔭 ZEROING  : {current_zeroing:.0f} m")

            if self.current_fps > 45:
                painter.setPen(QColor(*COLOR_FPS_GOOD))
            else:
                painter.setPen(QColor(255, 50, 50))
            painter.drawText(20, 90, f"📈 FPS : {int(self.current_fps)}")
            
            painter.setPen(QColor(*COLOR_INFO_TEXT))
            # if current_bullet_mass > 0:
                # painter.drawText(20, 110, f"⚖️ SHELL    : {current_bullet_mass:.2f}kg | Cd: {current_bullet_cd:.3f}")

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

            if my_unit != self.last_my_unit:
                if hasattr(self.scanner, "bone_cache"): self.scanner.bone_cache = {} 
                self.max_reload_cache = {} 
                self.vel_window = {}
                self.last_my_unit = my_unit

            valid_targets = []
            for u_ptr, is_air in all_units_data:
                # 🚫 ซ่อนเครื่องตัวเอง (Disable My unit overlays)
                if u_ptr == my_unit: continue 
                
                status = get_unit_status(self.scanner, u_ptr)
                if not status: continue
                u_team, u_state, unit_name, reload_val = status 
                if u_state >= 1: continue 
                
                # ซ่อนเพื่อนร่วมทีม
                if my_team != 0 and u_team == my_team: continue
                
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

                    barrel_base_2d = None
                    barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R)
                    if barrel_data:
                        p1, p2 = barrel_data
                        res_p1 = world_to_screen(view_matrix, p1[0], p1[1], p1[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        res_p2 = world_to_screen(view_matrix, p2[0], p2[1], p2[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                            painter.setPen(QPen(QColor(*COLOR_BARREL_LINE), 2)) 
                            painter.drawLine(int(res_p1[0]), int(res_p1[1]), int(res_p2[0]), int(res_p2[1]))
                            barrel_base_2d = res_p1 

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
                        # 🚀 THE ITERATIVE RAYMARCHING ENGINE (ABSOLUTE ACCURACY)
                        # -----------------------------------------------------
                        vel = get_unit_velocity(self.scanner, u_ptr, is_air_target)
                        
                        if vel and my_pos and dist > 10.0:
                            vx, vy, vz = vel
                            ax, ay, az = 0.0, 0.0, 0.0
                            
                            # ดึงความเร่งบริสุทธิ์จาก Sliding Window
                            if is_air_target:
                                t_x, t_y, t_z = pos[0], pos[1], pos[2] 
                                if u_ptr not in self.vel_window:
                                    self.vel_window[u_ptr] = []
                                
                                window = self.vel_window[u_ptr]
                                window.append((curr_t, vx, vy, vz))
                                while len(window) > 0 and curr_t - window[0][0] > 0.2:
                                    window.pop(0)
                                    
                                if len(window) >= 2:
                                    old_t, ovx, ovy, ovz = window[0]
                                    dt_win = curr_t - old_t
                                    if dt_win > 0.05: 
                                        ax = (vx - ovx) / dt_win
                                        ay = (vy - ovy) / dt_win
                                        az = (vz - ovz) / dt_win
                                        
                                        a_mag = math.sqrt(ax**2 + ay**2 + az**2)
                                        if a_mag < 3.0: 
                                            ax, ay, az = 0.0, 0.0, 0.0
                                        elif a_mag > 150.0: 
                                            ax = (ax / a_mag) * 150.0
                                            ay = (ay / a_mag) * 150.0
                                            az = (az / a_mag) * 150.0
                            else:
                                t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                            # ระบบแรงต้านอากาศ (Drag)
                            if current_bullet_mass > 0.001 and current_bullet_caliber > 0.001:
                                Cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                                rho = 1.225
                                area = math.pi * ((current_bullet_caliber / 2.0) ** 2)
                                k = (0.5 * rho * Cd * area) / current_bullet_mass
                            else:
                                k = 0.0001
                                
                            t_sight = current_zeroing / current_bullet_speed if current_bullet_speed > 0 else 0
                            sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)
                                
                            # 🧠 THE RAYMARCHING LOOP (แม่นยำที่สุด)
                            sim_t = 0.0       
                            sim_dt = 0.025     
                            max_sim_time = 5.0 
                            
                            sim_x, sim_y, sim_z = t_x, t_y, t_z
                            sim_vx, sim_vy, sim_vz = vx, vy, vz
                            
                            best_t = 0.0
                            final_x, final_y, final_z = sim_x, sim_y, sim_z
                            
                            while sim_t < max_sim_time:
                                if sim_t < 1.5:
                                    sim_vx += ax * sim_dt
                                    sim_vy += ay * sim_dt
                                    sim_vz += az * sim_dt
                                    
                                sim_x += sim_vx * sim_dt
                                sim_y += sim_vy * sim_dt
                                sim_z += sim_vz * sim_dt
                                
                                sim_t += sim_dt
                                
                                dx = sim_x - my_pos[0]
                                dy = sim_y - (my_pos[1] + 1.5)
                                dz = sim_z - my_pos[2]
                                dist_to_sim = math.sqrt(dx*dx + dy*dy + dz*dz)
                                
                                if current_bullet_speed > 0:
                                    if k > 0.000001:
                                        kx = min(k * dist_to_sim, 5.0)
                                        bullet_t = (math.exp(kx) - 1.0) / (k * current_bullet_speed)
                                    else:
                                        bullet_t = dist_to_sim / current_bullet_speed
                                else:
                                    bullet_t = 999.0
                                    
                                # 🎯 เมื่อกระสุนวิ่งทันจุดที่จำลองไว้ (Intersection)
                                if bullet_t <= sim_t:
                                    best_t = bullet_t
                                    # นำค่าจำลอง 100% จากลูปมาใช้ ไม่มีการคูณ 1.10 หรือสมการขยะมาผสม!
                                    final_x, final_y, final_z = sim_x, sim_y, sim_z 
                                    break
                            
                            drop = 0.5 * BULLET_GRAVITY * (best_t * best_t)
                            net_drop = drop - sight_drop_comp
                            
                            # ลบความเร็วตัวเรา (เผื่อเราขับรถไปยิงไป)
                            final_x -= (my_vx * best_t)
                            final_y = final_y - (my_vy * best_t) + net_drop 
                            final_z -= (my_vz * best_t)
                            
                            pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, SCREEN_WIDTH, SCREEN_HEIGHT)
                            
                            if pred_screen and pred_screen[2] > 0:
                                draw_start_x, draw_start_y = avg_x, avg_y
                                if is_air_target:
                                    pos_screen = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                                    if pos_screen and pos_screen[2] > 0:
                                        draw_start_x, draw_start_y = pos_screen[0], pos_screen[1]
                                        
                                # 👁️ อัปเกรดความชัดเจนของเป้าดัก (High Visibility)
                                painter.setPen(QPen(QColor(255, 100, 100, 150), 2, Qt.DashLine))
                                painter.drawLine(int(draw_start_x), int(draw_start_y), int(pred_screen[0]), int(pred_screen[1]))
                                
                                # วงกลมหลัก: แดงสด, หนา 3, ขยายใหญ่ขึ้น
                                painter.setPen(QPen(QColor(*COLOR_PREDICTION), 3))
                                painter.drawEllipse(int(pred_screen[0]) - 8, int(pred_screen[1]) - 8, 16, 16)
                                
                                # จุดศูนย์กลางตรงกลาง (Core)
                                painter.setBrush(QColor(*COLOR_PREDICTION))
                                painter.drawEllipse(int(pred_screen[0]) - 3, int(pred_screen[1]) - 3, 6, 6)
                                painter.setBrush(Qt.NoBrush)
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
                            else:
                                if dist > 550: hide_name = True

                        if hide_name: display_text = f"-{int(dist)}m-"
                        else: display_text = f"{clean_name.upper()} [{int(dist)}m]"
                            
                        fm = painter.fontMetrics()
                        text_w = fm.boundingRect(display_text).width()
                        text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)

                        aiming_me = False
                        if my_pos and barrel_data and dist > 10.0:
                            aiming_me = is_aiming_at(barrel_data[0], barrel_data[1], my_pos, threshold_degrees=6.0)

                        if aiming_me:
                            dot_text = "●"
                            dot_w = fm.boundingRect(dot_text).width()
                            dot_x = int(avg_x - dot_w / 2) 
                            dot_y = text_y - 14 
                            t_anim = (math.sin(time.time() * 15.0) + 1.0) / 2.0
                            r, g = int(t_anim * 255), int(255 - (t_anim * 90))
                            
                            painter.setPen(QColor(r, g, 0, 50))
                            for ox, oy in [(-1,-1), (1,-1), (-1,1), (1,1), (0,-2), (0,2), (-2,0), (2,0)]:
                                painter.drawText(dot_x + ox, dot_y + oy, dot_text)
                            painter.setPen(QColor(r, g, 0, 255))
                            painter.drawText(dot_x, dot_y, dot_text)

                            line_dest_x = barrel_base_2d[0] if barrel_base_2d else avg_x
                            line_dest_y = barrel_base_2d[1] if barrel_base_2d else avg_y
                            glow_thickness = max(3, int(t_anim * 6))
                            painter.setPen(QPen(QColor(r, g, 0, 80), glow_thickness))
                            painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))
                            painter.setPen(QPen(QColor(r, g, 0, 255), 2))
                            painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))

                        if is_air_target: painter.setPen(QColor(*COLOR_TEXT_AIR))
                        else: painter.setPen(QColor(*COLOR_TEXT_GROUND))
                            
                        painter.drawText(int(avg_x - text_w/2), text_y, display_text)

                        if has_reload_bar:
                            if u_ptr not in self.max_reload_cache: self.max_reload_cache[u_ptr] = reload_val
                            if reload_val > self.max_reload_cache[u_ptr]: self.max_reload_cache[u_ptr] = reload_val
                            max_val = self.max_reload_cache[u_ptr]
                            progress = 1.0 if (reload_val == 0 or max_val == 0) else 1.0 - (float(reload_val) / float(max_val))
                                
                            bar_w, bar_h = 40, 4
                            bar_x, bar_y = int(avg_x - bar_w / 2), int(min_y - 8)
                            
                            painter.setPen(Qt.NoPen)
                            painter.setBrush(QColor(*COLOR_RELOAD_BG))
                            painter.drawRect(bar_x, bar_y, bar_w, bar_h)
                            
                            fill_w = int(bar_w * progress)
                            if progress >= 0.99: painter.setBrush(QColor(*COLOR_RELOAD_READY))   
                            else: painter.setBrush(QColor(*COLOR_RELOAD_LOADING)) 
                            painter.drawRect(bar_x, bar_y, fill_w, bar_h)

                except Exception:
                    pass

            dead_targets = [ptr for ptr in self.vel_window if ptr not in seen_targets_this_frame]
            for ptr in dead_targets:
                del self.vel_window[ptr]

        except Exception as e: 
            print(e)
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