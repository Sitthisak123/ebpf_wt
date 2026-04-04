import sys
import math
import time
import struct
import os
import json
import traceback
import mss
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QRect

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


def _console_supports_sticky_dashboard():
    try:
        term = os.environ.get("TERM", "").lower()
        return sys.stdout.isatty() and term not in ("", "dumb")
    except Exception:
        return False

COLOR_INFO_TEXT         = (255, 228, 64, 255)   
COLOR_BARREL_LINE       = (0, 255, 0, 255)      
COLOR_BOX_TARGET        = (255, 255, 0, 200)
COLOR_BOX_SELECT_TARGET = (0, 0, 0, 200)
COLOR_TEXT_GROUND       = (255, 196, 20, 200)    
COLOR_TEXT_AIR          = (255, 196, 20, 230)   
COLOR_RELOAD_BG         = (0, 0, 0, 180)        
COLOR_RELOAD_READY      = (255, 0, 0, 200)      
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
COLOR_BOX_HITPOINT      = (255, 40, 40, 230)
COLOR_DEBUG_MUZZLE_RAY  = (80, 255, 120, 220)
COLOR_DEBUG_BOX_ENTRY   = (255, 120, 40, 235)
COLOR_DEBUG_VIRTUAL_BOX = (255, 64, 255, 235)
COLOR_CALIBRATION_HIT   = (0, 150, 255, 255)
COLOR_CLASS_ICON_GROUND = (255, 215, 96, 235)
COLOR_CLASS_ICON_AIR    = (120, 220, 255, 235)

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

DEBUG_DRAW_MUZZLE_RAY = False
DEBUG_DRAW_BOX_ENTRY_HIT = False
DEBUG_DRAW_VIRTUAL_BOX = True

ESP_POINT_ONLY_MODE = False             # เปลี่ยนเป็น False เพื่อปิดโหมดวาดแค่จุด
GROUND_USE_SIMPLE_SCREEN_BOX = False    # เปลี่ยนเป็น False เพื่อปิดโหมดกล่อง 2D แบนๆ
AIR_USE_SIMPLE_SCREEN_BOX = False       # เปลี่ยนเป็น False

DRAW_BASE_HITPOINT = False
CALIBRATION_STEP_PIXELS = 0.05
CALIBRATION_STEP_FAST_PIXELS = 0.05
CALIBRATION_SAVE_PATH = os.path.join("dumps", "hitpoint_calibration_samples.jsonl")

GROUND_AIM_HEIGHT_RATIO_CLOSE = 0.50
GROUND_AIM_HEIGHT_RATIO_FAR = 0.75
GROUND_AIM_HEIGHT_RATIO_BLEND_MAX = 1200.0
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

# Leadmark / ballistic solver tuning
LEADMARK_RANGE_LIMIT_RATIO = 0.80  # ต่ำลง = ซ่อน leadmark เร็วขึ้นเมื่อเป้าไกลเกิน effective range
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

DEBUG_DRAW_CALIBRATION_HIT = True
HITPOINT_DYNAMIC_Y_CORRECTION_ENABLE = False  # ใช้ correction ที่ fit จาก calibration samples
HITPOINT_DYNAMIC_Y_C0 = 3.9466988621714605
HITPOINT_DYNAMIC_Y_C1_DISTANCE_KM = 0.9904876542040268
HITPOINT_DYNAMIC_Y_C2_SPEED_DELTA100 = -1.115741131934388
HITPOINT_DYNAMIC_Y_C3_DISTANCE_SPEED = 2.703058755910346
HITPOINT_DYNAMIC_Y_C4_CALIBER_DELTA_MM = 0.1640374544497992
HITPOINT_DYNAMIC_Y_MIN = 0.0
HITPOINT_DYNAMIC_Y_MAX = 20.0
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
SNIPER_ZOOM_SCALE = 3.5       # อัตราการซูม (เท่า)
SNIPER_WINDOW_SIZE = 350      # ขนาดกรอบหน้าต่าง Sniper (พิกเซล)
SNIPER_POS_X = 20             # ตำแหน่งแกน X (มุมซ้ายบน)
SNIPER_POS_Y = 220            # ตำแหน่งแกน Y (มุมซ้ายบน ถัดจากตัวหนังสือ)

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


