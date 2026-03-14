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
COLOR_PREDICTION     = (255, 255, 255, 255)    # 🔴 สีเป้าดักหน้า 
COLOR_FPS_GOOD       = (0, 255, 0, 255)      

BULLET_GRAVITY       = 9.80665   # ค่า G ตามมาตรฐานเป๊ะๆ

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

def is_ground_threat(barrel_base, barrel_tip, target_pos):
    bx = barrel_tip[0] - barrel_base[0]
    by = barrel_tip[1] - barrel_base[1]
    bz = barrel_tip[2] - barrel_base[2]
    
    tx = target_pos[0] - barrel_base[0]
    ty = target_pos[1] - barrel_base[1]
    tz = target_pos[2] - barrel_base[2]
    
    dist_2d = math.hypot(tx, tz)
    len_b_2d = math.hypot(bx, bz)
    
    if dist_2d < 0.001 or len_b_2d < 0.001: return False
    
    dot_2d = (bx*tx + bz*tz) / (len_b_2d * dist_2d)
    dot_2d = max(-1.0, min(1.0, dot_2d))
    yaw_angle = math.degrees(math.acos(dot_2d))
    
    barrel_pitch = math.degrees(math.atan2(by, len_b_2d))
    target_pitch = math.degrees(math.atan2(ty, dist_2d))
    pitch_diff = barrel_pitch - target_pitch
    
    return yaw_angle <= .3 and -2.0 <= pitch_diff <= 6

