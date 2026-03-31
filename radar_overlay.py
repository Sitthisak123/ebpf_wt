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

# 🎯 นำเข้าจากระบบ Core Engine ที่แยกออกมาใหม่
from src.utils.scanner import *
from src.utils.mul import *
from src.utils.debug import *

COLOR_INFO_TEXT         = (255, 228, 64, 255)   
COLOR_BARREL_LINE       = (0, 255, 0, 255)      
COLOR_BOX_TARGET        = (255, 255, 0, 200)
COLOR_BOX_SELECT_TARGET = (255, 255, 0, 200)
COLOR_TEXT_GROUND       = (255, 196, 20, 200)    
COLOR_TEXT_AIR          = (255, 196, 20, 230)   
COLOR_RELOAD_BG         = (0, 0, 0, 180)        
COLOR_RELOAD_READY      = (255, 0, 0, 200)      
COLOR_RELOAD_LOADING    = (255, 165, 0, 200)    
COLOR_PREDICTION        = (255, 255, 255, 255)    
COLOR_FLIGHT_PATH       = (255, 200, 0, 150)    
COLOR_FPS_GOOD          = (0, 255, 0, 255)
COLOR_THREAD_TEXT       = (255, 0, 0, 50)
COLOR_THREAD_TEXT2      = (255, 0, 0, 255)
COLOR_THREAD_WARNING    = (255, 0, 0, 100)
COLOR_THREAD_WARNING2   = (255, 0, 0, 255) 
COLOR_THREAD_ALERT      = (255, 180, 0, 80)
COLOR_THREAD_ALERT2     = (255, 180, 0, 255)
COLOR_AXIS_X            = (255, 64, 64, 255)
COLOR_AXIS_Y            = (64, 255, 64, 255)
COLOR_AXIS_Z            = (64, 160, 255, 255)

BULLET_GRAVITY       = 9.80665   

DEBUG_DRAW_LOCAL_AXES = False
DEBUG_DRAW_LOCAL_AXES_GROUND_ONLY = False
DEBUG_AXIS_LENGTH_GROUND = 2.4
DEBUG_AXIS_LENGTH_AIR = 8.0
DEBUG_AXIS_LABELS_GROUND = {
    "X": "X/L",
    "Y": "Y/H",
    "Z": "Z/F",
}
DEBUG_AXIS_LABELS_AIR = {
    "X": "X/F",
    "Y": "Y/H",
    "Z": "Z/L",
}

BOT_KEYWORDS = [
    # "speaker", "water", "panzerzug", "windmill", "dummy", "dummy_plane",
    # "unit_fulda_windmill", "airfield", "noground", "fortification",
    # "bot", "ai_", "_ai", "target", "truck", "cannon", "aaa", "artillery",
    # "infantry", "freighter", "hangar", "technic", "vent", "railway", "freight",
]
NAME_PREFIXES = ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_"]
MAX_GROUND_TARGET_DISTANCE = 10000.0
MAX_AIR_TARGET_DISTANCE = 18000.0
ORIGIN_GHOST_RADIUS = 35.0
ORIGIN_GHOST_MY_DIST_MIN = 250.0

# 🎯 TURN BOOST: ตัวคูณช่วยดึงเป้าไปทางที่เลี้ยว
# 1.0 = ปกติ (ตามที่ AI คำนวณ)
# 1.15 = ดึงเป้าเผื่อเลี้ยวเพิ่มขึ้น 15%
# 1.30 = ดึงเป้าเผื่อเลี้ยวเพิ่มขึ้น 30%
DEBUG_LOG_INTERVAL = 0.5

# ========================================================
# 🚨 DUAL THREAT WARNING SYSTEM (จากเวอร์ชันเก่า)
# ========================================================
def is_aiming_at(barrel_base, barrel_tip, target_pos, threshold_degrees=6.0):
    dx = barrel_tip[0] - barrel_base[0]; dy = barrel_tip[1] - barrel_base[1]; dz = barrel_tip[2] - barrel_base[2]
    tx = target_pos[0] - barrel_base[0]; ty = target_pos[1] - barrel_base[1]; tz = target_pos[2] - barrel_base[2]
    len_d = math.sqrt(dx*dx + dy*dy + dz*dz)
    len_t = math.sqrt(tx*tx + ty*ty + tz*tz)
    if len_d < 0.001 or len_t < 0.001: return False
    dot_prod = max(-1.0, min(1.0, (dx*tx + dy*ty + dz*tz) / (len_d * len_t))) 
    return math.degrees(math.acos(dot_prod)) <= threshold_degrees

def is_ground_threat(barrel_base, barrel_tip, target_pos):
    bx = barrel_tip[0] - barrel_base[0]; by = barrel_tip[1] - barrel_base[1]; bz = barrel_tip[2] - barrel_base[2]
    tx = target_pos[0] - barrel_base[0]; ty = target_pos[1] - barrel_base[1]; tz = target_pos[2] - barrel_base[2]
    dist_2d = math.hypot(tx, tz)
    len_b_2d = math.hypot(bx, bz)
    if dist_2d < 0.001 or len_b_2d < 0.001: return False
    yaw_angle = math.degrees(math.acos(max(-1.0, min(1.0, (bx*tx + bz*tz) / (len_b_2d * dist_2d)))))
    pitch_diff = math.degrees(math.atan2(by, len_b_2d)) - math.degrees(math.atan2(ty, dist_2d))
    return yaw_angle <= .3 and -2.0 <= pitch_diff <= 6


def _read_ptr_fast(scanner, addr):
    try:
        raw = scanner.read_mem(addr, 8)
        if not raw or len(raw) < 8:
            return 0
        return struct.unpack("<Q", raw)[0]
    except Exception:
        return 0


def _read_f32_fast(scanner, addr, default=0.0):
    try:
        raw = scanner.read_mem(addr, 4)
        if not raw or len(raw) < 4:
            return default
        value = struct.unpack("<f", raw)[0]
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _smoothstep(edge0, edge1, x):
    if edge1 <= edge0:
        return 1.0 if x >= edge0 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _air_density_from_altitude(altitude):
    alt = max(0.0, altitude)
    return 1.225 * math.pow(max(1.0 - (2.25577e-5 * alt), 0.0), 4.2561)