def _map_aim_to_target_box_hitpoint(aim_screen, leadmark_screen, target_box_rect, target_pos=None, distance_to_target=0.0, my_rot=None, view_matrix=None, screen_w=1920, screen_h=1080, calibration_offset=(0.0, 0.0)):
    if not aim_screen or not leadmark_screen or not target_box_rect:
        return None

    min_x, min_y, max_x, max_y = target_box_rect
    box_h = max(max_y - min_y, 1.0)

    # 1. ระยะตก (Drop) จาก 2D Equation (นี่คือ UI Parallax ไม่ใช่แรงโน้มถ่วง 3D!)
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

    calib_x, calib_y = calibration_offset

    # 🎯 2. THE FLAWLESS MATRIX PROJECTION
    up_x, up_y = 0.0, -1.0 # ค่าเริ่มต้น: ชี้ขึ้นข้างบนจอ
    
    if my_rot and view_matrix and len(view_matrix) >= 16:
        up_wx, up_wy, up_wz = my_rot[3], my_rot[4], my_rot[5]
        
        # View Matrix 1D Array (16 elements)
        clip_x = (up_wx * view_matrix[0]) + (up_wy * view_matrix[4]) + (up_wz * view_matrix[8])
        clip_y = (up_wx * view_matrix[1]) + (up_wy * view_matrix[5]) + (up_wz * view_matrix[9])
        
        scr_vx = clip_x
        scr_vy = -clip_y
        
        mag = math.hypot(scr_vx, scr_vy)
        if mag > 0.001:
            up_x = scr_vx / mag
            up_y = scr_vy / mag

    # 🎯 3. สร้างแกนทิศทาง "ลง" (Down) และ "ขวา" (Right) อ้างอิงตามรถถังบนหน้าจอ
    down_x = -up_x
    down_y = -up_y
    right_x = -up_y
    right_y = up_x

    # 🎯 4. THE MASTERSTROKE: มัดรวม Parallax หน้าจอทั้งหมด!
    # เราต้องเอาระยะตก UI (drop_pixels_y) ไปหมุนด้วย เพราะสเกลของเป้า Crosshair มันเอียงตามกล้อง!
    total_parallax_y = drop_pixels_y + calib_y

    rot_x = (calib_x * right_x) + (total_parallax_y * down_x)
    rot_y = (calib_x * right_y) + (total_parallax_y * down_y)

    # 🎯 5. รวมพิกัด (ดึง drop_pixels_y ที่บวกแยกออก เพราะมันถูกบวกใน rot_y ไปแล้ว)
    final_x = base_x + dx + rot_x
    final_y = base_y + dy + rot_y

    return (final_x, final_y)


