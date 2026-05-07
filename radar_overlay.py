import sys
import math
import time
import struct
import os
import json
import shutil
import subprocess
import traceback
import pwd
import mss
from PyQt5.QtGui import QImage, QPixmap, QPolygon
from PyQt5.QtCore import QRect, QPoint

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    print("⚠️ กรุณาติดตั้งโมดูล keyboard: pip install keyboard")
    HAS_KEYBOARD = False

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
try:
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
    HAS_QT_MULTIMEDIA = True
except Exception:
    QMediaContent = None
    QMediaPlayer = None
    HAS_QT_MULTIMEDIA = False

# 🎯 นำเข้าจากระบบ Core Engine ที่แยกออกมาใหม่
from src.utils.scanner import *
from src.utils.mul import *
from src.utils.debug import *
from src.utils.ammo_family import resolve_ammo_family


def _console_supports_sticky_dashboard():
    try:
        term = os.environ.get("TERM", "").lower()
        return sys.stdout.isatty() and term not in ("", "dumb")
    except Exception:
        return False


def _get_default_pulse_sink_name():
    try:
        out = subprocess.check_output(
            ["pactl", "get-default-sink"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out or ""
    except Exception:
        return ""


def _get_desktop_audio_env():
    env = os.environ.copy()
    run_as_user = None
    sudo_user = (env.get("SUDO_USER") or "").strip()
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        try:
            pw = pwd.getpwnam(sudo_user)
            env["HOME"] = pw.pw_dir
            env["XDG_RUNTIME_DIR"] = f"/run/user/{pw.pw_uid}"
            run_as_user = sudo_user
        except Exception:
            run_as_user = None
    return env, run_as_user


def _get_alert_audio_volume():
    try:
        return max(0, min(100, int(ALERT_AUDIO_VOLUME)))
    except Exception:
        return 100


ALERT_AUDIO_DIR = os.path.join(os.path.dirname(__file__), ".assets", "audio", "alert")
ALERT_SOUND_AIRCRAFT = os.path.join(ALERT_AUDIO_DIR, "aircraft.mp3")
ALERT_SOUND_HELO = os.path.join(ALERT_AUDIO_DIR, "helo.mp3")
ALERT_AUDIO_ON = True
ALERT_AUDIO_VOLUME = 100  # 0..100
AIR_ALERT_SOUND_COOLDOWN = 1.0
ALERT_AUDIO_BACKEND = "auto"  # auto | system | qt

# Backward compatibility for older config references.
ENABLE_AIR_ALERT_SOUND = ALERT_AUDIO_ON


def _unit_family_from_code(code):
    code = str(code or "").strip().upper()
    mapping = {
        "LT": UNIT_FAMILY_GROUND_LIGHT_TANK,
        "MT": UNIT_FAMILY_GROUND_MEDIUM_TANK,
        "HT": UNIT_FAMILY_GROUND_HEAVY_TANK,
        "TD": UNIT_FAMILY_GROUND_TANK_DESTROYER,
        "AA": UNIT_FAMILY_GROUND_SPAA,
        "BT": UNIT_FAMILY_SHIP_BOAT,
        "FF": UNIT_FAMILY_SHIP_FRIGATE,
        "DD": UNIT_FAMILY_SHIP_DESTROYER,
        "CA": UNIT_FAMILY_SHIP_CRUISER,
        "BB": UNIT_FAMILY_SHIP_BATTLESHIP,
        "FG": UNIT_FAMILY_AIR_FIGHTER,
        "BM": UNIT_FAMILY_AIR_BOMBER,
        "AT": UNIT_FAMILY_AIR_ATTACKER,
        "HC": UNIT_FAMILY_AIR_HELICOPTER,
    }
    return mapping.get(code, UNIT_FAMILY_UNKNOWN)


def _match_pragmatic_unit_family_code(family_tag, token):
    family_tag = str(family_tag or "").lower()
    token = str(token or "").lower()

    if family_tag == "exp_tank":
        light_patterns = (
            "pt_76",
            "pzkpfw_ii",
            "m22_",
            "m24_",
            "m41",
            "amx_13",
            "asu_57",
            "asu_85",
            "bmp_",
            "brdm",
            "btr_",
            "pt-76",
        )
        heavy_patterns = (
            "tiger_ii",
            "tiger ii",
            "is_",
            "is-",
            "js_",
            "js-",
            "kv_",
            "kv-",
            "churchill",
            "t26e5",
            "t29",
            "t30",
            "t32",
            "m103",
            "conqueror",
        )
        td_patterns = (
            "panzerjager",
            "jagd",
            "su_85",
            "su-85",
            "su_100",
            "su-100",
            "asu_57",
            "asu-57",
            "asu_85",
            "asu-85",
        )
        aa_patterns = (
            "sdkfz_6_2",
            "zsu_",
            "wirbelwind",
            "ostwind",
            "coelian",
            "spaa",
        )

        if any(p in token for p in aa_patterns):
            return "AA"
        if any(p in token for p in td_patterns):
            return "TD"
        if any(p in token for p in heavy_patterns):
            return "HT"
        if any(p in token for p in light_patterns):
            return "LT"
        return ""

    return ""

COLOR_INFO_TEXT         = (255, 228, 64, 255)   
COLOR_BARREL_LINE       = (0, 255, 0, 255)      
COLOR_BOX_TARGET        = (255, 255, 0, 200)
COLOR_BOX_SELECT_TARGET = (255, 255, 0, 200)
COLOR_BOX_MY_UNIT       = (80, 220, 255, 220)
COLOR_TEXT_GROUND       = (255, 196, 20, 200)    
COLOR_TEXT_AIR          = (255, 196, 20, 230)   
COLOR_RELOAD_BG         = (0, 0, 0, 180)        
COLOR_RELOAD_READY      = (255, 255, 255, 255)      
COLOR_RELOAD_LOADING    = (255, 165, 0, 200)    
COLOR_PREDICTION        = (255, 255, 255, 255)    
COLOR_PREDICTION_GROUND_STATIC = (64, 220, 255, 120)
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
COLOR_BOX_HITPOINT      = (255, 255, 255, 255)
COLOR_DYNAMIC_COMPARE_HIT = (80, 255, 255, 235)
COLOR_FALLBACK_COMPARE_HIT = (255, 120, 40, 235)
COLOR_DEBUG_MUZZLE_RAY  = (80, 255, 120, 220)
COLOR_DEBUG_BOX_ENTRY   = (255, 120, 40, 235)
COLOR_CALIBRATION_HIT   = (0, 150, 255, 255)
COLOR_CLASS_ICON_GROUND = (255, 215, 96, 235)
COLOR_CLASS_ICON_AIR    = (120, 220, 255, 235)

BULLET_GRAVITY       = 9.80665   

GROUND_LEADMARK_TOP_N = 3  # <=0 = OFF/ALL visible ground targets

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

NON_PLAYABLE_RUNTIME_HINTS = (
    # "dummy",
    # "airfield",
    # "noground",
    # "air_defence",
    # "fortification",
    # "structure",
    # "infantry",
    # "controlled_",
    # "controlled_technic",
    # "technic",
    # "birthday",
    # "hangar",
)
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
INVALID_RUNTIME_FRAME_LIMIT = 20
STARTUP_LOADING_GRACE_SECONDS = 20.0
DRAW_CLASS_ICON = True
CLASS_ICON_SIZE = 15
CLASS_ICON_LINE_GAP = 14
DRAW_CLASS_ICON_DEBUG_TEXT = False
CLASS_ICON_DEBUG_TEXT_GAP = 12
DRAW_UNIT_FAMILY_OVERLAY_DEBUG = False
UNIT_FAMILY_OVERLAY_DEBUG_GAP = 30

DEBUG_VELOCITY = False

DEBUG_DRAW_MUZZLE_RAY = False
DEBUG_DRAW_BOX_ENTRY_HIT = False
DEBUG_COMPARE_DYNAMIC_GEOMETRY = False

ESP_POINT_ONLY_MODE = False             # เปลี่ยนเป็น False เพื่อปิดโหมดวาดแค่จุด
GROUND_USE_SIMPLE_SCREEN_BOX = False    # เปลี่ยนเป็น False เพื่อปิดโหมดกล่อง 2D แบนๆ
AIR_USE_SIMPLE_SCREEN_BOX = False       # เปลี่ยนเป็น False

DRAW_BASE_HITPOINT = True
BASE_HITPOINT_SIZE_MULT = 1
DEBUG_DRAW_CALIBRATION_HIT = False
SHOW_MY_UNIT_BOX = False
CALIBRATION_SAVE_PATH = os.path.join("dumps", "hitpoint_calibration_samples.jsonl")
LOCK_CAMERA_PARALLAX = True
DYNAMIC_GEOMETRY_ENABLE = True
DYNAMIC_GEOMETRY_COMPARE_FALLBACK = False

GROUND_AIM_HEIGHT_RATIO_CLOSE = 0.50
GROUND_AIM_HEIGHT_RATIO_FAR = 0.75
GROUND_AIM_HEIGHT_RATIO_BLEND_MAX = 1200.0

VERTICAL_BASELINE_AUTO_ENABLE = True
VERTICAL_BASELINE_CONFIG_PATH = os.path.join("config", "vertical_baseline_table.json")
VERTICAL_BASELINE_RUNTIME_SOURCE = "default"
DEFAULT_VERTICAL_BASELINE_TABLE = {}
VERTICAL_BASELINE_TABLE = json.loads(json.dumps(DEFAULT_VERTICAL_BASELINE_TABLE))
VERTICAL_BASELINE_LAST_MATCH = {
    "bucket": "",
    "profile_key": "",
    "entry_unit_key": "",
    "entry_speed": 0.0,
    "entry_caliber": 0.0,
    "entry_mass": 0.0,
    "entry_parallax": 0.0,
    "entry_cannon_size": 0.0,
    "ballistic_speed": 0.0,
    "ballistic_caliber": 0.0,
    "ballistic_mass": 0.0,
    "ballistic_cannon_size": 0.0,
    "family": "",
    "reason": "",
    "distance": 0.0,
    "value": 0.0,
}
DYNAMIC_PARALLAX_SCALE = 1
DYNAMIC_WORLDSPACE_ENABLE = True

BALLISTIC_STRUCT_BASE_OFF = 0x2058
BALLISTIC_SPEED_OFF = 0x2050
BALLISTIC_MASS_OFF = 0x205C
BALLISTIC_CALIBER_OFF = 0x2060
BALLISTIC_CX_OFF = 0x2064
BALLISTIC_MAX_DISTANCE_OFF = 0x2068
BALLISTIC_VEL_RANGE_X_OFF = 0x207C
BALLISTIC_VEL_RANGE_Y_OFF = 0x2080
BALLISTIC_PERSISTENCE_PATH = os.path.join("config", "ballistic_layout_persistence.json")
BBOX_PERSISTENCE_PATH = os.path.join("config", "unit_bbox_persistence.json")
VIEW_CANDIDATE_PERSISTENCE_PATH = os.path.join("config", "view_matrix_candidate_persistence.json")
VIEW_CANDIDATE_PERSISTENCE_ENABLE = False
DEFAULT_GAME_BINARY_PATH = "/home/xda-7/MyGames/WarThunder/linux64/aces"
GUN_BULLET_LIST_PTR_OFF = 0x358
GUN_BULLET_LIST_COUNT_OFF = 0xA0
GUN_BULLET_SLOT_BASE_OFF = 0xA8
GUN_BULLET_SLOT_STRIDE = 0xA0
GUN_CURRENT_BULLET_TYPE_OFF = 0x584
DYNAMIC_TURRET_BBOX_CANDIDATES = (
    (0x1F90, 0x1F9C, "turret_bbox_1f90"),
    (0x1F78, 0x1F84, "turret_bbox_1f78"),
)
DYNAMIC_GEOMETRY_FPS_MAX_DIST = 6.0
DYNAMIC_GEOMETRY_FPS_UNIT_SCALE = 1.35

# Leadmark / ballistic solver tuning
LEADMARK_RANGE_LIMIT_RATIO = 0.80  # ต่ำลง = ซ่อน leadmark เร็วขึ้นเมื่อเป้าไกลเกิน effective range
MAX_TOF_AIR_LEADMARK = 6.00       # <=0 = OFF
BALLISTIC_MIN_SPEED = 50.0
BALLISTIC_MAX_SPEED = 3000.0
BALLISTIC_MIN_MASS = 0.005
BALLISTIC_MAX_MASS = 200.0
BALLISTIC_MIN_CALIBER = 0.001
BALLISTIC_MAX_CALIBER = 0.5
BALLISTIC_MIN_CX = 0.01
BALLISTIC_MAX_CX = 3.0
BALLISTIC_MAX_CX_FOR_DRAG = 1.2
BALLISTIC_MIN_DISTANCE = 100.0
BALLISTIC_MAX_DISTANCE = 50000.0
BALLISTIC_MIN_VEL_RANGE = 0.0
BALLISTIC_MAX_VEL_RANGE = 4000.0
BALLISTIC_SUBCALIBER_SPEED_MIN = 1200.0
BALLISTIC_SUBCALIBER_CALIBER_MAX = 0.04
BALLISTIC_SUBCALIBER_LIGHT_MASS_MAX = 8.0
BALLISTIC_SUBCALIBER_WIDE_CALIBER_MAX = 0.05
BALLISTIC_SUBCALIBER_CX_CLAMP = 0.20  # APFSDS ต่ำไป -> เพิ่ม, APFSDS สูงไป -> ลด
BALLISTIC_FAST_ROUND_CX_FALLBACK = 0.24  # ใช้เมื่ออ่าน cx ของกระสุนเร็วไม่ได้น่าเชื่อถือ
BALLISTIC_FULLCAL_CX_FALLBACK = 0.35  # ใช้เมื่ออ่าน cx ของ HE/AP/HEAT ไม่ได้น่าเชื่อถือ
BALLISTIC_MODEL0_USE_DIRECT_DRAG_K = True  # model_0_direct ใน build ล่าสุดควรใช้ drag_k จาก memread-derived seed เป็นหลัก
BALLISTIC_MODEL0_DIRECT_FACTOR = 1.0  # factor สำหรับ model_0_direct; 1.0 = ใช้ drag_k ตรงโดยไม่ผ่าน VRange shaping
BALLISTIC_MODEL0_SUBCAL_SPEED_REF = 1500.0  # speed อ้างอิงของ APFSDS ที่ match ใกล้เคียงอยู่แล้ว
BALLISTIC_MODEL0_SUBCAL_SPEED_GAIN = 0.0118  # กระสุนเร็วกว่า ref จะได้ effective drag เพิ่มขึ้นเล็กน้อย
BALLISTIC_MODEL0_SUBCAL_CALIBER_REF = 0.016  # caliber อ้างอิงของ 2S38 APFSDS
BALLISTIC_MODEL0_SUBCAL_CALIBER_GAIN = 102.0  # นัด subcaliber ที่ใหญ่กว่า ref จะได้ effective drag เพิ่ม
BALLISTIC_MODEL0_SUBCAL_MIN = 1.0  # baseline ของ model_0_direct subcaliber
BALLISTIC_MODEL0_SUBCAL_MAX = 20.60  # clamp กัน heuristic โตเกินจริง

DRAG_BAND_DEFAULT = 0.5  # ใช้เมื่อ VRange ใช้ไม่ได้; สูงขึ้น = drag กลางแรงขึ้นเล็กน้อย
DRAG_FACTOR_BASE = 0.84  # สูงขึ้น = leadmark สูงขึ้น, ต่ำลง = leadmark ต่ำลง
DRAG_FACTOR_BAND_WEIGHT = 0.18  # สูงขึ้น = ผลของ VRange ต่อ leadmark ชัดขึ้น
DRAG_FACTOR_TRANSONIC_WEIGHT = 0.12  # จูนเฉพาะแถวความเร็วใกล้เสียง
DRAG_FACTOR_SUPERSONIC_WEIGHT = -0.06  # ติดลบมากขึ้น = กระสุนเร็วแบนขึ้น/leadmark ต่ำลง
DRAG_FACTOR_FAST_ROUND_MULT = 0.92  # APFSDS ต่ำไป -> เพิ่ม, APFSDS สูงไป -> ลด; ถ้าเพิ่มแล้วไม่เห็นผล ให้เช็ก DRAG_FACTOR_MAX
DRAG_FACTOR_MIN = 0.55
DRAG_FACTOR_MAX = 1.18  # clamp สูงสุดของ drag factor; ต่ำเกินไปจะบังผลของ FAST_ROUND_MULT/ค่า drag อื่นๆ
DRAG_BAND_TRANSONIC_MIN = 0.78
DRAG_BAND_TRANSONIC_MAX = 1.22
DRAG_BAND_SUPERSONIC_MIN = 1.15
DRAG_BAND_SUPERSONIC_MAX = 2.6
PROJECTILE_SIM_MAX_TIME = 12.0  # เพิ่มถ้าจะรองรับยิงไกลมาก
PROJECTILE_SIM_MIN_SPEED = 25.0  # ต่ำลง = sim ต่อได้นานขึ้น
PROJECTILE_SIM_DT_MIN = 0.003  # ลด = ละเอียดขึ้นแต่หนักขึ้น
PROJECTILE_SIM_DT_MAX = 0.012  # ลด = ละเอียดขึ้น
PROJECTILE_SIM_DT_SCALE = 4.0  # scale ของ adaptive dt
ZERO_PITCH_MAX_ITERS = 5  # เพิ่ม = zeroing นิ่งขึ้นแต่ช้าลง
ZERO_PITCH_GAIN = 0.92  # สูงขึ้น = zeroing เข้าค่าไวขึ้น
ZERO_PITCH_MIN = -0.08  # clamp ต่ำสุดของ zero pitch
ZERO_PITCH_MAX = 0.18  # clamp สูงสุดของ zero pitch

# ==========================================
# 🔎 SNIPER MODE (PiP) CONFIGURATION
# ==========================================
ENABLE_SNIPER_MODE = True
SNIPER_ZOOM_SCALE = 4.5       # อัตราการซูม (เท่า)
SNIPER_WINDOW_SIZE = 450      # ขนาดกรอบหน้าต่าง Sniper (พิกเซล)
SNIPER_POS_X = 20             # ตำแหน่งแกน X (มุมซ้ายบน)
SNIPER_POS_Y = 320            # ตำแหน่งแกน Y (มุมซ้ายบน ถัดจากตัวหนังสือ)
SNIPER_MIN_RANGE = 200.0      # ระยะต่ำสุดที่จะเปิด PiP sniper

#- อยากกดลงทุกระยะอีกหน่อย: เพิ่ม GROUND_HITPOINT_DROP_BASE
#- อยากให้ระยะไกลลงมากขึ้น: เพิ่ม GROUND_HITPOINT_DROP_EXP
#- อยากให้ correction โตเร็วขึ้นตั้งแต่ระยะกลาง: ลด GROUND_HITPOINT_DROP_RANGE
"""
- GROUND_HITPOINT_DROP_EXP
    ตัวนี้มีผลกับระยะไกลโดยตรงมากที่สุด

  - ถ้า hit point ระยะไกลยัง “สูงเกินจริง”
    เพิ่ม GROUND_HITPOINT_DROP_EXP
  - ถ้า hit point ระยะไกล “ต่ำเกินจริง”
    ลด GROUND_HITPOINT_DROP_EXP

  ส่วนอีก 2 ตัว:
  - GROUND_HITPOINT_DROP_BASE
    ใช้แก้ offset ทุกระยะ โดยเฉพาะระยะใกล้
  - GROUND_HITPOINT_DROP_RANGE
    ใช้คุมว่าผลของ correction จะโตเร็วหรือช้าเมื่อระยะเพิ่ม
      - ลดค่า = correction มาแรงตั้งแต่ระยะกลาง
      - เพิ่มค่า = correction ค่อยๆ โต
"""
GROUND_HITPOINT_DROP_BASE = -0.001
GROUND_HITPOINT_DROP_EXP = 0.480        #ถ้าใกล้ๆ เกือบตรงแล้ว แต่ไกลยังเพี้ยนเล็กน้อย ให้จูนตัวนี้ก่อน`
GROUND_HITPOINT_DROP_RANGE = 1600.0


def _get_binary_fingerprint(binary_path=DEFAULT_GAME_BINARY_PATH):
    try:
        real_path = os.path.realpath(binary_path)
        st = os.stat(real_path)
        return {
            "path": real_path,
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }
    except Exception:
        return None


def _fingerprint_matches(doc):
    persisted = doc.get("build_fingerprint") if isinstance(doc, dict) else None
    if not persisted:
        return True
    current = _get_binary_fingerprint()
    if not current:
        return False
    return (
        os.path.realpath(str(persisted.get("path", ""))) == current["path"]
        and int(persisted.get("size", -1)) == current["size"]
        and int(persisted.get("mtime_ns", -1)) == current["mtime_ns"]
    )


def _can_overwrite_persistence(path, new_confidence):
    try:
        if not os.path.exists(path):
            return True
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            return True
        current_confidence = float(doc.get("confidence", 0.0) or 0.0)
        return float(new_confidence) >= current_confidence
    except Exception:
        return True


def _load_persistence_doc(path):
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            return None
        return doc
    except Exception:
        return None


def _load_vertical_baseline_config():
    global VERTICAL_BASELINE_TABLE, VERTICAL_BASELINE_RUNTIME_SOURCE

    VERTICAL_BASELINE_TABLE = json.loads(json.dumps(DEFAULT_VERTICAL_BASELINE_TABLE))
    VERTICAL_BASELINE_RUNTIME_SOURCE = "default"
    path = VERTICAL_BASELINE_CONFIG_PATH
    if not os.path.exists(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        table = doc.get("table") if isinstance(doc, dict) and "table" in doc else doc
        if not isinstance(table, dict):
            print("[!] Vertical baseline config ignored: root table is not a dict")
            return False

        normalized = {}
        profile_count = 0
        for bucket_name, bucket_table in table.items():
            if not isinstance(bucket_table, dict):
                continue
            clean_bucket = {}
            for unit_key, raw_entry in bucket_table.items():
                entry = _normalize_vertical_baseline_entry(raw_entry)
                curve = []
                for point in entry.get("curve", []) or []:
                    if not isinstance(point, (list, tuple)) or len(point) < 2:
                        continue
                    try:
                        curve.append((float(point[0]), float(point[1])))
                    except Exception:
                        continue
                if not curve:
                    continue
                entry["curve"] = sorted(curve, key=lambda item: item[0])
                clean_bucket[str(unit_key)] = entry
                profile_count += 1
            if clean_bucket:
                normalized[str(bucket_name)] = clean_bucket

        if not normalized:
            print("[!] Vertical baseline config ignored: no usable curves found")
            return False

        VERTICAL_BASELINE_TABLE = normalized
        VERTICAL_BASELINE_RUNTIME_SOURCE = "file"
        source = "vertical_baseline_table"
        updated_by = "unknown"
        if isinstance(doc, dict):
            source = doc.get("source", source)
            updated_by = doc.get("updated_by_tool", updated_by)

        print("[*] 📐 Loaded Vertical Baseline Config")
        print(
            f"    path={path} | buckets={len(VERTICAL_BASELINE_TABLE)} | "
            f"profiles={profile_count}"
        )
        print(
            f"    source={source} | tool={updated_by}"
        )
        return True
    except Exception as e:
        print(f"[!] Vertical baseline config load failed: {e}")
        return False


def _load_ballistic_layout_persistence():
    global BALLISTIC_STRUCT_BASE_OFF
    global BALLISTIC_SPEED_OFF
    global BALLISTIC_MASS_OFF
    global BALLISTIC_CALIBER_OFF
    global BALLISTIC_CX_OFF
    global BALLISTIC_MAX_DISTANCE_OFF
    global BALLISTIC_VEL_RANGE_X_OFF
    global BALLISTIC_VEL_RANGE_Y_OFF

    if not os.path.exists(BALLISTIC_PERSISTENCE_PATH):
        return False

    try:
        with open(BALLISTIC_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            print("[!] Persistence warning: ballistic ignored due to build fingerprint mismatch")
            return False
        layout = doc.get("layout") or {}
        required_keys = (
            "base_off",
            "speed_off",
            "mass_off",
            "caliber_off",
            "cx_off",
            "max_distance_off",
            "vel_range_x_off",
            "vel_range_y_off",
        )
        if not all(k in layout for k in required_keys):
            print("[!] Persistence warning: ballistic ignored due to missing layout keys")
            return False

        BALLISTIC_STRUCT_BASE_OFF = int(layout["base_off"])
        BALLISTIC_SPEED_OFF = int(layout["speed_off"])
        BALLISTIC_MASS_OFF = int(layout["mass_off"])
        BALLISTIC_CALIBER_OFF = int(layout["caliber_off"])
        BALLISTIC_CX_OFF = int(layout["cx_off"])
        BALLISTIC_MAX_DISTANCE_OFF = int(layout["max_distance_off"])
        BALLISTIC_VEL_RANGE_X_OFF = int(layout["vel_range_x_off"])
        BALLISTIC_VEL_RANGE_Y_OFF = int(layout["vel_range_y_off"])
        print("[*] 📦 Loaded Ballistic Persistence")
        print(
            f"    layout={layout.get('layout_name', 'unknown')} | "
            f"base={hex(BALLISTIC_STRUCT_BASE_OFF)} | "
            f"speed={hex(BALLISTIC_SPEED_OFF)} | mass={hex(BALLISTIC_MASS_OFF)}"
        )
        print(
            f"    cal={hex(BALLISTIC_CALIBER_OFF)} | cx={hex(BALLISTIC_CX_OFF)} | "
            f"maxDist={hex(BALLISTIC_MAX_DISTANCE_OFF)} | "
            f"vrX={hex(BALLISTIC_VEL_RANGE_X_OFF)} | vrY={hex(BALLISTIC_VEL_RANGE_Y_OFF)}"
        )
        print(
            f"    source={doc.get('source', 'unknown')} | "
            f"tool={doc.get('updated_by_tool', 'unknown')} | "
            f"conf={float(doc.get('confidence', 0.0) or 0.0):.2f}"
        )
        return True
    except Exception as e:
        print(f"[!] Persistence warning: ballistic load failed: {e}")
        return False


def _infer_ballistic_layout_name():
    speed_rel = BALLISTIC_SPEED_OFF - BALLISTIC_STRUCT_BASE_OFF
    mass_rel = BALLISTIC_MASS_OFF - BALLISTIC_STRUCT_BASE_OFF
    caliber_rel = BALLISTIC_CALIBER_OFF - BALLISTIC_STRUCT_BASE_OFF
    cx_rel = BALLISTIC_CX_OFF - BALLISTIC_STRUCT_BASE_OFF
    max_dist_rel = BALLISTIC_MAX_DISTANCE_OFF - BALLISTIC_STRUCT_BASE_OFF
    vel_x_rel = BALLISTIC_VEL_RANGE_X_OFF - BALLISTIC_STRUCT_BASE_OFF
    vel_y_rel = BALLISTIC_VEL_RANGE_Y_OFF - BALLISTIC_STRUCT_BASE_OFF
    if (
        speed_rel == -0x08
        and mass_rel == 0x04
        and caliber_rel == 0x08
        and cx_rel == 0x0C
        and max_dist_rel == 0x10
        and vel_x_rel == 0x24
        and vel_y_rel == 0x28
    ):
        return "layout_old_guess"
    if (
        speed_rel == 0x00
        and mass_rel == 0x0C
        and caliber_rel == 0x10
        and cx_rel == 0x14
        and max_dist_rel == 0x18
        and vel_x_rel == 0x24
        and vel_y_rel == 0x28
    ):
        return "layout_new_guess"
    return "layout_runtime_unknown"


def _write_ballistic_layout_persistence(source="radar_overlay_auto_ballistic"):
    try:
        if not _can_overwrite_persistence(BALLISTIC_PERSISTENCE_PATH, 0.68):
            print("[*] Skip auto-save ballistic persistence: existing confidence is higher")
            return False
        os.makedirs(os.path.dirname(BALLISTIC_PERSISTENCE_PATH), exist_ok=True)
        doc = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "build_fingerprint": _get_binary_fingerprint(),
            "weapon_source": "runtime_effective_offsets",
            "best_layout_score": 0,
            "source": source,
            "updated_by_tool": "radar_overlay",
            "confidence": 0.68,
            "layout": {
                "layout_name": _infer_ballistic_layout_name(),
                "base_off": int(BALLISTIC_STRUCT_BASE_OFF),
                "speed_off": int(BALLISTIC_SPEED_OFF),
                "mass_off": int(BALLISTIC_MASS_OFF),
                "caliber_off": int(BALLISTIC_CALIBER_OFF),
                "cx_off": int(BALLISTIC_CX_OFF),
                "max_distance_off": int(BALLISTIC_MAX_DISTANCE_OFF),
                "vel_range_x_off": int(BALLISTIC_VEL_RANGE_X_OFF),
                "vel_range_y_off": int(BALLISTIC_VEL_RANGE_Y_OFF),
            },
        }
        with open(BALLISTIC_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        print(
            "[*] 💾 AUTO-SAVED! Ballistic persistence:"
            f" layout={doc['layout']['layout_name']}"
            f" base={hex(BALLISTIC_STRUCT_BASE_OFF)}"
            f" speed={hex(BALLISTIC_SPEED_OFF)}"
            f" mass={hex(BALLISTIC_MASS_OFF)}"
            f" cal={hex(BALLISTIC_CALIBER_OFF)}"
            f" cx={hex(BALLISTIC_CX_OFF)}"
            f" maxDist={hex(BALLISTIC_MAX_DISTANCE_OFF)}"
            f" vrX={hex(BALLISTIC_VEL_RANGE_X_OFF)}"
            f" vrY={hex(BALLISTIC_VEL_RANGE_Y_OFF)}"
            f" source={doc['source']}"
            f" tool={doc['updated_by_tool']}"
            f" conf={doc['confidence']:.2f}"
        )
        return True
    except Exception as e:
        print(f"[*] Ballistic persistence auto-save failed: {e}")
        return False


_ballistic_persistence_loaded = _load_ballistic_layout_persistence()
if not _ballistic_persistence_loaded:
    _write_ballistic_layout_persistence()


def _load_unit_bbox_persistence():
    global OFF_UNIT_BBMIN
    global OFF_UNIT_BBMAX

    if not os.path.exists(BBOX_PERSISTENCE_PATH):
        return False

    try:
        with open(BBOX_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            print("[!] Persistence warning: bbox ignored due to build fingerprint mismatch")
            return False
        bbmin_off = int(doc.get("bbmin_off", 0) or 0)
        bbmax_off = int(doc.get("bbmax_off", 0) or 0)
        if not (0x100 <= bbmin_off < bbmax_off <= 0x400):
            print("[!] Persistence warning: bbox ignored due to invalid offset range")
            return False
        OFF_UNIT_BBMIN = bbmin_off
        OFF_UNIT_BBMAX = bbmax_off
        print("[*] 📦 Loaded BBox Persistence")
        print(
            f"    bbmin={hex(OFF_UNIT_BBMIN)} | bbmax={hex(OFF_UNIT_BBMAX)}"
        )
        print(
            f"    source={doc.get('source', 'unknown')} | "
            f"tool={doc.get('updated_by_tool', 'unknown')} | "
            f"conf={float(doc.get('confidence', 0.0) or 0.0):.2f}"
        )
        return True
    except Exception as e:
        print(f"[!] Persistence warning: bbox load failed: {e}")
        return False


_load_unit_bbox_persistence()


def _log_view_matrix_persistence_preflight():
    doc = _load_persistence_doc(os.path.join("config", "view_matrix_persistence.json"))
    if not doc:
        return False
    try:
        camera_off = int(doc.get("camera_off", 0) or 0)
        matrix_off = int(doc.get("matrix_off", 0) or 0)
        print("[*] 👁️  Loaded View Persistence")
        print(
            f"    camera={hex(camera_off)} | matrix={hex(matrix_off)} | apply=phase8"
        )
        print(
            f"    source={doc.get('source', 'unknown')} | "
            f"tool={doc.get('updated_by_tool', 'unknown')} | "
            f"conf={float(doc.get('confidence', 0.0) or 0.0):.2f}"
        )
        return True
    except Exception:
        return False


_log_view_matrix_persistence_preflight()


def _load_view_candidate_persistence():
    if not VIEW_CANDIDATE_PERSISTENCE_ENABLE:
        return False
    if not os.path.exists(VIEW_CANDIDATE_PERSISTENCE_PATH):
        return False
    try:
        with open(VIEW_CANDIDATE_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        candidate = doc.get("global_candidate") or {}
        if not set_forced_view_profile(candidate):
            return False
        print(
            "[*] Loaded view candidate persistence:"
            f" matrix={candidate.get('matrix_off', '0x0')}"
            f" mode={candidate.get('projection_mode', 'unknown')}"
            f" sign={candidate.get('axis_signs', '+++')}"
            f" wins={candidate.get('wins', 0)}"
            f" source={candidate.get('source', 'unknown')}"
        )
        return True
    except Exception as e:
        print(f"[*] View candidate persistence load failed: {e}")
        return False


_load_view_candidate_persistence()

UNIT_FAMILY_UNKNOWN = 0
UNIT_FAMILY_AIR_FIGHTER = 1
UNIT_FAMILY_AIR_BOMBER = 2
UNIT_FAMILY_AIR_ATTACKER = 3
UNIT_FAMILY_AIR_HELICOPTER = 4
UNIT_FAMILY_GROUND_MEDIUM_TANK = 5
UNIT_FAMILY_GROUND_HEAVY_TANK = 6
UNIT_FAMILY_GROUND_TANK_DESTROYER = 7
UNIT_FAMILY_GROUND_SPAA = 8
UNIT_FAMILY_SHIP_BOAT = 9
UNIT_FAMILY_SHIP_FRIGATE = 10
UNIT_FAMILY_SHIP_DESTROYER = 11
UNIT_FAMILY_SHIP_CRUISER = 12
UNIT_FAMILY_SHIP_BATTLESHIP = 13
UNIT_FAMILY_GROUND_LIGHT_TANK = 14

def _solve_static_ground_leadmark(target_pos, fire_origin, my_vel, bullet_speed, zeroing, model, zero_pitch, my_rot=None):
    if not target_pos or not fire_origin or bullet_speed <= 0.0:
        return None

    t_x, t_y, t_z = target_pos
    my_vx, my_vy, my_vz = my_vel
    
    best_t = math.dist((t_x, t_z), (fire_origin[0], fire_origin[2])) / bullet_speed
    best_t = max(best_t, 0.01)
    bullet_drop = 0.0

    for _ in range(3):
        dx_imp = t_x - (fire_origin[0] + my_vx * best_t)
        dz_imp = t_z - (fire_origin[2] + my_vz * best_t)
        horizontal_imp = math.hypot(dx_imp, dz_imp)
        if horizontal_imp <= 0.01:
            return None
        best_t, bullet_drop, _ = _simulate_projectile_range(horizontal_imp, model, zero_pitch)

    t_sight = zeroing / bullet_speed if bullet_speed > 0 else 0
    sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)

    # 🎯 THE TRUTH: แรงโน้มถ่วงดึงลงแกนโลก (World Y) เสมอ! ห้ามเอาไปเอียงตามรถถังเด็ดขาด!
    final_x = t_x - (my_vx * best_t)
    final_y = t_y + bullet_drop - sight_drop_comp - (my_vy * best_t)
    final_z = t_z - (my_vz * best_t)
    
    return final_x, final_y, final_z


def _map_aim_to_target_box_hitpoint(aim_screen, leadmark_screen, target_box_rect, target_pos=None, distance_to_target=0.0, my_rot=None, view_matrix=None, screen_w=2560, screen_h=1440, calibration_offset=(0.0, 0.0), vertical_correction=0.0, camera_parallax=-4.5):
    if not aim_screen or not leadmark_screen or not target_box_rect:
        return None

    min_x, min_y, max_x, max_y = target_box_rect
    # 🎯 THE PROPORTIONAL FIX: ดึงความกว้างและความสูงมาแยกกันคำนวณ!
    box_w = max(max_x - min_x, 1.0)
    box_h = max(max_y - min_y, 1.0)

    dist_t = max(0.0, min(1.0, distance_to_target / max(GROUND_HITPOINT_DROP_RANGE, 1.0)))
    exp_t = (math.exp(dist_t) - 1.0) / (math.e - 1.0)
    drop_pixels_y = (GROUND_HITPOINT_DROP_BASE + (GROUND_HITPOINT_DROP_EXP * exp_t)) * box_h

    dx = aim_screen[0] - leadmark_screen[0]
    dy = aim_screen[1] - leadmark_screen[1]

    base_x = (min_x + max_x) * 0.5
    base_y = (min_y + max_y) * 0.5

    if target_pos and view_matrix:
        tx, ty, tz = target_pos
        scr_center = world_to_screen(view_matrix, tx, ty, tz, screen_w, screen_h)
        if scr_center and scr_center[2] > 0:
            base_x, base_y = scr_center[0], scr_center[1]

    calib_x = float(calibration_offset[0]) if calibration_offset else 0.0
    vertical_correction = float(vertical_correction or 0.0)

    up_x, up_y = 0.0, -1.0 
    if my_rot and view_matrix and len(view_matrix) >= 16:
        up_wx, up_wy, up_wz = my_rot[3], my_rot[4], my_rot[5]
        clip_x = (up_wx * view_matrix[0]) + (up_wy * view_matrix[4]) + (up_wz * view_matrix[8])
        clip_y = (up_wx * view_matrix[1]) + (up_wy * view_matrix[5]) + (up_wz * view_matrix[9])
        scr_vx = clip_x
        scr_vy = -clip_y
        mag = math.hypot(scr_vx, scr_vy)
        if mag > 0.001:
            up_x = scr_vx / mag
            up_y = scr_vy / mag

    down_x = -up_x
    down_y = -up_y

    # 🎯 ใช้อัตราส่วนเปอร์เซ็นต์ที่แยกแกน X, Y ออกจากกัน (100% = ขอบกล่อง)
    scaled_calib_x = (calib_x / 100.0) * box_w
    scaled_vertical_correction = (vertical_correction / 100.0) * box_h
    scaled_parallax = (camera_parallax / 100.0) * box_h

    parallax_shift_x = scaled_parallax * down_x
    parallax_shift_y = scaled_parallax * down_y

    final_x = base_x + dx + scaled_calib_x + parallax_shift_x
    final_y = base_y + dy + drop_pixels_y + scaled_vertical_correction + parallax_shift_y

    return (final_x, final_y)


def _get_hitpoint_parallax_debug_terms(target_box_rect, my_rot=None, view_matrix=None, camera_parallax=0.0):
    if not target_box_rect:
        return None
    min_x, min_y, max_x, max_y = target_box_rect
    box_h = max(max_y - min_y, 1.0)

    up_x, up_y = 0.0, -1.0
    if my_rot and view_matrix and len(view_matrix) >= 16:
        up_wx, up_wy, up_wz = my_rot[3], my_rot[4], my_rot[5]
        clip_x = (up_wx * view_matrix[0]) + (up_wy * view_matrix[4]) + (up_wz * view_matrix[8])
        clip_y = (up_wx * view_matrix[1]) + (up_wy * view_matrix[5]) + (up_wz * view_matrix[9])
        scr_vx = clip_x
        scr_vy = -clip_y
        mag = math.hypot(scr_vx, scr_vy)
        if mag > 0.001:
            up_x = scr_vx / mag
            up_y = scr_vy / mag

    down_x = -up_x
    down_y = -up_y
    scaled_parallax = (float(camera_parallax or 0.0) / 100.0) * box_h
    return {
        "box_h": float(box_h),
        "down_x": float(down_x),
        "down_y": float(down_y),
        "scaled_parallax": float(scaled_parallax),
        "shift_x": float(scaled_parallax * down_x),
        "shift_y": float(scaled_parallax * down_y),
    }


def _vertical_baseline_ammo_bucket(profile):
    return resolve_ammo_family(profile)["bucket"]


def _interpolate_vertical_curve(points, distance_to_target):
    if not points:
        return 0.0
    dist = float(distance_to_target or 0.0)
    ordered = sorted(points, key=lambda item: item[0])
    if dist <= ordered[0][0]:
        return float(ordered[0][1])
    if dist >= ordered[-1][0]:
        return float(ordered[-1][1])
    for i in range(len(ordered) - 1):
        left_d, left_v = ordered[i]
        right_d, right_v = ordered[i + 1]
        if left_d <= dist <= right_d:
            t = _smoothstep(left_d, right_d, dist)
            return float(left_v) + (float(right_v) - float(left_v)) * t
    return float(ordered[-1][1])


def _normalize_vertical_baseline_entry(entry):
    if isinstance(entry, dict):
        return {
            "my_unit_key": str(entry.get("my_unit_key", "") or ""),
            "speed": float(entry.get("speed", 0.0) or 0.0),
            "caliber": float(entry.get("caliber", 0.0) or 0.0),
            "mass": float(entry.get("mass", 0.0) or 0.0),
            "bullet_type_idx": int(entry.get("bullet_type_idx", -1) or -1),
            "camera_parallax": float(entry.get("camera_parallax", 0.0) or 0.0),
            "cannon_size": float(entry.get("cannon_size", 0.0) or 0.0),
            "ammo_family": str(entry.get("ammo_family", "") or ""),
            "curve": entry.get("curve", []) or [],
        }
    return {
        "my_unit_key": "",
        "speed": 0.0,
        "caliber": 0.0,
        "mass": 0.0,
        "bullet_type_idx": -1,
        "camera_parallax": 0.0,
        "cannon_size": 0.0,
        "ammo_family": "",
        "curve": entry or [],
    }


def _vertical_baseline_entry_matches_unit(entry_key, entry, my_unit_key):
    my_unit_key = str(my_unit_key or "")
    if not my_unit_key:
        return False
    if str(entry_key) == my_unit_key:
        return True
    entry_unit_key = str((entry or {}).get("my_unit_key", "") or "")
    if entry_unit_key == my_unit_key:
        return True
    return str(entry_key).startswith(f"{my_unit_key}|")


def _choose_vertical_baseline_entry(my_unit_key, ballistic_profile):
    ammo_bucket = _vertical_baseline_ammo_bucket(ballistic_profile)
    speed = float((ballistic_profile or {}).get("speed", 0.0) or 0.0)
    caliber = float((ballistic_profile or {}).get("caliber", 0.0) or 0.0)

    def iter_candidates(bucket_name):
        table = VERTICAL_BASELINE_TABLE.get(bucket_name, {}) or {}
        for unit_key, raw_entry in table.items():
            entry = _normalize_vertical_baseline_entry(raw_entry)
            yield bucket_name, unit_key, entry

    bucket_table = VERTICAL_BASELINE_TABLE.get(ammo_bucket, {}) or {}
    if my_unit_key in bucket_table:
        return ammo_bucket, my_unit_key, _normalize_vertical_baseline_entry(bucket_table[my_unit_key])

    exact_unit_candidates = []
    for entry_key, raw_entry in bucket_table.items():
        entry = _normalize_vertical_baseline_entry(raw_entry)
        if _vertical_baseline_entry_matches_unit(entry_key, entry, my_unit_key):
            exact_unit_candidates.append((ammo_bucket, entry_key, entry))
    if exact_unit_candidates:
        candidates = exact_unit_candidates
    else:
        candidates = list(iter_candidates(ammo_bucket))

    if not candidates:
        for bucket_name in VERTICAL_BASELINE_TABLE.keys():
            for entry_key, raw_entry in (VERTICAL_BASELINE_TABLE.get(bucket_name, {}) or {}).items():
                entry = _normalize_vertical_baseline_entry(raw_entry)
                if _vertical_baseline_entry_matches_unit(entry_key, entry, my_unit_key):
                    candidates.append((bucket_name, entry_key, entry))
        if not candidates:
            for bucket_name in VERTICAL_BASELINE_TABLE.keys():
                candidates.extend(iter_candidates(bucket_name))
    if not candidates:
        return ammo_bucket, "", {"speed": 0.0, "caliber": 0.0, "mass": 0.0, "bullet_type_idx": -1, "curve": []}

    best = None
    best_score = None
    for bucket_name, unit_key, entry in candidates:
        ref_speed = float(entry.get("speed", 0.0) or 0.0)
        ref_caliber = float(entry.get("caliber", 0.0) or 0.0)
        ref_mass = float(entry.get("mass", 0.0) or 0.0)
        ref_bullet_type = int(entry.get("bullet_type_idx", -1) or -1)
        speed_term = abs(speed - ref_speed) / max(max(speed, ref_speed, 1.0), 1.0)
        caliber_term = abs(caliber - ref_caliber) / max(max(caliber, ref_caliber, 0.001), 0.001)
        mass = float((ballistic_profile or {}).get("mass", 0.0) or 0.0)
        bullet_type_idx = int((ballistic_profile or {}).get("bullet_type_idx", -1) or -1)
        mass_term = abs(mass - ref_mass) / max(max(mass, ref_mass, 0.001), 0.001) if (mass > 0.0 and ref_mass > 0.0) else 0.0
        bullet_type_term = 0.0 if (bullet_type_idx >= 0 and ref_bullet_type >= 0 and bullet_type_idx == ref_bullet_type) else 0.25
        score = speed_term + (caliber_term * 2.0) + mass_term + bullet_type_term
        if best_score is None or score < best_score:
            best_score = score
            best = (bucket_name, unit_key, entry)
    return best


def _get_auto_vertical_baseline(my_unit_key, ballistic_profile, distance_to_target):
    global VERTICAL_BASELINE_LAST_MATCH
    if not VERTICAL_BASELINE_AUTO_ENABLE:
        return 0.0
    _bucket_name, _matched_unit_key, entry = _choose_vertical_baseline_entry(my_unit_key or "", ballistic_profile)
    curve = entry.get("curve", []) if isinstance(entry, dict) else []
    value = _interpolate_vertical_curve(curve, distance_to_target) if curve else 0.0
    family_info = resolve_ammo_family(ballistic_profile or {})
    VERTICAL_BASELINE_LAST_MATCH = {
        "bucket": str(_bucket_name or ""),
        "profile_key": str(_matched_unit_key or ""),
        "entry_unit_key": str((entry or {}).get("my_unit_key", "") or ""),
        "entry_speed": float((entry or {}).get("speed", 0.0) or 0.0),
        "entry_caliber": float((entry or {}).get("caliber", 0.0) or 0.0),
        "entry_mass": float((entry or {}).get("mass", 0.0) or 0.0),
        "entry_parallax": float((entry or {}).get("camera_parallax", 0.0) or 0.0),
        "entry_cannon_size": float((entry or {}).get("cannon_size", 0.0) or 0.0),
        "ballistic_speed": float((ballistic_profile or {}).get("speed", 0.0) or 0.0),
        "ballistic_caliber": float((ballistic_profile or {}).get("caliber", 0.0) or 0.0),
        "ballistic_mass": float((ballistic_profile or {}).get("mass", 0.0) or 0.0),
        "ballistic_cannon_size": float((ballistic_profile or {}).get("cannon_size", 0.0) or 0.0),
        "family": str(family_info.get("family", "") or ""),
        "reason": str(family_info.get("reason", "") or ""),
        "distance": float(distance_to_target or 0.0),
        "value": float(value or 0.0),
    }
    return value


_load_vertical_baseline_config()


def _read_vec3_candidate(scanner, addr):
    try:
        raw = scanner.read_mem(addr, 12)
        if not raw or len(raw) != 12:
            return None
        vals = struct.unpack("<fff", raw)
        if not all(math.isfinite(v) and abs(v) < 10000.0 for v in vals):
            return None
        return vals
    except Exception:
        return None


def _valid_local_bbox(bmin, bmax):
    if not bmin or not bmax:
        return False
    dx = float(bmax[0] - bmin[0])
    dy = float(bmax[1] - bmin[1])
    dz = float(bmax[2] - bmin[2])
    return 0.05 < dx < 100.0 and 0.05 < dy < 50.0 and 0.05 < dz < 100.0


def _get_dynamic_target_box_data(scanner, u_ptr, is_air=False):
    base_box = get_unit_3d_box_data(scanner, u_ptr, is_air)
    if not base_box or is_air:
        return base_box, "unit_bbox"
    pos, bmin, bmax, rot = base_box
    for min_off, max_off, label in DYNAMIC_TURRET_BBOX_CANDIDATES:
        cand_bmin = _read_vec3_candidate(scanner, u_ptr + min_off)
        cand_bmax = _read_vec3_candidate(scanner, u_ptr + max_off)
        if _valid_local_bbox(cand_bmin, cand_bmax):
            return (pos, cand_bmin, cand_bmax, rot), label
    return base_box, "unit_bbox"


def _world_to_local_delta(delta_world, axes):
    ax, ay, az = axes
    return (
        (delta_world[0] * ax[0]) + (delta_world[1] * ax[1]) + (delta_world[2] * ax[2]),
        (delta_world[0] * ay[0]) + (delta_world[1] * ay[1]) + (delta_world[2] * ay[2]),
        (delta_world[0] * az[0]) + (delta_world[1] * az[1]) + (delta_world[2] * az[2]),
    )


def _get_dynamic_my_geometry(scanner, cgame_base, my_unit, my_box_data):
    if not (DYNAMIC_GEOMETRY_ENABLE and scanner and cgame_base and my_unit and my_box_data):
        return None
    try:
        unit_pos, bmin, bmax, rot = my_box_data
        if not unit_pos or not rot:
            return None
        axes = get_local_axes_from_rotation(rot, False)
        unit_dims = (
            float(bmax[0] - bmin[0]),
            float(bmax[1] - bmin[1]),
            float(bmax[2] - bmin[2]),
        )
        camera_ptr_raw = scanner.read_mem(cgame_base + OFF_CAMERA_PTR, 8)
        if not camera_ptr_raw or len(camera_ptr_raw) != 8:
            return None
        camera_ptr = struct.unpack("<Q", camera_ptr_raw)[0]
        if not is_valid_ptr(camera_ptr):
            return None
        camera_world = _read_vec3_candidate(scanner, camera_ptr + 0x58)
        if not camera_world:
            return None
        barrel = get_weapon_barrel(scanner, my_unit, unit_pos, rot)
        if not barrel or not barrel[0]:
            return None
        barrel_base = barrel[0]
        camera_local = _world_to_local_delta(
            (camera_world[0] - unit_pos[0], camera_world[1] - unit_pos[1], camera_world[2] - unit_pos[2]),
            axes,
        )
        barrel_base_local = _world_to_local_delta(
            (barrel_base[0] - unit_pos[0], barrel_base[1] - unit_pos[1], barrel_base[2] - unit_pos[2]),
            axes,
        )
        camera_radius = math.sqrt((camera_local[0] ** 2) + (camera_local[1] ** 2) + (camera_local[2] ** 2))
        fps_dist_limit = max(DYNAMIC_GEOMETRY_FPS_MAX_DIST, max(unit_dims) * DYNAMIC_GEOMETRY_FPS_UNIT_SCALE)
        if camera_radius > fps_dist_limit:
            return None
        delta_local = (
            camera_local[0] - barrel_base_local[0],
            camera_local[1] - barrel_base_local[1],
            camera_local[2] - barrel_base_local[2],
        )
        unit_height = max(unit_dims[1], 0.25)
        dynamic_parallax_pct = (delta_local[1] / unit_height) * 100.0 * DYNAMIC_PARALLAX_SCALE
        return {
            "camera_ptr": camera_ptr,
            "camera_world": camera_world,
            "barrel_base_world": barrel_base,
            "camera_local": camera_local,
            "barrel_base_local": barrel_base_local,
            "delta_local": delta_local,
            "dynamic_parallax_pct": dynamic_parallax_pct,
        }
    except Exception:
        return None


def _offset_world_point(world_point, world_offset):
    if not world_point or not world_offset:
        return world_point
    return (
        float(world_point[0] + world_offset[0]),
        float(world_point[1] + world_offset[1]),
        float(world_point[2] + world_offset[2]),
    )


def _get_ground_target_aim_point(box_data, fallback_pos, distance_to_target):
    if not box_data:
        return (fallback_pos[0], fallback_pos[1] + 1.0, fallback_pos[2]) if fallback_pos else None

    pos, bmin, bmax, rot = box_data
    ax, ay, az = get_local_axes_from_rotation(rot, False)

    local_x = (bmin[0] + bmax[0]) * 0.5
    local_z = (bmin[2] + bmax[2]) * 0.5
    local_h = max(bmax[1] - bmin[1], 0.5)
    far_t = max(0.0, min(1.0, distance_to_target / max(GROUND_AIM_HEIGHT_RATIO_BLEND_MAX, 1.0)))
    aim_ratio = (
        GROUND_AIM_HEIGHT_RATIO_CLOSE +
        ((GROUND_AIM_HEIGHT_RATIO_FAR - GROUND_AIM_HEIGHT_RATIO_CLOSE) * _smoothstep(0.0, 1.0, far_t))
    )
    local_y = local_h * aim_ratio

    return (
        pos[0] + (ax[0] * local_x) + (ay[0] * local_y) + (az[0] * local_z),
        pos[1] + (ax[1] * local_x) + (ay[1] * local_y) + (az[1] * local_z),
        pos[2] + (ax[2] * local_x) + (ay[2] * local_y) + (az[2] * local_z),
    )


def _is_recon_drone_like(token):
    token = str(token or "").lower()
    drone_patterns = (
        "recon micro",
        "recon_micro",
        "recon drone",
        "recon_drone",
        "scout drone",
        "scout_drone",
        "observation drone",
        "observation_drone",
        "spotter drone",
        "spotter_drone",
        "quadcopter",
        "micro_uav",
        "micro uav",
        "uav",
        "drone",
    )
    return any(p in token for p in drone_patterns)


def _resolve_unit_family_enum(family_name, profile_tag, profile_path, unit_key, name_key, short_name, is_air):
    family_tag = (family_name or profile_tag or "").lower()
    token = " ".join((
        family_name or "",
        profile_tag or "",
        profile_path or "",
        unit_key or "",
        name_key or "",
        short_name or "",
    )).lower()

    pragmatic_code = _match_pragmatic_unit_family_code(family_tag, token)
    pragmatic_family = _unit_family_from_code(pragmatic_code)
    if pragmatic_family != UNIT_FAMILY_UNKNOWN:
        return pragmatic_family

    if family_tag == "exp_helicopter":
        return UNIT_FAMILY_AIR_HELICOPTER
    if family_tag == "exp_bomber":
        return UNIT_FAMILY_AIR_BOMBER
    if family_tag in ("exp_assault", "exp_attacker"):
        return UNIT_FAMILY_AIR_ATTACKER
    if family_tag == "exp_fighter":
        return UNIT_FAMILY_AIR_FIGHTER
    if family_tag == "exp_spaa":
        return UNIT_FAMILY_GROUND_SPAA
    if family_tag in ("exp_light_tank", "exp_tank_light", "exp_ltank"):
        return UNIT_FAMILY_GROUND_LIGHT_TANK
    if family_tag in ("exp_tank_destroyer", "exp_tank_destr"):
        return UNIT_FAMILY_GROUND_TANK_DESTROYER
    if family_tag == "exp_heavy_tank":
        return UNIT_FAMILY_GROUND_HEAVY_TANK
    if family_tag == "exp_tank":
        return UNIT_FAMILY_GROUND_MEDIUM_TANK
    if family_tag == "exp_destroyer":
        return UNIT_FAMILY_SHIP_DESTROYER
    if family_tag == "exp_cruiser":
        return UNIT_FAMILY_SHIP_CRUISER
    if family_tag in ("exp_torpedo_gun_boat", "exp_gun_boat", "exp_torpedo_boat"):
        return UNIT_FAMILY_SHIP_BOAT

    if is_air:
        if "helicopter" in token:
            return UNIT_FAMILY_AIR_HELICOPTER
        if "bomber" in token:
            return UNIT_FAMILY_AIR_BOMBER
        if "attacker" in token or "assault" in token:
            return UNIT_FAMILY_AIR_ATTACKER
        if "fighter" in token:
            return UNIT_FAMILY_AIR_FIGHTER
        return UNIT_FAMILY_AIR_FIGHTER

    if (
        "battleship" in token or
        "battlecruiser" in token
    ):
        return UNIT_FAMILY_SHIP_BATTLESHIP
    if "cruiser" in token:
        return UNIT_FAMILY_SHIP_CRUISER
    if "destroyer" in token:
        return UNIT_FAMILY_SHIP_DESTROYER
    if "frigate" in token:
        return UNIT_FAMILY_SHIP_FRIGATE
    if (
        "torpedo_gun_boat" in token or
        "gun_boat" in token or
        "torpedo_boat" in token or
        "type143" in token or
        "s38" in token or
        "lcs_" in token or
        "ships/" in token
    ):
        return UNIT_FAMILY_SHIP_BOAT
    if "spaa" in token:
        return UNIT_FAMILY_GROUND_SPAA
    if (
        "light_tank" in token or
        "light tank" in token or
        "exp_light_tank" in token or
        "exp_tank_light" in token
    ):
        return UNIT_FAMILY_GROUND_LIGHT_TANK
    if "tank_destroyer" in token or "tank_destr" in token:
        return UNIT_FAMILY_GROUND_TANK_DESTROYER
    if "heavy_tank" in token:
        return UNIT_FAMILY_GROUND_HEAVY_TANK
    if "tank" in token:
        return UNIT_FAMILY_GROUND_MEDIUM_TANK
    if not is_air:
        return UNIT_FAMILY_GROUND_MEDIUM_TANK
    return UNIT_FAMILY_UNKNOWN


def _resolve_is_air_now(default_is_air, family_name, profile_tag, profile_path):
    token = " ".join((
        family_name or "",
        profile_tag or "",
        profile_path or "",
    )).lower()

    if any(k in token for k in ("exp_helicopter", "exp_fighter", "exp_bomber", "exp_assault", "exp_attacker")):
        return True
    if any(k in token for k in (
        "exp_tank",
        "exp_heavy_tank",
        "exp_tank_destroyer",
        "exp_tank_destr",
        "exp_spaa",
        "exp_destroyer",
        "exp_cruiser",
        "exp_torpedo_boat",
        "exp_torpedo_gun_boat",
        "exp_gun_boat",
        "ships/",
    )):
        return False
    return default_is_air


def _draw_unit_class_icon(painter, center_x, center_y, unit_family, size):
    is_air = unit_family in (
        UNIT_FAMILY_AIR_FIGHTER,
        UNIT_FAMILY_AIR_BOMBER,
        UNIT_FAMILY_AIR_ATTACKER,
        UNIT_FAMILY_AIR_HELICOPTER,
    )

    color = QColor(*(COLOR_CLASS_ICON_AIR if is_air else COLOR_CLASS_ICON_GROUND))
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)

    half = max(5, int(size * 0.5))
    # สัดส่วนสมมาตร: Track H = Turret H = Body H และ Track W = Turret W
    u_h = max(2, int(half * 0.8))   # ความสูง 1 ส่วน (ใช้กับ ป้อมปืน, ตัวรถ, สายพาน)
    t_w = max(4, int(half * 1))     # ความกว้างของป้อมปืน (และสายพาน 1 ข้าง)
    
    inner_hw = int(t_w / 1.5)       # ระยะขอบในของสายพาน (ช่องว่างใต้ท้องรถ)
    turret_hw = int(t_w / 1.5)      # ครึ่งหนึ่งของความกว้างป้อมปืน
    body_hw = int(t_w * 1.5)        # ครึ่งหนึ่งของตัวรถ (กว้างพอดีสำหรับ ป้อมปืน + สายพาน)
    
    y0 = int(center_y - u_h * 1.5)  # ยอดป้อมปืน (Turret Top)
    y1 = int(center_y - u_h * 0.5)  # ฐานป้อมปืน / หลังคารถ (Body Top)
    y2 = int(center_y + u_h * 0.5)  # ท้องรถ (Body Bottom / Track Top)
    y3 = int(center_y + u_h * 1.5)  # ฐานสายพาน (Track Bottom)

    if unit_family == UNIT_FAMILY_GROUND_MEDIUM_TANK:
        # Medium Tank: ทรงแบน (ไม่มีป้อมบนสุด) 8 จุด
        poly = QPolygon([
            QPoint(int(center_x - body_hw), y1),  
            QPoint(int(center_x + body_hw), y1),  
            QPoint(int(center_x + body_hw), y3),  
            QPoint(int(center_x + inner_hw), y3), 
            QPoint(int(center_x + inner_hw), y2), 
            QPoint(int(center_x - inner_hw), y2), 
            QPoint(int(center_x - inner_hw), y3), 
            QPoint(int(center_x - body_hw), y3)   
        ])
        painter.drawPolygon(poly)
        return

    if unit_family == UNIT_FAMILY_GROUND_LIGHT_TANK:
        # Light Tank: ใช้ทรงใกล้ medium แต่ไม่มีส่วนสายพานด้านล่าง
        lt_body_hw = int(body_hw * 0.78)
        poly = QPolygon([
            QPoint(int(center_x - lt_body_hw), y1),
            QPoint(int(center_x + lt_body_hw), y1),
            QPoint(int(center_x + lt_body_hw), y2),
            QPoint(int(center_x - lt_body_hw), y2)
        ])
        painter.drawPolygon(poly)
        return
    
    if unit_family == UNIT_FAMILY_GROUND_HEAVY_TANK:
        # Heavy Tank: มีป้อมปืนตรงกลาง 12 จุด
        poly = QPolygon([
            QPoint(int(center_x - turret_hw), y0),  
            QPoint(int(center_x + turret_hw), y0),  
            QPoint(int(center_x + turret_hw), y1),  
            QPoint(int(center_x + body_hw), y1),    
            QPoint(int(center_x + body_hw), y3),    
            QPoint(int(center_x + turret_hw), y3),  
            QPoint(int(center_x + turret_hw), y2),  
            QPoint(int(center_x - turret_hw), y2),  
            QPoint(int(center_x - turret_hw), y3),  
            QPoint(int(center_x - body_hw), y3),    
            QPoint(int(center_x - body_hw), y1),    
            QPoint(int(center_x - turret_hw), y1)   
        ])
        painter.drawPolygon(poly)
        return
    
    if unit_family == UNIT_FAMILY_GROUND_SPAA:
        # SPAA: ย่อส่วนความกว้าง "ทั้งหมด" ลง 30% (สัดส่วนเดิมเป๊ะ แต่แคบลง)
        spaa_t_w = max(2, int(t_w * 0.70))
        spaa_turret_hw = int(spaa_t_w / 1.5)
        spaa_body_hw = int(spaa_t_w * 1.5)
        
        # ความกว้างเสา (หดลงตามสัดส่วนใหม่ แล้วลดอีก 30% ตามสั่ง)
        orig_pillar_w = spaa_body_hw - spaa_turret_hw
        new_pillar_w = max(2, int(orig_pillar_w * 0.7))
        
        left_center_x = center_x - int((spaa_body_hw + spaa_turret_hw) / 2)
        right_center_x = center_x + int((spaa_body_hw + spaa_turret_hw) / 2)
        
        pillar_y = y0
        pillar_h = y1 - y0 + 2
        radius = int(new_pillar_w / 2)
        
        # 1. วาดเสากลม
        painter.drawRoundedRect(int(left_center_x - radius), pillar_y, new_pillar_w, pillar_h, radius, radius)
        painter.drawRoundedRect(int(right_center_x - radius), pillar_y, new_pillar_w, pillar_h, radius, radius)
        
        # 2. วาดฐานตัวรถ (กว้างพอดีกับเสา)
        painter.drawRect(int(center_x - spaa_body_hw), y1, spaa_body_hw * 2, y2 - y1)
        return
    
    if unit_family == UNIT_FAMILY_GROUND_TANK_DESTROYER:
        # TD: ทรงลิ่มหักมุม (Angled Casemate) พร้อมระบบควบคุม Tilt Ratio
        lx = int(center_x - body_hw)
        beam_w = int(body_hw * 0.65)         # ความหนาแกนคงที่ 65% 
        
        # 🚀 อัตราส่วนความเอียง (Tilt Ratio)
        # เพิ่มค่า = เอียงลาดเป็นทรงสปอร์ตมากขึ้น / ลดค่า = ตั้งชันขึ้น
        tilt_ratio = 1.2 
        
        # คำนวณระยะร่นไปทางขวาของยอดป้อม ตามความสูง (y1 - y0) คูณด้วยอัตราส่วน
        tilt_shift = int((y1 - y0) * tilt_ratio)
        
        rx = lx + int(body_hw * 1.5)         # ปลายฐานล่าง
        tx_left = lx + tilt_shift            # ยอดป้อมซ้ายสุด (ถูกดันไปทางขวาตามอัตราส่วน)
        tx_right = tx_left + beam_w          # ยอดป้อมขวาสุด (ขนานกับเส้นซ้าย 100%)
        ix = lx + beam_w                     # มุมหักด้านในของฐานล่าง
        
        poly = QPolygon([
            QPoint(lx, y2),        # 1. ฐานซ้ายล่าง
            QPoint(rx, y2),        # 2. ฐานขวาล่าง
            QPoint(rx, y1),        # 3. ฐานขวาบน
            QPoint(ix, y1),        # 4. มุมหักเข้าด้านใน
            QPoint(tx_right, y0),  # 5. ยอดป้อมขวาสุด
            QPoint(tx_left, y0),   # 6. ยอดป้อมซ้ายสุด
            QPoint(lx, y1)         # 7. ฐานซ้ายบน (เส้นตั้งฉาก)
        ])
        painter.drawPolygon(poly)
        return
    
    if unit_family == UNIT_FAMILY_SHIP_BOAT:
        painter.drawLine(int(center_x - half), int(center_y + 2), int(center_x + half), int(center_y + 2))
        painter.drawLine(int(center_x - half + 4), int(center_y + 2), int(center_x - 1), int(center_y - 4))
        painter.drawLine(int(center_x + half - 4), int(center_y + 2), int(center_x + 1), int(center_y - 4))
        painter.drawLine(int(center_x), int(center_y - 4), int(center_x), int(center_y - 9))
        return

    if unit_family == UNIT_FAMILY_SHIP_FRIGATE:
        painter.drawLine(int(center_x - half), int(center_y + 2), int(center_x + half), int(center_y + 2))
        painter.drawLine(int(center_x - half + 2), int(center_y + 2), int(center_x - 3), int(center_y - 6))
        painter.drawLine(int(center_x + half - 3), int(center_y + 2), int(center_x + 3), int(center_y - 5))
        painter.drawLine(int(center_x - 2), int(center_y - 6), int(center_x - 2), int(center_y - 12))
        painter.drawLine(int(center_x + 3), int(center_y - 3), int(center_x + 3), int(center_y - 8))
        return

    if unit_family == UNIT_FAMILY_SHIP_DESTROYER:
        painter.drawLine(int(center_x - half), int(center_y + 2), int(center_x + half), int(center_y + 2))
        painter.drawLine(int(center_x - half + 2), int(center_y + 2), int(center_x - 3), int(center_y - 6))
        painter.drawLine(int(center_x + half - 3), int(center_y + 2), int(center_x + 4), int(center_y - 3))
        painter.drawLine(int(center_x - 2), int(center_y - 6), int(center_x - 2), int(center_y - 12))
        painter.drawLine(int(center_x + 2), int(center_y - 4), int(center_x + 2), int(center_y - 9))
        painter.drawLine(int(center_x - 6), int(center_y - 1), int(center_x - 1), int(center_y - 1))
        return

    if unit_family == UNIT_FAMILY_SHIP_CRUISER:
        painter.drawLine(int(center_x - half), int(center_y + 2), int(center_x + half), int(center_y + 2))
        painter.drawLine(int(center_x - half + 2), int(center_y + 2), int(center_x - 3), int(center_y - 7))
        painter.drawLine(int(center_x + half - 3), int(center_y + 2), int(center_x + 3), int(center_y - 6))
        painter.drawLine(int(center_x - 3), int(center_y - 7), int(center_x - 3), int(center_y - 13))
        painter.drawLine(int(center_x + 1), int(center_y - 6), int(center_x + 1), int(center_y - 11))
        painter.drawLine(int(center_x - 7), int(center_y - 2), int(center_x - 1), int(center_y - 2))
        painter.drawLine(int(center_x + 1), int(center_y - 2), int(center_x + 7), int(center_y - 2))
        return

    if unit_family == UNIT_FAMILY_SHIP_BATTLESHIP:
        painter.drawLine(int(center_x - half), int(center_y + 3), int(center_x + half), int(center_y + 3))
        painter.drawLine(int(center_x - half + 2), int(center_y + 3), int(center_x - 4), int(center_y - 8))
        painter.drawLine(int(center_x + half - 4), int(center_y + 3), int(center_x + 4), int(center_y - 8))
        painter.drawLine(int(center_x - 4), int(center_y - 8), int(center_x - 4), int(center_y - 14))
        painter.drawLine(int(center_x + 2), int(center_y - 8), int(center_x + 2), int(center_y - 13))
        painter.drawLine(int(center_x - 7), int(center_y - 2), int(center_x - 1), int(center_y - 2))
        painter.drawLine(int(center_x + 1), int(center_y - 2), int(center_x + 7), int(center_y - 2))
        return

    if unit_family == UNIT_FAMILY_AIR_HELICOPTER:
        painter.drawEllipse(int(center_x - 5), int(center_y - 3), 10, 6)
        painter.drawLine(int(center_x), int(center_y - 8), int(center_x), int(center_y - 2))
        painter.drawLine(int(center_x - half), int(center_y - 10), int(center_x + half), int(center_y - 10))
        painter.drawLine(int(center_x + 5), int(center_y), int(center_x + half + 4), int(center_y))
        return

    if unit_family == UNIT_FAMILY_AIR_BOMBER:
        painter.drawLine(int(center_x), int(center_y - 10), int(center_x), int(center_y + 8))
        painter.drawLine(int(center_x - half), int(center_y - 1), int(center_x + half), int(center_y - 1))
        painter.drawLine(int(center_x - half + 2), int(center_y + 2), int(center_x - 2), int(center_y + 5))
        painter.drawLine(int(center_x + half - 2), int(center_y + 2), int(center_x + 2), int(center_y + 5))
        return

    if unit_family == UNIT_FAMILY_AIR_ATTACKER:
        painter.drawLine(int(center_x), int(center_y - 10), int(center_x), int(center_y + 8))
        painter.drawLine(int(center_x - half), int(center_y + 1), int(center_x), int(center_y - 4))
        painter.drawLine(int(center_x + half), int(center_y + 1), int(center_x), int(center_y - 4))
        painter.drawLine(int(center_x - 7), int(center_y + 4), int(center_x - 3), int(center_y + 7))
        painter.drawLine(int(center_x + 7), int(center_y + 4), int(center_x + 3), int(center_y + 7))
        return

    if unit_family == UNIT_FAMILY_AIR_FIGHTER:
        painter.drawLine(int(center_x), int(center_y - 10), int(center_x), int(center_y + 8))
        painter.drawLine(int(center_x - half), int(center_y), int(center_x), int(center_y - 6))
        painter.drawLine(int(center_x + half), int(center_y), int(center_x), int(center_y - 6))
        painter.drawLine(int(center_x - 4), int(center_y + 3), int(center_x + 4), int(center_y + 3))
        return

    painter.drawLine(int(center_x), int(center_y - 10), int(center_x), int(center_y + 8))
    painter.drawLine(int(center_x - half), int(center_y), int(center_x), int(center_y - 4))
    painter.drawLine(int(center_x + half), int(center_y), int(center_x), int(center_y - 4))
    painter.drawLine(int(center_x - 4), int(center_y + 4), int(center_x + 4), int(center_y + 4))


def _draw_leadmark_glyph(painter, center_x, center_y, color, outer_radius=8, core_radius=3, pen_width=3):
    painter.setPen(QPen(color, pen_width))
    painter.drawEllipse(int(center_x - outer_radius), int(center_y - outer_radius), int(outer_radius * 2), int(outer_radius * 2))
    painter.setBrush(color)
    painter.drawEllipse(int(center_x - core_radius), int(center_y - core_radius), int(core_radius * 2), int(core_radius * 2))
    painter.setBrush(Qt.NoBrush)


def _blend_ground_lead_x(center_x, solver_x, target_vel_mag, distance_to_target, box_width):
    try:
        center_x = float(center_x)
        solver_x = float(solver_x)
        box_width = max(float(box_width), 1.0)
        vel_mag = max(0.0, float(target_vel_mag))
        dist = max(0.0, float(distance_to_target))

        # Keep close/slow targets near center, but still allow more horizontal lead
        # as motion and distance increase.
        vel_k = max(0.0, min(1.0, vel_mag / 12.0))
        dist_k = max(0.0, min(1.0, dist / 900.0))
        blend_k = max(vel_k * 0.85, dist_k * 0.20)

        blended_x = center_x + ((solver_x - center_x) * blend_k)

        # Cap the visible horizontal offset to a fraction of the target box width.
        max_ratio = 0.08 + (vel_k * 0.12) + (dist_k * 0.06)
        max_offset = box_width * max_ratio
        delta = blended_x - center_x
        if delta > max_offset:
            return center_x + max_offset
        if delta < -max_offset:
            return center_x - max_offset
        return blended_x
    except Exception:
        return solver_x


def _project_target_box_rect(view_matrix, box_data, screen_width, screen_height):
    if not box_data or not view_matrix:
        return None
    pos, bmin, bmax, rot = box_data
    if not pos or not bmin or not bmax or not rot:
        return None

    corners = [
        (bmin[0], bmin[1], bmin[2]), (bmin[0], bmin[1], bmax[2]),
        (bmin[0], bmax[1], bmin[2]), (bmin[0], bmax[1], bmax[2]),
        (bmax[0], bmin[1], bmin[2]), (bmax[0], bmin[1], bmax[2]),
        (bmax[0], bmax[1], bmin[2]), (bmax[0], bmax[1], bmax[2]),
    ]
    pts = []
    for c in corners:
        world_x = pos[0] + (c[0] * rot[0] + c[1] * rot[3] + c[2] * rot[6])
        world_y = pos[1] + (c[0] * rot[1] + c[1] * rot[4] + c[2] * rot[7])
        world_z = pos[2] + (c[0] * rot[2] + c[1] * rot[5] + c[2] * rot[8])
        scr = world_to_screen(view_matrix, world_x, world_y, world_z, screen_width, screen_height)
        if not scr or scr[2] <= 0:
            return None
        pts.append((scr[0], scr[1]))

    return (
        min(p[0] for p in pts),
        min(p[1] for p in pts),
        max(p[0] for p in pts),
        max(p[1] for p in pts),
    )


def _unit_family_debug_label(unit_family):
    labels = {
        UNIT_FAMILY_AIR_FIGHTER: "FG",
        UNIT_FAMILY_AIR_BOMBER: "BM",
        UNIT_FAMILY_AIR_ATTACKER: "AT",
        UNIT_FAMILY_AIR_HELICOPTER: "HC",
        UNIT_FAMILY_GROUND_LIGHT_TANK: "LT",
        UNIT_FAMILY_GROUND_MEDIUM_TANK: "MT",
        UNIT_FAMILY_GROUND_HEAVY_TANK: "HT",
        UNIT_FAMILY_GROUND_TANK_DESTROYER: "TD",
        UNIT_FAMILY_GROUND_SPAA: "AA",
        UNIT_FAMILY_SHIP_BOAT: "BT",
        UNIT_FAMILY_SHIP_FRIGATE: "FF",
        UNIT_FAMILY_SHIP_DESTROYER: "DD",
        UNIT_FAMILY_SHIP_CRUISER: "CA",
        UNIT_FAMILY_SHIP_BATTLESHIP: "BB",
        UNIT_FAMILY_UNKNOWN: "??",
    }
    return labels.get(unit_family, "??")


def _sanitize_debug_text(text, fallback="-"):
    value = (text or "").strip()
    if not value or value.lower() == "none":
        return fallback
    return value


def _screen_int_tuple(*values):
    out = []
    for value in values:
        if not math.isfinite(value):
            return None
        if value < -2147483000 or value > 2147483000:
            return None
        out.append(int(value))
    return tuple(out)

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


def _read_u32_fast(scanner, addr, default=0):
    try:
        raw = scanner.read_mem(addr, 4)
        if not raw or len(raw) < 4:
            return default
        return struct.unpack("<I", raw)[0]
    except Exception:
        return default


def _is_subcaliber_ballistic(speed, caliber, mass=0.0):
    if speed < BALLISTIC_SUBCALIBER_SPEED_MIN:
        return False
    if BALLISTIC_MIN_CALIBER <= caliber <= BALLISTIC_SUBCALIBER_CALIBER_MAX:
        return True
    if BALLISTIC_MIN_CALIBER <= caliber <= BALLISTIC_SUBCALIBER_WIDE_CALIBER_MAX and BALLISTIC_MIN_MASS <= mass <= BALLISTIC_SUBCALIBER_LIGHT_MASS_MAX:
        return True
    return False


def _plausible_ballistic_struct(scanner, base_addr, ref_cx=0.0):
    mass = _read_f32_fast(scanner, base_addr + 0x04, 0.0)
    caliber = _read_f32_fast(scanner, base_addr + 0x08, 0.0)
    cx = _read_f32_fast(scanner, base_addr + 0x0C, 0.0)
    max_distance = _read_f32_fast(scanner, base_addr + 0x10, 0.0)
    vel_min = _read_f32_fast(scanner, base_addr + 0x24, 0.0)
    vel_max = _read_f32_fast(scanner, base_addr + 0x28, 0.0)

    score = 0
    if 0.005 <= mass <= 200.0:
        score += 3
    if 0.001 <= caliber <= 0.5:
        score += 3
    if 0.01 <= cx <= 3.0:
        score += 3
    if 100.0 <= max_distance <= 50000.0:
        score += 2
    if 10.0 <= vel_min <= 4000.0:
        score += 1
    if vel_min <= vel_max <= 4000.0 and vel_max > 10.0:
        score += 1
    if 0.01 <= ref_cx <= 3.0 and 0.01 <= cx <= 3.0 and abs(cx - ref_cx) <= 0.05:
        score += 2

    return score, {
        "mass": mass,
        "caliber": caliber,
        "cx": cx,
        "max_distance": max_distance,
        "vel_range": (vel_min, vel_max),
    }


def _scan_ballistic_profile(scanner, weapon_ptr, fallback_cx=0.0):
    speed = 0.0
    best_speed_delta = None
    for off in range(0x2030, 0x2071, 4):
        value = _read_f32_fast(scanner, weapon_ptr + off, 0.0)
        if not (50.0 <= value <= 3000.0):
            continue
        delta = abs(off - OFF_BULLET_SPEED)
        if best_speed_delta is None or delta < best_speed_delta:
            best_speed_delta = delta
            speed = value

    best_score = -1
    best_candidate = None
    for off in range(0x2040, 0x20A1, 4):
        score, candidate = _plausible_ballistic_struct(scanner, weapon_ptr + off, fallback_cx)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None or best_score < 6:
        return {
            "speed": speed if 50.0 <= speed <= 3000.0 else 0.0,
            "mass": 0.0,
            "caliber": 0.0,
            "cx": fallback_cx if 0.01 <= fallback_cx <= 3.0 else 0.0,
            "max_distance": 0.0,
            "vel_range": (0.0, 0.0),
        }

    best_candidate["speed"] = speed if 50.0 <= speed <= 3000.0 else 0.0
    return best_candidate


def _read_current_bullet_type_index(scanner, weapon_ptr):
    if not is_valid_ptr(weapon_ptr):
        return -1
    raw = scanner.read_mem(weapon_ptr + GUN_CURRENT_BULLET_TYPE_OFF, 1)
    if not raw:
        return -1
    return raw[0]


def _read_slot_vel_range(scanner, weapon_ptr, bullet_type_idx, speed_hint=0.0):
    if not is_valid_ptr(weapon_ptr) or bullet_type_idx < 0:
        return (0.0, 0.0, 0)

    bullet_list_ptr = _read_ptr_fast(scanner, weapon_ptr + GUN_BULLET_LIST_PTR_OFF)
    if not is_valid_ptr(bullet_list_ptr):
        return (0.0, 0.0, 0)

    bullet_type_count = _read_u32_fast(scanner, bullet_list_ptr + GUN_BULLET_LIST_COUNT_OFF, 0)
    if bullet_type_count <= 0 or bullet_type_count > 64 or bullet_type_idx >= bullet_type_count:
        return (0.0, 0.0, 0)

    slot_base = bullet_list_ptr + GUN_BULLET_SLOT_BASE_OFF + (bullet_type_idx * GUN_BULLET_SLOT_STRIDE)
    best_score = -1
    best_pair = (0.0, 0.0, 0)

    for off in range(0, GUN_BULLET_SLOT_STRIDE - 7, 4):
        lo = _read_f32_fast(scanner, slot_base + off, 0.0)
        hi = _read_f32_fast(scanner, slot_base + off + 4, 0.0)
        if not (BALLISTIC_MIN_VEL_RANGE <= lo <= BALLISTIC_MAX_VEL_RANGE):
            continue
        if not (lo <= hi <= BALLISTIC_MAX_VEL_RANGE):
            continue
        if hi <= 0.0:
            continue

        score = 0
        if hi > lo:
            score += 2
        spread = hi - lo
        if 20.0 <= spread <= 2500.0:
            score += 1
        if speed_hint > 0.0:
            if 0.10 * speed_hint <= lo <= 1.05 * speed_hint:
                score += 1
            if 0.20 * speed_hint <= hi <= 1.05 * speed_hint:
                score += 2
            if lo <= speed_hint <= hi:
                score += 1
        if off == 0x24:
            score += 3

        if score > best_score:
            best_score = score
            best_pair = (lo, hi, slot_base + off)

    if best_score < 3:
        return (0.0, 0.0, 0)
    return best_pair


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
        "bullet_type_idx": -1,
        "model_enum": 0,
        "bullet_type_idx": -1,
        "speed": 1000.0,
        "mass": 0.0,
        "caliber": 0.0,
        "cx": 0.0,
        "max_distance": 0.0,
        "vel_range": (0.0, 0.0),
        "vel_range_addr": 0,
        "drag_valid": False,
    }
    weapon_ptr = _read_ptr_fast(scanner, cgame_base + OFF_WEAPON_PTR)
    if not is_valid_ptr(weapon_ptr):
        return profile

    props_base = weapon_ptr + BALLISTIC_STRUCT_BASE_OFF
    model_enum = _read_u32_fast(scanner, props_base + 0x00, 0)
    speed = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_SPEED_OFF, 1000.0)
    mass = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_MASS_OFF, 0.0)
    caliber = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_CALIBER_OFF, 0.0)
    cx = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_CX_OFF, 0.0)
    max_distance = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_MAX_DISTANCE_OFF, 0.0)
    vel_min = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_VEL_RANGE_X_OFF, 0.0)
    vel_max = _read_f32_fast(scanner, weapon_ptr + BALLISTIC_VEL_RANGE_Y_OFF, 0.0)
    props_mass = _read_f32_fast(scanner, props_base + 0x04, 0.0)
    props_caliber = _read_f32_fast(scanner, props_base + 0x08, 0.0)
    props_cx = _read_f32_fast(scanner, props_base + 0x0C, 0.0)
    props_max_distance = _read_f32_fast(scanner, props_base + 0x10, 0.0)
    bullet_type_idx = _read_current_bullet_type_index(scanner, weapon_ptr)
    if 0.005 <= props_mass <= 200.0 and not (0.005 <= mass <= 200.0):
        mass = props_mass
    if 0.001 <= props_caliber <= 0.5 and not (0.001 <= caliber <= 0.5):
        caliber = props_caliber
    if 0.01 <= props_cx <= 3.0 and not (0.01 <= cx <= 3.0):
        cx = props_cx
    if 100.0 <= props_max_distance <= 50000.0 and not (100.0 <= max_distance <= 50000.0):
        max_distance = props_max_distance

    slot_vel_min, slot_vel_max, slot_vel_addr = _read_slot_vel_range(scanner, weapon_ptr, bullet_type_idx, speed)
    generic_mem_vel = (
        abs(vel_min - 500.0) <= 0.5 and
        abs(vel_max - 700.0) <= 0.5
    )
    slot_vel_valid = (
        BALLISTIC_MIN_VEL_RANGE <= slot_vel_min <= BALLISTIC_MAX_VEL_RANGE and
        slot_vel_min <= slot_vel_max <= BALLISTIC_MAX_VEL_RANGE and
        slot_vel_max > slot_vel_min
    )
    if slot_vel_valid and (generic_mem_vel or vel_max <= vel_min):
        vel_min, vel_max = slot_vel_min, slot_vel_max

    needs_scan = (
        not (BALLISTIC_MIN_SPEED <= speed <= BALLISTIC_MAX_SPEED) or
        not (BALLISTIC_MIN_MASS <= mass <= BALLISTIC_MAX_MASS) or
        not (BALLISTIC_MIN_CALIBER <= caliber <= BALLISTIC_MAX_CALIBER) or
        not (BALLISTIC_MIN_DISTANCE <= max_distance <= BALLISTIC_MAX_DISTANCE)
    )
    if needs_scan:
        scanned = _scan_ballistic_profile(scanner, weapon_ptr, cx)
        if not (BALLISTIC_MIN_SPEED <= speed <= BALLISTIC_MAX_SPEED) and BALLISTIC_MIN_SPEED <= scanned["speed"] <= BALLISTIC_MAX_SPEED:
            speed = scanned["speed"]
        if not (BALLISTIC_MIN_MASS <= mass <= BALLISTIC_MAX_MASS) and BALLISTIC_MIN_MASS <= scanned["mass"] <= BALLISTIC_MAX_MASS:
            mass = scanned["mass"]
        if not (BALLISTIC_MIN_CALIBER <= caliber <= BALLISTIC_MAX_CALIBER) and BALLISTIC_MIN_CALIBER <= scanned["caliber"] <= BALLISTIC_MAX_CALIBER:
            caliber = scanned["caliber"]
        if not (BALLISTIC_MIN_CX <= cx <= BALLISTIC_MAX_CX) and BALLISTIC_MIN_CX <= scanned["cx"] <= BALLISTIC_MAX_CX:
            cx = scanned["cx"]
        if not (BALLISTIC_MIN_DISTANCE <= max_distance <= BALLISTIC_MAX_DISTANCE) and BALLISTIC_MIN_DISTANCE <= scanned["max_distance"] <= BALLISTIC_MAX_DISTANCE:
            max_distance = scanned["max_distance"]
        scan_vel_min, scan_vel_max = scanned["vel_range"]
        if not (BALLISTIC_MIN_VEL_RANGE <= vel_min <= BALLISTIC_MAX_VEL_RANGE) and BALLISTIC_MIN_VEL_RANGE <= scan_vel_min <= BALLISTIC_MAX_VEL_RANGE:
            vel_min = scan_vel_min
        if not (vel_min <= vel_max <= BALLISTIC_MAX_VEL_RANGE) and BALLISTIC_MIN_VEL_RANGE <= scan_vel_max <= BALLISTIC_MAX_VEL_RANGE:
            vel_max = scan_vel_max

    if not (BALLISTIC_MIN_SPEED <= speed <= BALLISTIC_MAX_SPEED):
        speed = 1000.0
    if not (BALLISTIC_MIN_MASS <= mass <= BALLISTIC_MAX_MASS):
        mass = 0.0
    if not (BALLISTIC_MIN_CALIBER <= caliber <= BALLISTIC_MAX_CALIBER):
        caliber = 0.0
    if not (BALLISTIC_MIN_CX <= cx <= BALLISTIC_MAX_CX):
        cx = 0.0
    if vel_min < BALLISTIC_MIN_VEL_RANGE or vel_min > BALLISTIC_MAX_VEL_RANGE:
        vel_min = 0.0
    if vel_max < vel_min or vel_max > BALLISTIC_MAX_VEL_RANGE:
        vel_max = max(vel_min, 0.0)
    if vel_max <= vel_min:
        vel_min = 0.0
        vel_max = 0.0

    profile.update({
        "weapon_ptr": weapon_ptr,
        "bullet_type_idx": bullet_type_idx,
        "model_enum": model_enum,
        "bullet_type_idx": bullet_type_idx,
        "speed": speed,
        "mass": mass,
        "caliber": caliber,
        "cx": cx,
        "max_distance": max_distance,
        "vel_range": (vel_min, vel_max),
        "vel_range_addr": slot_vel_addr,
        "drag_valid": (
            BALLISTIC_MIN_CX <= cx <= BALLISTIC_MAX_CX_FOR_DRAG and
            BALLISTIC_MIN_MASS <= mass <= BALLISTIC_MAX_MASS and
            BALLISTIC_MIN_CALIBER <= caliber <= BALLISTIC_MAX_CALIBER
        ),
    })
    return profile