def _read_ballistic_profile(scanner, cgame_base):
    profile = {
        "weapon_ptr": 0,
        "speed": 1000.0,
        "mass": 0.0,
        "caliber": 0.0,
        "cx": 0.0,
        "max_distance": 0.0,
        "vel_range": (0.0, 0.0),
    }
    weapon_ptr = _read_ptr_fast(scanner, cgame_base + OFF_WEAPON_PTR)
    if not is_valid_ptr(weapon_ptr):
        return profile

    props_base = weapon_ptr + (OFF_BULLET_MASS - 4)
    speed = _read_f32_fast(scanner, weapon_ptr + OFF_BULLET_SPEED, 1000.0)
    mass = _read_f32_fast(scanner, weapon_ptr + OFF_BULLET_MASS, 0.0)
    caliber = _read_f32_fast(scanner, weapon_ptr + OFF_BULLET_CALIBER, 0.0)
    cx = _read_f32_fast(scanner, weapon_ptr + OFF_BULLET_CD, 0.0)
    max_distance = _read_f32_fast(scanner, props_base + 0x10, 0.0)
    vel_min = _read_f32_fast(scanner, props_base + 0x24, 0.0)
    vel_max = _read_f32_fast(scanner, props_base + 0x28, 0.0)

    if not (50.0 <= speed <= 3000.0):
        speed = 1000.0
    if not (0.005 <= mass <= 200.0):
        mass = 0.0
    if not (0.001 <= caliber <= 0.5):
        caliber = 0.0
    if not (0.01 <= cx <= 3.0):
        cx = 0.0
    if vel_min < 0.0 or vel_min > 4000.0:
        vel_min = 0.0
    if vel_max < vel_min or vel_max > 4000.0:
        vel_max = max(vel_min, 0.0)

    profile.update({
        "weapon_ptr": weapon_ptr,
        "speed": speed,
        "mass": mass,
        "caliber": caliber,
        "cx": cx,
        "max_distance": max_distance,
        "vel_range": (vel_min, vel_max),
    })
    return profile


def _make_ballistic_model(profile, altitude):
    speed = max(profile.get("speed", 1000.0), 1.0)
    mass = max(profile.get("mass", 0.0), 0.001)
    caliber = max(profile.get("caliber", 0.0), 0.001)
    cx = profile.get("cx", 0.0)
    if cx <= 0.0:
        cx = 0.24 if speed >= 1200.0 else 0.35

    rho = _air_density_from_altitude(altitude)
    area = math.pi * ((caliber * 0.5) ** 2)
    base_k = (0.5 * rho * cx * area) / mass
    vel_lo, vel_hi = profile.get("vel_range", (0.0, 0.0))
    if vel_hi <= vel_lo:
        vel_lo = speed * 0.34
        vel_hi = speed * 0.48

    return {
        "speed": speed,
        "mass": mass,
        "caliber": caliber,
        "cx": cx,
        "rho": rho,
        "base_k": max(base_k, 1e-7),
        "vel_lo": max(0.0, vel_lo),
        "vel_hi": max(max(vel_lo, vel_hi), vel_lo + 1.0),
        "max_distance": max(profile.get("max_distance", 0.0), 0.0),
    }


def _get_leadmark_range_limit(profile):
    max_distance = max(profile.get("max_distance", 0.0), 0.0)
    if max_distance <= 1.0:
        return 0.0
    return max_distance * 0.8


def _drag_band_factor(model, speed):
    vel_lo = model["vel_lo"]
    vel_hi = model["vel_hi"]
    band = _smoothstep(vel_lo, vel_hi, speed)
    mach = speed / 343.0
    transonic = _smoothstep(0.78, 1.22, mach)
    supersonic = _smoothstep(1.15, 2.6, mach)
    factor = 0.84 + (0.18 * band) + (0.12 * transonic) - (0.06 * supersonic)
    if model["speed"] >= 1200.0:
        factor *= 0.92
    return max(0.55, min(1.18, factor))


def _simulate_projectile_range(horizontal_range, model, zero_pitch=0.0):
    if horizontal_range <= 0.001:
        return 0.0, 0.0, model["speed"]

    vx = model["speed"] * math.cos(zero_pitch)
    vy = -model["speed"] * math.sin(zero_pitch)
    x = 0.0
    y_down = 0.0
    t = 0.0
    prev_x = 0.0
    prev_y = 0.0
    prev_t = 0.0
    prev_speed = model["speed"]

    while x < horizontal_range and t < 12.0:
        speed_mag = math.hypot(vx, vy)
        if speed_mag < 25.0:
            break

        dt = max(0.003, min(0.012, 4.0 / (speed_mag + 1.0)))
        drag_scale = model["base_k"] * _drag_band_factor(model, speed_mag)
        ax = -drag_scale * speed_mag * vx
        ay = (drag_scale * speed_mag * -vy) + BULLET_GRAVITY

        prev_x = x
        prev_y = y_down
        prev_t = t
        prev_speed = speed_mag

        vx += ax * dt
        vy += ay * dt
        x += vx * dt
        y_down += vy * dt
        t += dt

    if x > prev_x and x >= horizontal_range:
        frac = (horizontal_range - prev_x) / max(x - prev_x, 1e-6)
        t = prev_t + ((t - prev_t) * frac)
        y_down = prev_y + ((y_down - prev_y) * frac)
        speed_mag = prev_speed + ((math.hypot(vx, vy) - prev_speed) * frac)
    else:
        speed_mag = math.hypot(vx, vy)

    return t, y_down, speed_mag


def _solve_zero_pitch(zeroing_distance, model):
    if zeroing_distance <= 1.0:
        return 0.0

    pitch = 0.0
    for _ in range(5):
        _, y_down, _ = _simulate_projectile_range(zeroing_distance, model, pitch)
        pitch += math.atan2(y_down, max(zeroing_distance, 1.0)) * 0.92
    return max(-0.08, min(0.18, pitch))


