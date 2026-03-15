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
COLOR_PREDICTION     = (255, 0, 255, 255)    
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
        
        # 🤖 ตัวแปรระบบ AI Auto-Calibration
        self.ai_ghost_queue = [] # คิวเก็บพิกัดอนาคตคู่ขนาน
        self.dynamic_decay = 0.15 # ค่าเริ่มต้นของการเลี้ยว (จะเปลี่ยนอัตโนมัติ)
        
        self.target_idx = 0
        self.q_pressed_last = False
        
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
            self.current_fps = (self.current_fps * 0.9) + ((1.0 / dt) * 0.1) 
            
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        
        seen_targets_this_frame = set()
        curr_t = time.time()
        lead_marks_to_draw = []
        
        closest_crosshair_dist = float('inf')
        active_flight_data = None 
        active_target_ptr = 0
        
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

            # 🤖 โชว์สถานะ AI บนหน้าจอซ้ายบน
            painter.setPen(QColor(*COLOR_FPS_GOOD) if self.current_fps > 45 else QColor(255, 50, 50))
            painter.drawText(20, 90, f"📈 FPS : {int(self.current_fps)}")
            painter.setPen(QColor(0, 255, 255, 255))
            painter.drawText(20, 115, f"🧠 AI Auto-Turn Decay : {self.dynamic_decay:.3f}")
            
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
                self.ai_ghost_queue = [] # ล้าง AI Queue เมื่อเปลี่ยนรถ
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
            # 1. หาระยะห่างเพื่อหาเป้าหมายหลักก่อน
            for u_ptr, raw_name, reload_val, is_air_target in valid_targets:
                if not is_air_target: continue
                pos = get_unit_pos(self.scanner, u_ptr)
                if not pos: continue
                
                res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                if res_pos and res_pos[2] > 0:
                    dist_crosshair = math.hypot(res_pos[0] - self.center_x, res_pos[1] - self.center_y)
                    if dist_crosshair < closest_crosshair_dist:
                        closest_crosshair_dist = dist_crosshair
                        active_target_ptr = u_ptr

            # ========================================================
            # 🧠 AI EVALUATION STEP (ประเมินผลการทำนายในอดีต)
            # ========================================================
            # คัดกรองและประเมินคิวที่เวลามาถึงแล้ว (หน่วงเวลาไปแล้ว 1.0 วินาที)
            remaining_ghosts = []
            for ghost in self.ai_ghost_queue:
                if curr_t >= ghost['impact_time']:
                    # เวลามาถึงแล้ว! เรามาดูว่าเป้าหมายจริงอยู่ไหน
                    if ghost['target_id'] == active_target_ptr:
                        actual_pos = get_unit_pos(self.scanner, ghost['target_id'])
                        if actual_pos:
                            # เทียบความห่างของสมการทั้ง 3 แบบกับความจริง
                            err1 = math.hypot(ghost['p1'][0]-actual_pos[0], ghost['p1'][1]-actual_pos[1], ghost['p1'][2]-actual_pos[2])
                            err2 = math.hypot(ghost['p2'][0]-actual_pos[0], ghost['p2'][1]-actual_pos[1], ghost['p2'][2]-actual_pos[2])
                            err3 = math.hypot(ghost['p3'][0]-actual_pos[0], ghost['p3'][1]-actual_pos[1], ghost['p3'][2]-actual_pos[2])
                            
                            # หาว่าแบบไหนแม่นสุด
                            min_err = min(err1, err2, err3)
                            best_decay_for_this_frame = self.dynamic_decay
                            if min_err == err1: best_decay_for_this_frame = 0.05  # เลี้ยวแคบ
                            elif min_err == err3: best_decay_for_this_frame = 0.35 # เลี้ยวกว้าง
                            
                            # Gradient Update: เลื่อนค่าหลักของโปรแกรมเข้าหาค่าที่แม่นยำที่สุด (Smooth Learning)
                            learning_rate = 0.05
                            self.dynamic_decay = (self.dynamic_decay * (1.0 - learning_rate)) + (best_decay_for_this_frame * learning_rate)
                            
                            # ตรึงค่าไว้ไม่ให้ AI เพี้ยนไปไกล
                            self.dynamic_decay = max(0.01, min(self.dynamic_decay, 0.8))
                else:
                    remaining_ghosts.append(ghost)
                    
            self.ai_ghost_queue = remaining_ghosts

            # ========================================================
            # 🎯 CALCULATE & RENDER TARGETS
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
                            box_color = QColor(255, 0, 255, 255) if u_ptr == active_target_ptr else QColor(*COLOR_BOX_TARGET)
                            painter.setPen(QPen(box_color, 2))
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

                    # ========================================================
                    # 🚀 KINEMATICS & ANTI-JITTER FILTER
                    # ========================================================
                    vel = get_unit_velocity(self.scanner, u_ptr, is_air_target)
                    is_turning = False 
                    
                    if not vel or current_bullet_speed <= 0 or not my_pos or dist <= 10.0: continue
                        
                    vx, vy, vz = vel
                    ax, ay, az = 0.0, 0.0, 0.0
                    
                    if is_air_target:
                        if u_ptr not in self.vel_window:
                            self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (0.0, 0.0, 0.0), 'fail_count': 0}
                        else:
                            history = self.vel_window[u_ptr]
                            old_v, old_t, old_a, fail_count = history['v'], history['time'], history['a'], history.get('fail_count', 0)
                            
                            if vx != old_v[0] or vy != old_v[1] or vz != old_v[2]:
                                dt_track = curr_t - old_t
                                if dt_track >= 0.01: 
                                    raw_ax = (vx - old_v[0]) / dt_track
                                    raw_ay = (vy - old_v[1]) / dt_track
                                    raw_az = (vz - old_v[2]) / dt_track
                                    
                                    alpha = 0.85 
                                    ax = old_a[0] + alpha * (raw_ax - old_a[0])
                                    ay = old_a[1] + alpha * (raw_ay - old_a[1])
                                    az = old_a[2] + alpha * (raw_az - old_a[2])
                                    self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (ax, ay, az), 'fail_count': 0}
                                else:
                                    ax, ay, az = old_a
                            else:
                                fail_count += 1
                                ax, ay, az = old_a
                                if fail_count > 12: ax, ay, az = 0.0, 0.0, 0.0
                                self.vel_window[u_ptr] = {'time': old_t, 'v': old_v, 'a': (ax, ay, az), 'fail_count': fail_count}
                                
                        a_mag = math.sqrt(ax**2 + ay**2 + az**2)
                        if a_mag > 3.0: is_turning = True
                        if a_mag > 150.0: ax, ay, az = (ax/a_mag)*150.0, (ay/a_mag)*150.0, (az/a_mag)*150.0
                        t_x, t_y, t_z = pos[0], pos[1], pos[2]
                        
                        # 🧠 AI GHOST PREDICTION STEP: ทิ้งพิกัดอนาคต 1 วินาที ไว้ให้ตัวเองตรวจข้อสอบทีหลัง
                        if u_ptr == active_target_ptr and len(self.ai_ghost_queue) < 100:
                            sim_t = 1.0 # ทำนายอนาคตล่วงหน้า 1 วินาที
                            
                            def get_pred_pos(d_rate):
                                a_t = (d_rate * sim_t - 1.0 + math.exp(-d_rate * sim_t)) / (d_rate**2) if d_rate>0 else 0.0
                                return (t_x + vx*sim_t + ax*a_t, t_y + vy*sim_t + ay*a_t, t_z + vz*sim_t + az*a_t)

                            self.ai_ghost_queue.append({
                                'impact_time': curr_t + sim_t,
                                'target_id': u_ptr,
                                'p1': get_pred_pos(0.05),                 # สมมติฐาน 1: เลี้ยวแคบ
                                'p2': get_pred_pos(self.dynamic_decay),   # สมมติฐาน 2: ค่าปัจจุบัน
                                'p3': get_pred_pos(0.35)                  # สมมติฐาน 3: เลี้ยวกว้าง
                            })
                            
                            active_flight_data = {'pos': pos, 'v': vel, 'a': (ax, ay, az)}
                    else:
                        t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                    # =========================================================
                    # 🚀 EXACT ANALYTICAL SOLVER
                    # =========================================================
                    if dist <= 1500.0:
                        DRAG_TUNE = 0.20 + (0.35 * (dist / 1500.0))
                    else:
                        DRAG_TUNE = 0.55 + (0.15 * min((dist - 1500.0) / 2000.0, 1.0))
                        
                    k = 0.0001
                    if current_bullet_mass > 0.001 and current_bullet_caliber > 0.001:
                        Cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                        altitude = max(0.0, my_pos[1])
                        rho = 1.225 * math.pow(max(1.0 - (2.25577e-5 * altitude), 0.0), 4.2561)
                        area = math.pi * ((current_bullet_caliber / 2.0) ** 2)
                        k = ((0.5 * rho * Cd * area) / current_bullet_mass) * DRAG_TUNE

                    t_sight = current_zeroing / current_bullet_speed if current_bullet_speed > 0 else 0
                    sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)
                    
                    best_t = dist / current_bullet_speed if current_bullet_speed > 0 else 0.1
                    final_x, final_y, final_z = t_x, t_y, t_z
                    
                    for _ in range(4):
                        if is_air_target:
                            # 🧠 ใช้งานค่า Decay Rate ที่ AI เพิ่งจะปรับแต่งมาให้แบบ Real-time!
                            a_term = (self.dynamic_decay * best_t - 1.0 + math.exp(-self.dynamic_decay * best_t)) / (self.dynamic_decay**2) if best_t > 0 else 0.0
                            pred_x = t_x + (vx * best_t) + (ax * a_term)
                            pred_y = t_y + (vy * best_t) + (ay * a_term)
                            pred_z = t_z + (vz * best_t) + (az * a_term)
                        else:
                            pred_x = t_x + (vx * best_t)
                            pred_y = t_y + (vy * best_t)
                            pred_z = t_z + (vz * best_t)
                        
                        dx_imp = pred_x - (my_pos[0] + my_vx * best_t)
                        dy_imp = pred_y - (my_pos[1] + 1.5 + my_vy * best_t)
                        dz_imp = pred_z - (my_pos[2] + my_vz * best_t)
                        d_imp = math.sqrt(dx_imp**2 + dy_imp**2 + dz_imp**2)
                        
                        if current_bullet_speed > 0:
                            if k > 0.000001:
                                kx = min(k * d_imp, 5.0) 
                                best_t = (math.exp(kx) - 1.0) / (k * current_bullet_speed)
                            else:
                                best_t = d_imp / current_bullet_speed
                        else:
                            best_t = 999.0
                            
                        final_x, final_y, final_z = pred_x, pred_y, pred_z

                    gravity_offset = 0.5 * BULLET_GRAVITY * (best_t ** 2) * 1.05
                    final_y += (gravity_offset - sight_drop_comp)
                    
                    final_x -= (my_vx * best_t)
                    final_y -= (my_vy * best_t)
                    final_z -= (my_vz * best_t)
                    
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

            # ========================================================
            # 🚀 FLIGHT PATH SIMULATION RENDERER (ด้วย AI Data)
            # ========================================================
            if active_flight_data:
                c_pos, c_v, c_a = active_flight_data['pos'], active_flight_data['v'], active_flight_data['a']
                path_pts = []
                for step in range(30): 
                    t_sim = step * 0.1
                    # เส้นทางการบินวาดตามสมอง AI ที่กำลังปรับจูนอยู่
                    a_term = (self.dynamic_decay * t_sim - 1.0 + math.exp(-self.dynamic_decay * t_sim)) / (self.dynamic_decay**2) if t_sim > 0 else 0.0
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
            # 🔝 FRONT LAYER RENDERER
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