def _make_ballistic_model(profile, altitude):
    speed = max(profile.get("speed", 1000.0), 1.0)
    drag_valid = bool(profile.get("drag_valid", False))
    model_enum = int(profile.get("model_enum", 0) or 0)
    raw_mass = profile.get("mass", 0.0)
    raw_caliber = profile.get("caliber", 0.0)
    mass = max(raw_mass, 0.001)
    caliber = max(profile.get("caliber", 0.0), 0.001)
    is_subcaliber = _is_subcaliber_ballistic(speed, caliber, raw_mass)
    cx = profile.get("cx", 0.0)
    if cx <= 0.0:
        cx = BALLISTIC_SUBCALIBER_CX_CLAMP if is_subcaliber else (BALLISTIC_FAST_ROUND_CX_FALLBACK if speed >= BALLISTIC_SUBCALIBER_SPEED_MIN else BALLISTIC_FULLCAL_CX_FALLBACK)
    elif cx > BALLISTIC_MAX_CX_FOR_DRAG:
        # Builds with partially wrong props can expose explosive/splinter fields as drag.
        cx = BALLISTIC_SUBCALIBER_CX_CLAMP if is_subcaliber else (BALLISTIC_FAST_ROUND_CX_FALLBACK if speed >= BALLISTIC_SUBCALIBER_SPEED_MIN else BALLISTIC_FULLCAL_CX_FALLBACK)
    elif is_subcaliber:
        # APFSDS-like rounds need a much lighter effective drag curve than full-caliber shells.
        cx = min(cx, BALLISTIC_SUBCALIBER_CX_CLAMP)

    rho = _air_density_from_altitude(altitude)
    area = math.pi * ((caliber * 0.5) ** 2)
    drag_k = (cx * area) / mass if drag_valid else 0.0
    base_k = 0.5 * rho * drag_k if drag_valid else 0.0
    vel_lo, vel_hi = profile.get("vel_range", (0.0, 0.0))

    return {
        "model_enum": model_enum,
        "speed": speed,
        "mass": raw_mass,
        "caliber": raw_caliber,
        "cx": cx,
        "rho": rho,
        "drag_k": max(drag_k, 0.0),
        "base_k": max(base_k, 0.0),
        "vel_lo": max(0.0, vel_lo),
        "vel_hi": max(max(vel_lo, vel_hi), vel_lo + 1.0),
        "max_distance": max(profile.get("max_distance", 0.0), 0.0),
        "drag_valid": drag_valid,
        "is_subcaliber": is_subcaliber,
    }