def _apply_dynamic_hitpoint_y_correction(hitpoint, profile, distance_to_target):
    if not HITPOINT_DYNAMIC_Y_CORRECTION_ENABLE or not hitpoint:
        return hitpoint
    model_enum = int(profile.get("model_enum", 0) or 0)
    speed = float(profile.get("speed", 0.0) or 0.0)
    caliber = float(profile.get("caliber", 0.0) or 0.0)
    mass = float(profile.get("mass", 0.0) or 0.0)
    if model_enum not in (0, 4):
        return hitpoint
    if not _is_subcaliber_ballistic(speed, caliber, mass):
        return hitpoint

    distance_km = max(0.0, float(distance_to_target or 0.0) / 1000.0)
    speed_delta100 = max(0.0, speed - 1500.0) / 100.0
    caliber_delta_mm = max(0.0, caliber - 0.016) / 0.001
    y_up = (
        HITPOINT_DYNAMIC_Y_C0 +
        (HITPOINT_DYNAMIC_Y_C1_DISTANCE_KM * distance_km) +
        (HITPOINT_DYNAMIC_Y_C2_SPEED_DELTA100 * speed_delta100) +
        (HITPOINT_DYNAMIC_Y_C3_DISTANCE_SPEED * distance_km * speed_delta100) +
        (HITPOINT_DYNAMIC_Y_C4_CALIBER_DELTA_MM * caliber_delta_mm)
    )
    y_up = max(HITPOINT_DYNAMIC_Y_MIN, min(HITPOINT_DYNAMIC_Y_MAX, y_up))
    return (hitpoint[0], hitpoint[1] - y_up)


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
    half = max(5, int(size * 0.5))
    is_air = unit_family in (
        UNIT_FAMILY_AIR_FIGHTER,
        UNIT_FAMILY_AIR_BOMBER,
        UNIT_FAMILY_AIR_ATTACKER,
        UNIT_FAMILY_AIR_HELICOPTER,
    )
    color = QColor(*(COLOR_CLASS_ICON_AIR if is_air else COLOR_CLASS_ICON_GROUND))
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.NoBrush)

    if unit_family == UNIT_FAMILY_GROUND_MEDIUM_TANK:
        painter.drawRect(int(center_x - half), int(center_y - 2), int(half * 2), 5)
        painter.drawRect(int(center_x - 4), int(center_y - 7), 8, 4)
        painter.drawLine(int(center_x + 4), int(center_y - 5), int(center_x + half + 5), int(center_y - 5))
        painter.drawLine(int(center_x - half), int(center_y + 4), int(center_x + half), int(center_y + 4))
        return

    if unit_family == UNIT_FAMILY_GROUND_HEAVY_TANK:
        painter.drawRect(int(center_x - half), int(center_y - 3), int(half * 2), 7)
        painter.drawRect(int(center_x - 5), int(center_y - 10), 10, 5)
        painter.drawLine(int(center_x + 5), int(center_y - 8), int(center_x + half + 6), int(center_y - 8))
        painter.drawLine(int(center_x - half + 1), int(center_y + 5), int(center_x + half - 1), int(center_y + 5))
        painter.drawLine(int(center_x - half + 3), int(center_y + 8), int(center_x + half - 3), int(center_y + 8))
        return

    if unit_family == UNIT_FAMILY_GROUND_SPAA:
        painter.drawRect(int(center_x - half), int(center_y - 3), int(half * 2), 6)
        painter.drawRect(int(center_x - 4), int(center_y - 8), 8, 5)
        painter.drawLine(int(center_x + 2), int(center_y - 7), int(center_x + half + 2), int(center_y - 10))
        painter.drawLine(int(center_x - 2), int(center_y - 7), int(center_x - half - 2), int(center_y - 10))
        painter.drawLine(int(center_x), int(center_y - 12), int(center_x), int(center_y - 4))
        return

    if unit_family == UNIT_FAMILY_GROUND_TANK_DESTROYER:
        painter.drawLine(int(center_x - half), int(center_y + 3), int(center_x + half), int(center_y + 3))
        painter.drawLine(int(center_x - half), int(center_y + 3), int(center_x - 2), int(center_y - 6))
        painter.drawLine(int(center_x - 2), int(center_y - 6), int(center_x + half), int(center_y - 3))
        painter.drawLine(int(center_x + 1), int(center_y - 5), int(center_x + half + 6), int(center_y - 7))
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
        self.dead_unit_latch = set()
        self.ballistic_zero_cache = {}
        self.invalid_runtime_frames = 0
        self.shutdown_requested = False
        self.startup_time = time.time()
        self.calibration_offset = [0.0, 0.0]
        self.calibration_last_keys = {
            "enter": False,
            "backspace": False,
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
            self.close()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _update_screen_metrics(self):
        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.geometry() if screen is not None else QApplication.desktop().screenGeometry()
        self.screen_width = geometry.width()
        self.screen_height = geometry.height()
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

    def _handle_hitpoint_calibration(self, context):
        if not DEBUG_DRAW_CALIBRATION_HIT or not context:
            return None

        # 🎯 1. ดึงสถานะปุ่มปัจจุบัน (ใช้ชื่อปุ่มมาตรฐานของ lib keyboard)
        enter_now = self._keyboard_down("enter")
        
        # 🎯 2. [Logic Gate] ล็อกไม่ให้ขยับจุดถ้ากำลังกด Enter เพื่อป้องกันพิกัดกระโดด
        if not enter_now:
            is_shift = self._keyboard_down("shift") or self._keyboard_down("right shift")
            step = CALIBRATION_STEP_FAST_PIXELS if is_shift else CALIBRATION_STEP_PIXELS
            
            # ⬅️ เปลี่ยนมาใช้ปุ่มลูกศร (Arrow Keys)
            if self._keyboard_down("left"):
                self.calibration_offset[0] -= step
            elif self._keyboard_down("right"):
                self.calibration_offset[0] += step
                
            if self._keyboard_down("up"):
                self.calibration_offset[1] -= step
            elif self._keyboard_down("down"):
                self.calibration_offset[1] += step

            # 🔄 ปุ่มรีเซ็ตและอัปเดตสถานะ (Backspace)
            backspace_now = self._keyboard_down("backspace")
            if backspace_now and not self.calibration_last_keys.get("backspace", False):
                self.calibration_offset = [0.0, 0.0]
                print("[CALIB] offset reset")
            self.calibration_last_keys["backspace"] = backspace_now

        # 🎯 3. ไม่ต้องบวกเพิ่มแล้ว ดึงพิกัดที่หมุนแกนมาแล้วไปใช้ได้เลย!
        calib_x = context["base_hitpoint"][0]
        calib_y = context["base_hitpoint"][1]

        # 🎯 4. ระบบบันทึกข้อมูล (Single-Shot Trigger)
        if enter_now and not self.calibration_last_keys.get("enter", False):
            sample = {
                "captured_at": time.time(),
                "unit_ptr": context.get("unit_ptr", 0),
                "unit_key": context.get("unit_key", ""),
                "distance": context.get("distance", 0.0),
                "model_enum": context.get("model_enum", 0),
                "speed": context.get("speed", 0.0),
                "caliber": context.get("caliber", 0.0),
                "calibration_offset": [round(self.calibration_offset[0], 3), round(self.calibration_offset[1], 3)],
            }
            self._save_calibration_sample(sample)
            print(f"[CALIB] SUCCESS: Saved offset {self.calibration_offset}")

        # อัปเดตสถานะปุ่ม Enter สำหรับเฟรมถัดไป
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
            raw_nonzero_axes = sum(1 for v in raw_vel if abs(v) > 0.05)
            pos_nonzero_axes = sum(1 for v in pos_vel if abs(v) > 0.05)

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
            elif raw_mag > 0.001:
                chosen_vel = (
                    (raw_vel[0] * 0.65) + (pos_vel[0] * 0.35),
                    (raw_vel[1] * 0.65) + (pos_vel[1] * 0.35),
                    (raw_vel[2] * 0.65) + (pos_vel[2] * 0.35),
                )
                source = "blended"

        if not is_air:
            # Ground units often have tiny noisy vectors around zero.
            idle_speed_enter = 0.22  # m/s (~0.8 km/h)
            idle_speed_exit = 0.38
            idle_speed = idle_speed_exit if prev_meta.get("source") == "ground_idle" else idle_speed_enter
            if raw_mag <= idle_speed and (pos_vel is None or pos_mag <= idle_speed):
                chosen_vel = (0.0, 0.0, 0.0)
                source = "ground_idle"
            else:
                # Ground lead solver should not react to suspension / axis-layout noise as vertical motion.
                chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
            chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)

            # Ground world velocity is derived from noisy local raw fields + short-frame position deltas.
            # Smooth the final vector to prevent source flapping and visible jitter on moving vehicles.
            prev_vel = cached.get('vel') if cached else None
            if prev_vel and len(prev_vel) == 3 and source != "ground_idle":
                prev_mag = math.sqrt(prev_vel[0]**2 + prev_vel[1]**2 + prev_vel[2]**2)
                if prev_mag > 0.0 or raw_mag > idle_speed_exit or pos_mag > idle_speed_exit:
                    smoothing = 0.78 if source.startswith("pos_") else 0.68
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
        lead_marks_to_draw = []
        hit_points_to_draw = []
        debug_muzzle_rays_to_draw = []
        debug_box_entry_hits_to_draw = []
        debug_virtual_boxes_to_draw = []
        calibration_hit_points_to_draw = []
        
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
            my_ground_shot_origin = my_pos
            if my_unit and my_pos and not my_is_air:
                try:
                    my_box_data = get_unit_3d_box_data(self.scanner, my_unit, False)
                    if my_box_data:
                        my_barrel_data = get_weapon_barrel(self.scanner, my_unit, my_box_data[0], my_box_data[3])
                        if my_barrel_data:
                            my_ground_shot_origin = my_barrel_data[1] or my_barrel_data[0] or my_pos
                except Exception:
                    my_ground_shot_origin = my_pos

            if my_unit != self.last_my_unit:
                reset_runtime_caches(clear_view=True)
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
                        select_box_data = get_unit_3d_box_data(self.scanner, u_ptr, False)
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
                    visible_targets.append((dist_crosshair, u_ptr))

            if visible_targets:
                visible_targets.sort(key=lambda item: item[0])
                active_target_ptr = visible_targets[0][1]
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

                    display_is_air = physics_is_air
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
                            int(icon_y),
                            unit_family,
                            CLASS_ICON_SIZE,
                        )
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

                    leadmark_in_range = (
                        leadmark_range_limit <= 0.0 or dist <= leadmark_range_limit
                    )

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

                    # 📉 Gravity Drop Compensation: 0.5 * g * t^2
                    gravity_offset = 0.5 * BULLET_GRAVITY * (best_t ** 2)
                    
                    # 🎯 แรงโน้มถ่วงดึงลงตรงๆ แกน Y ของโลกเท่านั้น!
                    final_y += gravity_offset                  
                    final_y -= sight_drop_comp
                    
                    # หักลบความเร็วรถถังเราออก (Galilean Relativity)
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
                        my_vel_meta = self.last_velocity_meta.get(my_unit, {})
                        my_vel_source = my_vel_meta.get('source', 'raw')
                        my_speed = math.sqrt(my_vx**2 + my_vy**2 + my_vz**2) * 3.6
                        target_speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                        accel_mag = math.sqrt(ax**2 + ay**2 + az**2)
                        
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

                    static_ground_final = None
                    if (not physics_is_air) and leadmark_in_range:
                        static_ground_final = _solve_static_ground_leadmark(
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

                    target_vel_mag = math.sqrt(vx**2 + vy**2 + vz**2)

                    static_screen = None
                    if (not physics_is_air) and leadmark_in_range and static_ground_final and all(math.isfinite(c) for c in static_ground_final):
                        target_anchor_screen = world_to_screen(
                            view_matrix,
                            t_x,
                            t_y,
                            t_z,
                            self.screen_width,
                            self.screen_height,
                        )
                        static_screen = world_to_screen(
                            view_matrix,
                            static_ground_final[0],
                            static_ground_final[1],
                            static_ground_final[2],
                            self.screen_width,
                            self.screen_height,
                        )
                        if static_screen and static_screen[2] > 0:
                            spx, spy = static_screen[0], static_screen[1]
                                
                            if u_ptr == active_target_ptr and target_box_rect:
                                if DEBUG_DRAW_VIRTUAL_BOX:
                                    min_x, min_y, max_x, max_y = target_box_rect
                                    box_w = max(max_x - min_x, 1.0)
                                    box_h = max(max_y - min_y, 1.0)
                                    anchor_u = 0.5
                                    anchor_v = 0.5
                                    if target_anchor_screen:
                                        tx, ty = target_anchor_screen[0], target_anchor_screen[1]
                                        if min_y <= ty <= max_y:
                                            anchor_v = (ty - min_y) / box_h
                                    dist_t = max(0.0, min(1.0, dist / max(GROUND_HITPOINT_DROP_RANGE, 1.0)))
                                    exp_t = (math.exp(dist_t) - 1.0) / (math.e - 1.0)
                                    anchor_v = min(0.98, anchor_v + GROUND_HITPOINT_DROP_BASE + (GROUND_HITPOINT_DROP_EXP * exp_t))
                                    
                                    # 🎯 FIX: เปลี่ยนจาก box_center_x เป็น spx (ให้กล่องวิ่งซ้าย/ขวาตามจุดเผื่อยิง)
                                    virtual_min_x = spx - (anchor_u * box_w)
                                    virtual_min_y = spy - (anchor_v * box_h)
                                    
                                    # 🎯 ดึงมุมกล่อง 3D ปัจจุบัน แล้วนำมา Shift (เลื่อน 2D) ตามเป้าดักยิง
                                    curr_bmin, curr_bmax = get_unit_bbox(self.scanner, u_ptr)
                                    curr_rot = get_unit_rotation(self.scanner, u_ptr)
                                    
                                    dx = virtual_min_x - min_x
                                    dy = virtual_min_y - min_y
                                    
                                    if curr_bmin and curr_bmax and curr_rot:
                                        local_corners = [
                                            (curr_bmin[0], curr_bmin[1], curr_bmin[2]), (curr_bmin[0], curr_bmin[1], curr_bmax[2]),
                                            (curr_bmin[0], curr_bmax[1], curr_bmin[2]), (curr_bmin[0], curr_bmax[1], curr_bmax[2]),
                                            (curr_bmax[0], curr_bmin[1], curr_bmin[2]), (curr_bmax[0], curr_bmin[1], curr_bmax[2]),
                                            (curr_bmax[0], curr_bmax[1], curr_bmin[2]), (curr_bmax[0], curr_bmax[1], curr_bmax[2])
                                        ]
                                        shifted_pts = []
                                        for c in local_corners:
                                            world_x = pos[0] + (c[0]*curr_rot[0] + c[1]*curr_rot[3] + c[2]*curr_rot[6])
                                            world_y = pos[1] + (c[0]*curr_rot[1] + c[1]*curr_rot[4] + c[2]*curr_rot[7])
                                            world_z = pos[2] + (c[0]*curr_rot[2] + c[1]*curr_rot[5] + c[2]*curr_rot[8])
                                            scr = world_to_screen(view_matrix, world_x, world_y, world_z, self.screen_width, self.screen_height)
                                            if scr and scr[2] > 0:
                                                shifted_pts.append((scr[0] + dx, scr[1] + dy))
                                        
                                        if len(shifted_pts) == 8:
                                            debug_virtual_boxes_to_draw.append(shifted_pts)
                                        else:
                                            debug_virtual_boxes_to_draw.append((virtual_min_x, virtual_min_y, virtual_min_x + box_w, virtual_min_y + box_h))
                                    else:
                                        virtual_max_x = virtual_min_x + box_w
                                        virtual_max_y = virtual_min_y + box_h
                                        debug_virtual_boxes_to_draw.append((
                                            virtual_min_x,
                                            virtual_min_y,
                                            virtual_max_x,
                                            virtual_max_y,
                                        ))
                                mapped_hitpoint = _map_aim_to_target_box_hitpoint(
                                    (self.center_x, self.center_y),
                                    (spx, spy),
                                    target_box_rect,
                                    (t_x, t_y, t_z),    
                                    dist,
                                    my_rot,
                                    view_matrix,        
                                    self.screen_width,  
                                    self.screen_height,
                                    self.calibration_offset  # 🎯 ส่งตัวแปรนี้เพิ่มเข้าไปท้ายสุด!
                                )
                                if mapped_hitpoint:
                                    mapped_hitpoint = _apply_dynamic_hitpoint_y_correction(
                                        mapped_hitpoint,
                                        ballistic_profile,
                                        dist,
                                    )
                                    if DRAW_BASE_HITPOINT:
                                        hit_points_to_draw.append(mapped_hitpoint)
                                        
                                    # 🎯 FIX 1: เก็บข้อมูล Sniper ทันทีถ้าเป็นเป้าหมายหลัก
                                    if u_ptr == active_target_ptr:
                                        active_sniper_data = {
                                            'center_x': avg_x,
                                            'center_y': avg_y,
                                            'hitpoint': mapped_hitpoint
                                        }

                                    calib_point = self._handle_hitpoint_calibration({
                                        "unit_ptr": u_ptr,
                                        "unit_label": unit_name,
                                        "unit_key": dna.get("name_key", ""),
                                        "distance": dist,
                                        "zeroing": current_zeroing,
                                        "model_enum": ballistic_profile.get("model_enum", 0),
                                        "speed": ballistic_profile.get("speed", 0.0),
                                        "mass": ballistic_profile.get("mass", 0.0),
                                        "caliber": ballistic_profile.get("caliber", 0.0),
                                        "cx": ballistic_profile.get("cx", 0.0),
                                        "drag_k": ballistic_model.get("drag_k", 0.0),
                                        "base_hitpoint": mapped_hitpoint,
                                    })
                                    if calib_point:
                                        calibration_hit_points_to_draw.append(calib_point)
                                    if DRAW_BASE_HITPOINT and DEBUG_DRAW_BOX_ENTRY_HIT:
                                        debug_box_entry_hits_to_draw.append(mapped_hitpoint)
                                if DEBUG_DRAW_MUZZLE_RAY:
                                    fire_origin_screen = world_to_screen(
                                        view_matrix,
                                        fire_origin[0],
                                        fire_origin[1],
                                        fire_origin[2],
                                        self.screen_width,
                                        self.screen_height,
                                    )
                                    if fire_origin_screen and fire_origin_screen[2] > 0:
                                        debug_muzzle_rays_to_draw.append({
                                            "sx": fire_origin_screen[0],
                                            "sy": fire_origin_screen[1],
                                            "px": spx,
                                            "py": spy,
                                        })

                            if target_vel_mag > 0.05 and math.isfinite(spx) and math.isfinite(spy):
                                lead_marks_to_draw.append({
                                    'sx': avg_x,
                                    'sy': avg_y,
                                    'px': spx,
                                    'py': spy,
                                    'is_air': False,
                                    'is_turning': False,
                                    'style': 'ground_static',
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
                if lm.get('style') == 'ground_static':
                    pred_color = QColor(*COLOR_PREDICTION_GROUND_STATIC)
                    line_pts = _screen_int_tuple(lm['sx'], lm['sy'], lm['px'], lm['py'])
                    center_pts = _screen_int_tuple(lm['px'], lm['py'])
                    if not line_pts or not center_pts:
                        continue
                    painter.setPen(QPen(pred_color, 2, Qt.DotLine))
                    painter.drawLine(*line_pts)
                    _draw_leadmark_glyph(painter, center_pts[0], center_pts[1], pred_color, outer_radius=6, core_radius=2, pen_width=2)
                    continue

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

            for hp_x, hp_y in hit_points_to_draw:
                hp_pts = _screen_int_tuple(hp_x, hp_y)
                if not hp_pts:
                    continue
                hit_color = QColor(*COLOR_BOX_HITPOINT)
                painter.setPen(QPen(hit_color, 3))
                painter.drawEllipse(hp_pts[0] - 7, hp_pts[1] - 7, 14, 14)
                painter.drawLine(hp_pts[0] - 10, hp_pts[1], hp_pts[0] + 10, hp_pts[1])
                painter.drawLine(hp_pts[0], hp_pts[1] - 10, hp_pts[0], hp_pts[1] + 10)

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

            if DEBUG_DRAW_VIRTUAL_BOX:
                virtual_color = QColor(*COLOR_DEBUG_VIRTUAL_BOX)
                painter.setPen(QPen(virtual_color, 2, Qt.DashDotLine))
                for box_item in debug_virtual_boxes_to_draw:
                    if len(box_item) == 8:
                        # วาด 3D Wireframe (8 มุม)
                        edges = [
                            (0,1), (0,2), (1,3), (2,3), # ฐานล่าง
                            (4,5), (4,6), (5,7), (6,7), # ฐานบน
                            (0,4), (1,5), (2,6), (3,7)  # เสาแนวตั้ง
                        ]
                        for p1, p2 in edges:
                            painter.drawLine(int(box_item[p1][0]), int(box_item[p1][1]), int(box_item[p2][0]), int(box_item[p2][1]))
                    elif len(box_item) == 4:
                        # วาดกล่อง 2D (4 ค่า) กรณี Fallback
                        rect_pts = _screen_int_tuple(*box_item)
                        if rect_pts:
                            rect_x1, rect_y1, rect_x2, rect_y2 = rect_pts
                            painter.drawRect(rect_x1, rect_y1, rect_x2 - rect_x1, rect_y2 - rect_y1)

            if DEBUG_DRAW_CALIBRATION_HIT:
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
                    
                painter.setPen(calib_color)
                painter.drawText(20, 140, "[CALIB] I/J/K/L move | Shift fast | Backspace reset | Enter save")
            
            # ========================================================
            # 🔎 PICTURE-IN-PICTURE (PiP) SNIPER SCOPE RENDERER
            # ========================================================
            if ENABLE_SNIPER_MODE and active_sniper_data:
                try:
                    cx = active_sniper_data['center_x']
                    cy = active_sniper_data['center_y']
                    t_hit = active_sniper_data['hitpoint']
                    
                    # 1. คำนวณขนาดที่จะแคปเจอร์
                    cap_size = int(SNIPER_WINDOW_SIZE / SNIPER_ZOOM_SCALE)
                    
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

        except Exception as e: 
            self._fatal_shutdown(
                f"main_loop_exception: {e.__class__.__name__}",
                traceback.format_exc(),
            )
        finally: 
            painter.end()

if __name__ == '__main__':
    try:
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