class ESPOverlay(QWidget):
    def __init__(self, scanner, base_address):
        super().__init__()
        set_dashboard_mode(True)
        self.scanner = scanner
        self.base_address = base_address
        self.max_reload_cache = {}
        self.profile_cache = {} # 🛡️ New Profile Cache
        self.last_my_unit = 0 
        self.vel_window = {} 
        self.velocity_cache = {}
        self.last_frame_time = time.time()
        self.current_fps = 0.0
        self.cached_matrix_offset = 0x1C0
        self.last_velocity_meta = {}
        self.last_cgame_base = 0
        
        # 🤖 AI Auto-Calibration for Maneuvers (6 Threads)
        self.ai_ghost_queue = []
        self.dynamic_decay = 0.15 
        
        self.target_cycle_index = 0
        self.q_pressed_last = False
        self.last_debug_log_time = 0.0
        self.console_initialized = False
        self.dead_unit_latch = set()
        self.ballistic_zero_cache = {}

        self._update_screen_metrics()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, self.screen_width, self.screen_height)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(12) 

    def _update_screen_metrics(self):
        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.geometry() if screen is not None else QApplication.desktop().screenGeometry()
        self.screen_width = geometry.width()
        self.screen_height = geometry.height()
        self.center_x = self.screen_width / 2
        self.center_y = self.screen_height / 2

    def _stabilize_velocity(self, u_ptr, is_air, pos, curr_t):
        if u_ptr and pos:
            raw_vel = get_air_velocity(self.scanner, u_ptr) if is_air else get_ground_velocity(self.scanner, u_ptr)
        else:
            raw_vel = (0.0, 0.0, 0.0)
        cached = self.velocity_cache.get(u_ptr)
        pos_vel = None

        if cached and pos:
            dt = curr_t - cached['time']
            min_dt = 0.005 if is_air else 0.03
            max_dt = 0.75 if is_air else 0.60
            if min_dt <= dt <= max_dt:
                dx = pos[0] - cached['pos'][0]
                dy = pos[1] - cached['pos'][1]
                dz = pos[2] - cached['pos'][2]
                pos_vel = (dx / dt, dy / dt, dz / dt)

        chosen_vel = raw_vel
        source = "raw"

        raw_mag = math.sqrt(raw_vel[0]**2 + raw_vel[1]**2 + raw_vel[2]**2)
        pos_mag = math.sqrt(pos_vel[0]**2 + pos_vel[1]**2 + pos_vel[2]**2) if pos_vel else 0.0
        max_jump = 90.0 if is_air else 12.0
        min_air_speed = 35.0 if is_air else 0.0

        if pos_vel:
            diff_mag = math.sqrt(
                (raw_vel[0] - pos_vel[0])**2 +
                (raw_vel[1] - pos_vel[1])**2 +
                (raw_vel[2] - pos_vel[2])**2
            )

            if raw_mag <= 0.001 and pos_mag > 0.001:
                chosen_vel = pos_vel
                source = "pos_only"
            elif pos_mag > 0.001 and diff_mag > max_jump:
                chosen_vel = pos_vel
                source = "pos_reject_raw"
            elif is_air and raw_mag < min_air_speed and pos_mag >= min_air_speed:
                chosen_vel = pos_vel
                source = "pos_air_floor"
            elif raw_mag > 0.001:
                chosen_vel = (
                    (raw_vel[0] * 0.65) + (pos_vel[0] * 0.35),
                    (raw_vel[1] * 0.65) + (pos_vel[1] * 0.35),
                    (raw_vel[2] * 0.65) + (pos_vel[2] * 0.35),
                )
                source = "blended"

        if not is_air:
            # Ground units often have tiny noisy vectors around zero.
            idle_speed = 0.22  # m/s (~0.8 km/h)
            if raw_mag <= idle_speed and (pos_vel is None or pos_mag <= idle_speed):
                chosen_vel = (0.0, 0.0, 0.0)
                source = "ground_idle"
            chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)

        self.velocity_cache[u_ptr] = {
            'time': curr_t,
            'pos': pos,
            'vel': chosen_vel,
        }
        self.last_velocity_meta[u_ptr] = {
            'source': source,
            'raw_vel': raw_vel,
            'raw_mag': raw_mag,
            'pos_vel': pos_vel,
            'pos_mag': pos_mag,
            'chosen_vel': chosen_vel,
        }

        if source not in ("raw", "ground_idle") and u_ptr != 0:
            msg = (
                "VEL STABILIZED"
                f" | unit={hex(u_ptr)}"
                f" | type={'AIR' if is_air else 'GROUND'}"
                f" | source={source}"
                f" | raw=({raw_vel[0]:.2f}, {raw_vel[1]:.2f}, {raw_vel[2]:.2f})"
            )
            if pos_vel:
                msg += f" | pos=({pos_vel[0]:.2f}, {pos_vel[1]:.2f}, {pos_vel[2]:.2f})"
            msg += f" | chosen=({chosen_vel[0]:.2f}, {chosen_vel[1]:.2f}, {chosen_vel[2]:.2f})"
            dprint(msg, force=False)

        return chosen_vel

    def paintEvent(self, event):
        self._update_screen_metrics()
        if self.width() != self.screen_width or self.height() != self.screen_height:
            self.setGeometry(0, 0, self.screen_width, self.screen_height)

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
        
        active_flight_data = None 
        active_target_ptr = 0
        
        if HAS_KEYBOARD:
            try:
                is_q_pressed = keyboard.is_pressed('q')
                if is_q_pressed and not self.q_pressed_last:
                    self.target_cycle_index += 1
                self.q_pressed_last = is_q_pressed
            except: pass

        try:
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            cgame_base = get_cgame_base(self.scanner, self.base_address)
            
            # 🐞 แทรก Debug: เช็ค CGame
            if cgame_base == 0: 
                dprint("CGame Base is 0! ข้ามการวาดรูป", force=False)
                return

            if cgame_base != self.last_cgame_base:
                reset_runtime_caches()
                self.last_cgame_base = cgame_base
                
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            
            # 🐞 แทรก Debug: เช็ค View Matrix
            if not view_matrix: 
                dprint("อ่าน View Matrix ไม่ได้! ข้ามการวาดรูป", force=False)
                return

            ballistic_profile = _read_ballistic_profile(self.scanner, cgame_base)
            leadmark_range_limit = _get_leadmark_range_limit(ballistic_profile)
            current_bullet_speed = ballistic_profile["speed"]
            current_zeroing = get_sight_compensation_factor(self.scanner, self.base_address)
            current_bullet_mass = ballistic_profile["mass"]
            current_bullet_cd = ballistic_profile["cx"]
            current_bullet_caliber = ballistic_profile["caliber"]

            painter.setPen(QColor(*COLOR_FPS_GOOD) if self.current_fps > 45 else QColor(255, 50, 50))
            painter.drawText(20, 90, f"📈 FPS : {int(self.current_fps)}")
            painter.setPen(QColor(*COLOR_INFO_TEXT))
            painter.drawText(20, 115, f"🧠 AI Tracking : 6 Threads Active (Decay={self.dynamic_decay:.3f})")

            all_units_data = get_all_units(self.scanner, cgame_base)
            all_unit_ptrs = {u_ptr for u_ptr, _ in all_units_data}
            if self.dead_unit_latch:
                self.dead_unit_latch.intersection_update(all_unit_ptrs)

            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            my_is_air = False
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit:
                    my_is_air = is_air; break
            if my_unit:
                my_profile = get_unit_filter_profile(self.scanner, my_unit)
                if my_profile.get("kind") == "air":
                    my_is_air = True
                elif my_profile.get("kind") == "ground":
                    my_is_air = False
            
            my_vel = self._stabilize_velocity(my_unit, my_is_air, my_pos, curr_t) if my_unit and my_pos else (0.0, 0.0, 0.0)
            if not my_vel: my_vel = (0.0, 0.0, 0.0)
            my_vx, my_vy, my_vz = my_vel

            if my_unit != self.last_my_unit:
                reset_runtime_caches()
                if hasattr(self.scanner, "bone_cache"): self.scanner.bone_cache = {} 
                self.max_reload_cache = {}
                self.vel_window = {} 
                self.velocity_cache = {}
                self.last_velocity_meta = {}
                self.ai_ghost_queue = [] 
                self.dead_unit_latch = set()
                self.last_my_unit = my_unit

            valid_targets = []
            current_seen_ptrs = set()
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit: continue 
                current_seen_ptrs.add(u_ptr)
                
                # 🛡️ Cache-based Profile & Status Retrieval
                cached_prof = self.profile_cache.get(u_ptr)
                if not cached_prof:
                    status = get_unit_status(self.scanner, u_ptr)
                    if not status: continue
                    profile = get_unit_filter_profile(self.scanner, u_ptr)
                    
                    # Store only necessary info
                    self.profile_cache[u_ptr] = {
                        'status': status,
                        'profile': profile,
                        'is_air_resolved': (profile.get("kind") == "air") if profile.get("kind") else is_air
                    }
                    cached_prof = self.profile_cache[u_ptr]
                
                u_team, u_state, unit_name, reload_val = cached_prof['status']
                # Update dynamic status part (reload and state) only if needed or every few frames
                status = get_unit_status(self.scanner, u_ptr)
                if not status: continue
                u_team, u_state, unit_name, reload_val = status
                cached_prof['status'] = status # Sync dynamic parts
                
                if u_state >= 1:
                    self.dead_unit_latch.add(u_ptr)
                    continue
                if u_ptr in self.dead_unit_latch:
                    continue
                if u_team == 0 or (my_team != 0 and u_team == my_team): continue

                profile = cached_prof['profile']
                if profile.get("skip"): continue
                
                profile_tag = (profile.get("tag") or "").lower()
                profile_path = (profile.get("path") or "").lower()
                if profile_tag in ("exp_aaa", "exp_fortification", "exp_structure", "exp_zero"): continue
                if ("air_defence/" in profile_path) or ("structures/" in profile_path) or ("dummy_plane" in profile_path): continue

                resolved_is_air = cached_prof['is_air_resolved']
                resolved_name = unit_name
                if (not resolved_name) or (len(resolved_name) < 2) or (resolved_name.lower() in ("unknown", "c", "none")):
                    resolved_name = profile.get("display_name") or "unknown"

                pos = get_unit_pos(self.scanner, u_ptr)
                if not pos: continue

                # Position checks (Origin ghost / Distance)
                pos_origin_dist = math.sqrt(pos[0]**2 + pos[1]**2 + pos[2]**2)
                if pos_origin_dist <= ORIGIN_GHOST_RADIUS:
                    if my_pos and math.sqrt(my_pos[0]**2 + my_pos[1]**2 + my_pos[2]**2) >= ORIGIN_GHOST_MY_DIST_MIN:
                        continue

                dist_to_me = 0.0
                if my_pos:
                    dx, dy, dz = pos[0]-my_pos[0], pos[1]-my_pos[1], pos[2]-my_pos[2]
                    dist_to_me = math.sqrt(dx*dx + dy*dy + dz*dz)
                    if dist_to_me > (MAX_AIR_TARGET_DISTANCE if resolved_is_air else MAX_GROUND_TARGET_DISTANCE):
                        continue

                valid_targets.append((u_ptr, resolved_name, reload_val, resolved_is_air, pos, dist_to_me))
            
            # 🧹 Clean up Profile Cache for missing units
            for ptr in list(self.profile_cache.keys()):
                if ptr not in current_seen_ptrs:
                    del self.profile_cache[ptr]
            
            dprint_frame_stats(
                self.current_fps, 
                cgame_base, 
                view_matrix is not None, 
                len(all_units_data), 
                len(valid_targets),
                my_unit != 0
            )

            # 🎯 เลือกเป้าหมายจากลิสต์ที่มองเห็น โดยให้ Q วนเป้าได้จริง
            visible_targets = []
            for u_ptr, raw_name, reload_val, is_air_target, pos, dist_to_me in valid_targets:
                res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                if res_pos and res_pos[2] > 0:
                    dist_crosshair = math.hypot(res_pos[0] - self.center_x, res_pos[1] - self.center_y)
                    visible_targets.append((dist_crosshair, u_ptr))

            if visible_targets:
                visible_targets.sort(key=lambda item: item[0])
                self.target_cycle_index %= len(visible_targets)
                active_target_ptr = visible_targets[self.target_cycle_index][1]
            else:
                self.target_cycle_index = 0

            # ========================================================
            # 🧠 AI EVALUATION STEP (ประเมินผล 6 สมมติฐาน)
            # ========================================================
            remaining_ghosts = []
            for ghost in self.ai_ghost_queue:
                if curr_t >= ghost['impact_time']:
                    if ghost['target_id'] == active_target_ptr:
                        actual_pos = get_unit_pos(self.scanner, ghost['target_id'])
                        if actual_pos:
                            errs = [
                                (0.01, math.hypot(ghost['p1'][0]-actual_pos[0], ghost['p1'][1]-actual_pos[1], ghost['p1'][2]-actual_pos[2])),
                                (0.05, math.hypot(ghost['p2'][0]-actual_pos[0], ghost['p2'][1]-actual_pos[1], ghost['p2'][2]-actual_pos[2])),
                                (0.15, math.hypot(ghost['p3'][0]-actual_pos[0], ghost['p3'][1]-actual_pos[1], ghost['p3'][2]-actual_pos[2])),
                                (ghost['dyn_val'], math.hypot(ghost['p4'][0]-actual_pos[0], ghost['p4'][1]-actual_pos[1], ghost['p4'][2]-actual_pos[2])),
                                (0.35, math.hypot(ghost['p5'][0]-actual_pos[0], ghost['p5'][1]-actual_pos[1], ghost['p5'][2]-actual_pos[2])),
                                (0.65, math.hypot(ghost['p6'][0]-actual_pos[0], ghost['p6'][1]-actual_pos[1], ghost['p6'][2]-actual_pos[2]))
                            ]
                            
                            best_decay = min(errs, key=lambda x: x[1])[0]
                            lr = 0.09
                            self.dynamic_decay = (self.dynamic_decay * (1.0 - lr)) + (best_decay * lr)
                            self.dynamic_decay = max(0.01, min(self.dynamic_decay, 0.8))
                else:
                    remaining_ghosts.append(ghost)
            self.ai_ghost_queue = remaining_ghosts

            # ========================================================
            # 🎯 MAIN PROCESSING LOOP
            # ========================================================
            for u_ptr, raw_name, reload_val, is_air_target, pos, dist_to_me in valid_targets:
                seen_targets_this_frame.add(u_ptr)
                try:
                    box_data = get_unit_3d_box_data(self.scanner, u_ptr, is_air_target)
                    pos = box_data[0] if box_data else pos
                    if not pos: continue
                    
                    dist = dist_to_me if my_pos else 0
                    
                    # 💥 เพิ่มตัวแปรสำหรับวาดเส้นปืน (Barrel) และแจ้งเตือนภัยคุกคาม
                    barrel_base_2d = None
                    barrel_data = None
                    if box_data:
                        barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, box_data[3])
                        
                    has_valid_box = False
                    avg_x, avg_y, min_y = 0, 0, 0

                    if box_data:
                        corners_3d = calculate_3d_box_corners(pos, box_data[1], box_data[2], box_data[3], is_air_target)
                        pts = [p for c in corners_3d if (p := world_to_screen(view_matrix, c[0], c[1], c[2], self.screen_width, self.screen_height)) and p[2] >= 0.001]
                        if len(pts) == 8:
                            box_color = QColor(*COLOR_BOX_SELECT_TARGET) if u_ptr == active_target_ptr else QColor(*COLOR_BOX_TARGET)
                            painter.setPen(QPen(box_color, 2))
                            for e1, e2 in [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]: 
                                painter.drawLine(int(pts[e1][0]), int(pts[e1][1]), int(pts[e2][0]), int(pts[e2][1]))
                            min_y, avg_x, avg_y = min(p[1] for p in pts), sum(p[0] for p in pts)/8.0, sum(p[1] for p in pts)/8.0  
                            has_valid_box = True

                    if not has_valid_box:
                        res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                        if res_pos and res_pos[2] > 0:
                            box_w = max(20, int(3000 / (dist + 1))) if is_air_target else max(30, int(4000 / (dist + 1)))
                            box_h = box_w * 0.8 if is_air_target else box_w * 0.6
                            painter.setPen(QPen(QColor(*COLOR_BOX_TARGET), 2))
                            painter.drawRect(int(res_pos[0] - box_w/2), int(res_pos[1] - box_h/2), int(box_w), int(box_h))
                            avg_x, avg_y, min_y = res_pos[0], res_pos[1], res_pos[1] - box_h/2
                            has_valid_box = True

                    if not has_valid_box: continue 
                    
                    should_draw_local_axes = (
                        DEBUG_DRAW_LOCAL_AXES
                        and box_data
                        and u_ptr == active_target_ptr
                        and ((not DEBUG_DRAW_LOCAL_AXES_GROUND_ONLY) or (not is_air_target))
                    )
                    if should_draw_local_axes:
                        axis_origin = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                        if axis_origin and axis_origin[2] > 0:
                            axis_len = DEBUG_AXIS_LENGTH_AIR if is_air_target else DEBUG_AXIS_LENGTH_GROUND
                            ax, ay, az = get_local_axes_from_rotation(box_data[3], is_air_target)
                            axis_labels = DEBUG_AXIS_LABELS_AIR if is_air_target else DEBUG_AXIS_LABELS_GROUND
                            axis_defs = [
                                ("X", COLOR_AXIS_X, ax),
                                ("Y", COLOR_AXIS_Y, ay),
                                ("Z", COLOR_AXIS_Z, az),
                            ]
                            for axis_name, axis_color, axis_vec in axis_defs:
                                end_pos = (
                                    pos[0] + (axis_vec[0] * axis_len),
                                    pos[1] + (axis_vec[1] * axis_len),
                                    pos[2] + (axis_vec[2] * axis_len),
                                )
                                end_scr = world_to_screen(
                                    view_matrix,
                                    end_pos[0],
                                    end_pos[1],
                                    end_pos[2],
                                    self.screen_width,
                                    self.screen_height,
                                )
                                if end_scr and end_scr[2] > 0:
                                    painter.setPen(QPen(QColor(*axis_color), 3))
                                    painter.drawLine(
                                        int(axis_origin[0]),
                                        int(axis_origin[1]),
                                        int(end_scr[0]),
                                        int(end_scr[1]),
                                    )
                                    painter.drawText(
                                        int(end_scr[0] + 4),
                                        int(end_scr[1] - 4),
                                        axis_labels.get(axis_name, axis_name),
                                    )

                    # 🔫 วาดเส้นเล็งของปืนศัตรู
                    if barrel_data:
                        res_p1 = world_to_screen(view_matrix, barrel_data[0][0], barrel_data[0][1], barrel_data[0][2], self.screen_width, self.screen_height)
                        res_p2 = world_to_screen(view_matrix, barrel_data[1][0], barrel_data[1][1], barrel_data[1][2], self.screen_width, self.screen_height)
                        if res_p1 and res_p2 and res_p1[2] > 0 and res_p2[2] > 0:
                            painter.setPen(QPen(QColor(*COLOR_BARREL_LINE), 2)) 
                            painter.drawLine(int(res_p1[0]), int(res_p1[1]), int(res_p2[0]), int(res_p2[1]))
                            barrel_base_2d = res_p1

                    clean_name = raw_name
                    for p in NAME_PREFIXES:
                        if clean_name.lower().startswith(p): clean_name = clean_name[len(p):]; break

                    physics_is_air = is_air_target
                    display_is_air = is_air_target
                    if display_is_air and my_pos and abs(pos[1] - my_pos[1]) < 50:
                        display_is_air = False

                    has_reload_bar = (not display_is_air and (0 <= reload_val < 500))
                    dist_to_crosshair = math.hypot(avg_x - self.center_x, avg_y - self.center_y)
                    hide_name = False if display_is_air else (dist > 550 and dist_to_crosshair >= 350)
                    
                    # 🎯 กลับมาใช้รูปแบบเดิมที่โชว์แค่ ชื่อ และ ระยะทาง
                    display_text = f"-{int(dist)}m-" if hide_name else f"{clean_name.upper()} [{int(dist)}m]"
                        
                    fm = painter.fontMetrics()
                    text_w = fm.boundingRect(display_text).width()
                    text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)

                    # ========================================================
                    # 🚨 THREAT WARNING SYSTEM (แจ้งเตือนภัยคุกคาม)
                    # ========================================================
                    warning_level = 0 
                    
                    if physics_is_air and my_pos and dist > 10.0:
                        vel = self._stabilize_velocity(u_ptr, physics_is_air, pos, curr_t)
                        if vel:
                            v_mag = math.sqrt(vel[0]**2 + vel[1]**2 + vel[2]**2)
                            if v_mag > 5.0: 
                                dx_v, dy_v, dz_v = vel[0]/v_mag, vel[1]/v_mag, vel[2]/v_mag
                                tx_v, ty_v, tz_v = my_pos[0] - pos[0], my_pos[1] - pos[1], my_pos[2] - pos[2]
                                t_mag = math.sqrt(tx_v**2 + ty_v**2 + tz_v**2)
                                if t_mag > 0:
                                    tx_v, ty_v, tz_v = tx_v/t_mag, ty_v/t_mag, tz_v/t_mag
                                    dot_prod = max(-1.0, min(1.0, dx_v*tx_v + dy_v*ty_v + dz_v*tz_v))
                                    angle = math.degrees(math.acos(dot_prod))
                                    if angle <= 2.5: warning_level = 2
                                    elif angle <= 6.0: warning_level = 1
                                        
                    elif not physics_is_air and my_pos and barrel_data and dist > 10.0:
                        if is_ground_threat(barrel_data[0], barrel_data[1], my_pos): warning_level = 2
                        elif is_aiming_at(barrel_data[0], barrel_data[1], my_pos, threshold_degrees=4.5): warning_level = 1

                    if warning_level > 0:
                        line_dest_x = barrel_base_2d[0] if barrel_base_2d else avg_x
                        line_dest_y = barrel_base_2d[1] if barrel_base_2d else avg_y
                        
                        if warning_level == 2:
                            dot_text = "⚠️ THREAT!"
                            dot_x = int(avg_x - fm.boundingRect(dot_text).width() / 2) 
                            dot_y = text_y - 14 
                            painter.setPen(QColor(*COLOR_THREAD_TEXT))
                            for ox, oy in [(-1,-1), (1,-1), (-1,1), (1,1), (0,-2), (0,2), (-2,0), (2,0)]:
                                painter.drawText(dot_x + ox, dot_y + oy, dot_text)
                            painter.setPen(QColor(*COLOR_THREAD_TEXT2))
                            painter.drawText(dot_x, dot_y, dot_text)
                            painter.setPen(QPen(QColor(*COLOR_THREAD_WARNING), 5, Qt.DashLine))
                            painter.drawLine(int(self.center_x), self.screen_height, int(line_dest_x), int(line_dest_y))
                            painter.setPen(QPen(QColor(*COLOR_THREAD_WARNING2), 2, Qt.DashLine))
                            painter.drawLine(int(self.center_x), self.screen_height, int(line_dest_x), int(line_dest_y))
                            
                        elif warning_level == 1:
                            painter.setPen(QPen(QColor(*COLOR_THREAD_ALERT), 5))
                            painter.drawLine(int(self.center_x), self.screen_height, int(line_dest_x), int(line_dest_y))
                            painter.setPen(QPen(QColor(*COLOR_THREAD_ALERT2), 2))
                            painter.drawLine(int(self.center_x), self.screen_height, int(line_dest_x), int(line_dest_y))

                    painter.setPen(QColor(*COLOR_TEXT_AIR) if display_is_air else QColor(*COLOR_TEXT_GROUND))
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
                    # 🚀 KINEMATICS: ANTI-JITTER TARGET TRACKING
                    # ========================================================
                    vel = self._stabilize_velocity(u_ptr, physics_is_air, pos, curr_t)
                    is_turning = False 
                    
                    if not vel or current_bullet_speed <= 0 or not my_pos or dist <= 10.0: continue
                        
                    vx, vy, vz = vel
                    ax, ay, az = 0.0, 0.0, 0.0
                    
                    if physics_is_air:
                        if u_ptr not in self.vel_window:
                            self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (0.0, 0.0, 0.0), 'fail_count': 0, 'turn_time': 0.0}
                        else:
                            history = self.vel_window[u_ptr]
                            old_v, old_t, old_a = history['v'], history['time'], history['a']
                            fail_count = history.get('fail_count', 0)
                            turn_time = history.get('turn_time', 0.0) 
                            
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
                                    self.vel_window[u_ptr] = {'time': curr_t, 'v': vel, 'a': (ax, ay, az), 'fail_count': 0, 'turn_time': turn_time}
                                else:
                                    ax, ay, az = old_a
                            else:
                                fail_count += 1
                                ax, ay, az = old_a
                                if fail_count > 15: ax, ay, az = 0.0, 0.0, 0.0
                                self.vel_window[u_ptr] = {'time': old_t, 'v': old_v, 'a': (ax, ay, az), 'fail_count': fail_count, 'turn_time': turn_time}
                                
                        a_mag = math.sqrt(ax**2 + ay**2 + az**2)
                        
                        if a_mag > 1.5: 
                            is_turning = True
                            self.vel_window[u_ptr]['turn_time'] = curr_t 
                        else:
                            if curr_t - self.vel_window[u_ptr].get('turn_time', 0.0) < 1.0:
                                is_turning = True 
                            else:
                                is_turning = False 
                                
                        if a_mag > 150.0: ax, ay, az = (ax/a_mag)*150.0, (ay/a_mag)*150.0, (az/a_mag)*150.0
                        
                        t_x, t_y, t_z = pos[0], pos[1], pos[2]
                        
                        if u_ptr == active_target_ptr and len(self.ai_ghost_queue) < 100:
                            sim_t = 1.0 
                            def get_pred_pos(d_rate):
                                a_t = (d_rate * sim_t - 1.0 + math.exp(-d_rate * sim_t)) / (d_rate**2) if d_rate>0 else 0.0
                                return (t_x + vx*sim_t + ax*a_t, t_y + vy*sim_t + ay*a_t, t_z + vz*sim_t + az*a_t)

                            self.ai_ghost_queue.append({
                                'impact_time': curr_t + sim_t,
                                'target_id': u_ptr,
                                'dyn_val': self.dynamic_decay,
                                'p1': get_pred_pos(0.01), 
                                'p2': get_pred_pos(0.05), 
                                'p3': get_pred_pos(0.15), 
                                'p4': get_pred_pos(self.dynamic_decay), 
                                'p5': get_pred_pos(0.35), 
                                'p6': get_pred_pos(0.60)  
                            })
                            active_flight_data = {'pos': pos, 'v': vel, 'a': (ax, ay, az)}
                    else:
                        t_x, t_y, t_z = pos[0], pos[1] + 1.5, pos[2]

                    leadmark_in_range = (
                        leadmark_range_limit <= 0.0 or dist <= leadmark_range_limit
                    )

                    # =========================================================
                    # 🚀 WT TRUE BALLISTICS SOLVER (Lanz-Odermatt & SPAAG Radar)
                    # =========================================================
                    altitude = max(0.0, my_pos[1])
                    ballistic_model = _make_ballistic_model(ballistic_profile, altitude)
                    is_active_target = (u_ptr == active_target_ptr)

                    best_t = dist / current_bullet_speed if current_bullet_speed > 0 else 0.1
                    final_x, final_y, final_z = t_x, t_y, t_z
                    pred_x, pred_y, pred_z = t_x, t_y, t_z
                    bullet_drop = 0.0
                    zero_pitch = 0.0

                    if is_active_target and leadmark_in_range:
                        zero_cache_key = (
                            round(ballistic_model["speed"], 1),
                            round(ballistic_model["mass"], 4),
                            round(ballistic_model["caliber"], 5),
                            round(ballistic_model["cx"], 4),
                            round(ballistic_model["vel_lo"], 1),
                            round(ballistic_model["vel_hi"], 1),
                            round(current_zeroing, 1),
                            int(altitude // 100),
                        )
                        zero_pitch = self.ballistic_zero_cache.get(zero_cache_key)
                        if zero_pitch is None:
                            zero_pitch = _solve_zero_pitch(current_zeroing, ballistic_model)
                            self.ballistic_zero_cache[zero_cache_key] = zero_pitch
                            if len(self.ballistic_zero_cache) > 64:
                                self.ballistic_zero_cache.clear()

                        # 🔄 Iterative TOF Solver (High-Precision for Active Target)
                        for _ in range(3):
                            if physics_is_air:
                                pred_x = t_x + (vx * best_t) + (0.5 * ax * (best_t ** 2))
                                pred_y = t_y + (vy * best_t) + (0.5 * ay * (best_t ** 2))
                                pred_z = t_z + (vz * best_t) + (0.5 * az * (best_t ** 2))
                            else:
                                pred_x = t_x + (vx * best_t)
                                pred_y = t_y + (vy * best_t)
                                pred_z = t_z + (vz * best_t)
                            
                            dx_imp = pred_x - (my_pos[0] + my_vx * best_t)
                            dz_imp = pred_z - (my_pos[2] + my_vz * best_t)
                            horizontal_imp = math.hypot(dx_imp, dz_imp)

                            if current_bullet_speed > 0 and horizontal_imp > 0.01:
                                best_t, bullet_drop, _ = _simulate_projectile_range(
                                    horizontal_imp,
                                    ballistic_model,
                                    zero_pitch,
                                )
                            else:
                                best_t = 999.0
                                bullet_drop = 0.0
                            final_x, final_y, final_z = pred_x, pred_y, pred_z
                    elif leadmark_in_range:
                        # 🎯 Lightweight Solver for other units (Background ESP)
                        pred_x = t_x + (vx * best_t)
                        pred_y = t_y + (vy * best_t)
                        pred_z = t_z + (vz * best_t)
                        
                        dx_imp = pred_x - (my_pos[0] + my_vx * best_t)
                        dz_imp = pred_z - (my_pos[2] + my_vz * best_t)
                        d_imp = math.hypot(dx_imp, dz_imp)

                        if current_bullet_speed > 0:
                            best_t = d_imp / current_bullet_speed
                            bullet_drop = 0.5 * BULLET_GRAVITY * (best_t ** 2)
                            t_sight = current_zeroing / current_bullet_speed
                            bullet_drop -= (0.5 * BULLET_GRAVITY * (t_sight**2))
                        else:
                            best_t = 999.0
                            bullet_drop = 0.0
                        
                        final_x, final_y, final_z = pred_x, pred_y, pred_z
                    else:
                        best_t = 0.0
                        bullet_drop = 0.0
                        gravity_offset = 0.0
                        final_x, final_y, final_z = t_x, t_y, t_z

                    gravity_offset = bullet_drop
                    final_y += bullet_drop
                    
                    final_x -= (my_vx * best_t)
                    final_y -= (my_vy * best_t)
                    final_z -= (my_vz * best_t)
                    
                    # =========================================================
                    # 📊 [STICKY DASHBOARD]: อัปเดตแบบ Real-time ทับบรรทัดเดิม
                    # =========================================================
                    if u_ptr == active_target_ptr:
                        vel_meta = self.last_velocity_meta.get(u_ptr, {})
                        vel_source = vel_meta.get('source', 'raw')
                        raw_mag = vel_meta.get('raw_mag', 0.0) * 3.6
                        pos_mag = vel_meta.get('pos_mag', 0.0) * 3.6
                        info_ptr = 0
                        mov_ptr = 0
                        mov_off = OFF_AIR_MOVEMENT if physics_is_air else OFF_GROUND_MOVEMENT
                        try:
                            info_raw = self.scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8)
                            if info_raw and len(info_raw) == 8:
                                info_ptr = struct.unpack("<Q", info_raw)[0]
                        except:
                            info_ptr = 0
                        try:
                            mov_raw = self.scanner.read_mem(u_ptr + mov_off, 8)
                            if mov_raw and len(mov_raw) == 8:
                                mov_ptr = struct.unpack("<Q", mov_raw)[0]
                        except:
                            mov_ptr = 0
                        # ใช้ ANSI Code ย้อน Cursor ไปบนสุด และล้างถึงท้ายหน้าจอ (\033[H\033[J)
                        my_speed = math.sqrt(my_vx**2 + my_vy**2 + my_vz**2) * 3.6
                        target_speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                        accel_mag = math.sqrt(ax**2 + ay**2 + az**2)
                        
                        out =  "================================================================\n"
                        out += f"📊 WTM TACTICAL DASHBOARD | FPS: {int(self.current_fps):<3} | Units: {len(valid_targets):<2}\n"
                        out += "================================================================\n"
                        out += f"🟢 [MY UNIT]  : {hex(my_unit)}\n"
                        out += f"🚀 Velocity   : {my_speed:>6.1f} km/h | V:({my_vx:>6.2f}, {my_vy:>6.2f}, {my_vz:>6.2f})\n"
                        out += "-" * 64 + "\n"
                        out += f"🎯 [TARGET]   : {clean_name.upper()} {'[LOCKED]':>35}\n"
                        out += f"🧷 Ptr/Off    : UNIT:{hex(u_ptr)} | INFO:{hex(info_ptr) if info_ptr else '0x0'} | MOV:{hex(mov_ptr) if mov_ptr else '0x0'} @ {hex(mov_off)}\n"
                        
                        # 🧬 [DNA] ดึงและแสดงข้อมูลเชิงลึก
                        from src.utils.mul import get_unit_detailed_dna
                        dna = get_unit_detailed_dna(self.scanner, u_ptr)
                        if dna:
                            invul_str = " [GOD MODE]" if dna['is_invul'] else ""
                            out += f"🧬 DNA        : NATION:{dna['nation_id']} | CLASS:{dna['class_id']} | STATE:{dna['state']}{invul_str}\n"
                            out += f"🏷️ UNIT       : {dna['short_name']} ({dna['family']})\n"
                            out += f"📛 KEY        : {dna['name_key']}\n"
                        
                        range_limit_text = (
                            f"{leadmark_range_limit:.0f}m" if leadmark_range_limit > 0.0 else "OFF"
                        )
                        out += f"📏 Distance   : {dist:>6.1f} m      | TOF: {best_t:>6.3f} s\n"
                        out += f"🚀 Velocity   : {target_speed:>6.1f} km/h | V:({vx:>6.2f}, {vy:>6.2f}, {vz:>6.2f}) | SRC:{vel_source}\n"
                        out += f"📡 Vel Check  : raw={raw_mag:>6.1f} km/h | pos={pos_mag:>6.1f} km/h | PTR:{hex(u_ptr)}\n"
                        out += f"🌪️ Accel      : {accel_mag:>6.2f} m/s² | A:({ax:>6.2f}, {ay:>6.2f}, {az:>6.2f})\n"
                        out += f"🎯 Lead Limit : {range_limit_text} | InRange:{'Y' if leadmark_in_range else 'N'}\n"
                        out += "-" * 64 + "\n"
                        out += f"📉 [BALLISTICS]\n"
                        vel_lo, vel_hi = ballistic_profile["vel_range"]
                        out += f"🔫 Bullet     : Spd:{current_bullet_speed:.0f} m/s | CD:{current_bullet_cd:.2f} | Mass:{current_bullet_mass:.2f} | Cal:{current_bullet_caliber:.3f}\n"
                        out += f"📉 Drop       : Bullet: +{gravity_offset:>5.2f} m | Zero: {math.degrees(zero_pitch):>5.2f} deg | VRange:{vel_lo:.0f}-{vel_hi:.0f}\n"
                        out += "================================================================\n"
                        out += " [Q] Cycle Targets | [Ctrl+C] Exit\n"

                        should_refresh_console = (
                            (curr_t - self.last_debug_log_time) >= DEBUG_LOG_INTERVAL
                        )
                        if should_refresh_console:
                            if not self.console_initialized:
                                sys.stdout.write("\033[2J\033[H")
                                self.console_initialized = True
                            else:
                                sys.stdout.write("\033[H\033[J")
                            sys.stdout.write(out)
                            sys.stdout.flush()
                            self.last_debug_log_time = curr_t

                    # 🛡️ เช็คว่าพิกัดทำนายไม่ใช่ค่าว่าง
                    if leadmark_in_range and all(math.isfinite(c) for c in [final_x, final_y, final_z]):
                        pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, self.screen_width, self.screen_height)
                        
                        if pred_screen and pred_screen[2] > 0:
                            px, py = pred_screen[0], pred_screen[1]
                            
                            # 🎯 เช็ค NaN ก่อนแปลงเป็น int
                            if math.isfinite(px) and math.isfinite(py):
                                # 🛡️ ใช้ avg_x และ avg_y ที่คำนวณไว้ด้านบนแทน screen_pos
                                draw_sx, draw_sy = avg_x, avg_y
                                
                                # ถ้าเป็นเครื่องบิน ให้ดึงพิกัดที่แม่นยำกว่ามาวาดเส้น
                                if display_is_air:
                                    pos_scr = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                                    if pos_scr and pos_scr[2] > 0:
                                        draw_sx, draw_sy = pos_scr[0], pos_scr[1]
                                
                                # ✅ เพิ่มเข้าคิววาดเมื่อทุกอย่างเป็นตัวเลขปกติ
                                if math.isfinite(draw_sx) and math.isfinite(draw_sy):
                                    lead_marks_to_draw.append({
                                        'sx': draw_sx, 'sy': draw_sy, 
                                        'px': px, 'py': py,
                                        'is_air': display_is_air, 
                                        'is_turning': is_turning
                                    })

                except Exception as e:
                    if "NaN" not in str(e):
                        print(f"Main processing error: {e}")
                    pass

            # ========================================================
            # 🚀 FLIGHT PATH SIMULATION RENDERER (SPAAG VERSION)
            # ========================================================
            if active_flight_data:
                c_pos, c_v, c_a = active_flight_data['pos'], active_flight_data['v'], active_flight_data['a']
                path_pts = []
                for step in range(30): 
                    t_sim = step * 0.1
                    # 🎯 ทำนายจุดตกในแต่ละช่วงเวลาด้วย P_pred = P + (V*t) + (0.5*A*t^2)
                    p_x = c_pos[0] + (c_v[0] * t_sim) + (0.5 * c_a[0] * (t_sim ** 2))
                    p_y = c_pos[1] + (c_v[1] * t_sim) + (0.5 * c_a[1] * (t_sim ** 2))
                    p_z = c_pos[2] + (c_v[2] * t_sim) + (0.5 * c_a[2] * (t_sim ** 2))
                    
                    scr = world_to_screen(view_matrix, p_x, p_y, p_z, self.screen_width, self.screen_height)
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
        
        # 🚀 THE MAGIC: สแกนหา Manager Offset อัตโนมัติก่อนเปิดเรดาร์!
        init_dynamic_offsets(scanner, base_addr)
        
        app = QApplication(sys.argv)
        overlay = ESPOverlay(scanner, base_addr)
        overlay.show()
        sys.exit(app.exec_())
    except Exception as e: 
        print(f"Error starting Overlay: {e}")
        sys.exit(1)
