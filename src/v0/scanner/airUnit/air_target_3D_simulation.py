import sys
import math
import time
import struct
import os

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    print("⚠️ กรุณาติดตั้งโมดูล keyboard: pip install keyboard")
    HAS_KEYBOARD = False

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from main import MemoryScanner, get_game_pid, get_game_base_address

# 🚨 นำเข้าฟังก์ชันทั้งหมด
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
COLOR_PREDICTION     = (0, 255, 255, 255)    
COLOR_FLIGHT_PATH    = (255, 200, 0, 180)    
COLOR_FPS_GOOD       = (0, 255, 0, 255)      

BULLET_GRAVITY       = 9.80665   

BOT_KEYWORDS = ["speaker","water", "panzerzug","windmill","dummy", "bot", "ai_", "_ai", "target", "truck", "cannon", "aaa", "artillery", "infantry", "ship", "boat", "freighter", "hangar", "technic", "vent", "railway", "freight"]
NAME_PREFIXES = ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_"]

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
        
        # 📊 ตัวแปรระบบ Logging (E)
        self.is_logging = False
        self.e_pressed_last = False
        self.log_buffer = [] 
        
        self.center_x = SCREEN_WIDTH / 2
        self.center_y = SCREEN_HEIGHT / 2
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(18) 

    def save_log_to_file(self):
        if not self.log_buffer: return
        filename = f"lead_calibration_log_{int(time.time())}.csv"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                # 🚨 อัปเดต Header: เพิ่ม Bullet_CD และ Bullet_Caliber เพื่อให้ข้อมูลครบ 100%
                f.write("Timestamp,Target_ID,Distance,T_PosX,T_PosY,T_PosZ,T_VelX,T_VelY,T_VelZ,T_AccX,T_AccY,T_AccZ,Pred_PosX,Pred_PosY,Pred_PosZ,Best_Time,Drag_K,Drag_Tune,Bullet_Speed,Bullet_Mass,Bullet_CD,Bullet_Caliber,My_PosX,My_PosY,My_PosZ,My_VelX,My_VelY,My_VelZ\n")
                for row in self.log_buffer:
                    f.write(",".join(map(lambda x: f"{x:.5f}" if isinstance(x, float) else str(x), row)) + "\n")
            print(f"✅ บันทึก Log สำเร็จ: {filename} (จำนวน {len(self.log_buffer)} เฟรม)")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการบันทึก Log: {e}")
        self.log_buffer.clear()

    def paintEvent(self, event):
        now = time.time()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        if dt > 0:
            self.current_fps = (self.current_fps * 0.9) + ((1.0 / dt) * 0.1) 
            
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        
        seen_targets_this_frame = set()
        curr_t = time.time()
        lead_marks_to_draw = []
        active_flight_data = None # เก็บข้อมูลวาด Flight Path ของเป้าหมายที่อยู่ใกล้เป้าเล็งสุด
        log_payload = None 
        
        # ========================================================
        # ⌨️ ตรวจจับปุ่ม E (Log)
        # ========================================================
        if HAS_KEYBOARD:
            try:
                is_e_pressed = keyboard.is_pressed('e')
                if is_e_pressed and not self.e_pressed_last:
                    self.is_logging = not self.is_logging
                    if not self.is_logging:
                        self.save_log_to_file()
                self.e_pressed_last = is_e_pressed
            except: pass
            
        if self.is_logging:
            blink = int(((math.sin(curr_t * 10.0) + 1.0) / 2.0) * 155 + 100)
            painter.setFont(QFont("Arial", 14, QFont.Bold))
            painter.setPen(QColor(255, 50, 50, blink))
            painter.drawText(int(self.center_x - 120), 50, "🔴 RECORDING LOGS [Press 'E' to Stop]")

        closest_crosshair_dist = float('inf')

        try:
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            cgame_base = get_cgame_base(self.scanner, self.base_address)
            if cgame_base == 0: return
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            if not view_matrix: return

            current_bullet_speed = get_bullet_speed(self.scanner, cgame_base)
            current_zeroing = get_sight_compensation_factor(self.scanner, self.base_address)
            current_bullet_mass = get_bullet_mass(self.scanner, cgame_base)
            current_bullet_cd = get_bullet_cd(self.scanner, cgame_base)
            current_bullet_caliber = get_bullet_caliber(self.scanner, cgame_base)

            painter.setPen(QColor(*COLOR_FPS_GOOD) if self.current_fps > 45 else QColor(255, 50, 50))
            painter.drawText(20, 90, f"📈 FPS : {int(self.current_fps)}")
            painter.setPen(QColor(*COLOR_INFO_TEXT))

            all_units_data = get_all_units(self.scanner, cgame_base) 
            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            my_is_air = False
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit:
                    my_is_air = is_air; break
            
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
                if u_state >= 1 or (my_team != 0 and u_team == my_team): continue 
                
                unit_name_lower = unit_name.lower()
                if any(kw in unit_name_lower for kw in BOT_KEYWORDS): continue
                valid_targets.append((u_ptr, unit_name, reload_val, is_air))

            # ========================================================
            # 🎯 MAIN PROCESSING LOOP
            # ========================================================
            for u_ptr, raw_name, reload_val, is_air_target in valid_targets:
                seen_targets_this_frame.add(u_ptr)
                try:
                    box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                    pos = box_data[0] if box_data else get_unit_pos(self.scanner, u_ptr)
                    if not pos: continue
                    
                    dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2) if my_pos else 0
                    has_valid_box = False
                    avg_x, avg_y, min_y = 0, 0, 0

                    if box_data:
                        corners_3d = calculate_3d_box_corners(pos, box_data[1], box_data[2], box_data[3])
                        pts = [p for c in corners_3d if (p := world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)) and p[2] >= 0.001]
                        if len(pts) == 8:
                            painter.setPen(QPen(QColor(*COLOR_BOX_TARGET), 2))
                            for e1, e2 in [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]: 
                                painter.drawLine(int(pts[e1][0]), int(pts[e1][1]), int(pts[e2][0]), int(pts[e2][1]))
                            min_y, avg_x, avg_y = min(p[1] for p in pts), sum(p[0] for p in pts)/8.0, sum(p[1] for p in pts)/8.0  
                            has_valid_box = True

                    if not has_valid_box:
                        res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                        if res_pos and res_pos[2] > 0:
                            box_w = max(20, int(3000 / (dist + 1))) if is_air_target else max(30, int(4000 / (dist + 1)))
                            box_h = box_w * 0.8 if is_air_target else box_w * 0.6
                            painter.setPen(QPen(QColor(*COLOR_BOX_TARGET), 2))
                            painter.drawRect(int(res_pos[0] - box_w/2), int(res_pos[1] - box_h/2), int(box_w), int(box_h))
                            avg_x, avg_y, min_y = res_pos[0], res_pos[1], res_pos[1] - box_h/2
                            has_valid_box = True

                    if not has_valid_box: continue 

                    clean_name = raw_name
                    for p in NAME_PREFIXES:
                        if clean_name.lower().startswith(p): clean_name = clean_name[len(p):]; break
                    
                    if is_air_target and my_pos and abs(pos[1] - my_pos[1]) < 50: is_air_target = False
                            
                    has_reload_bar = (not is_air_target and (0 <= reload_val < 500))
                    
                    # 📌 ระยะห่างหน้าจอเพื่อใช้กับระบบ Auto-Lock
                    dist_to_crosshair = math.hypot(avg_x - self.center_x, avg_y - self.center_y)
                    
                    hide_name = False if is_air_target else (dist > 550 and dist_to_crosshair >= 350)
                    display_text = f"-{int(dist)}m-" if hide_name else f"{clean_name.upper()} [{int(dist)}m]"
                        
                    fm = painter.fontMetrics()
                    text_w = fm.boundingRect(display_text).width()
                    text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)

                    painter.setPen(QColor(*COLOR_TEXT_AIR) if is_air_target else QColor(*COLOR_TEXT_GROUND))
                    painter.drawText(int(avg_x - text_w/2), text_y, display_text)

                    if has_reload_bar:
                        max_val = self.max_reload_cache.setdefault(u_ptr, reload_val)
                        if reload_val > max_val: self.max_reload_cache[u_ptr] = max_val = reload_val
                        progress = 1.0 if (reload_val == 0 or max_val == 0) else 1.0 - (float(reload_val) / float(max_val))
                        bar_w, bar_h, bar_x, bar_y = 40, 4, int(avg_x - 20), int(min_y - 8)
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QColor(*COLOR_RELOAD_BG))
                        painter.drawRect(bar_x, bar_y, bar_w, bar_h)
                        painter.setBrush(QColor(*COLOR_RELOAD_READY) if progress >= 0.99 else QColor(*COLOR_RELOAD_LOADING)) 
                        painter.drawRect(bar_x, bar_y, int(bar_w * progress), bar_h)
                        
                    # ========================================================
                    # 🚀 KINEMATICS & TARGET TRACKING FILTER
                    # ========================================================
                    vel = get_unit_velocity(self.scanner, u_ptr, is_air_target)
                    is_turning = False 
                    
                    if not vel or current_bullet_speed <= 0 or not my_pos or dist <= 10.0: continue
                        
                    vx, vy, vz = vel
                    ax, ay, az = 0.0, 0.0, 0.0
                    
                    if is_air_target:
                        if u_ptr not in self.vel_window:
                            self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (0.0, 0.0, 0.0)}
                        else:
                            history = self.vel_window[u_ptr]
                            dt_track = curr_t - history['time']
                            if dt_track >= 0.033: 
                                raw_ax = (vx - history['v'][0]) / dt_track
                                raw_ay = (vy - history['v'][1]) / dt_track
                                raw_az = (vz - history['v'][2]) / dt_track
                                
                                alpha = 0.25 
                                ax = history['a'][0] + alpha * (raw_ax - history['a'][0])
                                ay = history['a'][1] + alpha * (raw_ay - history['a'][1])
                                az = history['a'][2] + alpha * (raw_az - history['a'][2])
                                self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (ax, ay, az)}
                            else:
                                ax, ay, az = history['a']
                                
                        a_mag = math.sqrt(ax**2 + ay**2 + az**2)
                        if a_mag > 3.0: is_turning = True
                        if a_mag > 150.0: 
                            ax, ay, az = (ax / a_mag) * 150.0, (ay / a_mag) * 150.0, (az / a_mag) * 150.0
                            
                        t_x, t_y, t_z = pos[0], pos[1], pos[2]
                    else:
                        t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                    # =========================================================
                    # 🚀 EXACT ANALYTICAL SOLVER (สมการปริพันธ์แท้)
                    # =========================================================
                    DRAG_TUNE = 0.85
                    k = 0.0001
                    if current_bullet_mass > 0.001 and current_bullet_caliber > 0.001:
                        Cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                        altitude = max(0.0, my_pos[1])
                        rho = 1.225 * math.pow(max(1.0 - (2.25577e-5 * altitude), 0.0), 4.2561)
                        area = math.pi * ((current_bullet_caliber / 2.0) ** 2)
                        k = ((0.5 * rho * Cd * area) / current_bullet_mass) * DRAG_TUNE

                    t_sight = current_zeroing / current_bullet_speed
                    sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)
                    
                    best_t = dist / current_bullet_speed if current_bullet_speed > 0 else 0.1
                    final_x, final_y, final_z = t_x, t_y, t_z
                    pure_pred_x, pure_pred_y, pure_pred_z = t_x, t_y, t_z
                    
                    for _ in range(4):
                        if is_air_target:
                            a_term = (1.2 * best_t - 1.0 + math.exp(-1.2 * best_t)) / 1.44 if best_t > 0 else 0.0
                            pure_pred_x = t_x + (vx * best_t) + (ax * a_term)
                            pure_pred_y = t_y + (vy * best_t) + (ay * a_term)
                            pure_pred_z = t_z + (vz * best_t) + (az * a_term)
                        else:
                            pure_pred_x = t_x + (vx * best_t)
                            pure_pred_y = t_y + (vy * best_t)
                            pure_pred_z = t_z + (vz * best_t)
                        
                        dx_impact = pure_pred_x - (my_pos[0] + my_vx * best_t)
                        dy_impact = pure_pred_y - (my_pos[1] + 1.5 + my_vy * best_t)
                        dz_impact = pure_pred_z - (my_pos[2] + my_vz * best_t)
                        dist_to_impact = math.sqrt(dx_impact**2 + dy_impact**2 + dz_impact**2)
                        
                        if current_bullet_speed > 0:
                            if k > 0.000001:
                                kx = min(k * dist_to_impact, 5.0) 
                                best_t = (math.exp(kx) - 1.0) / (k * current_bullet_speed)
                            else:
                                best_t = dist_to_impact / current_bullet_speed
                        else:
                            best_t = 999.0
                            
                        final_x, final_y, final_z = pure_pred_x, pure_pred_y, pure_pred_z

                    drop = 0.5 * BULLET_GRAVITY * (best_t * best_t)
                    final_y += (drop - sight_drop_comp)
                    
                    final_x -= (my_vx * best_t)
                    final_y -= (my_vy * best_t)
                    final_z -= (my_vz * best_t)
                    
                    # ========================================================
                    # 📊 DYNAMIC AUTO-LOCK & LOGGING PAYLOAD
                    # ========================================================
                    # แทนที่การกด Q ด้วยการหาเป้าหมายที่อยู่ใกล้กลางจอที่สุด!
                    if is_air_target and dist_to_crosshair < closest_crosshair_dist:
                        closest_crosshair_dist = dist_to_crosshair
                        
                        # 1. เก็บข้อมูลไว้วาดหางจำลองเครื่องบิน (Flight Path)
                        active_flight_data = {'pos': pos, 'v': vel, 'a': (ax, ay, az)}
                        
                        # 2. จัดเตรียมข้อมูลสำหรับเก็บ Log (ครบทุกตัวแปรที่ใช้)
                        log_payload = [
                            curr_t, u_ptr, dist, 
                            t_x, t_y, t_z,                         # Target Pos
                            vx, vy, vz,                            # Target Vel
                            ax, ay, az,                            # Target Acc
                            pure_pred_x, pure_pred_y, pure_pred_z, # Predicted Exact Pos
                            best_t, k, DRAG_TUNE,                  # Ballistics Math
                            current_bullet_speed, current_bullet_mass,
                            current_bullet_cd, current_bullet_caliber, # Bullet Aero Data
                            my_pos[0], my_pos[1], my_pos[2],       # Shooter Pos
                            my_vx, my_vy, my_vz                    # Shooter Vel
                        ]

                    pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, SCREEN_WIDTH, SCREEN_HEIGHT)
                    
                    if pred_screen and pred_screen[2] > 0:
                        draw_sx, draw_sy = avg_x, avg_y
                        if is_air_target:
                            pos_scr = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                            if pos_scr and pos_scr[2] > 0: 
                                draw_sx, draw_sy = pos_scr[0], pos_scr[1]
                        
                        lead_marks_to_draw.append({
                            'sx': draw_sx, 'sy': draw_sy, 'px': pred_screen[0], 'py': pred_screen[1],
                            'is_air': is_air_target, 'is_turning': is_turning
                        })

                except Exception:
                    pass
            
            # บันทึก Payload ของ "เป้าที่ใกล้ศูนย์เล็งที่สุด" ลง Buffer
            if self.is_logging and log_payload:
                self.log_buffer.append(log_payload)

            # ========================================================
            # 🚀 FLIGHT PATH SIMULATION RENDERER (วาดหางอนาคตเฉพาะเป้า Auto-Lock)
            # ========================================================
            if active_flight_data:
                c_pos, c_v, c_a = active_flight_data['pos'], active_flight_data['v'], active_flight_data['a']
                path_pts = []
                for step in range(30): 
                    t_sim = step * 0.1
                    a_term = (1.2 * t_sim - 1.0 + math.exp(-1.2 * t_sim)) / 1.44
                    p_x = c_pos[0] + c_v[0] * t_sim + c_a[0] * a_term
                    p_y = c_pos[1] + c_v[1] * t_sim + c_a[1] * a_term
                    p_z = c_pos[2] + c_v[2] * t_sim + c_a[2] * a_term
                    
                    scr = world_to_screen(view_matrix, p_x, p_y, p_z, SCREEN_WIDTH, SCREEN_HEIGHT)
                    if scr and scr[2] > 0: path_pts.append((scr[0], scr[1]))
                
                if len(path_pts) > 1:
                    painter.setPen(QPen(QColor(*COLOR_FLIGHT_PATH), 2, Qt.DotLine))
                    for i in range(len(path_pts) - 1):
                        painter.drawLine(int(path_pts[i][0]), int(path_pts[i][1]), int(path_pts[i+1][0]), int(path_pts[i+1][1]))

            # ========================================================
            # 🔝 FRONT LAYER RENDERER (วาดเป้าดักหน้าเป็นชั้นบนสุด)
            # ========================================================
            for lm in lead_marks_to_draw:
                painter.setPen(QPen(QColor(255, 100, 100, 150), 2, Qt.DashLine))
                painter.drawLine(int(lm['sx']), int(lm['sy']), int(lm['px']), int(lm['py']))
                
                pred_color = QColor(*COLOR_PREDICTION)
                if lm['is_air'] and lm['is_turning']:
                    blink_alpha = int(((math.sin(time.time() * 25.0) + 1.0) / 2.0) * 150 + 105)
                    pred_color.setAlpha(blink_alpha)
                
                painter.setPen(QPen(pred_color, 3))
                painter.drawEllipse(int(lm['px']) - 8, int(lm['py']) - 8, 16, 16)
                painter.setBrush(pred_color)
                painter.drawEllipse(int(lm['px']) - 3, int(lm['py']) - 3, 6, 6)
                painter.setBrush(Qt.NoBrush)

            for ptr in [ptr for ptr in self.vel_window if ptr not in seen_targets_this_frame]:
                del self.vel_window[ptr]

        except Exception as e: 
            print(f"Main loop error: {e}")
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