def _get_leadmark_range_limit(profile):
    max_distance = max(profile.get("max_distance", 0.0), 0.0)
    if max_distance <= 1.0:
        return 0.0
    return max_distance * LEADMARK_RANGE_LIMIT_RATIO


def _get_leadmark_tof_limit(is_air_target):
    if not is_air_target:
        return 0.0
    return max(0.0, float(MAX_TOF_AIR_LEADMARK or 0.0))


def _drag_band_factor(model, speed):
    if BALLISTIC_MODEL0_USE_DIRECT_DRAG_K and model.get("model_enum", 0) in (0, 4) and model.get("drag_k", 0.0) > 0.0:
        factor = BALLISTIC_MODEL0_DIRECT_FACTOR
        if model.get("is_subcaliber", False):
            speed_bias = max(0.0, model.get("speed", 0.0) - BALLISTIC_MODEL0_SUBCAL_SPEED_REF)
            caliber_bias = max(0.0, model.get("caliber", 0.0) - BALLISTIC_MODEL0_SUBCAL_CALIBER_REF)
            factor *= (
                1.0 +
                (speed_bias * BALLISTIC_MODEL0_SUBCAL_SPEED_GAIN) +
                (caliber_bias * BALLISTIC_MODEL0_SUBCAL_CALIBER_GAIN)
            )
            factor = max(BALLISTIC_MODEL0_SUBCAL_MIN, min(BALLISTIC_MODEL0_SUBCAL_MAX, factor))
        return factor
    vel_lo = model["vel_lo"]
    vel_hi = model["vel_hi"]
    if vel_hi <= vel_lo or vel_hi <= 0.0:
        band = DRAG_BAND_DEFAULT
    else:
        band = _smoothstep(vel_lo, vel_hi, speed)
    mach = speed / 343.0
    transonic = _smoothstep(DRAG_BAND_TRANSONIC_MIN, DRAG_BAND_TRANSONIC_MAX, mach)
    supersonic = _smoothstep(DRAG_BAND_SUPERSONIC_MIN, DRAG_BAND_SUPERSONIC_MAX, mach)
    factor = (
        DRAG_FACTOR_BASE +
        (DRAG_FACTOR_BAND_WEIGHT * band) +
        (DRAG_FACTOR_TRANSONIC_WEIGHT * transonic) +
        (DRAG_FACTOR_SUPERSONIC_WEIGHT * supersonic)
    )
    if model["speed"] >= BALLISTIC_SUBCALIBER_SPEED_MIN:
        factor *= DRAG_FACTOR_FAST_ROUND_MULT
    return max(DRAG_FACTOR_MIN, min(DRAG_FACTOR_MAX, factor))


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

    while x < horizontal_range and t < PROJECTILE_SIM_MAX_TIME:
        speed_mag = math.hypot(vx, vy)
        if speed_mag < PROJECTILE_SIM_MIN_SPEED:
            break

        dt = max(PROJECTILE_SIM_DT_MIN, min(PROJECTILE_SIM_DT_MAX, PROJECTILE_SIM_DT_SCALE / (speed_mag + 1.0)))
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
    for _ in range(ZERO_PITCH_MAX_ITERS):
        _, y_down, _ = _simulate_projectile_range(zeroing_distance, model, pitch)
        pitch += math.atan2(y_down, max(zeroing_distance, 1.0)) * ZERO_PITCH_GAIN
    return max(ZERO_PITCH_MIN, min(ZERO_PITCH_MAX, pitch))


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
        self.live_velocity_debug = None
        self.last_cgame_base = 0
        
        # 🤖 AI Auto-Calibration for Maneuvers (6 Threads)
        self.ai_ghost_queue = []
        self.dynamic_decay = 0.15

        # 📷 เริ่มระบบแคปหน้าจอความเร็วสูง
        self.sct = mss.mss() 
        
        self.target_cycle_index = 0
        self.q_pressed_last = False
        self.last_debug_log_time = 0.0
        self.console_initialized = False
        self.dead_unit_latch = {}
        self.air_alert_seen = {}
        self.last_air_alert_sound_at = 0.0
        self.alert_players = {}
        self.alert_processes = {}
        self.ballistic_zero_cache = {}
        self.invalid_runtime_frames = 0
        self.my_unit_spawn_grace_until = 0.0
        self.shutdown_requested = False
        self.startup_time = time.time()
        self.calibration_offset = [0.0, 0.0]
        self.vertical_correction = 0.0
        self.camera_parallax = -4.5  # 🎯 NEW: ค่าแรงเหวี่ยงกล้องเริ่มต้น (T-80U-E1)
        self.calibration_last_keys = {
            "enter": False,
            "backspace": False,
        }
        self.compare_visibility_modes = ["base", "fallback", "dynamic"]
        self.compare_visibility_index = 0
        self.compare_show_all = False
        self.compare_enabled = True
        self.compare_last_keys = {
            "up": False,
            "down": False,
            "left": False,
            "right": False,
        }

        self._update_screen_metrics()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.StrongFocus) # 🎯 บังคับให้หน้าต่างรับการกดปุ่มได้
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, self.screen_width, self.screen_height)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(12)


        

    def _fatal_shutdown(self, reason, detail=""):
        if self.shutdown_requested:
            return
        self.shutdown_requested = True

        print("\n" + "=" * 72)
        print("❌ OVERLAY AUTO-SHUTDOWN")
        print("=" * 72)
        print(f"Reason : {reason}")
        if detail:
            print(detail)
        print(f"PID    : {getattr(self.scanner, 'pid', 0)}")
        print(f"CGame  : {hex(self.last_cgame_base) if self.last_cgame_base else '0x0'}")
        print(
            "Offsets: "
            f"UNIT_X={hex(OFF_UNIT_X)} "
            f"INFO={hex(OFF_UNIT_INFO)} "
            f"TEAM={hex(OFF_UNIT_TEAM)} "
            f"STATE={hex(OFF_UNIT_STATE)} "
            f"CAM={hex(OFF_CAMERA_PTR)} "
            f"VM={hex(OFF_VIEW_MATRIX)}"
        )
        print("=" * 72)

        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.scanner.close()
        except Exception:
            pass
        try:
            for proc in self.alert_processes.values():
                if proc and proc.poll() is None:
                    proc.kill()
        except Exception:
            pass
        try:
            self.close()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _play_alert_sound(self, sound_key, sound_path, curr_t):
        if not ALERT_AUDIO_ON:
            return
        if not sound_path or not os.path.isfile(sound_path):
            return
        if (curr_t - self.last_air_alert_sound_at) < AIR_ALERT_SOUND_COOLDOWN:
            return
        volume = _get_alert_audio_volume()
        if ALERT_AUDIO_BACKEND == "system":
            backends = ("system",)
        elif ALERT_AUDIO_BACKEND == "qt":
            backends = ("qt",)
        else:
            backends = ("system", "qt")

        for backend in backends:
            if backend == "system":
                try:
                    prev = self.alert_processes.get(sound_key)
                    if prev and prev.poll() is None:
                        prev.kill()
                    env, run_as_user = _get_desktop_audio_env()
                    sink_name = _get_default_pulse_sink_name()
                    if sink_name:
                        env["PULSE_SINK"] = sink_name

                    command_variants = []
                    ffplay = shutil.which("ffplay")
                    if ffplay:
                        command_variants.append([ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(volume), sound_path])
                    mpv = shutil.which("mpv")
                    if mpv:
                        command_variants.append([mpv, "--no-video", "--really-quiet", f"--volume={volume}", sound_path])
                    gst_play = shutil.which("gst-play-1.0")
                    if gst_play:
                        command_variants.append([gst_play, sound_path])

                    for base_cmd in command_variants:
                        cmd = list(base_cmd)
                        if run_as_user:
                            sudo_cmd = [
                                "sudo",
                                "--preserve-env=HOME,XDG_RUNTIME_DIR,PULSE_SINK",
                                "-u",
                                run_as_user,
                                "--",
                                "env",
                                f"HOME={env.get('HOME', '')}",
                                f"XDG_RUNTIME_DIR={env.get('XDG_RUNTIME_DIR', '')}",
                            ]
                            if env.get("PULSE_SINK"):
                                sudo_cmd.append(f"PULSE_SINK={env['PULSE_SINK']}")
                            cmd = sudo_cmd + cmd
                        proc = subprocess.Popen(
                            cmd,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                            close_fds=True,
                            env=env,
                        )
                        self.alert_processes[sound_key] = proc
                        self.last_air_alert_sound_at = curr_t
                        return
                except Exception:
                    continue

            if backend == "qt":
                if not HAS_QT_MULTIMEDIA:
                    continue
                player = self.alert_players.get(sound_key)
                if player is None:
                    try:
                        player = QMediaPlayer(self)
                        player.setVolume(volume)
                        player.setMedia(QMediaContent(QUrl.fromLocalFile(sound_path)))
                        self.alert_players[sound_key] = player
                    except Exception:
                        continue
                try:
                    player.setVolume(volume)
                    player.stop()
                    player.setPosition(0)
                    player.play()
                    self.last_air_alert_sound_at = curr_t
                    return
                except Exception:
                    continue

    def _maybe_alert_for_air_target(self, u_ptr, unit_family, curr_t):
        if unit_family == UNIT_FAMILY_AIR_HELICOPTER:
            sound_key = "helo"
            sound_path = ALERT_SOUND_HELO
        elif unit_family in (
            UNIT_FAMILY_AIR_FIGHTER,
            UNIT_FAMILY_AIR_BOMBER,
            UNIT_FAMILY_AIR_ATTACKER,
        ):
            sound_key = "aircraft"
            sound_path = ALERT_SOUND_AIRCRAFT
        else:
            return
        if u_ptr in self.air_alert_seen:
            return
        self.air_alert_seen[u_ptr] = curr_t
        self._play_alert_sound(sound_key, sound_path, curr_t)

    def _update_screen_metrics(self):
        # screen = self.screen() or QApplication.primaryScreen()
        # geometry = screen.geometry() if screen is not None else QApplication.desktop().screenGeometry()
        self.screen_width = 2560
        self.screen_height = 1440
        self.center_x = self.screen_width / 2
        self.center_y = self.screen_height / 2

    def _keyboard_down(self, key):
        if not HAS_KEYBOARD:
            return False
        try:
            # 🎯 ใช้ keyboard.is_pressed ตรงๆ เพราะทำงานระดับ Global ไม่ต้องมี Focus
            return keyboard.is_pressed(key)
        except Exception:
            return False

    def _save_calibration_sample(self, sample):
        try:
            os.makedirs("dumps", exist_ok=True)
            with open(CALIBRATION_SAVE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            print(f"[CALIB] saved -> {CALIBRATION_SAVE_PATH}")
        except Exception as e:
            print(f"[CALIB] save failed: {e}")

    def _handle_compare_visibility_toggle(self):
        if not DEBUG_COMPARE_DYNAMIC_GEOMETRY:
            self.compare_last_keys["up"] = False
            self.compare_last_keys["down"] = False
            self.compare_last_keys["left"] = False
            self.compare_last_keys["right"] = False
            return False

        up_now = self._keyboard_down("up")
        down_now = self._keyboard_down("down")
        left_now = self._keyboard_down("left")
        right_now = self._keyboard_down("right")
        changed = False

        if up_now and not self.compare_last_keys.get("up", False):
            self.compare_show_all = True
            self.compare_enabled = True
            changed = True
        elif down_now and not self.compare_last_keys.get("down", False):
            self.compare_show_all = False
            self.compare_enabled = False
            changed = True
        elif left_now and not self.compare_last_keys.get("left", False):
            self.compare_show_all = False
            self.compare_enabled = True
            self.compare_visibility_index = (self.compare_visibility_index - 1) % len(self.compare_visibility_modes)
            changed = True
        elif right_now and not self.compare_last_keys.get("right", False):
            self.compare_show_all = False
            self.compare_enabled = True
            self.compare_visibility_index = (self.compare_visibility_index + 1) % len(self.compare_visibility_modes)
            changed = True

        self.compare_last_keys["up"] = up_now
        self.compare_last_keys["down"] = down_now
        self.compare_last_keys["left"] = left_now
        self.compare_last_keys["right"] = right_now
        return changed

    def _get_compare_visibility_mode(self):
        if not self.compare_enabled:
            return "off"
        if self.compare_show_all:
            return "all"
        return self.compare_visibility_modes[self.compare_visibility_index]

    def _handle_hitpoint_calibration(self, context):
        if not DEBUG_DRAW_CALIBRATION_HIT or not context:
            return None

        enter_now = self._keyboard_down("enter")
        backspace_now = self._keyboard_down("backspace")
        ctrl_now = self._keyboard_down("ctrl") or self._keyboard_down("left ctrl") or self._keyboard_down("right ctrl")
        shift_now = self._keyboard_down("shift") or self._keyboard_down("left shift") or self._keyboard_down("right shift")
        
        if backspace_now and not self.calibration_last_keys.get("backspace", False):
            self.calibration_offset = [0.0, 0.0]
            self.vertical_correction = 0.0
            
        self.calibration_last_keys["backspace"] = backspace_now

        if not enter_now:
                step = 0.1
                compare_controls_active = DEBUG_COMPARE_DYNAMIC_GEOMETRY
                if ctrl_now and not LOCK_CAMERA_PARALLAX:
                    parallax_step = 0.1
                    if (not compare_controls_active) and self._keyboard_down("left"):
                        self.camera_parallax -= parallax_step
                    elif (not compare_controls_active) and self._keyboard_down("right"):
                        self.camera_parallax += parallax_step

                # 🎯 ลูกศรเพียวๆ = ปรับจุดอ่อน (Weakspot) ซ้าย/ขวา/บน/ล่าง
                if (not compare_controls_active) and self._keyboard_down("left"):
                    if not ctrl_now:
                        self.calibration_offset[0] -= step
                elif (not compare_controls_active) and self._keyboard_down("right"):
                    if not ctrl_now:
                        self.calibration_offset[0] += step

                if (not compare_controls_active) and self._keyboard_down("up"):
                    self.vertical_correction -= step
                elif (not compare_controls_active) and self._keyboard_down("down"):
                    self.vertical_correction += step

        calib_x = context["base_hitpoint"][0]
        calib_y = context["base_hitpoint"][1]

        if enter_now and not self.calibration_last_keys.get("enter", False):
            auto_vertical_baseline = float(context.get("auto_vertical_baseline", 0.0) or 0.0)
            sample = {
                "captured_at": time.time(),
                "target_unit_ptr": context.get("target_unit_ptr", context.get("unit_ptr", 0)),
                "target_unit_key": context.get("target_unit_key", context.get("unit_key", "")),
                "my_unit_ptr": context.get("my_unit_ptr", 0),
                "my_unit_key": context.get("my_unit_key", ""),
                "my_vehicle_name": context.get("my_vehicle_name", ""),
                # Backward-compat aliases for old parsers
                "unit_ptr": context.get("target_unit_ptr", context.get("unit_ptr", 0)),
                "unit_key": context.get("target_unit_key", context.get("unit_key", "")),
                "distance": context.get("distance", 0.0),
                "model_enum": context.get("model_enum", 0),
                "speed": context.get("speed", 0.0),
                "mass": context.get("mass", 0.0),
                "caliber": context.get("caliber", 0.0),
                "bullet_type_idx": context.get("bullet_type_idx", -1),
                "camera_parallax": round(self.camera_parallax, 3),
                "ammo_bucket": resolve_ammo_family(context).get("bucket", "other"),
                "ammo_family": resolve_ammo_family(context).get("family", "other"),
                "auto_vertical_baseline": round(auto_vertical_baseline, 3),
                "vertical_correction": round(self.vertical_correction, 3),
                "effective_vertical_correction": round(auto_vertical_baseline + self.vertical_correction, 3),
                "calibration_offset": [round(self.calibration_offset[0], 3), round(self.vertical_correction, 3)],
            }
            self._save_calibration_sample(sample)

        self.calibration_last_keys["enter"] = enter_now

        return (calib_x, calib_y)

    def _stabilize_velocity(self, u_ptr, is_air, pos, curr_t):
        if u_ptr and pos:
            raw_vel = get_air_velocity(self.scanner, u_ptr) if is_air else get_ground_velocity(self.scanner, u_ptr)
        else:
            raw_vel = (0.0, 0.0, 0.0)
        cached = self.velocity_cache.get(u_ptr)
        prev_meta = self.last_velocity_meta.get(u_ptr, {})
        pos_vel = None

        if cached and pos:
            dt = curr_t - cached['time']
            min_dt = 0.005 if is_air else 0.008
            max_dt = 0.75 if is_air else 0.60
            if min_dt <= dt <= max_dt:
                dx = pos[0] - cached['pos'][0]
                dy = pos[1] - cached['pos'][1]
                dz = pos[2] - cached['pos'][2]
                pos_vel = (dx / dt, dy / dt, dz / dt)
                if not is_air:
                    prev_pos_filtered = prev_meta.get("pos_vel_filtered")
                    planar_pos_vel = (pos_vel[0], 0.0, pos_vel[2])
                    if prev_pos_filtered and len(prev_pos_filtered) == 3:
                        pos_vel = (
                            (prev_pos_filtered[0] * 0.82) + (planar_pos_vel[0] * 0.18),
                            0.0,
                            (prev_pos_filtered[2] * 0.82) + (planar_pos_vel[2] * 0.18),
                        )
                    else:
                        pos_vel = planar_pos_vel

        chosen_vel = raw_vel
        source = "raw"

        if is_air:
            raw_mag = math.sqrt(raw_vel[0]**2 + raw_vel[1]**2 + raw_vel[2]**2)
            pos_mag = math.sqrt(pos_vel[0]**2 + pos_vel[1]**2 + pos_vel[2]**2) if pos_vel else 0.0
        else:
            # Ground lead should react to planar movement only. Suspension / axis-layout noise on Y
            # was leaking into source selection, then getting zeroed afterwards, which caused flapping.
            raw_mag = math.hypot(raw_vel[0], raw_vel[2])
            pos_mag = math.hypot(pos_vel[0], pos_vel[2]) if pos_vel else 0.0
        max_jump = 90.0 if is_air else 12.0
        min_air_speed = 35.0 if is_air else 0.0

        if pos_vel:
            if is_air:
                diff_mag = math.sqrt(
                    (raw_vel[0] - pos_vel[0])**2 +
                    (raw_vel[1] - pos_vel[1])**2 +
                    (raw_vel[2] - pos_vel[2])**2
                )
                raw_nonzero_axes = sum(1 for v in raw_vel if abs(v) > 0.05)
                pos_nonzero_axes = sum(1 for v in pos_vel if abs(v) > 0.05)
            else:
                diff_mag = math.hypot(raw_vel[0] - pos_vel[0], raw_vel[2] - pos_vel[2])
                raw_nonzero_axes = sum(1 for v in (raw_vel[0], raw_vel[2]) if abs(v) > 0.05)
                pos_nonzero_axes = sum(1 for v in (pos_vel[0], pos_vel[2]) if abs(v) > 0.05)

            if raw_mag <= 0.001 and pos_mag > 0.001:
                chosen_vel = pos_vel
                source = "pos_only"
            elif (not is_air) and pos_mag > 0.5 and (
                abs(raw_mag - pos_mag) <= max(3.0, pos_mag * 0.45)
                or raw_nonzero_axes <= 1
            ):
                # Ground raw movement often behaves like a local forward-speed field.
                # Once we have enough position history, prefer world-space velocity.
                chosen_vel = pos_vel
                source = "pos_ground_world"
            elif (not is_air) and raw_nonzero_axes <= 1 and pos_nonzero_axes >= 1 and pos_mag > 0.5:
                chosen_vel = pos_vel
                source = "pos_ground_axis_fix"
            elif pos_mag > 0.001 and diff_mag > max_jump:
                chosen_vel = pos_vel
                source = "pos_reject_raw"
            elif is_air and raw_mag < min_air_speed and pos_mag >= min_air_speed:
                chosen_vel = pos_vel
                source = "pos_air_floor"
            elif raw_mag > 0.001 and pos_mag > 0.05:
                chosen_vel = (
                    (raw_vel[0] * 0.65) + (pos_vel[0] * 0.35),
                    (raw_vel[1] * 0.65) + (pos_vel[1] * 0.35),
                    (raw_vel[2] * 0.65) + (pos_vel[2] * 0.35),
                )
                source = "blended"

        if not is_air:
            prev_vel = cached.get('vel') if cached else None
            prev_source = prev_meta.get("source", "")

            if prev_vel and pos_vel and pos_mag > 0.5 and source in ("raw", "blended"):
                prev_planar = math.hypot(prev_vel[0], prev_vel[2])
                chosen_delta = math.hypot(chosen_vel[0] - prev_vel[0], chosen_vel[2] - prev_vel[2])
                pos_delta = math.hypot(pos_vel[0] - prev_vel[0], pos_vel[2] - prev_vel[2])
                if prev_source.startswith("pos_") and prev_planar > 0.1 and pos_delta <= (chosen_delta + 0.75):
                    chosen_vel = pos_vel
                    source = "pos_ground_sticky"

            # Ground units often have tiny noisy vectors around zero.
            idle_speed_enter = 0.22  # m/s (~0.8 km/h)
            idle_speed_exit = 0.38
            prev_motion_state = prev_meta.get("ground_motion_state", "")
            idle_speed = idle_speed_exit if prev_motion_state == "idle" else idle_speed_enter
            chosen_planar_mag = math.hypot(chosen_vel[0], chosen_vel[2])
            can_enter_idle = (
                raw_mag <= idle_speed_enter
                and (pos_vel is None or pos_mag <= idle_speed_enter)
                and chosen_planar_mag <= idle_speed_enter
            )
            can_stay_idle = (
                raw_mag <= idle_speed_exit
                and (pos_vel is None or pos_mag <= idle_speed_exit)
                and chosen_planar_mag <= idle_speed_exit
            )
            if can_enter_idle or (prev_motion_state == "idle" and can_stay_idle):
                chosen_vel = (0.0, 0.0, 0.0)
                source = "ground_idle"
            else:
                # Ground lead solver should not react to suspension / axis-layout noise as vertical motion.
                chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
            chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)

            # Ground world velocity is derived from noisy local raw fields + short-frame position deltas.
            # Smooth the final vector to prevent source flapping and visible jitter on moving vehicles.
            if prev_vel and len(prev_vel) == 3 and source != "ground_idle":
                prev_mag = math.sqrt(prev_vel[0]**2 + prev_vel[1]**2 + prev_vel[2]**2)
                if prev_mag > 0.0 or raw_mag > idle_speed_exit or pos_mag > idle_speed_exit:
                    smoothing = 0.84 if source.startswith("pos_") else 0.72
                    chosen_vel = tuple(
                        (prev_vel[i] * smoothing) + (chosen_vel[i] * (1.0 - smoothing))
                        for i in range(3)
                    )
                    chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
                    chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)
                    source = f"{source}_smoothed"

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
            'pos_vel_filtered': pos_vel if (pos_vel and not is_air) else None,
            'pos_mag': pos_mag,
            'chosen_vel': chosen_vel,
            'ground_motion_state': (
                "idle"
                if ((not is_air) and source == "ground_idle")
                else ("move" if not is_air else "")
            ),
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
        if self.shutdown_requested:
            return
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
        self._handle_compare_visibility_toggle()
        lead_marks_to_draw = []
        hit_points_to_draw = []
        debug_muzzle_rays_to_draw = []
        debug_box_entry_hits_to_draw = []
        debug_virtual_boxes_to_draw = []
        calibration_hit_points_to_draw = []
        dynamic_compare_points_to_draw = []
        dynamic_compare_debug = None
        self.live_velocity_debug = None
        
        active_flight_data = None 
        active_target_ptr = 0
        
        try:
            if not self.scanner.is_alive():
                self._fatal_shutdown(
                    "game_process_closed_or_memory_unavailable",
                    f"Scanner error: {getattr(self.scanner, 'last_error', 'unknown')}",
                )
                return

            in_startup_grace = (curr_t - self.startup_time) < STARTUP_LOADING_GRACE_SECONDS

            painter.setFont(QFont("Arial", 12, QFont.Bold))
            cgame_base = get_cgame_base(self.scanner, self.base_address)
            
            # 🐞 แทรก Debug: เช็ค CGame
            if cgame_base == 0: 
                dprint("CGame Base is 0! ข้ามการวาดรูป", force=False)
                if in_startup_grace:
                    return
                self.invalid_runtime_frames += 1
                if self.invalid_runtime_frames >= INVALID_RUNTIME_FRAME_LIMIT:
                    self._fatal_shutdown(
                        "invalid_runtime_state_cgame_base_zero",
                        (
                            f"CGame stayed 0 for {self.invalid_runtime_frames} frames.\n"
                            f"BaseAddr={hex(self.base_address)} "
                            f"ManagerOff={hex(MANAGER_OFFSET)} "
                            f"ScannerErr={getattr(self.scanner, 'last_error', '')}"
                        ),
                    )
                return

            if cgame_base != self.last_cgame_base:
                reset_runtime_caches(clear_view=True)
                self.last_cgame_base = cgame_base
                
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            
            # 🐞 แทรก Debug: เช็ค View Matrix
            if not view_matrix: 
                dprint("อ่าน View Matrix ไม่ได้! ข้ามการวาดรูป", force=False)
                if in_startup_grace:
                    return
                self.invalid_runtime_frames += 1
                if self.invalid_runtime_frames >= INVALID_RUNTIME_FRAME_LIMIT:
                    self._fatal_shutdown(
                        "invalid_runtime_state_view_matrix_unreadable",
                        (
                            f"View matrix unreadable for {self.invalid_runtime_frames} frames.\n"
                            f"CGame={hex(cgame_base)} CAM={hex(OFF_CAMERA_PTR)} VM={hex(OFF_VIEW_MATRIX)} "
                            f"ScannerErr={getattr(self.scanner, 'last_error', '')}"
                        ),
                    )
                return
            self.invalid_runtime_frames = 0

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
                self.dead_unit_latch = {
                    ptr: meta
                    for ptr, meta in self.dead_unit_latch.items()
                    if ptr in all_unit_ptrs
                }

            my_unit, my_team = get_local_team(self.scanner, self.base_address)
            my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None

            if my_unit != self.last_my_unit:
                reset_runtime_caches(clear_view=True)
                if hasattr(self.scanner, "bone_cache"): self.scanner.bone_cache = {}
                self.max_reload_cache = {}
                self.vel_window = {}
                self.velocity_cache = {}
                self.last_velocity_meta = {}
                self.ai_ghost_queue = []
                self.dead_unit_latch = {}
                self.live_velocity_debug = None
                self.last_my_unit = my_unit
                self.my_unit_spawn_grace_until = curr_t + 0.40

            my_is_air = False
            my_name = ""
            my_name_key = ""
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit:
                    my_is_air = is_air; break
            if my_unit:
                my_profile = get_unit_filter_profile(self.scanner, my_unit)
                my_name = my_profile.get("short_name") or ""
                my_name_key = my_profile.get("unit_key") or ""
                if my_profile.get("kind") == "air":
                    my_is_air = True
                elif my_profile.get("kind") == "ground":
                    my_is_air = False
            
            my_spawn_in_grace = curr_t < self.my_unit_spawn_grace_until
            if my_spawn_in_grace:
                my_vel = (0.0, 0.0, 0.0)
            else:
                my_vel = self._stabilize_velocity(my_unit, my_is_air, my_pos, curr_t) if my_unit and my_pos else (0.0, 0.0, 0.0)
            if not my_vel: my_vel = (0.0, 0.0, 0.0)
            my_vx, my_vy, my_vz = my_vel
            my_ground_shot_origin = my_pos
            my_box_data = None
            my_dynamic_geometry = None
            if my_unit and my_pos and not my_is_air:
                try:
                    my_box_data = get_unit_3d_box_data(self.scanner, my_unit, False)
                    if my_box_data:
                        my_barrel_data = get_weapon_barrel(self.scanner, my_unit, my_box_data[0], my_box_data[3])
                        if my_barrel_data:
                            my_ground_shot_origin = my_barrel_data[1] or my_barrel_data[0] or my_pos
                        my_dynamic_geometry = _get_dynamic_my_geometry(self.scanner, cgame_base, my_unit, my_box_data)
                except Exception:
                    my_ground_shot_origin = my_pos
                    my_dynamic_geometry = None

            if SHOW_MY_UNIT_BOX and my_unit and my_pos:
                try:
                    my_bmin, my_bmax = get_unit_bbox(self.scanner, my_unit)
                    my_rot = get_unit_rotation(self.scanner, my_unit)
                    if my_bmin and my_bmax and my_rot:
                        my_corners = [
                            (my_bmin[0], my_bmin[1], my_bmin[2]), (my_bmin[0], my_bmin[1], my_bmax[2]),
                            (my_bmin[0], my_bmax[1], my_bmin[2]), (my_bmin[0], my_bmax[1], my_bmax[2]),
                            (my_bmax[0], my_bmin[1], my_bmin[2]), (my_bmax[0], my_bmin[1], my_bmax[2]),
                            (my_bmax[0], my_bmax[1], my_bmin[2]), (my_bmax[0], my_bmax[1], my_bmax[2]),
                        ]
                        my_pts = []
                        for c in my_corners:
                            world_x = my_pos[0] + (c[0] * my_rot[0] + c[1] * my_rot[3] + c[2] * my_rot[6])
                            world_y = my_pos[1] + (c[0] * my_rot[1] + c[1] * my_rot[4] + c[2] * my_rot[7])
                            world_z = my_pos[2] + (c[0] * my_rot[2] + c[1] * my_rot[5] + c[2] * my_rot[8])
                            scr = world_to_screen(view_matrix, world_x, world_y, world_z, self.screen_width, self.screen_height)
                            if scr and scr[2] > 0:
                                my_pts.append((int(scr[0]), int(scr[1])))
                            else:
                                my_pts.append(None)
                        if my_pts.count(None) == 0:
                            my_edges = [
                                (0, 1), (0, 2), (1, 3), (2, 3),
                                (4, 5), (4, 6), (5, 7), (6, 7),
                                (0, 4), (1, 5), (2, 6), (3, 7),
                            ]
                            painter.setPen(QPen(QColor(*COLOR_BOX_MY_UNIT), 1.5))
                            for p1, p2 in my_edges:
                                painter.drawLine(my_pts[p1][0], my_pts[p1][1], my_pts[p2][0], my_pts[p2][1])
                except Exception:
                    pass

            valid_targets = []
            current_seen_ptrs = set()
            for u_ptr, is_air in all_units_data:
                if u_ptr == my_unit: continue 
                current_seen_ptrs.add(u_ptr)
                
                # 🛡️ Cache-based Profile & Status Retrieval
                info_ptr_now = _read_ptr_fast(self.scanner, u_ptr + OFF_UNIT_INFO)
                status = get_unit_status(self.scanner, u_ptr)
                if not status:
                    continue
                profile = get_unit_filter_profile(self.scanner, u_ptr)
                dna = get_unit_detailed_dna(self.scanner, u_ptr) or {}
                cached_prof = {
                    'status': status,
                    'profile': profile,
                    'dna': dna,
                    'is_air_resolved': is_air,
                    'info_ptr': info_ptr_now,
                }
                self.profile_cache[u_ptr] = cached_prof
                
                u_team, u_state, unit_name, reload_val = cached_prof['status']

                latch_meta = self.dead_unit_latch.get(u_ptr)
                if u_state >= 1:
                    self.dead_unit_latch[u_ptr] = {
                        "info_ptr": info_ptr_now if is_valid_ptr(info_ptr_now) else 0,
                        "latched_at": curr_t,
                    }
                    continue
                if latch_meta:
                    latched_info_ptr = int(latch_meta.get("info_ptr") or 0)
                    info_ptr_changed = (
                        is_valid_ptr(info_ptr_now)
                        and is_valid_ptr(latched_info_ptr)
                        and info_ptr_now != latched_info_ptr
                    )
                    info_ptr_reborn = (
                        is_valid_ptr(info_ptr_now)
                        and not is_valid_ptr(latched_info_ptr)
                    )
                    if info_ptr_changed or info_ptr_reborn:
                        del self.dead_unit_latch[u_ptr]
                    else:
                        continue
                if u_team == 0 or (my_team != 0 and u_team == my_team): continue

                profile = cached_prof['profile']
                if profile.get("skip"): continue
                
                profile_tag = (profile.get("tag") or "").lower()
                profile_path = (profile.get("path") or "").lower()
                if profile_tag in ("exp_aaa", "exp_fortification", "exp_structure", "exp_zero"): continue
                if ("air_defence/" in profile_path) or ("structures/" in profile_path) or ("dummy_plane" in profile_path): continue

                dna = cached_prof.get('dna') or {}
                short_name = (dna.get("short_name") or "").strip()
                family_name = (dna.get("family") or "").strip()
                name_key = (dna.get("name_key") or "").strip()
                resolved_is_air = _resolve_is_air_now(
                    cached_prof.get('is_air_resolved', is_air),
                    family_name,
                    profile_tag,
                    profile_path,
                )
                cached_prof['is_air_resolved'] = resolved_is_air

                resolved_name = short_name
                if (not resolved_name) or (resolved_name.lower() in ("none", "unknown", "c")):
                    resolved_name = unit_name
                if (not resolved_name) or (len(resolved_name) < 2) or (resolved_name.lower() in ("unknown", "c", "none")):
                    resolved_name = profile.get("display_name") or "unknown"

                runtime_filter_blob = " ".join((
                    (resolved_name or ""),
                    short_name,
                    family_name,
                    name_key,
                    (profile.get("display_name") or ""),
                    (profile.get("unit_key") or ""),
                    (profile.get("path") or ""),
                    (profile.get("tag") or ""),
                )).lower()
                if any(h in runtime_filter_blob for h in NON_PLAYABLE_RUNTIME_HINTS):
                    continue

                pos = get_unit_pos(self.scanner, u_ptr)
                if not pos: continue
                pre_vel = None
                if not resolved_is_air:
                    pre_vel = self._stabilize_velocity(u_ptr, False, pos, curr_t)

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

                valid_targets.append((
                    u_ptr,
                    resolved_name,
                    reload_val,
                    resolved_is_air,
                    pos,
                    dist_to_me,
                    short_name,
                    family_name,
                    name_key,
                    profile_tag,
                    profile_path,
                    (profile.get("unit_key") or ""),
                    pre_vel,
                ))
            
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

            # 🎯 เลือกเป้าหมายจากลิสต์ที่มองเห็น โดยล็อกตัวที่ใกล้ crosshair ที่สุดเสมอ
            visible_targets = []
            for (
                u_ptr,
                raw_name,
                reload_val,
                is_air_target,
                pos,
                dist_to_me,
                short_name,
                family_name,
                name_key,
                profile_tag,
                profile_path,
                profile_unit_key,
                pre_vel,
            ) in valid_targets:
                select_screen = None
                select_box_rect = None
                select_fire_origin = my_ground_shot_origin if my_ground_shot_origin else my_pos
                select_vx, select_vy, select_vz = pre_vel if pre_vel else (0.0, 0.0, 0.0)
                select_tx, select_ty, select_tz = pos[0], pos[1], pos[2]

                if (not is_air_target) and current_bullet_speed > 0.0 and my_pos:
                    # Ground selection: compare by leadmark-like point, not raw unit center.
                    try:
                        select_box_data, _select_box_source = _get_dynamic_target_box_data(self.scanner, u_ptr, False)
                        select_box_rect = _project_target_box_rect(
                            view_matrix,
                            select_box_data,
                            self.screen_width,
                            self.screen_height,
                        )
                        ground_aim_point = _get_ground_target_aim_point(select_box_data, pos, dist_to_me)
                        if ground_aim_point:
                            select_tx, select_ty, select_tz = ground_aim_point
                    except Exception:
                        select_box_rect = None

                    select_t = max(dist_to_me / current_bullet_speed, 0.01)
                    pred_x = select_tx + (select_vx * select_t)
                    pred_y = select_ty + (select_vy * select_t)
                    pred_z = select_tz + (select_vz * select_t)

                    dx_imp = pred_x - (select_fire_origin[0] + my_vx * select_t)
                    dz_imp = pred_z - (select_fire_origin[2] + my_vz * select_t)
                    d_imp = math.hypot(dx_imp, dz_imp)

                    if current_bullet_speed > 0.0:
                        select_t = d_imp / current_bullet_speed
                        bullet_drop = 0.5 * BULLET_GRAVITY * (select_t ** 2)
                        t_sight = current_zeroing / current_bullet_speed
                        bullet_drop -= (0.5 * BULLET_GRAVITY * (t_sight ** 2))
                    else:
                        bullet_drop = 0.0

                    select_x = pred_x - (my_vx * select_t)
                    select_y = pred_y + bullet_drop - (my_vy * select_t)
                    select_z = pred_z - (my_vz * select_t)
                    select_screen = world_to_screen(view_matrix, select_x, select_y, select_z, self.screen_width, self.screen_height)
                else:
                    # Air selection: keep old stable behavior, use unit center only.
                    select_screen = world_to_screen(view_matrix, select_tx, select_ty, select_tz, self.screen_width, self.screen_height)

                res_pos = select_screen
                if res_pos and res_pos[2] > 0:
                    select_sx = res_pos[0]
                    select_sy = res_pos[1]
                    if select_box_rect and not is_air_target:
                        select_sx = (select_box_rect[0] + select_box_rect[2]) * 0.5
                    dist_crosshair = math.hypot(select_sx - self.center_x, select_sy - self.center_y)
                    visible_targets.append((dist_crosshair, u_ptr, is_air_target))

            ground_leadmark_allow_ptrs = None
            if visible_targets:
                visible_targets.sort(key=lambda item: item[0])
                active_target_ptr = visible_targets[0][1]
                if GROUND_LEADMARK_TOP_N > 0:
                    ordered_ground = [
                        u_ptr
                        for _dist_crosshair, u_ptr, is_air_target in visible_targets
                        if not is_air_target
                    ]
                    ground_leadmark_allow_ptrs = set(ordered_ground[:GROUND_LEADMARK_TOP_N])
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
            # 🔧 PRE-CALCULATE BALLISTICS & ORIGIN FOR THIS FRAME
            altitude = max(0.0, my_pos[1]) if my_pos else 0.0
            ballistic_model = _make_ballistic_model(ballistic_profile, altitude)
            zero_pitch = _solve_zero_pitch(current_zeroing, ballistic_model)
            fire_origin = my_ground_shot_origin if my_ground_shot_origin else (my_pos if my_pos else (0.0, 0.0, 0.0))
            
            active_sniper_data = None

            for (
                u_ptr,
                raw_name,
                reload_val,
                is_air_target,
                pos,
                dist_to_me,
                short_name,
                family_name,
                name_key,
                profile_tag,
                profile_path,
                profile_unit_key,
                pre_vel,
            ) in valid_targets:
                seen_targets_this_frame.add(u_ptr)
                try:
                    box_data, dynamic_box_source = _get_dynamic_target_box_data(self.scanner, u_ptr, is_air_target)
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
                    target_box_rect = None

                    if ESP_POINT_ONLY_MODE:
                        res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                        if res_pos and res_pos[2] > 0:
                            point_color = QColor(*COLOR_BOX_SELECT_TARGET) if u_ptr == active_target_ptr else QColor(*COLOR_BOX_TARGET)
                            painter.setPen(QPen(point_color, 2))
                            painter.drawEllipse(int(res_pos[0] - 4), int(res_pos[1] - 4), 8, 8)
                            painter.drawLine(int(res_pos[0] - 8), int(res_pos[1]), int(res_pos[0] + 8), int(res_pos[1]))
                            painter.drawLine(int(res_pos[0]), int(res_pos[1] - 8), int(res_pos[0]), int(res_pos[1] + 8))
                            avg_x, avg_y, min_y = res_pos[0], res_pos[1], res_pos[1] - 8
                            target_box_rect = (
                                res_pos[0] - 8.0,
                                res_pos[1] - 8.0,
                                res_pos[0] + 8.0,
                                res_pos[1] + 8.0,
                            )
                            has_valid_box = True

                    use_simple_screen_box = (
                        (not is_air_target and GROUND_USE_SIMPLE_SCREEN_BOX)
                        or (is_air_target and AIR_USE_SIMPLE_SCREEN_BOX)
                    )
                    if (not ESP_POINT_ONLY_MODE) and not use_simple_screen_box:
                        # ========================================================
                        # 📦 3D BOUNDING BOX RENDERER (PERFECT ROTATION)
                        # ========================================================
                        bmin, bmax = get_unit_bbox(self.scanner, u_ptr)
                        rot = get_unit_rotation(self.scanner, u_ptr)
                        
                        if bmin and bmax and rot:
                            # 1. สร้างมุมกล่องทั้ง 8 มุมแบบ Local
                            corners = [
                                (bmin[0], bmin[1], bmin[2]), (bmin[0], bmin[1], bmax[2]),
                                (bmin[0], bmax[1], bmin[2]), (bmin[0], bmax[1], bmax[2]),
                                (bmax[0], bmin[1], bmin[2]), (bmax[0], bmin[1], bmax[2]),
                                (bmax[0], bmax[1], bmin[2]), (bmax[0], bmax[1], bmax[2])
                            ]
                            
                            pts = []
                            # 2. หมุนกล่องตามองศารถถัง (Rotation) + ย้ายไปตำแหน่งจริง (Translation)
                            for c in corners:
                                world_x = pos[0] + (c[0]*rot[0] + c[1]*rot[3] + c[2]*rot[6])
                                world_y = pos[1] + (c[0]*rot[1] + c[1]*rot[4] + c[2]*rot[7])
                                world_z = pos[2] + (c[0]*rot[2] + c[1]*rot[5] + c[2]*rot[8])
                                
                                # 3. แปลงลงหน้าจอ
                                scr = world_to_screen(view_matrix, world_x, world_y, world_z, self.screen_width, self.screen_height)
                                if scr and scr[2] > 0:
                                    pts.append((int(scr[0]), int(scr[1])))
                                else:
                                    pts.append(None)
                                    
                            # 4. ลากเส้นเชื่อมมุมทั้ง 8 (ถ้าอยู่บนหน้าจอครบ)
                            if pts.count(None) == 0:
                                edges = [
                                    (0,1), (0,2), (1,3), (2,3), # ฐานล่าง
                                    (4,5), (4,6), (5,7), (6,7), # ฐานบน
                                    (0,4), (1,5), (2,6), (3,7)  # เสาแนวตั้ง
                                ]
                                
                               
                                box_color = QColor(*COLOR_BOX_TARGET) if not is_air_target else QColor(*COLOR_BOX_TARGET)
                                if u_ptr == active_target_ptr:
                                    box_color = QColor(*COLOR_BOX_SELECT_TARGET)
                                    
                                painter.setPen(QPen(box_color, 1.5))
                                for p1, p2 in edges:
                                    painter.drawLine(pts[p1][0], pts[p1][1], pts[p2][0], pts[p2][1])

                                # 5. คำนวณข้อมูลสำหรับระบบล็อกเป้าและระยะทาง
                                valid_pts = [p for p in pts if p]
                                min_y = min(p[1] for p in valid_pts)
                                avg_x = sum(p[0] for p in valid_pts) / len(valid_pts)
                                avg_y = sum(p[1] for p in valid_pts) / len(valid_pts)
                                target_box_rect = (
                                    min(p[0] for p in valid_pts),
                                    min(p[1] for p in valid_pts),
                                    max(p[0] for p in valid_pts),
                                    max(p[1] for p in valid_pts),
                                )
                                has_valid_box = True

                    if (not ESP_POINT_ONLY_MODE) and not has_valid_box:
                        res_pos = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                        if res_pos and res_pos[2] > 0:
                            box_w = max(20, int(3000 / (dist + 1))) if is_air_target else max(30, int(4000 / (dist + 1)))
                            box_h = box_w * 0.8 if is_air_target else box_w * 0.6
                            painter.setPen(QPen(QColor(*COLOR_BOX_TARGET), 2))
                            painter.drawRect(int(res_pos[0] - box_w/2), int(res_pos[1] - box_h/2), int(box_w), int(box_h))
                            avg_x, avg_y, min_y = res_pos[0], res_pos[1], res_pos[1] - box_h/2
                            target_box_rect = (
                                res_pos[0] - (box_w * 0.5),
                                res_pos[1] - (box_h * 0.5),
                                res_pos[0] + (box_w * 0.5),
                                res_pos[1] + (box_h * 0.5),
                            )
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
                    unit_family = _resolve_unit_family_enum(
                        family_name,
                        profile_tag,
                        profile_path,
                        profile_unit_key,
                        name_key,
                        short_name,
                        physics_is_air,
                    )
                    family_is_air = unit_family in (
                        UNIT_FAMILY_AIR_FIGHTER,
                        UNIT_FAMILY_AIR_BOMBER,
                        UNIT_FAMILY_AIR_ATTACKER,
                        UNIT_FAMILY_AIR_HELICOPTER,
                    )
                    family_is_ground = unit_family in (
                        UNIT_FAMILY_GROUND_LIGHT_TANK,
                        UNIT_FAMILY_GROUND_MEDIUM_TANK,
                        UNIT_FAMILY_GROUND_HEAVY_TANK,
                        UNIT_FAMILY_GROUND_TANK_DESTROYER,
                        UNIT_FAMILY_GROUND_SPAA,
                        UNIT_FAMILY_SHIP_BOAT,
                        UNIT_FAMILY_SHIP_FRIGATE,
                        UNIT_FAMILY_SHIP_DESTROYER,
                        UNIT_FAMILY_SHIP_CRUISER,
                        UNIT_FAMILY_SHIP_BATTLESHIP,
                    )
                    if family_is_air:
                        physics_is_air = True
                    elif family_is_ground:
                        physics_is_air = False

                    self._maybe_alert_for_air_target(u_ptr, unit_family, curr_t)

                    display_is_air = physics_is_air
                    if display_is_air and my_pos and abs(pos[1] - my_pos[1]) < 50:
                        display_is_air = False

                    is_recon_drone = _is_recon_drone_like(" ".join((
                        family_name or "",
                        profile_tag or "",
                        profile_path or "",
                        profile_unit_key or "",
                        name_key or "",
                        short_name or "",
                        clean_name or "",
                    )))

                    has_reload_bar = (not display_is_air and (0 <= reload_val < 500))
                    dist_to_crosshair = math.hypot(avg_x - self.center_x, avg_y - self.center_y)
                    hide_name = (dist > 550 and dist_to_crosshair >= 350) if (is_recon_drone or not display_is_air) else False
                    
                    # 🎯 กลับมาใช้รูปแบบเดิมที่โชว์แค่ ชื่อ และ ระยะทาง
                    display_text = f"-{int(dist)}m-" if hide_name else f"{clean_name.upper()} [{int(dist)}m]"
                        
                    fm = painter.fontMetrics()
                    text_w = fm.boundingRect(display_text).width()
                    text_y = int(min_y - 14) if has_reload_bar else int(min_y - 8)
                    icon_y = text_y - CLASS_ICON_LINE_GAP
                    debug_label_y = icon_y - CLASS_ICON_DEBUG_TEXT_GAP
                    overlay_debug_y = debug_label_y - UNIT_FAMILY_OVERLAY_DEBUG_GAP

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
                    if DRAW_UNIT_FAMILY_OVERLAY_DEBUG:
                        debug_parts = [
                            f"ptr={hex(u_ptr)}",
                            f"short={_sanitize_debug_text(short_name)}",
                            f"fam={_sanitize_debug_text(family_name)}",
                            f"lbl={_unit_family_debug_label(unit_family)}",
                        ]
                        overlay_debug_text = " | ".join(debug_parts)
                        overlay_debug_w = fm.boundingRect(overlay_debug_text).width()
                        painter.drawText(
                            int(avg_x - (overlay_debug_w * 0.5)),
                            int(overlay_debug_y),
                            overlay_debug_text,
                        )
                    if DRAW_CLASS_ICON_DEBUG_TEXT:
                        debug_label = _unit_family_debug_label(unit_family)
                        debug_w = fm.boundingRect(debug_label).width()
                        painter.drawText(int(avg_x - (debug_w * 0.5)), int(debug_label_y), debug_label)
                    if DRAW_CLASS_ICON:
                        _draw_unit_class_icon(
                            painter,
                            int(avg_x),
                            int(icon_y - 10),
                            unit_family,
                            CLASS_ICON_SIZE,
                        )
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
                    vel = pre_vel if (pre_vel and not physics_is_air) else self._stabilize_velocity(u_ptr, physics_is_air, pos, curr_t)
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
                        ground_aim_point = _get_ground_target_aim_point(box_data, pos, dist)
                        if not ground_aim_point:
                            continue
                        t_x, t_y, t_z = ground_aim_point

                    process_ground_leadmark = (
                        physics_is_air or
                        ground_leadmark_allow_ptrs is None or
                        u_ptr in ground_leadmark_allow_ptrs
                    )
                    if (not physics_is_air) and (not process_ground_leadmark):
                        continue

                    leadmark_tof_limit = _get_leadmark_tof_limit(physics_is_air)
                    leadmark_range_ok = (
                        leadmark_range_limit <= 0.0 or dist <= leadmark_range_limit
                    )
                    leadmark_tof_ok = True
                    leadmark_in_range = leadmark_range_ok

                    # =========================================================
                    # 🚀 WT TRUE BALLISTICS SOLVER (TILT-COMPENSATED)
                    # =========================================================
                    altitude = max(0.0, my_pos[1])
                    rho = 1.225 * math.pow(max(1.0 - (2.25577e-5 * altitude), 0.0), 4.2561)
                    
                    is_sub_caliber = (current_bullet_speed >= 1200.0)
                    if is_sub_caliber:
                        eff_cd = current_bullet_cd if current_bullet_cd > 0 else 0.20
                        eff_caliber = current_bullet_caliber if current_bullet_caliber < 0.05 else current_bullet_caliber * 0.25
                    else:
                        eff_cd = current_bullet_cd if current_bullet_cd > 0 else 0.35
                        eff_caliber = current_bullet_caliber

                    area = math.pi * ((eff_caliber / 2.0) ** 2)
                    base_k = (0.5 * rho * eff_cd * area) / current_bullet_mass if current_bullet_mass > 0.001 else 0.0001
                    
                    avg_speed = current_bullet_speed * (1.0 - min(dist / 5000.0, 0.4))
                    mach = avg_speed / 343.0
                    
                    if mach > 2.5:    mach_mult = 0.35 + (1.0 / mach) 
                    elif mach > 1.2:  mach_mult = 0.95                
                    elif mach > 0.8:  mach_mult = 0.9                
                    else:             mach_mult = 0.85                

                    k = base_k * mach_mult

                    t_sight = current_zeroing / current_bullet_speed if current_bullet_speed > 0 else 0
                    sight_drop_comp = 0.5 * BULLET_GRAVITY * (t_sight * t_sight)
                    
                    best_t = dist / current_bullet_speed if current_bullet_speed > 0 else 0.1
                    bullet_drop_sim = 0.0
                    final_x, final_y, final_z = t_x, t_y, t_z
                    pred_x, pred_y, pred_z = t_x, t_y, t_z
                    
                    # 🎯 ดึงองศาการเอียงของรถถังเรา (My Unit Rotation)
                    my_rot = get_unit_rotation(self.scanner, my_unit)
                    if not my_rot:
                        my_rot = (1.0, 0.0, 0.0,  0.0, 1.0, 0.0,  0.0, 0.0, 1.0)
                        
                    # 📐 ดึงแกน 'ด้านบน' ของรถถังเรา (Local UP Vector) ออกมาจาก Matrix
                    up_x, up_y, up_z = my_rot[3], my_rot[4], my_rot[5]
                    
                    # 📍 จุดกำเนิดกระสุนที่แท้จริง: เลื่อนขึ้น 1.5m ตามองศารถถัง (ไม่ฝืนตั้งตรงแบบเดิมแล้ว)
                    origin_x = my_pos[0] + (1.5 * up_x)
                    origin_y = my_pos[1] + (1.5 * up_y)
                    origin_z = my_pos[2] + (1.5 * up_z)

                    # 🔄 Iterative TOF Solver (วนลูป 4 รอบเพื่อความนิ่ง)
                    for _ in range(4):
                        if physics_is_air:
                            pred_x = t_x + (vx * best_t) + (0.5 * ax * (best_t ** 2))
                            pred_y = t_y + (vy * best_t) + (0.5 * ay * (best_t ** 2))
                            pred_z = t_z + (vz * best_t) + (0.5 * az * (best_t ** 2))
                        else:
                            pred_x = t_x + (vx * best_t)
                            pred_y = t_y + (vy * best_t)
                            pred_z = t_z + (vz * best_t)
                        
                        # ใช้ออริจินใหม่ที่เอียงตามรถถังในการหาระยะจัดกระสุน
                        dx_imp = pred_x - (origin_x + my_vx * best_t)
                        dy_imp = pred_y - (origin_y + my_vy * best_t)
                        dz_imp = pred_z - (origin_z + my_vz * best_t)
                        horizontal_imp = math.hypot(dx_imp, dz_imp)
                        
                        if current_bullet_speed > 0:
                            if physics_is_air:
                                best_t, bullet_drop_sim, _ = _simulate_projectile_range(horizontal_imp, ballistic_model, zero_pitch)
                            elif k > 0.000001:
                                kx = min(k * horizontal_imp, 5.0) 
                                best_t = (math.exp(kx) - 1.0) / (k * current_bullet_speed)
                            else:
                                best_t = horizontal_imp / current_bullet_speed
                        else:
                            best_t = 999.0
                            
                        final_x, final_y, final_z = pred_x, pred_y, pred_z

                    # 📉 Gravity Drop Compensation: 0.5 * g * t^2
                    gravity_offset = bullet_drop_sim if physics_is_air else (0.5 * BULLET_GRAVITY * (best_t ** 2))
                    
                    # 🎯 แรงโน้มถ่วงดึงลงตรงๆ แกน Y ของโลกเท่านั้น!
                    final_y += gravity_offset                  
                    final_y -= sight_drop_comp
                    
                    # หักลบความเร็วรถถังเราออก (Galilean Relativity)
                    final_x -= (my_vx * best_t)
                    final_y -= (my_vy * best_t)
                    final_z -= (my_vz * best_t)

                    leadmark_tof_ok = (
                        leadmark_tof_limit <= 0.0 or best_t <= leadmark_tof_limit
                    )
                    leadmark_in_range = leadmark_range_ok and leadmark_tof_ok
                    
                    # =========================================================
                    # 📊 [STICKY DASHBOARD]: อัปเดตแบบ Real-time ทับบรรทัดเดิม
                    # =========================================================
                    if u_ptr == active_target_ptr:
                        vel_meta = self.last_velocity_meta.get(u_ptr, {})
                        vel_source = vel_meta.get('source', 'raw')
                        raw_mag = vel_meta.get('raw_mag', 0.0) * 3.6
                        pos_mag = vel_meta.get('pos_mag', 0.0) * 3.6
                        chosen_mag = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
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
                        my_vel_meta = self.last_velocity_meta.get(my_unit, {})
                        my_vel_source = my_vel_meta.get('source', 'raw')
                        my_speed = math.sqrt(my_vx**2 + my_vy**2 + my_vz**2) * 3.6
                        my_raw_mag = my_vel_meta.get('raw_mag', 0.0) * 3.6
                        my_pos_mag = my_vel_meta.get('pos_mag', 0.0) * 3.6
                        target_speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                        accel_mag = math.sqrt(ax**2 + ay**2 + az**2)

                        self.live_velocity_debug = {
                            "my": {
                                "source": my_vel_source,
                                "raw_kmh": my_raw_mag,
                                "pos_kmh": my_pos_mag,
                                "chosen_kmh": my_speed,
                                "vec": (my_vx, my_vy, my_vz),
                            },
                            "target": {
                                "source": vel_source,
                                "raw_kmh": raw_mag,
                                "pos_kmh": pos_mag,
                                "chosen_kmh": chosen_mag,
                                "vec": (vx, vy, vz),
                            },
                        }
                        
                        out =  "================================================================\n"
                        out += f"📊 WTM TACTICAL DASHBOARD | FPS: {int(self.current_fps):<3} | Units: {len(valid_targets):<2}\n"
                        out += "================================================================\n"
                        out += f"🟢 [MY UNIT]  : {hex(my_unit)}\n"
                        out += f"🚀 Velocity   : {my_speed:>6.1f} km/h | V:({my_vx:>6.2f}, {my_vy:>6.2f}, {my_vz:>6.2f}) | SRC:{my_vel_source}\n"
                        out += "-" * 64 + "\n"
                        out += f"🎯 [TARGET]   : {clean_name.upper()} {'[LOCKED]':>35}\n"
                        out += f"🧷 Ptr/Off    : UNIT:{hex(u_ptr)} | INFO:{hex(info_ptr) if info_ptr else '0x0'} | MOV:{hex(mov_ptr) if mov_ptr else '0x0'} @ {hex(mov_off)}\n"
                        
                        # 🧬 [DNA] ดึงและแสดงข้อมูลเชิงลึก
                        dna = (self.profile_cache.get(u_ptr) or {}).get('dna')
                        if not dna:
                            dna = get_unit_detailed_dna(self.scanner, u_ptr)
                            if u_ptr in self.profile_cache:
                                self.profile_cache[u_ptr]['dna'] = dna or {}
                        if dna:
                            invul_str = " [GOD MODE]" if dna['is_invul'] else ""
                            out += f"🧬 DNA        : NATION:{dna['nation_id']} | CLASS:{dna['class_id']} | STATE:{dna['state']}{invul_str}\n"
                            out += f"🏷️ UNIT       : {dna['short_name']} ({dna['family']})\n"
                            out += f"📛 KEY        : {dna['name_key']}\n"
                        
                        range_limit_text = (
                            f"{leadmark_range_limit:.0f}m" if leadmark_range_limit > 0.0 else "OFF"
                        )
                        tof_limit_text = (
                            f"{leadmark_tof_limit:.2f}s" if leadmark_tof_limit > 0.0 else "OFF"
                        )
                        out += f"📏 Distance   : {dist:>6.1f} m      | TOF: {best_t:>6.3f} s\n"
                        out += f"🚀 Velocity   : {target_speed:>6.1f} km/h | V:({vx:>6.2f}, {vy:>6.2f}, {vz:>6.2f}) | SRC:{vel_source}\n"
                        out += f"📡 Vel Check  : raw={raw_mag:>6.1f} km/h | pos={pos_mag:>6.1f} km/h | PTR:{hex(u_ptr)}\n"
                        out += f"🌪️ Accel      : {accel_mag:>6.2f} m/s² | A:({ax:>6.2f}, {ay:>6.2f}, {az:>6.2f})\n"
                        out += f"🎯 Lead Limit : {range_limit_text} | RangeOK:{'Y' if leadmark_range_ok else 'N'} | TOFLimit:{tof_limit_text} | TOFOK:{'Y' if leadmark_tof_ok else 'N'} | InRange:{'Y' if leadmark_in_range else 'N'}\n"
                        out += "-" * 64 + "\n"
                        out += f"📉 [BALLISTICS]\n"
                        vel_lo, vel_hi = ballistic_profile["vel_range"]
                        out += f"🔫 Bullet     : Spd:{current_bullet_speed:.0f} m/s | CD:{current_bullet_cd:.2f} | Mass:{current_bullet_mass:.2f} | Cal:{current_bullet_caliber:.3f}\n"
                        out += f"📉 Drop       : Bullet: +{gravity_offset:>5.2f} m | Zero: {math.degrees(zero_pitch):>5.2f} deg | VRange:{vel_lo:.0f}-{vel_hi:.0f}\n"
                        out += f"🧪 Model      : {ballistic_profile.get('model_enum', 0)} | drag_k:{ballistic_model.get('drag_k', 0.0):.6e}\n"
                        out += "================================================================\n"
                        out += " [Auto] Closest Target | [Ctrl+C] Exit\n"

                        should_refresh_console = (
                            (curr_t - self.last_debug_log_time) >= DEBUG_LOG_INTERVAL
                        )
                        if should_refresh_console:
                            if _console_supports_sticky_dashboard():
                                if not self.console_initialized:
                                    sys.stdout.write("\033[2J\033[H")
                                    self.console_initialized = True
                                else:
                                    sys.stdout.write("\033[H\033[J")
                                sys.stdout.write(out)
                                sys.stdout.flush()
                            else:
                                if not self.console_initialized:
                                    print("[*] Console note: sticky dashboard disabled (no ANSI/TTY support)")
                                    self.console_initialized = True
                                print(out, end="")
                            self.last_debug_log_time = curr_t

                    ground_reference_final = None
                    if (not physics_is_air) and leadmark_in_range and (not my_spawn_in_grace):
                        ground_reference_final = _solve_static_ground_leadmark(
                            (t_x, t_y, t_z),
                            fire_origin,
                            (my_vx, my_vy, my_vz),
                            current_bullet_speed,
                            current_zeroing,
                            ballistic_model,
                            zero_pitch,
                            my_rot  # 🎯 ส่งค่าความเอียงเข้าไปตรงนี้
                        )

                    # 🛡️ เช็คว่าพิกัดทำนายไม่ใช่ค่าว่าง
                    if leadmark_in_range and all(math.isfinite(c) for c in [final_x, final_y, final_z]):
                        pred_screen = world_to_screen(view_matrix, final_x, final_y, final_z, self.screen_width, self.screen_height)
                        
                        if pred_screen and pred_screen[2] > 0:
                            px, py = pred_screen[0], pred_screen[1]
                            
                            # 🎯 เช็ค NaN ก่อนแปลงเป็น int
                            if math.isfinite(px) and math.isfinite(py):
                                # ใช้ center ของ 2D target box เป็น origin ของเส้น leadmark
                                if target_box_rect:
                                    draw_sx = (target_box_rect[0] + target_box_rect[2]) * 0.5
                                    draw_sy = (target_box_rect[1] + target_box_rect[3]) * 0.5
                                else:
                                    draw_sx, draw_sy = avg_x, avg_y
                                
                                # ถ้าเป็นเครื่องบิน ให้ดึงพิกัดที่แม่นยำกว่ามาวาดเส้น
                                if display_is_air:
                                    pos_scr = world_to_screen(view_matrix, pos[0], pos[1], pos[2], self.screen_width, self.screen_height)
                                    if pos_scr and pos_scr[2] > 0:
                                        draw_sx, draw_sy = pos_scr[0], pos_scr[1]
                                elif target_box_rect:
                                    center_x = (target_box_rect[0] + target_box_rect[2]) * 0.5
                                    # หาจุด 3D บนจอ แล้ววัดระยะห่าง (Lead Pixel) เพื่อเอามาบวกกับ Center 2D
                                    anchor_scr = world_to_screen(view_matrix, t_x, t_y, t_z, self.screen_width, self.screen_height)
                                    if anchor_scr and anchor_scr[2] > 0:
                                        pixel_lead_x = px - anchor_scr[0]
                                        px = center_x + pixel_lead_x
                                
                                # ✅ เพิ่มเข้าคิววาดเมื่อทุกอย่างเป็นตัวเลขปกติ
                                if math.isfinite(draw_sx) and math.isfinite(draw_sy):
                                    lead_marks_to_draw.append({
                                        'sx': draw_sx, 'sy': draw_sy, 
                                        'px': px, 'py': py,
                                        'is_air': display_is_air, 
                                        'is_turning': is_turning,
                                        'style': 'main',
                                    })

                    ground_reference_screen = None
                    if (not physics_is_air) and leadmark_in_range and ground_reference_final and all(math.isfinite(c) for c in ground_reference_final):
                        ground_reference_screen = world_to_screen(
                            view_matrix,
                            ground_reference_final[0],
                            ground_reference_final[1],
                            ground_reference_final[2],
                            self.screen_width,
                            self.screen_height,
                        )
                        if ground_reference_screen and ground_reference_screen[2] > 0:
                                spx, spy = ground_reference_screen[0], ground_reference_screen[1]
                                    
                                # 🎯 THE CLEAN HITPOINT ENGINE (ลบ VirtualBox ทิ้ง และทำงานเฉพาะ Selected Ground Target)
                                if u_ptr == active_target_ptr and target_box_rect and not physics_is_air:
                                    auto_vertical_baseline = _get_auto_vertical_baseline(
                                        my_name_key,
                                        ballistic_profile,
                                        dist,
                                    )
                                    effective_camera_parallax = self.camera_parallax
                                    dynamic_world_offset = None
                                    dynamic_reference_screen = ground_reference_screen
                                    if my_dynamic_geometry:
                                        effective_camera_parallax = float(
                                            my_dynamic_geometry.get("dynamic_parallax_pct", self.camera_parallax)
                                        )
                                        if DYNAMIC_WORLDSPACE_ENABLE:
                                            camera_world = my_dynamic_geometry.get("camera_world")
                                            barrel_base_world = my_dynamic_geometry.get("barrel_base_world")
                                            if camera_world and barrel_base_world:
                                                dynamic_world_offset = (
                                                    float(camera_world[0] - barrel_base_world[0]),
                                                    float(camera_world[1] - barrel_base_world[1]),
                                                    float(camera_world[2] - barrel_base_world[2]),
                                                )
                                                dynamic_reference_world = _offset_world_point(ground_reference_final, dynamic_world_offset)
                                                projected_dynamic_reference = world_to_screen(
                                                    view_matrix,
                                                    dynamic_reference_world[0],
                                                    dynamic_reference_world[1],
                                                    dynamic_reference_world[2],
                                                    self.screen_width,
                                                    self.screen_height,
                                                )
                                                if projected_dynamic_reference and projected_dynamic_reference[2] > 0:
                                                    dynamic_reference_screen = projected_dynamic_reference
                                                    effective_camera_parallax = 0.0
                                    compare_base_hitpoint = None
                                    compare_fallback_hitpoint = None
                                    dynamic_spx, dynamic_spy = spx, spy
                                    if dynamic_reference_screen and dynamic_reference_screen[2] > 0:
                                        dynamic_spx, dynamic_spy = dynamic_reference_screen[0], dynamic_reference_screen[1]
                                    compare_dynamic_hitpoint = _map_aim_to_target_box_hitpoint(
                                        (self.center_x, self.center_y),
                                        (dynamic_spx, dynamic_spy),
                                        target_box_rect,
                                        (t_x, t_y, t_z),
                                        dist,
                                        my_rot,
                                        view_matrix,
                                        self.screen_width,
                                        self.screen_height,
                                        self.calibration_offset,
                                        self.vertical_correction + auto_vertical_baseline,
                                        effective_camera_parallax
                                    )
                                    mapped_hitpoint = compare_dynamic_hitpoint
                                    if DEBUG_COMPARE_DYNAMIC_GEOMETRY:
                                        fallback_box_data = get_unit_3d_box_data(self.scanner, u_ptr, False)
                                        fallback_box_rect = _project_target_box_rect(
                                            view_matrix,
                                            fallback_box_data,
                                            self.screen_width,
                                            self.screen_height,
                                        ) if fallback_box_data else None
                                        if fallback_box_rect:
                                            compare_base_hitpoint = _map_aim_to_target_box_hitpoint(
                                                (self.center_x, self.center_y),
                                                (spx, spy),
                                                fallback_box_rect,
                                                (t_x, t_y, t_z),
                                                dist,
                                                my_rot,
                                                view_matrix,
                                                self.screen_width,
                                                self.screen_height,
                                                self.calibration_offset,
                                                self.vertical_correction + auto_vertical_baseline,
                                                self.camera_parallax,
                                            )
                                            compare_fallback_hitpoint = _map_aim_to_target_box_hitpoint(
                                                (self.center_x, self.center_y),
                                                (spx, spy),
                                                target_box_rect,
                                                (t_x, t_y, t_z),
                                                dist,
                                                my_rot,
                                                view_matrix,
                                                self.screen_width,
                                                self.screen_height,
                                                self.calibration_offset,
                                                self.vertical_correction + auto_vertical_baseline,
                                                self.camera_parallax,
                                            )
                                            if compare_base_hitpoint:
                                                dynamic_compare_points_to_draw.append({
                                                    "kind": "base",
                                                    "pt": compare_base_hitpoint,
                                                })
                                            if compare_dynamic_hitpoint:
                                                dynamic_compare_points_to_draw.append({
                                                    "kind": "dynamic",
                                                    "pt": compare_dynamic_hitpoint,
                                                })
                                            if compare_fallback_hitpoint:
                                                dynamic_compare_points_to_draw.append({
                                                    "kind": "fallback",
                                                    "pt": compare_fallback_hitpoint,
                                                })
                                            if compare_dynamic_hitpoint and compare_base_hitpoint:
                                                base_dx = compare_dynamic_hitpoint[0] - compare_base_hitpoint[0]
                                                base_dy = compare_dynamic_hitpoint[1] - compare_base_hitpoint[1]
                                                base_dist_px = math.hypot(base_dx, base_dy)
                                            else:
                                                base_dx = base_dy = base_dist_px = 0.0
                                            if compare_dynamic_hitpoint and compare_fallback_hitpoint:
                                                fallback_dx = compare_dynamic_hitpoint[0] - compare_fallback_hitpoint[0]
                                                fallback_dy = compare_dynamic_hitpoint[1] - compare_fallback_hitpoint[1]
                                                fallback_dist_px = math.hypot(fallback_dx, fallback_dy)
                                            else:
                                                fallback_dx = fallback_dy = fallback_dist_px = 0.0
                                            dynamic_parallax_terms = _get_hitpoint_parallax_debug_terms(
                                                target_box_rect,
                                                my_rot,
                                                view_matrix,
                                                effective_camera_parallax,
                                            )
                                            fallback_parallax_terms = _get_hitpoint_parallax_debug_terms(
                                                target_box_rect,
                                                my_rot,
                                                view_matrix,
                                                self.camera_parallax,
                                            )
                                            if compare_base_hitpoint or compare_fallback_hitpoint or compare_dynamic_hitpoint:
                                                dynamic_compare_debug = {
                                                    "target_box_source": dynamic_box_source,
                                                    "fallback_box_source": "unit_bbox",
                                                    "baseline_source": VERTICAL_BASELINE_RUNTIME_SOURCE,
                                                    "baseline_value": float(auto_vertical_baseline),
                                                    "baseline_bucket": VERTICAL_BASELINE_LAST_MATCH.get("bucket", ""),
                                                    "baseline_family": VERTICAL_BASELINE_LAST_MATCH.get("family", ""),
                                                    "baseline_profile_key": VERTICAL_BASELINE_LAST_MATCH.get("profile_key", ""),
                                                    "dynamic_geometry_used": bool(my_dynamic_geometry),
                                                    "dynamic_worldspace_used": bool(dynamic_world_offset) and bool(dynamic_reference_screen and dynamic_reference_screen[2] > 0),
                                                    "dynamic_parallax_scale": float(DYNAMIC_PARALLAX_SCALE),
                                                    "dynamic_parallax": float(effective_camera_parallax),
                                                    "fallback_parallax": float(self.camera_parallax),
                                                    "base_dx_px": base_dx,
                                                    "base_dy_px": base_dy,
                                                    "base_dist_px": base_dist_px,
                                                    "fallback_dx_px": fallback_dx,
                                                    "fallback_dy_px": fallback_dy,
                                                    "fallback_dist_px": fallback_dist_px,
                                                    "dynamic_parallax_terms": dynamic_parallax_terms,
                                                    "fallback_parallax_terms": fallback_parallax_terms,
                                                    "dynamic_world_offset": dynamic_world_offset,
                                                    "dynamic_screen_dx": (dynamic_spx - spx) if dynamic_reference_screen and ground_reference_screen else 0.0,
                                                    "dynamic_screen_dy": (dynamic_spy - spy) if dynamic_reference_screen and ground_reference_screen else 0.0,
                                                }
                                    if mapped_hitpoint:
                                        is_hitpoint_inside_bbox = True
                                        bx1, by1, bx2, by2 = target_box_rect
                                        hx, hy = mapped_hitpoint
                                        
                                        # 🛠️ THE FIX: ขยายขอบเขต (Margin) ให้กว้างขึ้น!
                                        # บวกเพิ่ม 50px เผื่อให้จุด Hitpoint ที่ถูกดึงลงด้วย Camera Parallax ไม่หลุดกล่องจนปุ่มกดตาย
                                        margin_x = (bx2 - bx1) * 0.20 + 50.0
                                        margin_y = (by2 - by1) * 0.20 + 50.0
                                        
                                        if not ((bx1 - margin_x) <= hx <= (bx2 + margin_x) and (by1 - margin_y) <= hy <= (by2 + margin_y)):
                                            is_hitpoint_inside_bbox = False

                                        # 🎯 รวบทุกอย่างที่เกี่ยวกับ Hitpoint มาซ่อนไว้ในเงื่อนไขนี้ทั้งหมด!
                                        if is_hitpoint_inside_bbox:
                                            if DRAW_BASE_HITPOINT:
                                                hit_points_to_draw.append(mapped_hitpoint)
                                            if DEBUG_DRAW_BOX_ENTRY_HIT:
                                                debug_box_entry_hits_to_draw.append(mapped_hitpoint)
                                                
                                            active_sniper_data = {
                                                'center_x': avg_x,
                                                'center_y': avg_y,
                                                'hitpoint': mapped_hitpoint,
                                                'target_box_rect': target_box_rect,
                                                'distance': dist,
                                            }

                                            # 🛠️ BUG FIX: ย้ายฟังก์ชันวาดกากบาทสีฟ้า (Calibration) เข้ามาด้วย!
                                            calib_point = self._handle_hitpoint_calibration({
                                                "target_unit_ptr": u_ptr,
                                                "target_unit_label": raw_name,
                                                "target_unit_key": name_key,
                                                "unit_ptr": u_ptr,
                                                "unit_label": raw_name,
                                                "unit_key": name_key,
                                                "my_unit_ptr": my_unit if my_unit else 0,
                                                "my_unit_key": my_name_key,
                                                "my_vehicle_name": my_name,
                                                "distance": dist,
                                                "zeroing": current_zeroing,
                                                "model_enum": ballistic_profile.get("model_enum", 0),
                                                "speed": ballistic_profile.get("speed", 0.0),
                                                "mass": ballistic_profile.get("mass", 0.0),
                                                "caliber": ballistic_profile.get("caliber", 0.0),
                                                "bullet_type_idx": ballistic_profile.get("bullet_type_idx", -1),
                                                "cx": ballistic_profile.get("cx", 0.0),
                                                "drag_k": ballistic_model.get("drag_k", 0.0),
                                                "dynamic_geometry_used": bool(my_dynamic_geometry),
                                                "dynamic_camera_parallax": round(float(effective_camera_parallax), 3),
                                                "dynamic_target_box_source": dynamic_box_source,
                                                "auto_vertical_baseline": auto_vertical_baseline,
                                                "base_hitpoint": mapped_hitpoint,
                                            })
                                            if calib_point:
                                                calibration_hit_points_to_draw.append(calib_point)
                                                
                                    
                                    if DEBUG_DRAW_MUZZLE_RAY:
                                        fire_origin_screen = world_to_screen(
                                            view_matrix, fire_origin[0], fire_origin[1], fire_origin[2], self.screen_width, self.screen_height
                                        )
                                        if fire_origin_screen and fire_origin_screen[2] > 0:
                                            debug_muzzle_rays_to_draw.append({
                                                "sx": fire_origin_screen[0], "sy": fire_origin_screen[1], "px": spx, "py": spy,
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
                line_pts = _screen_int_tuple(lm['sx'], lm['sy'], lm['px'], lm['py'])
                center_pts = _screen_int_tuple(lm['px'], lm['py'])
                if not line_pts or not center_pts:
                    continue
                painter.setPen(QPen(QColor(255, 100, 100, 150), 2, Qt.DashLine))
                painter.drawLine(*line_pts)
                
                pred_color = QColor(*COLOR_PREDICTION)
                if lm['is_air'] and lm['is_turning']:
                    blink_alpha = int(((math.sin(time.time() * 25.0) + 1.0) / 2.0) * 150 + 105)
                    pred_color.setAlpha(blink_alpha)
                
                _draw_leadmark_glyph(painter, center_pts[0], center_pts[1], pred_color, outer_radius=8, core_radius=3, pen_width=3)

            compare_visibility_mode = self._get_compare_visibility_mode()
            show_base_compare = compare_visibility_mode in ("all", "base")
            show_fallback_compare = compare_visibility_mode in ("all", "fallback")
            show_dynamic_compare = compare_visibility_mode in ("all", "dynamic")
            show_live_hitpoint = not DEBUG_COMPARE_DYNAMIC_GEOMETRY

            if show_live_hitpoint:
                for hp_x, hp_y in hit_points_to_draw:
                    hp_pts = _screen_int_tuple(hp_x, hp_y)
                    if not hp_pts:
                        continue
                    hit_color = QColor(*COLOR_BOX_HITPOINT)
                    
                    # 🎯 คำนวณขนาดของกากบาท X (ฐานคือ 3 pixel และกำหนดขนาดขั้นต่ำสุดไว้ที่ 2)
                    x_size = max(2, int(3 * BASE_HITPOINT_SIZE_MULT))
                    
                    # 🎯 คำนวณความหนาของเส้นปากกาให้สมดุลกับขนาด (ค่าเริ่มต้นหนา 2)
                    pen_width = max(1, int(2 * BASE_HITPOINT_SIZE_MULT))
                    painter.setPen(QPen(hit_color, pen_width))
                    
                    # วาดเป็นรูปกากบาท X แบบเฉียง (คมขึ้น เล็งจุดอ่อนง่ายขึ้น)
                    painter.drawLine(hp_pts[0] - x_size, hp_pts[1] - x_size, hp_pts[0] + x_size, hp_pts[1] + x_size)
                    painter.drawLine(hp_pts[0] - x_size, hp_pts[1] + x_size, hp_pts[0] + x_size, hp_pts[1] - x_size)

            if DEBUG_COMPARE_DYNAMIC_GEOMETRY:
                for item in dynamic_compare_points_to_draw:
                    if item["kind"] == "base" and not show_base_compare:
                        continue
                    if item["kind"] == "dynamic" and not show_dynamic_compare:
                        continue
                    if item["kind"] == "fallback" and not show_fallback_compare:
                        continue
                    hp_pts = _screen_int_tuple(item["pt"][0], item["pt"][1])
                    if not hp_pts:
                        continue
                    if item["kind"] == "base":
                        cmp_color = QColor(*COLOR_BOX_HITPOINT)
                        painter.setPen(QPen(cmp_color, 2))
                        painter.drawEllipse(hp_pts[0] - 6, hp_pts[1] - 6, 12, 12)
                        painter.drawLine(hp_pts[0] - 8, hp_pts[1], hp_pts[0] + 8, hp_pts[1])
                        painter.drawLine(hp_pts[0], hp_pts[1] - 8, hp_pts[0], hp_pts[1] + 8)
                    elif item["kind"] == "dynamic":
                        cmp_color = QColor(*COLOR_DYNAMIC_COMPARE_HIT)
                        painter.setPen(QPen(cmp_color, 2))
                        painter.drawEllipse(hp_pts[0] - 6, hp_pts[1] - 6, 12, 12)
                        painter.drawLine(hp_pts[0] - 8, hp_pts[1], hp_pts[0] + 8, hp_pts[1])
                        painter.drawLine(hp_pts[0], hp_pts[1] - 8, hp_pts[0], hp_pts[1] + 8)
                    else:
                        cmp_color = QColor(*COLOR_FALLBACK_COMPARE_HIT)
                        painter.setPen(QPen(cmp_color, 2))
                        painter.drawRect(hp_pts[0] - 6, hp_pts[1] - 6, 12, 12)
                        painter.drawLine(hp_pts[0] - 8, hp_pts[1] - 8, hp_pts[0] + 8, hp_pts[1] + 8)
                        painter.drawLine(hp_pts[0] - 8, hp_pts[1] + 8, hp_pts[0] + 8, hp_pts[1] - 8)

            if DEBUG_DRAW_MUZZLE_RAY:
                painter.setPen(QPen(QColor(*COLOR_DEBUG_MUZZLE_RAY), 2, Qt.DashDotLine))
                for ray in debug_muzzle_rays_to_draw:
                    ray_pts = _screen_int_tuple(ray["sx"], ray["sy"], ray["px"], ray["py"])
                    if not ray_pts:
                        continue
                    painter.drawLine(*ray_pts)

            if DEBUG_DRAW_BOX_ENTRY_HIT:
                entry_color = QColor(*COLOR_DEBUG_BOX_ENTRY)
                painter.setPen(QPen(entry_color, 2))
                for hp_x, hp_y in debug_box_entry_hits_to_draw:
                    hp_pts = _screen_int_tuple(hp_x, hp_y)
                    if not hp_pts:
                        continue
                    painter.drawEllipse(hp_pts[0] - 4, hp_pts[1] - 4, 8, 8)
                    painter.drawLine(hp_pts[0] - 6, hp_pts[1] - 6, hp_pts[0] + 6, hp_pts[1] + 6)
                    painter.drawLine(hp_pts[0] - 6, hp_pts[1] + 6, hp_pts[0] + 6, hp_pts[1] - 6)


            show_calibration_markers = DEBUG_DRAW_CALIBRATION_HIT and (not DEBUG_COMPARE_DYNAMIC_GEOMETRY)
            if show_calibration_markers:
                calib_color = QColor(*COLOR_CALIBRATION_HIT)
                
                # ⚙️ CONFIG: ความหนาของเส้น (1 = บางสุด, 2 = ปกติ)
                painter.setPen(QPen(calib_color, 1)) 
                
                for hp_x, hp_y in calibration_hit_points_to_draw:
                    hp_pts = _screen_int_tuple(hp_x, hp_y)
                    if not hp_pts:
                        continue
                        
                    # ⚙️ CONFIG: ขนาดกล่องสี่เหลี่ยมตรงกลาง 
                    # สูตร: drawRect(x - ครึ่งความกว้าง, y - ครึ่งความสูง, ความกว้าง, ความสูง)
                    # เปลี่ยนเลข 2 และ 4 ถ้าต้องการขยาย/หดกล่อง
                    # painter.drawRect(hp_pts[0] - 2, hp_pts[1] - 4, 8, 8)
                    
                    # ⚙️ CONFIG: ความยาวเส้นกากบาทแนวนอน (แกน X)
                    # เปลี่ยนเลข 4 เป็นเลขที่มากขึ้น ถ้าอยากให้กากบาทยาวขึ้น
                    painter.drawLine(hp_pts[0] - 8, hp_pts[1], hp_pts[0] + 8, hp_pts[1])
                    
                    # ⚙️ CONFIG: ความยาวเส้นกากบาทแนวตั้ง (แกน Y)
                    # เปลี่ยนเลข 8 เป็นเลขอื่น ถ้าอยากให้เส้นแนวตั้งสั้น/ยาวไม่เท่าแนวนอน
                    painter.drawLine(hp_pts[0], hp_pts[1] - 8, hp_pts[0], hp_pts[1] + 8)

            if DEBUG_DRAW_CALIBRATION_HIT or DEBUG_COMPARE_DYNAMIC_GEOMETRY:
                calib_color = QColor(*COLOR_CALIBRATION_HIT)
                painter.setPen(calib_color)
                display_parallax = self.camera_parallax
                if my_dynamic_geometry:
                    display_parallax = float(my_dynamic_geometry.get("dynamic_parallax_pct", self.camera_parallax))
                painter.drawText(
                    20,
                    140,
                    f"[CALIB] Arrow: WeakspotX {self.calibration_offset[0]:.1f} | "
                    f"Vertical {self.vertical_correction:.1f}{' [HOLD]' if DEBUG_COMPARE_DYNAMIC_GEOMETRY else ''} | "
                    f"AutoBase {'ON' if VERTICAL_BASELINE_AUTO_ENABLE else 'OFF'} | "
                    f"DynGeo {'ON' if my_dynamic_geometry else 'OFF'} | "
                    f"Parallax {display_parallax:.1f}{' [LOCK]' if LOCK_CAMERA_PARALLAX else ''} | "
                    f"Enter: Save"
                )
                vb = VERTICAL_BASELINE_LAST_MATCH or {}
                painter.drawText(
                    20,
                    165 if not DEBUG_COMPARE_DYNAMIC_GEOMETRY else 290,
                    f"[VB] bucket={vb.get('bucket', '')} family={vb.get('family', '')} "
                    f"profile={str(vb.get('profile_key', ''))[:72]} | "
                    f"live s={vb.get('ballistic_speed', 0.0):.0f} c={vb.get('ballistic_caliber', 0.0):.3f} m={vb.get('ballistic_mass', 0.0):.3f} | "
                    f"entry s={vb.get('entry_speed', 0.0):.0f} c={vb.get('entry_caliber', 0.0):.3f} m={vb.get('entry_mass', 0.0):.3f}"
                )

            vel_dbg = self.live_velocity_debug or {}
            if vel_dbg:
                painter.setPen(QColor(*COLOR_CALIBRATION_HIT))
                vel_dbg = self.live_velocity_debug or {}
                my_dbg = vel_dbg.get("my") or {}
                tg_dbg = vel_dbg.get("target") or {}
                if DEBUG_COMPARE_DYNAMIC_GEOMETRY:
                    vel_dbg_y0 = 315
                elif DEBUG_DRAW_CALIBRATION_HIT:
                    vel_dbg_y0 = 190
                else:
                    vel_dbg_y0 = 140
                if DEBUG_VELOCITY:
                    painter.drawText(
                        20,
                        vel_dbg_y0,
                        f"[VEL-MY] src={my_dbg.get('source', '')} | "
                        f"raw={my_dbg.get('raw_kmh', 0.0):.1f} pos={my_dbg.get('pos_kmh', 0.0):.1f} chosen={my_dbg.get('chosen_kmh', 0.0):.1f} km/h | "
                        f"v=({(my_dbg.get('vec') or (0.0, 0.0, 0.0))[0]:.2f}, {(my_dbg.get('vec') or (0.0, 0.0, 0.0))[1]:.2f}, {(my_dbg.get('vec') or (0.0, 0.0, 0.0))[2]:.2f})"
                    )
                    painter.drawText(
                        20,
                        vel_dbg_y0 + 25,
                        f"[VEL-TG] src={tg_dbg.get('source', '')} | "
                        f"raw={tg_dbg.get('raw_kmh', 0.0):.1f} pos={tg_dbg.get('pos_kmh', 0.0):.1f} chosen={tg_dbg.get('chosen_kmh', 0.0):.1f} km/h | "
                        f"v=({(tg_dbg.get('vec') or (0.0, 0.0, 0.0))[0]:.2f}, {(tg_dbg.get('vec') or (0.0, 0.0, 0.0))[1]:.2f}, {(tg_dbg.get('vec') or (0.0, 0.0, 0.0))[2]:.2f})"
                    )

            if DEBUG_COMPARE_DYNAMIC_GEOMETRY and dynamic_compare_debug:
                painter.setPen(QColor(*COLOR_DYNAMIC_COMPARE_HIT))
                painter.drawText(
                    20,
                    165,
                    f"[CMP] {self._get_compare_visibility_mode().upper()} | "
                    f"VB:{dynamic_compare_debug['baseline_source']}:{dynamic_compare_debug.get('baseline_bucket', '')}/{dynamic_compare_debug.get('baseline_family', '')} "
                    f"{dynamic_compare_debug['baseline_value']:.2f} | "
                    f"DG:{'ON' if dynamic_compare_debug['dynamic_geometry_used'] else 'OFF'} | "
                    f"WS:{'ON' if dynamic_compare_debug.get('dynamic_worldspace_used') else 'OFF'} | "
                    f"Scale:{dynamic_compare_debug['dynamic_parallax_scale']:.2f}"
                )
                painter.drawText(
                    20,
                    190,
                    f"[CMP-PATH] B=unit_bbox+baseP | "
                    f"F={dynamic_compare_debug['target_box_source']}+baseP | "
                    f"D={dynamic_compare_debug['target_box_source']}+dynP"
                )
                painter.drawText(
                    20,
                    215,
                    f"[CMP-Δ] Src Dyn:{dynamic_compare_debug['target_box_source']} Base:{dynamic_compare_debug['fallback_box_source']} | "
                    f"ΔBase {dynamic_compare_debug['base_dist_px']:.2f} "
                    f"(dx {dynamic_compare_debug['base_dx_px']:.2f}, dy {dynamic_compare_debug['base_dy_px']:.2f}) | "
                    f"ΔFallback {dynamic_compare_debug['fallback_dist_px']:.2f} "
                    f"(dx {dynamic_compare_debug['fallback_dx_px']:.2f}, dy {dynamic_compare_debug['fallback_dy_px']:.2f}) | "
                    f"DynP {dynamic_compare_debug['dynamic_parallax']:.2f} | "
                    f"BaseP {dynamic_compare_debug['fallback_parallax']:.2f}"
                )
                dyn_terms = dynamic_compare_debug.get("dynamic_parallax_terms") or {}
                fb_terms = dynamic_compare_debug.get("fallback_parallax_terms") or {}
                painter.drawText(
                    20,
                    240,
                    f"[CMP-PY] Dyn downY {dyn_terms.get('down_y', 0.0):.3f} shiftY {dyn_terms.get('shift_y', 0.0):.3f} "
                    f"(scaled {dyn_terms.get('scaled_parallax', 0.0):.3f}) | "
                    f"Base downY {fb_terms.get('down_y', 0.0):.3f} shiftY {fb_terms.get('shift_y', 0.0):.3f} "
                    f"(scaled {fb_terms.get('scaled_parallax', 0.0):.3f})"
                )
                world_off = dynamic_compare_debug.get("dynamic_world_offset") or (0.0, 0.0, 0.0)
                painter.drawText(
                    20,
                    265,
                    f"[CMP-WS] Off({world_off[0]:.3f}, {world_off[1]:.3f}, {world_off[2]:.3f}) | "
                    f"ScreenΔ ({dynamic_compare_debug.get('dynamic_screen_dx', 0.0):.3f}, "
                    f"{dynamic_compare_debug.get('dynamic_screen_dy', 0.0):.3f})"
                )
                painter.drawText(
                    20,
                    290,
                    f"[CMP-VB] profile={str(dynamic_compare_debug.get('baseline_profile_key', ''))[:96]}"
                )
            elif DEBUG_COMPARE_DYNAMIC_GEOMETRY:
                painter.setPen(QColor(*COLOR_DYNAMIC_COMPARE_HIT))
                painter.drawText(
                    20,
                    165,
                    f"[CMP] {self._get_compare_visibility_mode().upper()} | "
                    f"VB:{VERTICAL_BASELINE_RUNTIME_SOURCE} | DG:{'ON' if my_dynamic_geometry else 'OFF'} | "
                    f"WS:OFF | "
                    f"Scale:{DYNAMIC_PARALLAX_SCALE:.2f}"
                )
                painter.drawText(
                    20,
                    190,
                    "[CMP-PATH] B=unit_bbox+baseP | F=dyn_bbox+baseP | D=dyn_bbox+dynP"
                )
                painter.drawText(
                    20,
                    215,
                    "[CMP-CTL] Left/Right: switch | Up: all | Down: off"
                )
            
            # ========================================================
            # 🔎 PICTURE-IN-PICTURE (PiP) SNIPER SCOPE RENDERER
            # ========================================================
            if ENABLE_SNIPER_MODE and active_sniper_data:
                try:
                    if float(active_sniper_data.get('distance', 0.0) or 0.0) < SNIPER_MIN_RANGE:
                        raise ValueError("sniper_min_range_skip")
                    cx = active_sniper_data['center_x']
                    cy = active_sniper_data['center_y']
                    t_hit = active_sniper_data['hitpoint']
                    sniper_box_rect = active_sniper_data.get('target_box_rect')
                    
                    # 1. คำนวณขนาดที่จะแคปเจอร์
                    base_cap_size = int(SNIPER_WINDOW_SIZE / SNIPER_ZOOM_SCALE)
                    cap_size = base_cap_size
                    if sniper_box_rect:
                        bx1, by1, bx2, by2 = sniper_box_rect
                        box_w = max(1.0, float(bx2) - float(bx1))
                        box_h = max(1.0, float(by2) - float(by1))
                        # ถ้าเป้าใหญ่กว่ากรอบ crop ปกติ ให้ขยายพื้นที่แคปเพื่อบีบเป้าลงมาให้พอดี PiP
                        target_span = max(box_w, box_h)
                        fit_cap_size = int(target_span * 1.12)
                        cap_size = max(cap_size, fit_cap_size)
                    cap_size = max(32, min(cap_size, self.screen_width, self.screen_height))
                    
                    # ป้องกันการแคปทะลุขอบจอ (ยึดจากจุดกึ่งกลางรถถังโดยตรง)
                    left = int(max(0, min(self.screen_width - cap_size, cx - cap_size / 2)))
                    top = int(max(0, min(self.screen_height - cap_size, cy - cap_size / 2)))
                    
                    # 2. สั่งแคปหน้าจอด้วย mss
                    monitor = {"top": top, "left": left, "width": cap_size, "height": cap_size}
                    img = self.sct.grab(monitor)
                    
                    # 🎯 FIX 1: ดึงภาพมาแค่ RGB เพียวๆ (ตัดปัญหา Alpha เฟดขาวทิ้ง 100%)
                    raw_rgb = img.rgb
                    
                    # 🎯 FIX 2: เปลี่ยนฟอร์แมตเป็น RGB888 (3 ไบต์ต่อพิกเซล) และใส่ .copy()
                    qimg = QImage(raw_rgb, img.width, img.height, img.width * 3, QImage.Format_RGB888)
                    
                    # 3. วาดภาพซูมลงมุมซ้ายบน
                    painter.drawImage(QRect(SNIPER_POS_X, SNIPER_POS_Y, SNIPER_WINDOW_SIZE, SNIPER_WINDOW_SIZE), qimg)
                    
                    # วาดกรอบ Scope สวยๆ
                    painter.setPen(QPen(QColor(*COLOR_BOX_SELECT_TARGET), 2))
                    painter.drawRect(SNIPER_POS_X, SNIPER_POS_Y, SNIPER_WINDOW_SIZE, SNIPER_WINDOW_SIZE)
                    
                    # 4. แปลงพิกัด Hitpoint ลงไปในกรอบ Sniper
                    hx_local = t_hit[0] - left
                    hy_local = t_hit[1] - top
                    
                    pip_hx = SNIPER_POS_X + (hx_local * SNIPER_ZOOM_SCALE)
                    pip_hy = SNIPER_POS_Y + (hy_local * SNIPER_ZOOM_SCALE)

                except Exception as e:
                    # ป้องกันโปรแกรมค้างหากแคปจอผิดพลาด
                    pass
                
            for ptr in [ptr for ptr in self.vel_window if ptr not in seen_targets_this_frame]:
                del self.vel_window[ptr]
            for ptr in [ptr for ptr in self.air_alert_seen if ptr not in seen_targets_this_frame]:
                del self.air_alert_seen[ptr]

        except Exception as e: 
            self._fatal_shutdown(
                f"main_loop_exception: {e.__class__.__name__}",
                traceback.format_exc(),
            )
        finally: 
            painter.end()

if __name__ == '__main__':
    try:
        # 🎯 เพิ่มบรรทัดนี้: ปิดระบบ OS Display Scaling ให้จอ 2560x1440 แมปพิกเซลแบบ 1:1 เสมอ
        QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)

        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        if base_addr == 0:
            raise RuntimeError(
                f"พบ PID ของเกมแล้ว ({pid}) แต่หา base address ของ binary 'aces' ไม่เจอ"
            )
        scanner = MemoryScanner(pid)
        
        # 🚀 THE MAGIC: สแกนหา Manager Offset อัตโนมัติก่อนเปิดเรดาร์!
        init_dynamic_offsets(scanner, base_addr)
        
        app = QApplication(sys.argv)
        overlay = ESPOverlay(scanner, base_addr)
        overlay.show()
        sys.exit(app.exec_())
    except RuntimeError as e:
        print("\n" + "=" * 72)
        print("❌ STARTUP ERROR")
        print("=" * 72)
        print(f"Reason : {e}")
        print("=" * 72)
        sys.exit(1)
    except Exception as e: 
        print("\n" + "=" * 72)
        print("❌ STARTUP ERROR")
        print("=" * 72)
        print(f"Reason : {e}")
        print("-" * 72)
        print(traceback.format_exc())
        print("=" * 72)
        sys.exit(1)
