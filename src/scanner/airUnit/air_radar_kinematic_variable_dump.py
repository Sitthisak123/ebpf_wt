import sys
import math
import time
import struct
import datetime
import keyboard # 🚨 ต้องติดตั้ง: pip install keyboard
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
COLOR_PREDICTION     = (255, 40, 40, 255)    
COLOR_FPS_GOOD       = (0, 255, 0, 255)      

# 🟢 สีสำหรับเป้าหมายที่เลือก (Selected Target) และตอนกด R (Flash)
COLOR_BOX_SELECTED   = (0, 255, 255, 255) # สีฟ้า Cyan
COLOR_BOX_FLASH      = (255, 255, 255, 255) # สีขาวสว่างวาบ

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
        self.vel_window = {} 
        
        self.last_frame_time = time.time()
        self.current_fps = 0.0
        
        # 🛠️ ตัวแปรสำหรับระบบ Debugging
        self.air_targets_list = []
        self.selected_target_idx = 0
        self.selected_target_ptr = 0
        self.debug_history = {} # เก็บข้อมูล 5 วินาทีย้อนหลัง {u_ptr: [data1, data2, ...]}
        self.flag_dump_data = False
        self.flash_timer = 0.0
        
        # ดักจับปุ่มกด (รันแบบ Asynchronous ไม่ทำให้จอกระตุก)
        keyboard.on_press_key('q', self.cmd_next_target)
        keyboard.on_press_key('e', self.cmd_record_dump)
        
        self.center_x = SCREEN_WIDTH / 2
        self.center_y = SCREEN_HEIGHT / 2
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(12) 
        
        print("\n" + "="*50)
        print("🛠️ DEBUGGING MODE ACTIVATED 🛠️")
        print("กด 'N' เพื่อเลื่อนเปลี่ยนเป้าหมายเครื่องบิน (จะขีดกรอบสีฟ้า)")
        print("กด 'R' เพื่อบันทึกข้อมูล (Dump) ย้อนหลัง 5 วินาทีลงไฟล์ .txt")
        print("="*50 + "\n")

    def cmd_next_target(self, e):
        if self.air_targets_list:
            self.selected_target_idx = (self.selected_target_idx + 1) % len(self.air_targets_list)
            self.selected_target_ptr = self.air_targets_list[self.selected_target_idx]
            print(f"[>] เปลี่ยนเป้าหมายเป็น Pointer: {hex(self.selected_target_ptr)}")

    def cmd_record_dump(self, e):
        if self.selected_target_ptr != 0:
            self.flag_dump_data = True
            self.flash_timer = time.time()
            print(f"[*] 🔴 กด R! กำลังบันทึกข้อมูลของ Pointer: {hex(self.selected_target_ptr)} ...")

    def perform_data_dump(self, unit_name):
        ptr = self.selected_target_ptr
        if ptr not in self.debug_history or len(self.debug_history[ptr]) == 0:
            print("[-] ไม่มีข้อมูลประวัติสำหรับเป้าหมายนี้!")
            return
            
        history = self.debug_history[ptr]
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"air_unit_{unit_name}_{timestamp_str}_dump.txt"
        
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"=== WAR THUNDER RAYMARCHING DEBUG DUMP ===\n")
                f.write(f"Time Triggered: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}\n")
                f.write(f"Target Name: {unit_name} | Pointer: {hex(ptr)}\n")
                f.write(f"Total Frames Logged: {len(history)} (Max ~5 seconds)\n")
                f.write("="*60 + "\n\n")
                
                # เขียน Header
                f.write("TimeDiff(s), BulletSpeed, Sim_Best_T, Target_Vx, Target_Vy, Target_Vz, Calc_Ax, Calc_Ay, Calc_Az, Dist(m)\n")
                f.write("-" * 120 + "\n")
                
                # เขียนข้อมูลย้อนหลัง 5 วิ
                ref_time = history[-1]['time'] # เวลาล่าสุด
                for data in history:
                    t_diff = data['time'] - ref_time
                    f.write(f"{t_diff:+.3f}, {data['bullet_speed']:.1f}, {data['best_t']:.4f}, ")
                    f.write(f"{data['vx']:.2f}, {data['vy']:.2f}, {data['vz']:.2f}, ")
                    f.write(f"{data['ax']:.3f}, {data['ay']:.3f}, {data['az']:.3f}, {data['dist']:.1f}\n")
                    
            print(f"[+] บันทึกไฟล์สำเร็จ: {filename}\n")
        except Exception as e:
            print(f"[-] เขียนไฟล์ล้มเหลว: {e}")

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
            current_bullet_cd = get_bullet_cd(self.scanner, cgame_base)
            current_bullet_caliber = get_bullet_caliber(self.scanner, cgame_base)

            if self.current_fps > 45:
                painter.setPen(QColor(*COLOR_FPS_GOOD))
            else:
                painter.setPen(QColor(255, 50, 50))
            painter.drawText(20, 90, f"📈 FPS : {int(self.current_fps)}")
            
            painter.setPen(QColor(*COLOR_INFO_TEXT))
            painter.drawText(20, 110, f"🛠️ DEBUG MODE (N=Next, R=Dump)")

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
                self.debug_history = {}
                self.last_my_unit = my_unit

            valid_targets = []
            current_air_ptrs = []
            
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
                
                if is_air: current_air_ptrs.append(u_ptr)

            # อัปเดตรายการเครื่องบินสำหรับปุ่ม N
            self.air_targets_list = current_air_ptrs
            if self.selected_target_ptr not in self.air_targets_list and len(self.air_targets_list) > 0:
                self.selected_target_idx = 0
                self.selected_target_ptr = self.air_targets_list[0]

            for u_ptr, raw_name, reload_val, is_air_target in valid_targets:
                seen_targets_this_frame.add(u_ptr)
                
                clean_name = raw_name
                for p in NAME_PREFIXES:
                    if clean_name.lower().startswith(p): clean_name = clean_name[len(p):]; break
                        
                is_selected_target = (u_ptr == self.selected_target_ptr)
                
                try:
                    pos = None
                    box_data = get_unit_3d_box_data(self.scanner, u_ptr)
                    
                    if box_data: pos, bmin, bmax, R = box_data
                    else: pos = get_unit_pos(self.scanner, u_ptr)
                        
                    if not pos: continue
                    
                    dist = 0
                    if my_pos: dist = math.sqrt((pos[0]-my_pos[0])**2 + (pos[1]-my_pos[1])**2 + (pos[2]-my_pos[2])**2)

                    barrel_base_2d = None
                    barrel_data = None
                    if box_data: barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R)
                        
                    has_valid_box = False
                    avg_x, avg_y, min_y = 0, 0, 0

                    # 🎨 จัดการสีกล่อง (ปกติ / เลือก / กด R กระพริบ)
                    box_color = QColor(*COLOR_BOX_TARGET)
                    if is_selected_target:
                        if curr_t - self.flash_timer < 0.2: # กด R แล้วสว่างวาบ 0.2 วิ
                            box_color = QColor(*COLOR_BOX_FLASH)
                        else:
                            box_color = QColor(*COLOR_BOX_SELECTED)

                    if box_data:
                        corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
                        pts = []
                        for c in corners_3d:
                            res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                            if res and res[2] >= 0.001: pts.append((res[0], res[1]))
                        
                        if len(pts) == 8:
                            painter.setPen(QPen(box_color, 3 if is_selected_target else 2))
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
                            painter.setPen(QPen(box_color, 3 if is_selected_target else 2))
                            painter.drawRect(int(res_pos[0] - box_w/2), int(res_pos[1] - box_h/2), int(box_w), int(box_h))
                            avg_x, avg_y, min_y = res_pos[0], res_pos[1], res_pos[1] - box_h/2
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
                    
                    if is_selected_target: display_text = "🎯 " + display_text # ใส่ไอคอนให้รู้ว่าเลือกอยู่
                        
                    fm = painter.fontMetrics()
                    text_w = fm.boundingRect(display_text).width()
                    text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)

                    if is_air_target: painter.setPen(QColor(*COLOR_TEXT_AIR))
                    else: painter.setPen(QColor(*COLOR_TEXT_GROUND))
                    painter.drawText(int(avg_x - text_w/2), text_y, display_text)
                        
                    # ========================================================
                    # 🚀 THE ITERATIVE RAYMARCHING ENGINE
                    # ========================================================
                    vel = get_unit_velocity(self.scanner, u_ptr, is_air_target)
                    
                    if vel and my_pos and dist > 10.0:
                        vx, vy, vz = vel
                        ax, ay, az = 0.0, 0.0, 0.0
                        
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
                                        
                                    if a_mag > 150.0: 
                                        ax = (ax / a_mag) * 150.0
                                        ay = (ay / a_mag) * 150.0
                                        az = (az / a_mag) * 150.0
                        else:
                            t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                        if current_bullet_mass > 0.001 and current_bullet_caliber > 0.001:
                            Cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                            rho = 1.225
                            area = math.pi * ((current_bullet_caliber / 2.0) ** 2)
                            k = (0.5 * rho * Cd * area) / current_bullet_mass
                        else:
                            k = 0.0001
                            
                        t_sight = current_zeroing / current_bullet_speed if current_bullet_speed > 0 else 0
                        sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)
                            
                        sim_t = 0.0       
                        sim_dt = 0.025     
                        max_sim_time = 10.0 
                        
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
                                
                            if bullet_t <= sim_t:
                                best_t = bullet_t
                                final_x, final_y, final_z = sim_x, sim_y, sim_z 
                                break
                        
                        drop = 0.5 * BULLET_GRAVITY * (best_t * best_t)
                        net_drop = drop - sight_drop_comp
                        
                        final_x -= (my_vx * best_t)
                        final_y = final_y - (my_vy * best_t) + net_drop 
                        final_z -= (my_vz * best_t)
                        
                        # -----------------------------------------------------
                        # 🛠️ HISTORY LOGGING (ระบบบันทึกข้อมูล 5 วินาทีย้อนหลัง)
                        # -----------------------------------------------------
                        if is_air_target and is_selected_target:
                            if u_ptr not in self.debug_history:
                                self.debug_history[u_ptr] = []
                            
                            self.debug_history[u_ptr].append({
                                'time': curr_t,
                                'vx': vx, 'vy': vy, 'vz': vz,
                                'ax': ax, 'ay': ay, 'az': az,
                                'dist': dist,
                                'bullet_speed': current_bullet_speed,
                                'best_t': best_t,
                                'pred_x': final_x, 'pred_y': final_y, 'pred_z': final_z
                            })
                            
                            # ลบข้อมูลที่เก่ากว่า 5 วินาทีทิ้ง
                            while len(self.debug_history[u_ptr]) > 0 and curr_t - self.debug_history[u_ptr][0]['time'] > 5.0:
                                self.debug_history[u_ptr].pop(0)
                                
                            # ตรวจสอบการกด R
                            if self.flag_dump_data:
                                self.perform_data_dump(clean_name)
                                self.flag_dump_data = False
                        
                        # วาดเป้าหน้าจอตามปกติ
                        pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, SCREEN_WIDTH, SCREEN_HEIGHT)
                        
                        if pred_screen and pred_screen[2] > 0:
                            draw_start_x, draw_start_y = avg_x, avg_y
                            if is_air_target:
                                pos_screen = world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                                if pos_screen and pos_screen[2] > 0:
                                    draw_start_x, draw_start_y = pos_screen[0], pos_screen[1]
                                    
                            painter.setPen(QPen(QColor(255, 100, 100, 150), 2, Qt.DashLine))
                            painter.drawLine(int(draw_start_x), int(draw_start_y), int(pred_screen[0]), int(pred_screen[1]))
                            painter.setPen(QPen(QColor(*COLOR_PREDICTION), 3))
                            painter.drawEllipse(int(pred_screen[0]) - 8, int(pred_screen[1]) - 8, 16, 16)
                            painter.setBrush(QColor(*COLOR_PREDICTION))
                            painter.drawEllipse(int(pred_screen[0]) - 3, int(pred_screen[1]) - 3, 6, 6)
                            painter.setBrush(Qt.NoBrush)

                except Exception:
                    pass

            dead_targets = [ptr for ptr in self.vel_window if ptr not in seen_targets_this_frame]
            for ptr in dead_targets:
                del self.vel_window[ptr]
                if ptr in self.debug_history:
                    del self.debug_history[ptr]

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