class ESPOverlay(QWidget):
    def __init__(self, scanner, base_address):
        super().__init__()
        self.scanner = scanner
        self.base_address = base_address
        self.max_reload_cache = {}
        
        self.last_my_unit = 0 
        self.vel_window = {} # 🛡️ ประวัติศาสตร์ความเร็วสำหรับหาความเร่ง
        
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
        lead_marks_to_draw = []
        
        try:
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            # ดึงข้อมูลกระสุน
            current_bullet_speed = get_bullet_speed(self.scanner, cgame_base)
            current_zeroing = get_sight_compensation_factor(self.scanner, self.base_address)
            current_bullet_mass = get_bullet_mass(self.scanner, cgame_base)
            current_bullet_cd = get_bullet_cd(self.scanner, cgame_base)
            current_bullet_caliber = get_bullet_caliber(self.scanner, cgame_base)

            if self.current_fps > 45:
                painter.setPen(QColor(*COLOR_FPS_GOOD))
            else:
                painter.setPen(QColor(255, 50, 50))
            painter.drawText(20, 90, f"📈 FPS : {int(self.current_fps)}")
            
            painter.setPen(QColor(*COLOR_INFO_TEXT))

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
                if u_ptr == my_unit: continue 
                
                status = get_unit_status(self.scanner, u_ptr)
                if not status: continue
                u_team, u_state, unit_name, reload_val = status 
                if u_state >= 1: continue 
                
                if my_team != 0 and u_team == my_team: continue
                
                unit_name_lower = unit_name.lower()
                if any(kw in unit_name_lower for kw in BOT_KEYWORDS): continue
                valid_targets.append((u_ptr, unit_name, reload_val, is_air))

            # ========================================================
            # 🎯 Main Loop
            # ========================================================
            for u_ptr, raw_name, reload_val, is_air_target in valid_targets:
                seen_targets_this_frame.add(u_ptr)
                try:
                    pos = None
                    box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                    
                    if box_data:
                        pos, bmin, bmax, R = box_data
                    else:
                        pos = get_unit_pos(self.scanner, u_ptr)
                        
                    if not pos: continue
                    
                    dist = 0
                    if my_pos:
                        dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2)

                    barrel_base_2d = None
                    barrel_data = None
                    if box_data:
                        barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R)
                        
                    has_valid_box = False
                    avg_x, avg_y, min_y = 0, 0, 0

                    if box_data:
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
                            has_valid_box = True

                    if not has_valid_box:
                        res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        if res_pos and res_pos[2] > 0:
                            box_w = max(20, int(3000 / (dist + 1))) if is_air_target else max(30, int(4000 / (dist + 1)))
                            box_h = box_w * 0.8 if is_air_target else box_w * 0.6
                            
                            painter.setPen(QPen(QColor(*COLOR_BOX_TARGET), 2))
                            painter.drawRect(int(res_pos[0] - box_w/2), int(res_pos[1] - box_h/2), int(box_w), int(box_h))
                            
                            avg_x = res_pos[0]
                            avg_y = res_pos[1]
                            min_y = res_pos[1] - box_h/2
                            has_valid_box = True

                    if not has_valid_box: continue 

                    if barrel_data:
                        p1, p2 = barrel_data
                        res_p1 = world_to_screen(view_matrix, p1[0], p1[1], p1[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        res_p2 = world_to_screen(view_matrix, p2[0], p2[1], p2[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                            painter.setPen(QPen(QColor(*COLOR_BARREL_LINE), 2)) 
                            painter.drawLine(int(res_p1[0]), int(res_p1[1]), int(res_p2[0]), int(res_p2[1]))
                            barrel_base_2d = res_p1 
                            
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

                    # ========================================================
                    # 🚨 DUAL THREAT WARNING SYSTEM
                    # ========================================================
                    warning_level = 0 
                    vel = get_unit_velocity(self.scanner, u_ptr, is_air_target)
                    
                    if is_air_target and my_pos and dist > 10.0:
                        if vel:
                            v_mag = math.sqrt(vel[0]**2 + vel[1]**2 + vel[2]**2)
                            if v_mag > 5.0: 
                                dx_v, dy_v, dz_v = vel[0]/v_mag, vel[1]/v_mag, vel[2]/v_mag
                                tx, ty, tz = my_pos[0] - pos[0], my_pos[1] - pos[1], my_pos[2] - pos[2]
                                t_mag = math.sqrt(tx**2 + ty**2 + tz**2)
                                if t_mag > 0:
                                    tx, ty, tz = tx/t_mag, ty/t_mag, tz/t_mag
                                    dot_prod = max(-1.0, min(1.0, dx_v*tx + dy_v*ty + dz_v*tz))
                                    angle = math.degrees(math.acos(dot_prod))
                                    if angle <= 2.5: 
                                        warning_level = 2
                                    elif angle <= 6.0:
                                        warning_level = 1
                                        
                    elif not is_air_target and my_pos and barrel_data and dist > 10.0:
                        is_alert = is_ground_threat(barrel_data[0], barrel_data[1], my_pos)
                        is_warn = is_aiming_at(barrel_data[0], barrel_data[1], my_pos, threshold_degrees=4.5)
                        
                        if is_alert: warning_level = 2
                        elif is_warn: warning_level = 1

                    if warning_level > 0:
                        line_dest_x = barrel_base_2d[0] if barrel_base_2d else avg_x
                        line_dest_y = barrel_base_2d[1] if barrel_base_2d else avg_y
                        
                        if warning_level == 2:
                            dot_text = "⚠️ THREAT!"
                            dot_w = fm.boundingRect(dot_text).width()
                            dot_x = int(avg_x - dot_w / 2) 
                            dot_y = text_y - 14 
                            
                            painter.setPen(QColor(255, 0, 0, 50))
                            for ox, oy in [(-1,-1), (1,-1), (-1,1), (1,1), (0,-2), (0,2), (-2,0), (2,0)]:
                                painter.drawText(dot_x + ox, dot_y + oy, dot_text)
                            
                            painter.setPen(QColor(255, 0, 0, 255))
                            painter.drawText(dot_x, dot_y, dot_text)

                            painter.setPen(QPen(QColor(255, 0, 0, 100), 5, Qt.DashLine))
                            painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))
                            painter.setPen(QPen(QColor(255, 0, 0, 255), 2, Qt.DashLine))
                            painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))
                            
                        elif warning_level == 1:
                            painter.setPen(QPen(QColor(255, 180, 0, 80), 5))
                            painter.drawLine(int(self.center_x), SCREEN_HEIGHT, int(line_dest_x), int(line_dest_y))
                            painter.setPen(QPen(QColor(255, 180, 0, 255), 2))
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
                        
                    # ========================================================
                    # 🚀 ZERO-LAG RADAR TRACKING (Exact Ghidra Method)
                    # ========================================================
                    is_turning = False 
                    
                    if not vel or current_bullet_speed <= 0:
                        continue
                        
                    vx, vy, vz = vel
                    ax, ay, az = 0.0, 0.0, 0.0
                    
                    if is_air_target:
                        t_x, t_y, t_z = pos[0], pos[1], pos[2]
                        if u_ptr not in self.vel_window:
                            self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (0.0, 0.0, 0.0)}
                        else:
                            history = self.vel_window[u_ptr]
                            dt_track = curr_t - history['time']
                            
                            if dt_track >= 0.033: # Update ความเร่งที่ 30Hz (เท่ากับ Tick เกม)
                                raw_ax = (vx - history['v'][0]) / dt_track
                                raw_ay = (vy - history['v'][1]) / dt_track
                                raw_az = (vz - history['v'][2]) / dt_track
                                
                                # EMA Filter เลียนแบบความหน่วงเรดาร์ในเกม
                                alpha = 0.25 
                                ax = history['a'][0] + alpha * (raw_ax - history['a'][0])
                                ay = history['a'][1] + alpha * (raw_ay - history['a'][1])
                                az = history['a'][2] + alpha * (raw_az - history['a'][2])
                                
                                self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (ax, ay, az)}
                            else:
                                ax, ay, az = history['a']
                                
                        a_mag = math.sqrt(ax**2 + ay**2 + az**2)
                        if a_mag > 3.0: is_turning = True
                        if a_mag > 150.0: # Cap กันเป้ากระเด็น
                            ax = (ax / a_mag) * 150.0; ay = (ay / a_mag) * 150.0; az = (az / a_mag) * 150.0
                    else:
                        t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                    # =========================================================
                    # 🚀 THE EXACT ITERATIVE SOLVER (Newton-Raphson 5 Steps)
                    # =========================================================
                    k = 0.0001
                    if current_bullet_mass > 0.001 and current_bullet_caliber > 0.001:
                        Cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                        altitude = max(0.0, my_pos[1])
                        temp_lapse = 1.0 - (2.25577e-5 * altitude)
                        rho = 1.225 * math.pow(max(temp_lapse, 0.0), 4.2561)
                        area = math.pi * ((current_bullet_caliber / 2.0) ** 2)
                        k = (0.5 * rho * Cd * area) / current_bullet_mass

                    t_sight = current_zeroing / current_bullet_speed if current_bullet_speed > 0 else 0
                    sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)
                    
                    # 1. เดาเวลาเริ่มต้นจากความเร็วต้นดื้อๆ
                    best_t = dist / current_bullet_speed
                    final_x, final_y, final_z = t_x, t_y, t_z
                    
                    # 2. วนลูป 5 ครั้งเพื่อบีบหาจุดตัด (Converge)
                    for _ in range(5):
                        # คำนวณพิกัดเป้าหมายในอนาคต (บวกความเร่งและดึงความเร่งให้ลดลงตามเวลา)
                        decay = math.exp(-2.0 * best_t) if is_air_target else 1.0
                        
                        pred_x = t_x + (vx * best_t) + 0.5 * (ax * decay) * (best_t ** 2)
                        pred_y = t_y + (vy * best_t) + 0.5 * (ay * decay) * (best_t ** 2)
                        pred_z = t_z + (vz * best_t) + 0.5 * (az * decay) * (best_t ** 2)
                        
                        # หักลบความเร็วรถถังเรา (Shooter Velocity Compensation)
                        pred_x -= (my_vx * best_t)
                        pred_y -= (my_vy * best_t)
                        pred_z -= (my_vz * best_t)
                        
                        # คำนวณระยะทางใหม่
                        dx = pred_x - my_pos[0]
                        dy = pred_y - (my_pos[1] + 1.5)
                        dz = pred_z - my_pos[2]
                        d_new = math.sqrt(dx*dx + dy*dy + dz*dz)
                        
                        # ปรับเวลาใหม่ด้วยสมการ Air Drag
                        if k > 0.000001:
                            kx = min(k * d_new, 5.0) 
                            best_t = (math.exp(kx) - 1.0) / (k * current_bullet_speed)
                        else:
                            best_t = d_new / current_bullet_speed
                            
                        final_x, final_y, final_z = pred_x, pred_y, pred_z

                    # 3. ชดเชยแรงโน้มถ่วงขั้นสุดท้าย
                    drop = 0.5 * BULLET_GRAVITY * (best_t * best_t)
                    final_y += (drop - sight_drop_comp)
                    
                    pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, SCREEN_WIDTH, SCREEN_HEIGHT)
                    
                    if pred_screen and pred_screen[2] > 0:
                        draw_start_x, draw_start_y = avg_x, avg_y
                        if is_air_target:
                            pos_screen = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                            if pos_screen and pos_screen[2] > 0:
                                draw_start_x, draw_start_y = pos_screen[0], pos_screen[1]
                        
                        lead_marks_to_draw.append({
                            'sx': draw_start_x,
                            'sy': draw_start_y,
                            'px': pred_screen[0],
                            'py': pred_screen[1],
                            'is_air': is_air_target,
                            'is_turning': is_turning
                        })

                except Exception as e:
                    pass

            # ========================================================
            # 🔝 FRONT LAYER RENDERER (วาดเป้าดักหน้า)
            # ========================================================
            for lm in lead_marks_to_draw:
                painter.setPen(QPen(QColor(255, 100, 100, 150), 2, Qt.DashLine))
                painter.drawLine(int(lm['sx']), int(lm['sy']), int(lm['px']), int(lm['py']))
                
                pred_color = QColor(*COLOR_PREDICTION)
                if lm['is_air'] and lm['is_turning']:
                    blink_alpha = int(((math.sin(time.time() * 25.0) + 1.0) / 2.0) * 200 + 55)
                    pred_color.setAlpha(blink_alpha)
                else:
                    pred_color.setAlpha(255) 
                
                painter.setPen(QPen(pred_color, 3))
                painter.drawEllipse(int(lm['px']) - 8, int(lm['py']) - 8, 16, 16)
                painter.setBrush(pred_color)
                painter.drawEllipse(int(lm['px']) - 3, int(lm['py']) - 3, 6, 6)
                painter.setBrush(Qt.NoBrush)

            # ล้างประวัติเป้าหมายที่หลุดจอ/ตาย
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