import struct
import math
import os
import time
from typing import Tuple, Optional, Dict, List, Any

try:
    from src.utils.debug import dprint
except Exception:
    def dprint(msg, force=False):
        return

# ===================================================
# 🎯 2026 VERIFIED OFFSETS (อัปเดตล่าสุด)
# ===================================================
GHIDRA_BASE         = 0x400000
DAT_MANAGER         = 0xb02b1c0
MANAGER_OFFSET      = 0xac2b1c0
MANAGER_CANDIDATE_OFFSETS = [0xac2b1c0, 0xac2b1a8, 0xac28160, 0xac27160]
DAT_CONTROLLED_UNIT = 0xb02d508

OFF_CAMERA_PTR      = 0x660
OFF_VIEW_MATRIX     = 0x1D8

OFF_UNIT_X          = 0x0D38
OFF_UNIT_ROTATION   = OFF_UNIT_X - 0x24
OFF_UNIT_BBMIN      = 0x0260
OFF_UNIT_BBMAX      = 0x026C
_BBOX_FALLBACK_LOGGED = set()

# 🟢 สถานะและข้อมูลของยูนิต (เพิ่งอัปเดตใหม่)
OFF_UNIT_ID         = 0x08      # Session Unit ID (u16) ตรงกับ target_id ของขีปนาวุธ
OFF_UNIT_STATE      = 0x0F90    # สถานะรถถัง (เป็น/ตาย: 0=alive, 1=burning, >=2 dead)
OFF_UNIT_TEAM       = 0x1010    # ทีม (มิตร/ศัตรู: 1=friendly, 2=enemy)
OFF_UNIT_INFO       = 0x1020    # 🎯 ฐานข้อมูล Unit Info
OFF_PLAYER_INFO     = 0x0F98    # 👤 Pointer ไปยัง PlayerInfo (Human Player)
OFF_INFO_NAME_KEY   = 0x40         # 📛 Key สำหรับชื่อจริง (Localized)
OFF_INFO_SHORT_NAME = 0x28         # 🏷️ ชื่อย่อยูนิต (เช่น T-34-85)
OFF_INFO_FAMILY     = 0x38         # 📂 ตระกูลยูนิต (เช่น exp_tank)
OFF_INFO_STATUS     = 0x290        # 📊 สถานะพิเศษ (Class ID)
OFF_UNIT_NATION     = 0x98c        # 🏳️ ID ประเทศ
OFF_UNIT_INVUL      = 0x0E90       # 🛡️ สถานะอมตะ (Is Invulnerable - 0x0E90)
OFF_UNIT_TYPE       = 0x80         # ✈️ Unit Type discriminator (0x80=1, 0x84=2 for Air; 0 for Ground)
OFF_UNIT_CLASS_PTR  = 0      # 🎯 Pointer ไปหาประเภทรถ (เช่น Light tank, Medium tank)

OFF_UNIT_TYPE_PTR   = 0      # 🎯 Pointer ไปหาชนิด (เช่น exp_tank)
OFF_UNIT_NAME_PTR   = 0x28   # 🎯 Pointer ไปหาชื่อย่อ (เช่น ussr_2s38)
OFF_UNIT_RELOADING  = 0
OFF_UNIT_RELOAD     = 0

OFF_ACTIVE_UNITS    = (0x310, True, 0x10)   # Air units (active count at +0x10)
OFF_ACTIVE_EXTRA_UNIT_LISTS = (
    (0x328, False, 0x10),  # Ground units (active count at +0x10)
)
ENABLE_WORLD_UNIT_LIST_FALLBACK = True
OFF_AIR_UNITS       = (0x310, True)
OFF_AIR_MOVEMENT    = 0x0018      # 🎯 Air-specific movement ptr from air kinematics dumpers (Legacy net)
OFF_AIR_VEL         = 0x0318      # 🎯 Velocity (FLOAT Vector 12-byte)
OFF_AIR_OMEGA       = 0x0550      # 🌪️ Angular Velocity (Updated 2026-09: 0x0550 FLOAT vec3)
OFF_AIR_HIGH_TICK_MOVEMENT = 0x20F0  # 🚀 High-Tick Target Air Movement pointer (41-43 Hz 3D World Vec)
OFF_AIR_HIGH_TICK_VEL      = 0x07C0  # 🚀 High-Tick Air 3D Velocity (FLOAT vec3)
OFF_MY_AIR_VEL      = 0x0068      # My air velocity: DOUBLE vec3 at move_ptr + 0x0068 (47.5Hz)
OFF_MY_AIR_MOVEMENT = 0x0D48      # My air movement pointer (Updated 2026-09: 0x0D48 / 0x0D50)
OFF_MY_AIR_OMEGA    = 0x0098      # 🌪️ My air angular velocity: DOUBLE vec3 at move_ptr + 0x0098 (Updated 2026-09)

# 🚀 Missile/Rocket Projectile & ECS Offsets (confirmed 2026-09)
OFF_PROJ_LIST       = 0xac02ab8   # base + this → pointer to active projectile table (Tab<Projectile>)
OFF_ECS_MANAGER     = 0x8ccd918   # base + this → ECS manager ptr (fallback/multiplayer confirmed 2026-09)
OFF_ECS_NODE_TABLE  = 0x178       # manager + this → node_table ptr
OFF_ECS_CLASS_TABLE = 0x5E8       # manager + this → class_table ptr
OFF_RKT_ENTITY_ID   = 0x40        # rocket + this → entity id (u32)
OFF_RKT_OWNER       = 0x50        # rocket + this → owner unit pointer (u_ptr | 1)
OFF_RKT_STATE       = 0x94        # rocket + this → state byte
OFF_RKT_POS         = 0x23c       # rocket + this → Vec3 position
OFF_RKT_VEL         = 0x258       # rocket + this → Vec3 velocity
OFF_RKT_DETONATED   = 0x420       # rocket + this → detonation/impact flag (0 = flying, non-zero = detonated)
OFF_RKT_PHASE       = 0x498       # rocket + this → projectile phase (3 = in-flight, 6 = terminated/impacted)
OFF_RKT_GUIDANCE    = 0x680       # rocket + this → guidance struct ptr (updated from 0x670)
OFF_RKT_ALIVE       = 0x6d0       # rocket + this → is_alive (updated from 0x6c0)
OFF_RKT_PROPS       = 0x710       # rocket + this → props ptr (name at +0x28 / +0x50) (updated from 0x700)
OFF_GUID_LOCKED     = 0x4C        # guidance + this → isLocked byte (updated from 0x50)
OFF_GUID_TRACKING   = 0x4D        # guidance + this → isTracking byte (updated from 0x51)
OFF_GUID_TARGET_ID  = 0x84        # guidance + this → target unit id (i16) (updated from 0x8C)

OFF_GROUND_UNITS    = (0x328, False)
OFF_GROUND_MOVEMENT = 0x0D30
OFF_GROUND_VEL      = 0x0068
OFF_GROUND_OMEGA    = 0
FILTER_ZERO_POS_UNITS = True
# 🔫 ระบบขีปนาวุธ (BALLISTICS - อัปเดตโครงสร้าง 2.59+ เลื่อน +0x20)
OFF_WEAPON_PTR      = 0x3f0        # 🎯 อัปเดตจากผลสแกน Ballistic
OFF_CCIP_IMPACT     = 0x1CCC       # 🎯 vec3_t (x, y, z) CCIP Impact Point จาก Dagor Engine (เดิม 0x1CBC / 0x1C9C)
OFF_BULLET_SPEED    = 0x2118       # 🎯 ความเร็วต้น (Muzzle Velocity - เดิม 0x2108 / 0x20E8)
OFF_BULLET_MASS     = 0x2124       # ⚖️ มวลกระสุน (เดิม 0x2114 / 0x20F4)
OFF_BULLET_CALIBER  = 0x2128       # 📏 Caliber เมตร (เดิม 0x2118 / 0x20F8)
OFF_BULLET_CD       = 0x212C       # 💨 Drag Coeff (เดิม 0x211C / 0x20FC)

OFF_INVUL_TIMER     = 0x0E6C       # 🛡️ นับถอยหลังอมตะเกิดใหม่ (วินาที)
OFF_INVULNERABLE    = 0x0E90       # 🛡️ แฟล็กอมตะเกิดใหม่ (bool)
OFF_PLAYER_INFO     = 0x0F98       # 👤 พอยเตอร์ PlayerInfo (มีค่าเฉพาะผู้เล่นจริง, บอท/ซากเป็น Null)


OFF_WEAPON_BARREL   = 0x480  # 🎯 ตัวคูณทิศทางลำกล้อง
PROJECTION_MODES = (
    ("xyz_col", False, (0, 1, 2)),
    ("xzy_col", False, (0, 2, 1)),
    ("yxz_col", False, (1, 0, 2)),
    ("yzx_col", False, (1, 2, 0)),
    ("zxy_col", False, (2, 0, 1)),
    ("zyx_col", False, (2, 1, 0)),
    ("xyz_row", True, (0, 1, 2)),
    ("xzy_row", True, (0, 2, 1)),
    ("yxz_row", True, (1, 0, 2)),
    ("yzx_row", True, (1, 2, 0)),
    ("zxy_row", True, (2, 0, 1)),
    ("zyx_row", True, (2, 1, 0)),
)
AXIS_SIGN_VARIANTS = {
    "+++": (1.0, 1.0, 1.0),
    "-++": (-1.0, 1.0, 1.0),
    "+-+": (1.0, -1.0, 1.0),
    "++-": (1.0, 1.0, -1.0),
    "--+": (-1.0, -1.0, 1.0),
    "-+-": (-1.0, 1.0, -1.0),
    "+--": (1.0, -1.0, -1.0),
    "---": (-1.0, -1.0, -1.0),
}

SIGHT_POINTER_CHAINS = [
    [0x13C50, -0x64C0, 0x1780, 0x1C28],
    [0x123E0, -0x37B8, 0x1780, 0x1C28],
    [0x13260, -0x4680, 0x1780, 0x1C28],
    [0x133D0, -0x4E40, 0x13D0, 0x7088],
    [0x13B88, -0x5140, 0x13D0, 0x7088],
    [0x13E68, -0x75F0, 0x13D0, 0x7088]
]

def is_valid_ptr(p):
    if not isinstance(p, int):
        return False
    return 0x10000 < p < 0x7FFFFFFFFFFF

_is_valid_ptr = is_valid_ptr


UNIT_KIND_CACHE = {}
LAST_CGAME_PTR = 0
LAST_VIEW_MATRIX = None
LAST_VIEW_PROJECTION_MODE = None
FORCED_VIEW_PROFILE = None
UNIT_FILTER_CACHE = {}
VELOCITY_SPEC_CACHE = {}
VELOCITY_LOG_CACHE = {}

PLAYABLE_AIR_TAGS = {
    "exp_fighter",
    "exp_bomber",
    "exp_helicopter",
    "exp_assault",
    "exp_attacker",
}

PLAYABLE_GROUND_TAGS = {
    "exp_tank",
    "exp_heavy_tank",
    "exp_tank_destroyer",
    "exp_spaa",
}

PLAYABLE_NAVAL_TAGS = {
    "exp_torpedo_boat",
    "exp_torpedo_gun_boat",
    "exp_gun_boat",
    "exp_destroyer",
    "exp_cruiser",
}

NON_PLAYABLE_TAGS = {
    "exp_structure",
    "exp_zero",
    "exp_aaa",
    "exp_fortification",
}

NON_PLAYABLE_PATH_HINTS = (
    "air_defence/",
    "/air_defence/",
    "structures/",
    "/structures/",
    "infantry/",
    "/infantry/",
    "dummy_plane",
)

NON_PLAYABLE_NAME_HINTS = (
    "dummy",
    "windmill",
    "airfield",
    "noground",
    "_noground",
    "controlled_",
    "controlled_technic",
    "technic",
    "birthday",
    "hangar",
)

NON_PLAYABLE_PATH_BLOCKLIST = (
    "air_defence/",
    "/air_defence/",
    "structures/",
    "/structures/",
    "infantry/",
    "/infantry/",
    "dummy_plane",
)


def reset_runtime_caches(clear_view=False):
    global LAST_CGAME_PTR, LAST_VIEW_MATRIX, LAST_VIEW_PROJECTION_MODE
    UNIT_KIND_CACHE.clear()
    UNIT_FILTER_CACHE.clear()
    _BBOX_FALLBACK_LOGGED.clear()
    if clear_view:
        LAST_CGAME_PTR = 0
        LAST_VIEW_MATRIX = None
        LAST_VIEW_PROJECTION_MODE = None


def _projection_mode_by_name(name):
    for mode_name, row_major, perm in PROJECTION_MODES:
        if mode_name == name:
            return {"name": mode_name, "row_major": row_major, "perm": perm}
    return None


def set_forced_view_profile(doc):
    global FORCED_VIEW_PROFILE
    if not isinstance(doc, dict):
        return False
    matrix_off_raw = doc.get("matrix_off", 0)
    camera_off_raw = doc.get("camera_off", OFF_CAMERA_PTR)
    matrix_off = int(matrix_off_raw, 16) if isinstance(matrix_off_raw, str) else int(matrix_off_raw or 0)
    camera_off = int(camera_off_raw, 16) if isinstance(camera_off_raw, str) else int(camera_off_raw or OFF_CAMERA_PTR)
    mode_name = (doc.get("projection_mode") or "").strip()
    sign_name = (doc.get("axis_signs") or "+++").strip()
    mode = _projection_mode_by_name(mode_name)
    signs = AXIS_SIGN_VARIANTS.get(sign_name)
    if not mode or not signs:
        return False
    FORCED_VIEW_PROFILE = {
        "camera_off": camera_off,
        "matrix_off": matrix_off,
        "mode": {**mode, "signs": signs, "axis_signs": sign_name},
    }
    return True


def _read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _read_c_string(scanner, ptr, max_len=96):
    if not is_valid_ptr(ptr):
        return None
    data = scanner.read_mem(ptr, max_len)
    if not data:
        return None
    raw = data.split(b"\x00")[0]
    if len(raw) < 3:
        return None
    try:
        text = raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if len(text) < 3:
        return None
    if not any(ch.isalnum() for ch in text):
        return None
    return text


def _read_info_string(scanner, info_ptr, off, max_len=96):
    ptr = _read_ptr(scanner, info_ptr + off)
    if not is_valid_ptr(ptr):
        return None
    return _read_c_string(scanner, ptr, max_len)


def _read_info_ptr_signature(scanner, info_ptr):
    return (
        _read_ptr(scanner, info_ptr + 0x08),
        _read_ptr(scanner, info_ptr + 0x10),
        _read_ptr(scanner, info_ptr + 0x18),
        _read_ptr(scanner, info_ptr + 0x38),
        _read_ptr(scanner, info_ptr + 0x40),
    )

def get_unit_bbox(scanner, unit_ptr):
    try:
        bmin_raw = scanner.read_mem(unit_ptr + OFF_UNIT_BBMIN, 12)
        bmax_raw = scanner.read_mem(unit_ptr + OFF_UNIT_BBMAX, 12)
        if not bmin_raw or not bmax_raw: 
            return None, None
        return struct.unpack("<fff", bmin_raw), struct.unpack("<fff", bmax_raw)
    except:
        return None, None

def get_unit_rotation(scanner, unit_ptr):
    try:
        rot_raw = scanner.read_mem(unit_ptr + OFF_UNIT_ROTATION, 36)
        if not rot_raw: 
            return None
        return struct.unpack("<9f", rot_raw)
    except:
        return None

def get_unit_kind_from_info(scanner, u_ptr):
    if OFF_UNIT_INFO == 0:
        return None
    info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO)
    if not is_valid_ptr(info_ptr):
        return None
    info_sig = _read_info_ptr_signature(scanner, info_ptr)
    cached = UNIT_KIND_CACHE.get(info_ptr)
    if cached and cached.get("sig") == info_sig:
        return cached.get("kind")

    kind = None
    tag = _read_info_string(scanner, info_ptr, 0x38, 64)
    if tag:
        label = tag.lower()
        if any(k in label for k in ("fighter", "bomber", "helicopter", "attacker", "assault", "jet", "air")):
            kind = "air"
        elif any(k in label for k in ("tank", "spaa", "destroyer", "fortification", "ship", "boat", "cruiser", "battleship", "aaa")):
            kind = "ground"

    if not kind:
        path = _read_info_string(scanner, info_ptr, 0x10, 96) or _read_info_string(scanner, info_ptr, 0x18, 96)
        if path:
            p = path.replace("\\", "/").lower()
            if "tankmodels/" in p or "/tankmodels/" in p:
                kind = "ground"
            elif "ships/" in p or "/ships/" in p or "air_defence/" in p:
                kind = "ground"
            elif "helicopter" in p or "aircraft" in p or "plane" in p:
                kind = "air"

    if kind:
        UNIT_KIND_CACHE[info_ptr] = {"sig": info_sig, "kind": kind}
    return kind


def _name_from_path(path):
    if not path:
        return ""
    name = path.replace("\\", "/").split("/")[-1]
    if name.lower().endswith(".blk"):
        name = name[:-4]
    return "".join(c for c in name if c.isalnum() or c in "-_")


def get_unit_filter_profile(scanner, u_ptr):
    profile = {
        "skip": False,
        "reason": "",
        "kind": None,
        "tag": "",
        "path": "",
        "unit_key": "",
        "display_name": "",
    }
    if OFF_UNIT_INFO == 0:
        return profile

    info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO)
    if not is_valid_ptr(info_ptr):
        return profile

    info_sig = _read_info_ptr_signature(scanner, info_ptr)
    cached = UNIT_FILTER_CACHE.get(info_ptr)
    if cached and cached.get("sig") == info_sig:
        return cached["profile"].copy()

    tag = _read_info_string(scanner, info_ptr, 0x38, 64) or ""
    path = _read_info_string(scanner, info_ptr, 0x18, 128)
    if not path:
        path = _read_info_string(scanner, info_ptr, 0x10, 128)
    path = path or ""
    unit_key = _read_info_string(scanner, info_ptr, 0x40, 96)
    if not unit_key:
        unit_key = _read_info_string(scanner, info_ptr, 0x08, 96)
    unit_key = unit_key or ""

    tag_l = tag.lower()
    path_l = path.lower()
    key_l = unit_key.lower()

    kind = None
    if tag_l in PLAYABLE_AIR_TAGS:
        kind = "air"
    elif tag_l in PLAYABLE_GROUND_TAGS or tag_l in PLAYABLE_NAVAL_TAGS:
        kind = "ground"
    elif "flightmodels/" in path_l or "helicopter" in path_l or "aircraft" in path_l or "plane" in path_l:
        kind = "air"
    elif "tankmodels/" in path_l or "ships/" in path_l or "air_defence/" in path_l or "structures/" in path_l:
        kind = "ground"

    skip = False
    reason = ""
    if tag_l in NON_PLAYABLE_TAGS:
        skip = True
        reason = f"tag:{tag_l}"
    elif any(h in path_l for h in NON_PLAYABLE_PATH_HINTS):
        skip = True
        reason = "path_hint"
    elif any(h in key_l for h in NON_PLAYABLE_NAME_HINTS):
        skip = True
        reason = "name_hint"

    # Defensive rule: if blocklist path is visible, always skip.
    if not skip and any(h in path_l for h in NON_PLAYABLE_PATH_BLOCKLIST):
        skip = True
        reason = "path_block"

    display_name = unit_key
    profile = {
        "skip": skip,
        "reason": reason,
        "kind": kind,
        "tag": tag,
        "path": path,
        "unit_key": unit_key,
        "display_name": display_name,
    }

    # Cache only when enough source data is readable. This avoids poisoning cache
    # with transient empty reads during map/match transitions.
    cacheable = bool(tag or path or unit_key or skip or kind)
    if cacheable:
        UNIT_FILTER_CACHE[info_ptr] = {"sig": info_sig, "profile": profile.copy()}
    else:
        UNIT_FILTER_CACHE.pop(info_ptr, None)
    return profile.copy()


VELOCITY_PROFILES = {
    "air": {
        "requested_label": "AIR",
        "primary": {
            "label": "AIR_TARGET_HIGH_TICK",
            "mov_off": lambda: OFF_AIR_HIGH_TICK_MOVEMENT,
            "vel_off": lambda: OFF_AIR_HIGH_TICK_VEL,
            "fmt": "fff",
            "max_speed": 15000.0,
        },
        "fallbacks": [
            {"label": "AIR_UNIVERSAL_HIGH_TICK", "mov_off": lambda: 0x24C0, "vel_off": lambda: 0x0E90, "fmt": "fff", "max_speed": 15000.0},
            {"label": "AIR_PLAYER", "mov_off": lambda: OFF_MY_AIR_MOVEMENT, "vel_off": lambda: OFF_MY_AIR_VEL, "fmt": "ddd", "max_speed": 15000.0},
            {"label": "AIR_LEGACY_NET", "mov_off": lambda: OFF_AIR_MOVEMENT, "vel_off": lambda: OFF_AIR_VEL, "fmt": "fff", "max_speed": 15000.0},
        ],
    },
    "ground": {
        "requested_label": "GROUND",
        "primary": {
            "label": "GROUND_PRIMARY",
            "mov_off": lambda: OFF_GROUND_MOVEMENT,
            "vel_off": lambda: OFF_GROUND_VEL,
            "fmt": "ddd",
            "max_speed": 500.0,
            "shuffle": (0, 1, 2),
        },
        "fallbacks": [],
    },
}


def _format_bytes_hex(data, max_len=24):
    if not data:
        return "None"
    trimmed = data[:max_len]
    suffix = " ..." if len(data) > max_len else ""
    return " ".join(f"{b:02X}" for b in trimmed) + suffix


def _normalize_velocity_spec(spec):
    normalized = spec.copy()
    if callable(normalized.get("mov_off")):
        normalized["mov_off"] = normalized["mov_off"]()
    if callable(normalized.get("vel_off")):
        normalized["vel_off"] = normalized["vel_off"]()
    normalized["size"] = struct.calcsize("<" + normalized["fmt"])
    normalized.setdefault("max_speed", 2500.0)
    return normalized


def _get_velocity_profile_name(is_air):
    return "air" if is_air else "ground"


def _iter_velocity_specs(profile_name):
    profile = VELOCITY_PROFILES[profile_name]
    primary = _normalize_velocity_spec(profile["primary"])
    specs = [primary]
    seen = {(primary["mov_off"], primary["vel_off"], primary["fmt"])}
    for spec in profile["fallbacks"]:
        normalized = _normalize_velocity_spec(spec)
        key = (normalized["mov_off"], normalized["vel_off"], normalized["fmt"])
        if key in seen:
            continue
        specs.append(normalized)
        seen.add(key)
    return specs


def _throttled_velocity_log(key, msg, interval=2.0):
    now = time.time()
    last_t = VELOCITY_LOG_CACHE.get(key, 0.0)
    if (now - last_t) < interval:
        return
    VELOCITY_LOG_CACHE[key] = now
    dprint(msg, force=False)


def _debug_velocity_failure(reason, u_ptr, spec, raw_ptr=None, base_ptr=None, data=None, decoded=None):
    decoded_str = "None"
    if decoded is not None:
        decoded_str = f"({decoded[0]:.4f}, {decoded[1]:.4f}, {decoded[2]:.4f})"
    raw_ptr_hex = _format_bytes_hex(raw_ptr, 8)
    data_hex = _format_bytes_hex(data, spec["size"])
    base_ptr_str = hex(base_ptr) if isinstance(base_ptr, int) and base_ptr > 0 else str(base_ptr)
    _throttled_velocity_log(
        ("fail", u_ptr, spec["label"], reason),
        "VEL READ FAIL"
        f" | type={spec['label']}"
        f" | unit={hex(u_ptr)}"
        f" | mov_off={hex(spec['mov_off'])}"
        f" | vel_off={hex(spec['vel_off'])}"
        f" | fmt={spec['fmt']}"
        f" | raw_ptr=[{raw_ptr_hex}]"
        f" | mov_ptr={base_ptr_str}"
        f" | raw_vel=[{data_hex}]"
        f" | decoded={decoded_str}"
        f" | reason={reason}",
        interval=3.0,
    )


def _try_read_velocity(scanner, u_ptr, spec):
    raw_ptr = scanner.read_mem(u_ptr + spec["mov_off"], 8)
    if not raw_ptr or len(raw_ptr) < 8:
        return None, ("movement pointer unreadable", raw_ptr, None, None, None)

    base_ptr = struct.unpack("<Q", raw_ptr)[0]
    if not is_valid_ptr(base_ptr):
        return None, ("movement pointer invalid", raw_ptr, base_ptr, None, None)

    data = scanner.read_mem(base_ptr + spec["vel_off"], spec["size"])
    if not data or len(data) < spec["size"]:
        return None, ("velocity bytes unreadable", raw_ptr, base_ptr, data, None)

    decoded = tuple(float(v) for v in struct.unpack("<" + spec["fmt"], data[:spec["size"]]))
    
    # 🎯 Apply axis shuffle if defined
    if "shuffle" in spec:
        s = spec["shuffle"]
        decoded = (decoded[s[0]], decoded[s[1]], decoded[s[2]])
        
    # 🎯 Apply negation if defined
    if "negate" in spec:
        n = spec["negate"]
        decoded = (
            -decoded[0] if n[0] else decoded[0],
            -decoded[1] if n[1] else decoded[1],
            -decoded[2] if n[2] else decoded[2]
        )

    if not all(math.isfinite(v) for v in decoded):
        return None, ("decoded non-finite vector", raw_ptr, base_ptr, data, decoded)

    if all(abs(v) <= 0.001 for v in decoded):
        # Near-zero velocity is valid for idle/stopped units.
        return (0.0, 0.0, 0.0), None

    speed = math.sqrt(decoded[0] ** 2 + decoded[1] ** 2 + decoded[2] ** 2)
    if speed > spec["max_speed"]:
        return None, ("decoded implausible speed", raw_ptr, base_ptr, data, decoded)

    if spec["label"].startswith("GROUND"):
        planar_speed = math.hypot(decoded[0], decoded[2])
        vertical_speed = abs(decoded[1])
        # Ground motion fields occasionally decode as pure Y-only suspension / local-axis noise.
        # These values destabilize both ground lead and air lead (via my_vel subtraction), so reject them.
        if planar_speed <= 0.05 and vertical_speed >= 0.20:
            return None, ("decoded ground vertical-only noise", raw_ptr, base_ptr, data, decoded)

    return decoded, None


def _velocity_spec_score(profile_name, spec, result, u_ptr):
    score = 0.0
    cached_label = VELOCITY_SPEC_CACHE.get((profile_name, u_ptr))
    if spec["label"] == cached_label:
        score += 18.0
    if spec["label"].endswith("PRIMARY"):
        score += 24.0

    if profile_name == "ground":
        planar_speed = math.hypot(result[0], result[2])
        vertical_speed = abs(result[1])
        score += min(planar_speed, 40.0)
        score -= (vertical_speed * 8.0)
        if planar_speed >= 0.15:
            score += 12.0
        if planar_speed >= 0.40:
            score += 10.0
        if vertical_speed <= 0.08:
            score += 8.0
        elif vertical_speed >= max(0.2, planar_speed * 0.6):
            score -= 12.0
    else:
        speed = math.sqrt(result[0] ** 2 + result[1] ** 2 + result[2] ** 2)
        score += min(speed / 20.0, 18.0)

    return score


def _ordered_velocity_specs(profile_name, u_ptr):
    specs = _iter_velocity_specs(profile_name)
    cached_label = VELOCITY_SPEC_CACHE.get((profile_name, u_ptr))
    if not cached_label:
        return specs

    preferred = None
    others = []
    for spec in specs:
        if spec["label"] == cached_label:
            preferred = spec
        else:
            others.append(spec)

    if preferred is None or preferred["label"].endswith("PRIMARY"):
        return specs

    primary = specs[0]
    ordered = [primary, preferred]
    ordered.extend(spec for spec in others if spec is not primary)
    return ordered


def _read_velocity_by_profile(scanner, u_ptr, profile_name):
    if u_ptr == 0:
        return (0.0, 0.0, 0.0)

    profile = VELOCITY_PROFILES[profile_name]
    requested_label = profile["requested_label"]
    attempts = []
    successes = []

    for idx, spec in enumerate(_ordered_velocity_specs(profile_name, u_ptr)):
        result, failure = _try_read_velocity(scanner, u_ptr, spec)
        if result is not None:
            successes.append((spec, result, idx))
            continue
        attempts.append((spec, failure))

    if successes:
        if profile_name == "ground":
            scored = sorted(
                (
                    (_velocity_spec_score(profile_name, spec, result, u_ptr), spec, result, idx)
                    for spec, result, idx in successes
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            _score, chosen_spec, chosen_result, chosen_idx = scored[0]
        else:
            chosen_spec, chosen_result, chosen_idx = successes[0]

        previous_label = VELOCITY_SPEC_CACHE.get((profile_name, u_ptr))
        VELOCITY_SPEC_CACHE[(profile_name, u_ptr)] = chosen_spec["label"]
        if chosen_idx > 0 and previous_label != chosen_spec["label"]:
            _throttled_velocity_log(
                ("fallback", requested_label, u_ptr, chosen_spec["label"]),
                "VEL FALLBACK HIT"
                f" | requested_type={requested_label}"
                f" | unit={hex(u_ptr)}"
                f" | using={chosen_spec['label']}"
                f" | mov_off={hex(chosen_spec['mov_off'])}"
                f" | vel_off={hex(chosen_spec['vel_off'])}"
                f" | fmt={chosen_spec['fmt']}"
                f" | decoded=({chosen_result[0]:.4f}, {chosen_result[1]:.4f}, {chosen_result[2]:.4f})",
                interval=1.5,
            )
        return chosen_result

    if attempts:
        spec, failure = attempts[0]
        reason, raw_ptr, base_ptr, data, decoded = failure
        _debug_velocity_failure(reason, u_ptr, spec, raw_ptr=raw_ptr, base_ptr=base_ptr, data=data, decoded=decoded)
        _throttled_velocity_log(
            ("exhausted", requested_label, u_ptr),
            "VEL FALLBACKS EXHAUSTED"
            f" | requested_type={requested_label}"
            f" | unit={hex(u_ptr)}"
            f" | tried="
            + ", ".join(
                f"{s['label']}@{hex(s['mov_off'])}/{hex(s['vel_off'])}:{s['fmt']}:{f[0]}"
                for s, f in attempts
            ),
            interval=3.0,
        )
    return (0.0, 0.0, 0.0)


def _score_cgame_live(scanner, cgame_ptr):
    total_units = 0
    score = 0

    for unit_off, _ in (OFF_AIR_UNITS, OFF_GROUND_UNITS, (0x340, False)):
        raw_array_ptr = scanner.read_mem(cgame_ptr + unit_off, 8)
        raw_count = scanner.read_mem(cgame_ptr + unit_off + 16, 4)
        if not raw_array_ptr or len(raw_array_ptr) < 8 or not raw_count or len(raw_count) < 4:
            continue

        array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
        count = struct.unpack("<I", raw_count)[0]

        if 0 < count <= 256 and is_valid_ptr(array_ptr):
            sample_n = min(count, 16)
            ptr_data = scanner.read_mem(array_ptr, sample_n * 8)
            if ptr_data and len(ptr_data) >= sample_n * 8:
                valid_units = 0
                for i in range(sample_n):
                    u_ptr = struct.unpack_from("<Q", ptr_data, i * 8)[0]
                    if is_valid_ptr(u_ptr):
                        pos = get_unit_pos(scanner, u_ptr)
                        if pos and not _is_zero_unit_pos(scanner, u_ptr):
                            valid_units += 1
                if valid_units:
                    total_units += valid_units
                    score += valid_units * 10

    return score, total_units


def _manager_offsets():
    offsets = []

    def _add(off):
        if isinstance(off, int) and 0 < off < 0x20000000 and off not in offsets:
            offsets.append(off)

    _add(MANAGER_OFFSET)
    _add(DAT_MANAGER - GHIDRA_BASE)
    for off in MANAGER_CANDIDATE_OFFSETS:
        _add(off)

    return offsets

def get_cgame_base(scanner, base_addr):
    global LAST_CGAME_PTR

    candidate_offsets = _manager_offsets()
    if not candidate_offsets:
        candidate_offsets = [DAT_MANAGER - GHIDRA_BASE]

    best_candidate = None
    best_rank = (-1, -1, -1, -1, -1, -1, -1)

    for idx, offset in enumerate(candidate_offsets):
        cgame_ptr = _read_ptr(scanner, base_addr + offset)
        if not is_valid_ptr(cgame_ptr):
            continue

        vtable_ok = is_valid_ptr(_read_ptr(scanner, cgame_ptr))
        live_score, total_units = _score_cgame_live(scanner, cgame_ptr)
        matrix_ok = False
        cam_offsets = [OFF_CAMERA_PTR]
        for c_off in (0x660, 0x670, 0x668, 0x6f8, 0x708):
            if c_off not in cam_offsets:
                cam_offsets.append(c_off)
        matrix_offsets = [OFF_VIEW_MATRIX]
        for m_off in (0x1D8, 0x1C0, 0x1a0, 0x120, 0x198, 0x118):
            if m_off not in matrix_offsets:
                matrix_offsets.append(m_off)

        for cam_off in cam_offsets:
            cam_ptr = _read_ptr(scanner, cgame_ptr + cam_off)
            if not is_valid_ptr(cam_ptr):
                continue

            camera_candidates = [cam_ptr]
            nested_ptr = _read_ptr(scanner, cam_ptr)
            if is_valid_ptr(nested_ptr):
                camera_candidates.append(nested_ptr)

            for cam_candidate in camera_candidates:
                for mat_off in matrix_offsets:
                    matrix_data = scanner.read_mem(cam_candidate + mat_off, 64)
                    if not matrix_data or len(matrix_data) < 64:
                        continue
                    values = struct.unpack("<16f", matrix_data[:64])
                    non_zero = sum(1 for v in values if math.isfinite(v) and abs(v) > 1e-6)
                    dir_sq = values[3]**2 + values[7]**2 + values[11]**2
                    if non_zero >= 8 and 0.5 < dir_sq < 2.0 and all(math.isfinite(v) and abs(v) <= 1e6 for v in values):
                        matrix_ok = True
                        break
                if matrix_ok:
                    break
            if matrix_ok:
                break

        rank = (
            1 if matrix_ok and total_units > 0 else 0,
            1 if total_units > 0 else 0,
            1 if matrix_ok else 0,
            live_score,
            total_units,
            1 if vtable_ok else 0,
            -idx,
        )

        if best_candidate is None or rank > best_rank:
            best_candidate = cgame_ptr
            best_rank = rank

    if is_valid_ptr(best_candidate):
        LAST_CGAME_PTR = best_candidate
        return best_candidate

    if is_valid_ptr(LAST_CGAME_PTR):
        return LAST_CGAME_PTR
    return 0

def get_view_matrix(scanner, cgame_base):
    global LAST_VIEW_MATRIX, LAST_VIEW_PROJECTION_MODE
    if cgame_base == 0:
        return LAST_VIEW_MATRIX

    def _matrix_ok(values):
        if len(values) != 16:
            return False
        if not all(math.isfinite(v) for v in values):
            return False
        if any(abs(v) > 1e6 for v in values):
            return False
        non_zero = sum(1 for v in values if abs(v) > 1e-6)
        if non_zero < 8:
            return False
        dir_sq = values[3]**2 + values[7]**2 + values[11]**2
        return 0.5 < dir_sq < 2.0

    if FORCED_VIEW_PROFILE:
        camera_ptr = _read_ptr(scanner, cgame_base + FORCED_VIEW_PROFILE["camera_off"])
        if is_valid_ptr(camera_ptr):
            matrix_data = scanner.read_mem(camera_ptr + FORCED_VIEW_PROFILE["matrix_off"], 64)
            if matrix_data and len(matrix_data) >= 64:
                values = struct.unpack("<16f", matrix_data[:64])
                if _matrix_ok(values):
                    LAST_VIEW_MATRIX = values
                    LAST_VIEW_PROJECTION_MODE = FORCED_VIEW_PROFILE["mode"]
                    return values

    cam_offsets = [OFF_CAMERA_PTR]
    for c_off in (0x660, 0x670, 0x668, 0x6f8, 0x708):
        if c_off not in cam_offsets:
            cam_offsets.append(c_off)

    matrix_offsets = [OFF_VIEW_MATRIX]
    for m_off in (0x1D8, 0x1C0, 0x1a0, 0x120, 0x198, 0x118):
        if m_off not in matrix_offsets:
            matrix_offsets.append(m_off)

    for cam_off in cam_offsets:
        camera_ptr = _read_ptr(scanner, cgame_base + cam_off)
        if not is_valid_ptr(camera_ptr):
            continue

        camera_candidates = [camera_ptr]
        nested_ptr = _read_ptr(scanner, camera_ptr)
        if is_valid_ptr(nested_ptr):
            camera_candidates.append(nested_ptr)

        for cam_ptr in camera_candidates:
            for matrix_off in matrix_offsets:
                matrix_data = scanner.read_mem(cam_ptr + matrix_off, 64)
                if not matrix_data or len(matrix_data) < 64:
                    continue
                values = struct.unpack("<16f", matrix_data)
                if not _matrix_ok(values):
                    continue
                LAST_VIEW_MATRIX = values
                LAST_VIEW_PROJECTION_MODE = None
                return values

    return LAST_VIEW_MATRIX

def get_unit_pos(scanner, u_ptr):
    if u_ptr == 0: return None
    data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not data or len(data) < 12: return None
    val1, val2, val3 = struct.unpack("<fff", data)
    if not (math.isfinite(val1) and math.isfinite(val2) and math.isfinite(val3)): return None
    return (val1, val2, val3)

def _is_zero_unit_pos(scanner, u_ptr):
    pos = get_unit_pos(scanner, u_ptr)
    if not pos:
        return True
    return all(abs(v) < 0.01 for v in pos)

def get_all_units(scanner, cgame_base):
    if cgame_base == 0: return []
    units = []
    list_specs = [OFF_ACTIVE_UNITS, *OFF_ACTIVE_EXTRA_UNIT_LISTS]
    if ENABLE_WORLD_UNIT_LIST_FALLBACK:
        list_specs.extend((
            (OFF_AIR_UNITS[0], OFF_AIR_UNITS[1], 0x10),
            (OFF_GROUND_UNITS[0], OFF_GROUND_UNITS[1], 0x10),
        ))
    for off, is_air, count_off in list_specs:
        raw_array_ptr = scanner.read_mem(cgame_base + off, 8)
        raw_count = scanner.read_mem(cgame_base + off + count_off, 4) 
        if raw_array_ptr and raw_count:
            array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
            count = struct.unpack("<I", raw_count)[0]
            if 0 < count <= 2048 and is_valid_ptr(array_ptr):
                ptr_data = scanner.read_mem(array_ptr, count * 8)
                if ptr_data:
                      for i in range(count):
                          u_ptr = struct.unpack_from("<Q", ptr_data, i * 8)[0]
                          if is_valid_ptr(u_ptr):
                              units.append((u_ptr, is_air))
    deduped = list({u[0]: u for u in units}.values())
    refined = []
    for u_ptr, is_air in deduped:
        profile = get_unit_filter_profile(scanner, u_ptr)
        if profile.get("skip"):
            continue
        kind = profile.get("kind") or get_unit_kind_from_info(scanner, u_ptr)
        if kind == "air":
            is_air = True
        elif kind == "ground":
            is_air = False
        if FILTER_ZERO_POS_UNITS and _is_zero_unit_pos(scanner, u_ptr):
            continue
        refined.append((u_ptr, is_air))
    return refined

def get_unit_3d_box_data(scanner, u_ptr, is_air=False):
    if u_ptr == 0: return None
    
    # 📍 พิกัดตัวละคร (Unit Position)
    pos_data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not pos_data or len(pos_data) < 12: return None
    pos = struct.unpack("<fff", pos_data)

    # 📍 การหมุน (Rotation Matrix)
    rot_data = scanner.read_mem(u_ptr + OFF_UNIT_ROTATION, 36)
    if not rot_data or len(rot_data) < 36: return None
    R = struct.unpack("<9f", rot_data)

    # 📍 Bounding Box - บาง build เก็บ BBMIN/BBMAX แยกกัน แม้ offset จะต่อกัน
    def _valid_bbox(bmin, bmax):
        dx, dy, dz = bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2]
        return 0.5 < dx < 100.0 and 0.2 < dy < 40.0 and 0.5 < dz < 100.0

    bmin_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 12) if OFF_UNIT_BBMIN else None
    if bmin_data and len(bmin_data) == 12:
        bmin = struct.unpack("<fff", bmin_data)
        for bmax_off in (OFF_UNIT_BBMAX, OFF_UNIT_BBMIN + 0x10, OFF_UNIT_BBMIN + 0x0C):
            if not bmax_off:
                continue
            bmax_data = scanner.read_mem(u_ptr + bmax_off, 12)
            if not bmax_data or len(bmax_data) != 12:
                continue
            bmax = struct.unpack("<fff", bmax_data)
            if _valid_bbox(bmin, bmax):
                return pos, bmin, bmax, R

    # เผื่อ build ที่วาง BBMIN/BBMAX ติดกันจริง ค่อยลองอ่านรวดเดียวเป็น fallback
    bbox_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 24) if OFF_UNIT_BBMIN else None
    if bbox_data and len(bbox_data) == 24:
        bmin = struct.unpack_from("<fff", bbox_data, 0)
        bmax = struct.unpack_from("<fff", bbox_data, 12)
        if _valid_bbox(bmin, bmax):
            return pos, bmin, bmax, R

    # Fallback กรณีอ่านไม่ได้ (ใช้ค่ากลางมาตรฐาน)
    if is_air:
        best_bmin, best_bmax = (-8.0, -2.0, -6.0), (8.0, 3.0, 6.0)
    else:
        best_bmin, best_bmax = (-1.8, -0.8, -3.0), (1.8, 1.6, 3.0)

    if u_ptr not in _BBOX_FALLBACK_LOGGED:
        _BBOX_FALLBACK_LOGGED.add(u_ptr)
        dprint(
            f"BBOX FALLBACK | unit={hex(u_ptr)} | type={'AIR' if is_air else 'GROUND'} "
            f"| bbmin_off={hex(OFF_UNIT_BBMIN)} | bbmax_off={hex(OFF_UNIT_BBMAX)}",
            force=False,
        )

    return pos, best_bmin, best_bmax, R

def calculate_3d_box_corners(pos, bmin, bmax, R, is_air=False):
    ax, ay, az = get_local_axes_from_rotation(R, is_air)

    l_min = bmin
    l_max = bmax
    
    local_center = [(l_min[i] + l_max[i]) * 0.5 for i in range(3)]
    local_ext = [(l_max[i] - l_min[i]) * 0.5 for i in range(3)]

    # Ground units use unit position on the bottom border of the hull.
    # Force the bottom face of the 3D box to pass through the unit origin.
    if not is_air:
        local_center[1] = local_ext[1]
    
    # 🚀 World Center Calculation
    wc = [
        pos[0] + ax[0]*local_center[0] + ay[0]*local_center[1] + az[0]*local_center[2],
        pos[1] + ax[1]*local_center[0] + ay[1]*local_center[1] + az[1]*local_center[2],
        pos[2] + ax[2]*local_center[0] + ay[2]*local_center[1] + az[2]*local_center[2]
    ]

    # 📐 Axis Extents
    ex = [ax[i] * local_ext[0] for i in range(3)]
    ey = [ay[i] * local_ext[1] for i in range(3)]
    ez = [az[i] * local_ext[2] for i in range(3)]
    
    corners = []
    s = [(-1,-1,-1), (1,-1,-1), (1,1,-1), (-1,1,-1), (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1)]
    for sx, sy, sz in s:
        corners.append((
            wc[0] + sx*ex[0] + sy*ey[0] + sz*ez[0],
            wc[1] + sx*ex[1] + sy*ey[1] + sz*ez[1],
            wc[2] + sx*ex[2] + sy*ey[2] + sz*ez[2]
        ))
    return corners


def get_local_axes_from_rotation(R, is_air=False):
    # ใช้ basis แบบเดียวกับกล่อง 3D เพื่อให้ debug axes ตรงกับ logic ปัจจุบัน
    ax = [R[0], R[1], R[2]]
    ay = [R[3], R[4], R[5]]
    az = [R[6], R[7], R[8]]

    def normalize(v):
        length = math.sqrt((v[0] * v[0]) + (v[1] * v[1]) + (v[2] * v[2]))
        if length <= 1e-8:
            return [0.0, 0.0, 0.0]
        return [v[0] / length, v[1] / length, v[2] / length]

    ax = normalize(ax)
    ay = normalize(ay)
    az = normalize(az)

    return ax, ay, az
def world_to_screen(matrix, pos_x, pos_y, pos_z, screen_width, screen_height):
    try:
        if not matrix or any(not math.isfinite(v) for v in matrix):
            return None

        # 🎯 สมการ W2S มาตรฐานของ Dagor Engine (Row-Major)
        w = (pos_x * matrix[3]) + (pos_y * matrix[7]) + (pos_z * matrix[11]) + matrix[15]
        
        # ถ้ายูนิตอยู่หลังกล้องหรือใกล้ระนาบกล้องเกินไป (Near-plane clipping < 0.10m) ให้ตัดทิ้ง
        if w < 0.10 or not math.isfinite(w): 
            return None
        
        clip_x = (pos_x * matrix[0]) + (pos_y * matrix[4]) + (pos_z * matrix[8]) + matrix[12]
        clip_y = (pos_x * matrix[1]) + (pos_y * matrix[5]) + (pos_z * matrix[9]) + matrix[13]
        
        ndc_x = clip_x / w
        ndc_y = clip_y / w
        
        # แปลงเป็นพิกัดหน้าจอ
        screen_x = (screen_width * 0.5) * (1.0 + ndc_x)
        screen_y = (screen_height * 0.5) * (1.0 - ndc_y)
        
        if math.isfinite(screen_x) and math.isfinite(screen_y):
            return (screen_x, screen_y, w)
        return None
    except:
        return None

def get_weapon_barrel(scanner, u_ptr, unit_pos, unit_rot_matrix, should_log=False):
    if u_ptr == 0: return None
    if not hasattr(scanner, "bone_cache"): scanner.bone_cache = {}
    if not hasattr(scanner, "model_barrel_cache"): scanner.model_barrel_cache = {}

    def to_world(lx, ly, lz):
        return (lx*unit_rot_matrix[0] + ly*unit_rot_matrix[3] + lz*unit_rot_matrix[6] + unit_pos[0],
                lx*unit_rot_matrix[1] + ly*unit_rot_matrix[4] + lz*unit_rot_matrix[7] + unit_pos[1],
                lx*unit_rot_matrix[2] + ly*unit_rot_matrix[5] + lz*unit_rot_matrix[8] + unit_pos[2])

    try:
        current_info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO) if OFF_UNIT_INFO else 0

        # 1. ตรวจสอบ bone_cache ก่อน (Per-Unit Cache)
        if u_ptr in scanner.bone_cache:
            cache = scanner.bone_cache[u_ptr]
            if cache.get('no_barrel'):
                if current_info_ptr and cache.get('info_ptr') and cache.get('info_ptr') != current_info_ptr:
                    del scanner.bone_cache[u_ptr]
                elif (time.time() - cache.get('failed_at', 0)) > 5.0:
                    del scanner.bone_cache[u_ptr]
                else:
                    return None
            else:
                if cache.get('info_ptr') and current_info_ptr and cache.get('info_ptr') != current_info_ptr:
                    del scanner.bone_cache[u_ptr]
                else:
                    anim_wtm = cache.get('anim_wtm_ptr', 0)
                    breech_idx = cache.get('breech_idx', -1)
                    muzzle_idx = cache.get('muzzle_idx', -1)
                    if anim_wtm and is_valid_ptr(anim_wtm) and breech_idx != -1 and muzzle_idx != -1:
                        b_bytes = scanner.read_mem(anim_wtm + breech_idx * 64, 64)
                        m_bytes = scanner.read_mem(anim_wtm + muzzle_idx * 64, 64)
                        if b_bytes and m_bytes and len(b_bytes) == 64 and len(m_bytes) == 64:
                            bx, by, bz = struct.unpack_from("<fff", b_bytes, 0x30)
                            mx, my, mz = struct.unpack_from("<fff", m_bytes, 0x30)
                            fx, fy, fz = struct.unpack_from("<fff", m_bytes, 0x00)
                            if math.isfinite(bx) and math.isfinite(mx) and abs(bx) < 50.0 and abs(mx) < 50.0:
                                cache['fail_count'] = 0
                                if breech_idx == muzzle_idx or (abs(mx - bx) < 0.05 and abs(my - by) < 0.05):
                                    mx, my, mz = bx + fx * 4.0, by + fy * 4.0, bz + fz * 4.0
                                return to_world(bx, by, bz), to_world(mx, my, mz)
                        cache['fail_count'] = int(cache.get('fail_count', 0) or 0) + 1
                        if cache['fail_count'] >= 10:
                            del scanner.bone_cache[u_ptr]

        # 2. ตรวจสอบ model_barrel_cache (Per-Vehicle Model)
        cached_model = scanner.model_barrel_cache.get(current_info_ptr) if current_info_ptr else None
        if cached_model:
            breech_idx, muzzle_idx = cached_model
            t250 = _read_ptr(scanner, u_ptr + 0x250)
            if is_valid_ptr(t250):
                anim_wtm = t250 + 0x30
                b_bytes = scanner.read_mem(anim_wtm + breech_idx * 64, 64)
                m_bytes = scanner.read_mem(anim_wtm + muzzle_idx * 64, 64)
                if b_bytes and m_bytes and len(b_bytes) == 64 and len(m_bytes) == 64:
                    bx, by, bz = struct.unpack_from("<fff", b_bytes, 0x30)
                    mx, my, mz = struct.unpack_from("<fff", m_bytes, 0x30)
                    fx, fy, fz = struct.unpack_from("<fff", m_bytes, 0x00)
                    if math.isfinite(bx) and math.isfinite(mx) and abs(bx) < 50.0 and abs(mx) < 50.0:
                        scanner.bone_cache[u_ptr] = {
                            "breech_idx": breech_idx,
                            "muzzle_idx": muzzle_idx,
                            "anim_wtm_ptr": anim_wtm,
                            "info_ptr": current_info_ptr,
                            "fail_count": 0,
                        }
                        if breech_idx == muzzle_idx or (abs(mx - bx) < 0.05 and abs(my - by) < 0.05):
                            mx, my, mz = bx + fx * 4.0, by + fy * 4.0, bz + fz * 4.0
                        return to_world(bx, by, bz), to_world(mx, my, mz)

        # 3. Geometric Scan บน Dagor GeomNodeTree (Bind Pose 0x208 vs Animated Pose 0x250)
        t208 = _read_ptr(scanner, u_ptr + 0x208)
        t250 = _read_ptr(scanner, u_ptr + 0x250)
        if is_valid_ptr(t208) and is_valid_ptr(t250):
            cnt_raw = scanner.read_mem(t208 + 0x10, 2)
            cnt208 = struct.unpack("<H", cnt_raw)[0] if cnt_raw and len(cnt_raw) == 2 else 0
            if 0 < cnt208 < 1000:
                raw_mats = scanner.read_mem(t208 + 0x30, cnt208 * 64)
                if raw_mats and len(raw_mats) == cnt208 * 64:
                    bmin_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 12) if OFF_UNIT_BBMIN else None
                    bmax_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMAX, 12) if OFF_UNIT_BBMAX else None
                    if bmin_data and bmax_data and len(bmin_data) == 12 and len(bmax_data) == 12:
                        bmin = struct.unpack("<fff", bmin_data)
                        bmax = struct.unpack("<fff", bmax_data)
                        y_min = bmin[1] + (bmax[1] - bmin[1]) * 0.35
                        y_max = bmax[1] + 0.6
                    else:
                        y_min, y_max = 0.5, 4.0

                    candidates = []
                    for b in range(cnt208):
                        m_data = raw_mats[b*64:(b+1)*64]
                        r0 = struct.unpack_from("<ffff", m_data, 0x00)
                        r1 = struct.unpack_from("<ffff", m_data, 0x10)
                        r3 = struct.unpack_from("<ffff", m_data, 0x30)
                        bx, by, bz = r3[0], r3[1], r3[2]
                        d_fwd = (r0[0]-1.0)**2 + r0[1]**2 + r0[2]**2
                        d_up  = r1[0]**2 + (r1[1]-1.0)**2 + r1[2]**2
                        if d_fwd < 0.04 and d_up < 0.04 and y_min <= by <= y_max and abs(bz) < 0.8 and bx > -0.6:
                            candidates.append((bx, b))

                    if candidates:
                        candidates.sort(key=lambda x: x[0])
                        breech_idx = candidates[0][1]
                        muzzle_idx = candidates[-1][1]
                        anim_wtm = t250 + 0x30

                        if current_info_ptr:
                            scanner.model_barrel_cache[current_info_ptr] = (breech_idx, muzzle_idx)
                        scanner.bone_cache[u_ptr] = {
                            "breech_idx": breech_idx,
                            "muzzle_idx": muzzle_idx,
                            "anim_wtm_ptr": anim_wtm,
                            "info_ptr": current_info_ptr,
                            "fail_count": 0,
                        }

                        b_bytes = scanner.read_mem(anim_wtm + breech_idx * 64, 64)
                        m_bytes = scanner.read_mem(anim_wtm + muzzle_idx * 64, 64)
                        if b_bytes and m_bytes and len(b_bytes) == 64 and len(m_bytes) == 64:
                            bx, by, bz = struct.unpack_from("<fff", b_bytes, 0x30)
                            mx, my, mz = struct.unpack_from("<fff", m_bytes, 0x30)
                            fx, fy, fz = struct.unpack_from("<fff", m_bytes, 0x00)
                            if math.isfinite(bx) and math.isfinite(mx) and abs(bx) < 50.0 and abs(mx) < 50.0:
                                if breech_idx == muzzle_idx or (abs(mx - bx) < 0.05 and abs(my - by) < 0.05):
                                    mx, my, mz = bx + fx * 4.0, by + fy * 4.0, bz + fz * 4.0
                                return to_world(bx, by, bz), to_world(mx, my, mz)

        # 4. Fallback (Legacy Scan สำหรับโมเดลรุ่นเก่า)
        best_score, best_idx = -1, -1
        u_ptr_tree = 0
        best_wtm_off = 0x00
        for off in [0x250, 0x208, 0x238, 0x1F0, 0x1FD8, 0x2E20, 0x2F38, 0x1E8, 0x1E0, 0x1D8]:
            raw_ptr = scanner.read_mem(u_ptr + off, 8)
            if not raw_ptr: continue
            tree_ptr = struct.unpack("<Q", raw_ptr)[0]
            if not is_valid_ptr(tree_ptr): continue
            
            cnt_raw = scanner.read_mem(tree_ptr + 0x08, 4)
            bone_cnt = struct.unpack("<I", cnt_raw)[0] if cnt_raw and len(cnt_raw) == 4 else 400
            if bone_cnt <= 0 or bone_cnt > 1000: bone_cnt = 400

            for sub_off in [0x40, 0x20, 0xB0]:
                raw_name = scanner.read_mem(tree_ptr + sub_off, 8)
                if not raw_name: continue
                name_ptr = struct.unpack("<Q", raw_name)[0]
                if not is_valid_ptr(name_ptr): continue
                names_block = scanner.read_mem(name_ptr, max(0x4000, bone_cnt * 32))
                if not names_block: continue
                    
                for i in range(min(bone_cnt, 512)):
                    try:
                        str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                        if str_offset == 0 or str_offset >= len(names_block): continue
                        end_idx = names_block.find(b'\x00', str_offset)
                        if end_idx != -1:
                            bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').lower().strip()
                            score = -1
                            if "bone_gun_barrel" in bone_name: score = 100
                            elif "gun_barrel" in bone_name: score = 80
                            elif bone_name == "bone_gun": score = 70
                            elif "bone_gun" in bone_name: score = 60
                            elif "barrel" in bone_name: score = 40
                            if any(b in bone_name for b in ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root"]): score = -100
                            if score > best_score:
                                best_score = score
                                best_idx = i
                                u_ptr_tree = tree_ptr
                                best_wtm_off = 0x00
                            if best_score >= 100: break
                    except: pass
                if best_score >= 100: break
            if best_score >= 100: break

        if best_idx != -1 and u_ptr_tree:
            wtm_base_raw = scanner.read_mem(u_ptr_tree + best_wtm_off, 8)
            if wtm_base_raw:
                w_ptr = struct.unpack("<Q", wtm_base_raw)[0]
                if is_valid_ptr(w_ptr):
                    matrix_data = scanner.read_mem(w_ptr + (best_idx * 64), 64)
                    if matrix_data and len(matrix_data) == 64:
                        fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00)
                        bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30)
                        if math.isfinite(bx) and math.isfinite(fx):
                            scanner.bone_cache[u_ptr] = {
                                "breech_idx": best_idx,
                                "muzzle_idx": best_idx,
                                "anim_wtm_ptr": w_ptr,
                                "info_ptr": current_info_ptr,
                                "fail_count": 0,
                            }
                            length = 6.0
                            return to_world(bx, by, bz), to_world(bx + fx * length, by + fy * length, bz + fz * length)

        if u_ptr not in scanner.bone_cache:
            scanner.bone_cache[u_ptr] = {
                "no_barrel": True,
                "info_ptr": current_info_ptr,
                "failed_at": time.time(),
            }
    except Exception:
        pass
    return None


ENABLE_XRAY = False  # ปิดการทำงาน X-Ray เพื่อไม่ให้ส่งผลกระทบต่อ main flow


def get_unit_xray_components(scanner, u_ptr, unit_pos, unit_rot_matrix):
    """
    ดึงตำแหน่งชิ้นส่วนภายใน X-Ray (Crew, Ammo, Engine, Breech) ของรถถัง
    (ปิดการทำงานชั่วคราวตาม ENABLE_XRAY = False เพื่อไม่ให้มี overhead ใน main flow)
    """
    if not ENABLE_XRAY:
        return []

    if u_ptr == 0 or not unit_pos or not unit_rot_matrix:
        return []

    if not hasattr(scanner, "xray_cache"):
        scanner.xray_cache = {}

    current_info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO) if OFF_UNIT_INFO else 0
    cache = scanner.xray_cache.get(u_ptr)

    # ตรวจสอบการหมดอายุของแคชเมื่อยูนิต Respawn หรือเปลี่ยนรถ
    if cache:
        if cache.get("info_ptr") and current_info_ptr and cache.get("info_ptr") != current_info_ptr:
            del scanner.xray_cache[u_ptr]
            cache = None

    if not cache:
        # ดึง AnimChar tree_ptr
        tree_ptr = 0
        wtm_off = 0x00

        # ตรวจสอบจาก persistence ก่อน
        try:
            import src.utils.scanner as scanner_mod
            persisted = scanner_mod._load_barrel_persistence()
            if persisted:
                a_off = persisted.get("animchar_off", 0x238)
                wtm_off = persisted.get("wtm_off", 0x00)
                raw_ptr = scanner.read_mem(u_ptr + a_off, 8)
                if raw_ptr:
                    t = struct.unpack("<Q", raw_ptr)[0]
                    if is_valid_ptr(t):
                        tree_ptr = t
        except Exception:
            pass

        if not tree_ptr:
            for off in [0x238, 0x1F0, 0x1FD8, 0x2E20, 0x2F38, 0x1E8, 0x1E0, 0x1D8, 0x200, 0x210, 0x228, 0x1C8, 0x3E8, 0x400, 0x13B0]:
                raw_ptr = scanner.read_mem(u_ptr + off, 8)
                if not raw_ptr:
                    continue
                t = struct.unpack("<Q", raw_ptr)[0]
                if is_valid_ptr(t):
                    tree_ptr = t
                    break

        if not tree_ptr:
            scanner.xray_cache[u_ptr] = {"empty": True, "info_ptr": current_info_ptr}
            return []

        # ตรวจสอบจำนวนกระดูกที่แท้จริงจาก tree_ptr + 0x08
        cnt_raw = scanner.read_mem(tree_ptr + 0x08, 4)
        bone_cnt = struct.unpack("<I", cnt_raw)[0] if cnt_raw and len(cnt_raw) == 4 else 400
        if bone_cnt <= 0 or bone_cnt > 1000:
            bone_cnt = 400

        # หา Sub-Offset ของ Names block
        names_block = None
        for sub_off in [0x40, 0x20, 0xB0]:
            raw_name = scanner.read_mem(tree_ptr + sub_off, 8)
            if not raw_name:
                continue
            name_ptr = struct.unpack("<Q", raw_name)[0]
            if not is_valid_ptr(name_ptr):
                continue
            nb = scanner.read_mem(name_ptr, max(0x4000, bone_cnt * 32))
            if nb:
                names_block = nb
                break

        if not names_block:
            scanner.xray_cache[u_ptr] = {"empty": True, "info_ptr": current_info_ptr}
            return []

        # หา WTM matrix array
        # Dagor AnimChar GeomNodeTree:
        # +0x00: mat44f *wtm (World/Model Transform Matrix - รวม Hierarchy ป้อมปืน/ลำกล้องแล้ว)
        # +0x10: mat44f *ltm (Local Transform Matrix - พิกัด Local สัมพัทธ์กับกระดูกแม่)
        w_ptr = 0
        for w_off in [0x00, wtm_off]:
            wtm_base_raw = scanner.read_mem(tree_ptr + w_off, 8)
            if not wtm_base_raw:
                continue
            cand_w = struct.unpack("<Q", wtm_base_raw)[0]
            if is_valid_ptr(cand_w):
                w_ptr = cand_w
                break

        if not w_ptr:
            scanner.xray_cache[u_ptr] = {"empty": True, "info_ptr": current_info_ptr}
            return []

        # วิเคราะห์ Component Indices ครบทุกกระดูกตาม bone_cnt จริง
        component_indices = []
        for i in range(min(bone_cnt, 512)):
            try:
                str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                if str_offset == 0 or str_offset >= len(names_block):
                    continue
                end_idx = names_block.find(b"\x00", str_offset)
                if end_idx == -1:
                    continue
                bone_name = names_block[str_offset:end_idx].decode("utf-8", errors="ignore").strip()
                lname = bone_name.lower()

                cat = None
                if "ammo" in lname and ("dm" in lname or "body" in lname or "turret" in lname) and "fire" not in lname:
                    cat = "AMMO"
                elif lname.startswith("gunner_dm"):
                    cat = "GUNNER"
                elif lname.startswith("driver_dm"):
                    cat = "DRIVER"
                elif lname.startswith("commander_dm"):
                    cat = "COMMANDER"
                elif lname.startswith("loader_dm"):
                    cat = "LOADER"
                elif "cannon_breech" in lname:
                    cat = "BREECH"
                elif "rocket_launcher" in lname or "launcher_dm" in lname or "missile_rail" in lname:
                    cat = "BREECH"
                elif lname.startswith("engine_dm"):
                    cat = "ENGINE"
                elif lname.startswith("transmission_dm"):
                    cat = "TRANS"
                elif lname.startswith("radiator_dm"):
                    cat = "RADIATOR"

                if cat:
                    component_indices.append((cat, i, bone_name))
            except Exception:
                pass

        if not component_indices:
            scanner.xray_cache[u_ptr] = {"empty": True, "info_ptr": current_info_ptr}
            return []

        max_idx = max(idx for _, idx, _ in component_indices)
        cache = {
            "tree_ptr": tree_ptr,
            "w_ptr": w_ptr,
            "indices": component_indices,
            "buf_size": (max_idx + 1) * 64,
            "info_ptr": current_info_ptr,
        }
        scanner.xray_cache[u_ptr] = cache

    if cache.get("empty"):
        return []

    # ตรวจสอบ live WTM pointer จาก tree_ptr + 0x00 เสมอ เพื่อความแม่นยำ
    tree_ptr = cache.get("tree_ptr")
    w_ptr = cache.get("w_ptr", 0)
    if tree_ptr:
        live_raw = scanner.read_mem(tree_ptr + 0x00, 8)
        if live_raw:
            live_w = struct.unpack("<Q", live_raw)[0]
            if is_valid_ptr(live_w):
                w_ptr = live_w
    buf_size = cache["buf_size"]
    wtm_buffer = scanner.read_mem(w_ptr, buf_size)
    if not wtm_buffer or len(wtm_buffer) < buf_size:
        return []

    r = unit_rot_matrix
    px, py, pz = unit_pos
    extracted = []
    for cat, idx, name in cache["indices"]:
        offset = idx * 64 + 0x30
        bx, by, bz = struct.unpack_from("<fff", wtm_buffer, offset)
        if math.isfinite(bx) and math.isfinite(by) and math.isfinite(bz):
            if abs(bx) > 0.02 or abs(by) > 0.02 or abs(bz) > 0.02:
                wx = bx * r[0] + by * r[3] + bz * r[6] + px
                wy = bx * r[1] + by * r[4] + bz * r[7] + py
                wz = bx * r[2] + by * r[5] + bz * r[8] + pz
                
                # อ่านทิศทางหันของชิ้นส่วนจาก Row 0 (X axis)
                fx, fy, fz = struct.unpack_from("<fff", wtm_buffer, idx * 64 + 0x00)
                if math.isfinite(fx) and math.isfinite(fy) and math.isfinite(fz):
                    wfx = fx * r[0] + fy * r[3] + fz * r[6]
                    wfy = fx * r[1] + fy * r[4] + fz * r[7]
                    wfz = fx * r[2] + fy * r[5] + fz * r[8]
                else:
                    wfx, wfy, wfz = 0.0, 0.0, 0.0

                extracted.append({
                    "category": cat,
                    "name": name,
                    "local_pos": (bx, by, bz),
                    "world_pos": (wx, wy, wz),
                    "world_forward": (wfx, wfy, wfz),
                })

    return extracted



def get_local_team(scanner, base_addr):
    try:
        # ใช้ตำแหน่งที่เราหาเจอใหม่
        raw_ptr = scanner.read_mem(base_addr + (DAT_CONTROLLED_UNIT - 0x400000), 8)
        if not raw_ptr: return 0, 0
        control_ptr = struct.unpack("<Q", raw_ptr)[0]
        
        # ทีมมักจะอยู่ที่ Offset 0xDE8 หรือ 0xFB8
        team_data = scanner.read_mem(control_ptr + OFF_UNIT_TEAM, 1)
        team = struct.unpack("<B", team_data)[0] if team_data else 0
        return control_ptr, team
    except: return 0, 0

def get_unit_id(scanner, u_ptr):
    if not u_ptr: return -1
    raw = scanner.read_mem(u_ptr + OFF_UNIT_ID, 2)
    return struct.unpack("<H", raw)[0] if raw and len(raw) == 2 else -1

def get_unit_status(scanner, u_ptr, read_name=True):
    if u_ptr == 0: return None
    try:
        # 🎯 FIX: ขยายขนาดการอ่านเป็น 256 bytes เพื่อให้ครอบคลุมถึง OFF_UNIT_TEAM (0xFB8)
        status_data = scanner.read_mem(u_ptr + OFF_UNIT_STATE, 256) 
        if not status_data: return None
        
        state = struct.unpack_from("<H", status_data, 0)[0]
        # คำนวณระยะห่างจากจุดเริ่มสแกน (0xF30) ไปยังทีม (0xFB8)
        team_offset = OFF_UNIT_TEAM - OFF_UNIT_STATE 
        team = struct.unpack_from("<B", status_data, team_offset)[0]
        
        unit_name = "UNKNOWN"
        if read_name:
            info_raw = scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8) 
            if info_raw:
                info_ptr = struct.unpack("<Q", info_raw)[0]
                if is_valid_ptr(info_ptr):
                    for name_off in (OFF_INFO_SHORT_NAME, 0x28, 0x20, 0x10, 0x08):
                        name_ptr_raw = scanner.read_mem(info_ptr + name_off, 8) 
                        if name_ptr_raw:
                            name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                            if is_valid_ptr(name_ptr):
                                str_data = scanner.read_mem(name_ptr, 64)
                                if str_data:
                                    raw_str = str_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
                                    clean_name = "".join([c for c in raw_str if c.isalnum() or c in '-_ ']).strip()
                                    if clean_name:
                                        unit_name = clean_name
                                        break
                                
        # 🎯 ดึงสถานะ Reload (ตอนนี้เป็น 1 ไบต์: 0-16)
        reload_raw = scanner.read_mem(u_ptr + OFF_UNIT_RELOAD, 1)
        reload_val = reload_raw[0] if reload_raw else -1
        return team, state, unit_name, reload_val
    except: return None

def get_unit_detailed_dna(scanner, u_ptr):
    """
    🧬 ดึงข้อมูล DNA เชิงลึกของยูนิต
    """
    try:
        dna = {
            "info_ptr": 0, 
            "name_key": "None",
            "short_name": "None",
            "family": "None",
            "nation_id": -1, 
            "class_id": -1,
            "is_invul": False,
            "invul_timer": 0.0,
            "is_real_player": True,
            "state": -1
        }
        
        # 1. NATION ID
        nation_raw = scanner.read_mem(u_ptr + OFF_UNIT_NATION, 4)
        dna["nation_id"] = struct.unpack("<i", nation_raw)[0] if nation_raw else -1
        
        # 2. INVULNERABLE & TIMER
        invul_raw = scanner.read_mem(u_ptr + OFF_INVULNERABLE, 1)
        timer_raw = scanner.read_mem(u_ptr + OFF_INVUL_TIMER, 4)
        timer_val = struct.unpack("<f", timer_raw)[0] if timer_raw else 0.0
        dna["invul_timer"] = max(0.0, timer_val)
        dna["is_invul"] = bool((invul_raw and invul_raw[0]) or timer_val > 0.05)

        # 2.1 PLAYER INFO (HUMAN VS BOT)
        pinfo_raw = scanner.read_mem(u_ptr + OFF_PLAYER_INFO, 8)
        pinfo_val = struct.unpack("<Q", pinfo_raw)[0] if pinfo_raw else 0
        dna["is_real_player"] = is_valid_ptr(pinfo_val)
        
        # 3. STATE
        state_raw = scanner.read_mem(u_ptr + OFF_UNIT_STATE, 4)
        dna["state"] = struct.unpack("<i", state_raw)[0] if state_raw else -1

        # 4. INFO POINTER ข้อมูลภายใน
        info_ptr_raw = scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8)
        if info_ptr_raw:
            info_ptr = struct.unpack("<Q", info_ptr_raw)[0]
            if is_valid_ptr(info_ptr):
                dna["info_ptr"] = info_ptr
                
                # Name Key
                key_ptr_raw = scanner.read_mem(info_ptr + OFF_INFO_NAME_KEY, 8)
                if key_ptr_raw:
                    key_ptr = struct.unpack("<Q", key_ptr_raw)[0]
                    dna["name_key"] = _read_c_string(scanner, key_ptr) or "None"
                
                # Short Name
                short_ptr_raw = scanner.read_mem(info_ptr + OFF_INFO_SHORT_NAME, 8)
                if short_ptr_raw:
                    short_ptr = struct.unpack("<Q", short_ptr_raw)[0]
                    dna["short_name"] = _read_c_string(scanner, short_ptr) or "None"
                
                # Family
                family_ptr_raw = scanner.read_mem(info_ptr + OFF_INFO_FAMILY, 8)
                if family_ptr_raw:
                    family_ptr = struct.unpack("<Q", family_ptr_raw)[0]
                    dna["family"] = _read_c_string(scanner, family_ptr) or "None"

                # Class ID
                class_raw = scanner.read_mem(info_ptr + OFF_INFO_STATUS, 4)
                dna["class_id"] = struct.unpack("<i", class_raw)[0] if class_raw else -1
        
        return dna
    except: return None
    

# ==========================================
# Velocity Helpers
# ==========================================
def get_air_velocity_detailed(scanner, u_ptr):
    """
    ดึงข้อมูล Air Velocity แบบละเอียดทุกช่องทาง (Candidates):
    1. 🚀 Target High-Tick (41Hz 3D World Vec): OFF_AIR_HIGH_TICK_MOVEMENT (0x20F0) -> (0x07C0, 0x0CF0, 0x0EA4) Float
    2. 🚀 Universal High-Tick (39-46Hz): 0x24C0 -> 0x0E90 Float
    3. 🌟 Local Player High-Tick (57.5Hz): OFF_MY_AIR_MOVEMENT (0x0D48 / 0x0D50) -> 0x0068 Double
    4. 🚀 Target High-Tick Alt 2 (43Hz): 0x14B8 -> 0x0F48 Float
    5. ⚪ Legacy Network Fallback (0.1-5Hz): OFF_AIR_MOVEMENT (0x0018) -> 0x0318 Float

    คืนค่า: ((vx, vy, vz), info_dict)
    """
    info = {
        "source": "none",
        "move_off": 0,
        "vel_off": 0,
        "move_ptr": 0,
        "vel_type": "FLOAT",
        "all_raw": {},
        "chosen_vel": (0.0, 0.0, 0.0),
    }

    try:
        # --- 1. Target High-Tick (0x20F0) ---
        move_raw = scanner.read_mem(u_ptr + OFF_AIR_HIGH_TICK_MOVEMENT, 8)
        if move_raw and len(move_raw) == 8:
            m_ptr = struct.unpack("<Q", move_raw)[0]
            if is_valid_ptr(m_ptr):
                for v_off, key in ((OFF_AIR_HIGH_TICK_VEL, "0x20F0_0x07C0"), (0x0CF0, "0x20F0_0x0CF0"), (0x0EA4, "0x20F0_0x0EA4")):
                    v_raw = scanner.read_mem(m_ptr + v_off, 12)
                    if v_raw and len(v_raw) == 12:
                        vx, vy, vz = struct.unpack("<fff", v_raw)
                        if all(math.isfinite(x) and abs(x) < 2500.0 for x in (vx, vy, vz)):
                            info["all_raw"][key] = (vx, vy, vz)
                            if info["source"] == "none" and any(abs(x) > 0.05 for x in (vx, vy, vz)):
                                info["source"] = key
                                info["move_off"] = OFF_AIR_HIGH_TICK_MOVEMENT
                                info["vel_off"] = v_off
                                info["move_ptr"] = m_ptr
                                info["chosen_vel"] = (vx, vy, vz)

        # --- 2. Universal High-Tick (0x24C0) ---
        move_raw = scanner.read_mem(u_ptr + 0x24C0, 8)
        if move_raw and len(move_raw) == 8:
            m_ptr = struct.unpack("<Q", move_raw)[0]
            if is_valid_ptr(m_ptr):
                v_raw = scanner.read_mem(m_ptr + 0x0E90, 12)
                if v_raw and len(v_raw) == 12:
                    vx, vy, vz = struct.unpack("<fff", v_raw)
                    if all(math.isfinite(x) and abs(x) < 2500.0 for x in (vx, vy, vz)):
                        info["all_raw"]["0x24C0_0x0E90"] = (vx, vy, vz)
                        if info["source"] == "none" and any(abs(x) > 0.05 for x in (vx, vy, vz)):
                            info["source"] = "0x24C0_0x0E90"
                            info["move_off"] = 0x24C0
                            info["vel_off"] = 0x0E90
                            info["move_ptr"] = m_ptr
                            info["chosen_vel"] = (vx, vy, vz)

        # --- 3. Local Player High-Tick (0x0D48 / 0x0D50 Double) ---
        for off_mov in (OFF_MY_AIR_MOVEMENT, 0x0D50, 0x0D28, 0x0D10):
            move_raw = scanner.read_mem(u_ptr + off_mov, 8)
            if move_raw and len(move_raw) == 8:
                m_ptr = struct.unpack("<Q", move_raw)[0]
                if is_valid_ptr(m_ptr):
                    v_raw = scanner.read_mem(m_ptr + OFF_MY_AIR_VEL, 24)
                    if v_raw and len(v_raw) == 24:
                        vx, vy, vz = struct.unpack("<ddd", v_raw)
                        if all(math.isfinite(x) and abs(x) < 2500.0 for x in (vx, vy, vz)):
                            info["all_raw"]["0x0D48_0x0068"] = (vx, vy, vz)
                            if info["source"] == "none" and any(abs(x) > 0.05 for x in (vx, vy, vz)):
                                info["source"] = "0x0D48_0x0068"
                                info["move_off"] = off_mov
                                info["vel_off"] = OFF_MY_AIR_VEL
                                info["move_ptr"] = m_ptr
                                info["vel_type"] = "DOUBLE"
                                info["chosen_vel"] = (vx, vy, vz)
                            break

        # --- 4. Target High-Tick Alt 2 (0x14B8) ---
        move_raw = scanner.read_mem(u_ptr + 0x14B8, 8)
        if move_raw and len(move_raw) == 8:
            m_ptr = struct.unpack("<Q", move_raw)[0]
            if is_valid_ptr(m_ptr):
                v_raw = scanner.read_mem(m_ptr + 0x0F48, 12)
                if v_raw and len(v_raw) == 12:
                    vx, vy, vz = struct.unpack("<fff", v_raw)
                    if all(math.isfinite(x) and abs(x) < 2500.0 for x in (vx, vy, vz)):
                        info["all_raw"]["0x14B8_0x0F48"] = (vx, vy, vz)
                        if info["source"] == "none" and any(abs(x) > 0.05 for x in (vx, vy, vz)):
                            info["source"] = "0x14B8_0x0F48"
                            info["move_off"] = 0x14B8
                            info["vel_off"] = 0x0F48
                            info["move_ptr"] = m_ptr
                            info["chosen_vel"] = (vx, vy, vz)

        # --- 5. Legacy Fallback (0x0018) ---
        move_raw = scanner.read_mem(u_ptr + OFF_AIR_MOVEMENT, 8)
        if move_raw and len(move_raw) == 8:
            m_ptr = struct.unpack("<Q", move_raw)[0]
            if is_valid_ptr(m_ptr):
                v_raw = scanner.read_mem(m_ptr + OFF_AIR_VEL, 12)
                if v_raw and len(v_raw) == 12:
                    vx, vy, vz = struct.unpack("<fff", v_raw)
                    if all(math.isfinite(x) and abs(x) < 2500.0 for x in (vx, vy, vz)):
                        info["all_raw"]["0x0018_0x0318"] = (vx, vy, vz)
                        if info["source"] == "none" and any(abs(x) > 0.05 for x in (vx, vy, vz)):
                            info["source"] = "0x0018_0x0318"
                            info["move_off"] = OFF_AIR_MOVEMENT
                            info["vel_off"] = OFF_AIR_VEL
                            info["move_ptr"] = m_ptr
                            info["chosen_vel"] = (vx, vy, vz)

        return info["chosen_vel"], info
    except Exception:
        return (0.0, 0.0, 0.0), info


def get_air_velocity(scanner, u_ptr):
    """ดึงความเร็วเครื่องบิน 3 มิติ (Air Velocity) คืนค่าเฉพาะเวกเตอร์ (vx, vy, vz)."""
    v, _ = get_air_velocity_detailed(scanner, u_ptr)
    return v

def get_my_air_velocity(scanner, my_unit_ptr):
    """
    [MY UNIT ONLY] ดึงความเร็วเครื่องบินเราเองแบบ High Precision (48-60Hz)
    ใช้ Move Ptr: 0x0D48 / 0x0D50 | Vel Offset: 0x0068 | Type: DOUBLE
    """
    try:
        for off_mov in (OFF_MY_AIR_MOVEMENT, 0x0D50, 0x0D28, 0x0D10):
            move_raw = scanner.read_mem(my_unit_ptr + off_mov, 8)
            if not move_raw:
                continue
            move_ptr = struct.unpack("<Q", move_raw)[0]
            if is_valid_ptr(move_ptr):
                vel_raw = scanner.read_mem(move_ptr + OFF_MY_AIR_VEL, 24)
                if vel_raw and len(vel_raw) == 24:
                    vx, vy, vz = struct.unpack("<ddd", vel_raw)
                    if any(abs(v) > 0.01 for v in (vx, vy, vz)) and all(abs(v) < 2000.0 for v in (vx, vy, vz)):
                        return (vx, vy, vz)
        return (0.0, 0.0, 0.0)
    except Exception as e:
        return (0.0, 0.0, 0.0)


def get_ground_velocity(scanner, u_ptr):
    try:
        # 🌟 1. Fast Path: Read Move Pointer (0x0D30) -> Velocity (0x0068 as double <ddd>)
        mov_raw = scanner.read_mem(u_ptr + OFF_GROUND_MOVEMENT, 8)
        if mov_raw:
            mov_ptr = struct.unpack("<Q", mov_raw)[0]
            if is_valid_ptr(mov_ptr):
                vel_raw = scanner.read_mem(mov_ptr + OFF_GROUND_VEL, 24)
                if vel_raw and len(vel_raw) == 24:
                    vx, vy, vz = struct.unpack("<ddd", vel_raw)
                    if all(math.isfinite(v) for v in (vx, vy, vz)) and all(abs(v) < 500.0 for v in (vx, vy, vz)):
                        return (vx, vy, vz)
        return _read_velocity_by_profile(scanner, u_ptr, "ground")
    except Exception as e:
        dprint(f"VEL READ EXCEPTION | unit={hex(u_ptr)} | type=GROUND | error={e}", force=False)
        return (0.0, 0.0, 0.0)


# ==========================================
# Omega Helpers (Angular Velocity)
# ==========================================
_AIR_ROT_CACHE: Dict[int, Tuple[Tuple[float, ...], float, Tuple[float, float, float], float]] = {}

def get_air_omega_detailed(scanner, unit_ptr):
    """
    ดึงเวกเตอร์ความเร็วเชิงมุม 3 มิติ (rad/s) ของเครื่องบิน พร้อมข้อมูล Offsets ละเอียด:
    1. Net Omega: OFF_AIR_MOVEMENT (0x0018) -> OFF_AIR_OMEGA (0x0550) Float
    2. Kinematic Omega: OFF_UNIT_ROTATION (0x0D14) 3x3 Matrix แบบ Non-Strobe Anti-Jitter (~46Hz)

    คืนค่า: ((wx, wy, wz), info_dict)
    """
    global _AIR_ROT_CACHE
    info = {
        "source": "none",
        "offset": 0,
        "raw_0550": (0.0, 0.0, 0.0),
        "raw_0d14": (0.0, 0.0, 0.0),
        "chosen_omega": (0.0, 0.0, 0.0),
    }

    try:
        # 1. Net Omega (0x0018 + 0x0550)
        mov_ptr_raw = scanner.read_mem(unit_ptr + OFF_AIR_MOVEMENT, 8)
        if mov_ptr_raw and len(mov_ptr_raw) == 8:
            mov_ptr = struct.unpack("<Q", mov_ptr_raw)[0]
            if is_valid_ptr(mov_ptr):
                omega_data = scanner.read_mem(mov_ptr + OFF_AIR_OMEGA, 12)
                if omega_data and len(omega_data) == 12:
                    wx, wy, wz = struct.unpack("<fff", omega_data)
                    if math.isfinite(wx) and math.isfinite(wy) and math.isfinite(wz):
                        info["raw_0550"] = (wx, wy, wz)
                        if (wx*wx + wy*wy + wz*wz) > 1e-4:
                            info["source"] = "0x0018_0x0550"
                            info["offset"] = OFF_AIR_OMEGA
                            info["chosen_omega"] = (wx, wy, wz)
                            return (wx, wy, wz), info

        # 2. Kinematic Omega (OFF_UNIT_ROTATION = 0x0D14)
        rot_raw = scanner.read_mem(unit_ptr + OFF_UNIT_ROTATION, 36)
        if rot_raw and len(rot_raw) == 36:
            r_curr = struct.unpack("<9f", rot_raw)
            if all(math.isfinite(x) for x in r_curr):
                now = time.time()
                cached = _AIR_ROT_CACHE.get(unit_ptr)
                if cached:
                    r_prev, t_prev, w_prev, t_last_change = cached
                    dt = now - t_prev
                    if 0.005 <= dt <= 0.5:
                        # R_rel = r_curr * r_prev^T
                        r_rel = [0.0] * 9
                        for i in range(3):
                            for j in range(3):
                                r_rel[i*3 + j] = sum(r_curr[i*3 + k] * r_prev[j*3 + k] for k in range(3))
                        trace = r_rel[0] + r_rel[4] + r_rel[8]
                        val = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
                        angle = math.acos(val)

                        if angle >= 1e-4:
                            sin_a = math.sin(angle)
                            if abs(sin_a) >= 1e-4:
                                dt_eff = max(0.005, now - t_last_change)
                                scale = angle / (2.0 * sin_a * dt_eff)
                                # 🛠️ Matrix Transposition Alignment:
                                # ในหน่วยความจำของ War Thunder เมทริกซ์ 0x0D14 จัดเก็บแบบ Transpose (Column-Major)
                                # สลับเครื่องหมายให้ตรงกับเวกเตอร์การเลี้ยวจริงใน World Space (+0.615 alignment)
                                raw_wx = (r_rel[5] - r_rel[7]) * scale
                                raw_wy = (r_rel[6] - r_rel[2]) * scale
                                raw_wz = (r_rel[1] - r_rel[3]) * scale
                                if all(math.isfinite(x) and abs(x) < 25.0 for x in (raw_wx, raw_wy, raw_wz)):
                                    # Low-Pass Filter ป้องกันการสไปก์ฉับพลัน
                                    filt_wx = (w_prev[0] * 0.35) + (raw_wx * 0.65)
                                    filt_wy = (w_prev[1] * 0.35) + (raw_wy * 0.65)
                                    filt_wz = (w_prev[2] * 0.35) + (raw_wz * 0.65)
                                    w_res = (filt_wx, filt_wy, filt_wz)
                                    _AIR_ROT_CACHE[unit_ptr] = (r_curr, now, w_res, now)
                                    info["raw_0d14"] = w_res
                                    info["source"] = "0x0D14_RotMatrix"
                                    info["offset"] = OFF_UNIT_ROTATION
                                    info["chosen_omega"] = w_res
                                    return w_res, info
                        else:
                            # 🛡️ ANTI-STROBE: เมื่อ Matrix ยังไม่อัปเดตในเฟรมนี้ (เช่น overlay 60Hz แต่เกมอัปเดต 46Hz)
                            # ไม่ดรอปเป็น 0 ทันที เพื่อป้องกัน Jitter แบบฟันปลา!
                            idle_time = now - t_last_change
                            if idle_time < 0.08:
                                # คงค่าเดิมไว้เพื่อให้ Leadmark นิ่งสนิท
                                info["raw_0d14"] = w_prev
                                info["source"] = "0x0D14_RotMatrix_Hold"
                                info["offset"] = OFF_UNIT_ROTATION
                                info["chosen_omega"] = w_prev
                                return w_prev, info
                            elif idle_time < 0.25:
                                # ค่อยๆ Decay สู่ 0 อย่างนุ่มนวล
                                decay = max(0.0, 1.0 - ((idle_time - 0.08) / 0.17))
                                w_decayed = (w_prev[0] * decay, w_prev[1] * decay, w_prev[2] * decay)
                                info["raw_0d14"] = w_decayed
                                info["source"] = "0x0D14_RotMatrix_Decay"
                                info["offset"] = OFF_UNIT_ROTATION
                                info["chosen_omega"] = w_decayed
                                return w_decayed, info
                            else:
                                # เครื่องบินบินตรงจริงๆ เกิน 0.25 วินาที
                                _AIR_ROT_CACHE[unit_ptr] = (r_curr, now, (0.0, 0.0, 0.0), now)
                                info["source"] = "0x0D14_Cruising"
                                info["offset"] = OFF_UNIT_ROTATION
                                return (0.0, 0.0, 0.0), info
                else:
                    _AIR_ROT_CACHE[unit_ptr] = (r_curr, now, (0.0, 0.0, 0.0), now)
    except Exception as e:
        dprint(f"get_air_omega error: {e}", force=False)

    return (0.0, 0.0, 0.0), info


def get_air_omega(scanner, unit_ptr):
    """ดึงเวกเตอร์ความเร็วเชิงมุม 3 มิติ (rad/s) คืนค่าเฉพาะเวกเตอร์ (wx, wy, wz)."""
    w, _ = get_air_omega_detailed(scanner, unit_ptr)
    return w


def get_my_air_omega(scanner, my_unit_ptr):
    """
    [MY UNIT ONLY] ดึงความเร็วเชิงมุมเครื่องบินเราเองแบบ High-Tick (~50Hz)
    อ่านจาก OFF_MY_AIR_MOVEMENT (0x0D48 / 0x0D50) -> OFF_MY_AIR_OMEGA (0x0098) แบบ Double (<ddd)
    """
    try:
        for off_mov in (OFF_MY_AIR_MOVEMENT, 0x0D50, 0x0D28, 0x0D10):
            move_raw = scanner.read_mem(my_unit_ptr + off_mov, 8)
            if not move_raw:
                continue
            move_ptr = struct.unpack("<Q", move_raw)[0]
            if is_valid_ptr(move_ptr):
                omega_raw = scanner.read_mem(move_ptr + OFF_MY_AIR_OMEGA, 24)
                if omega_raw and len(omega_raw) == 24:
                    wx, wy, wz = struct.unpack("<ddd", omega_raw)
                    if all(math.isfinite(v) for v in (wx, wy, wz)):
                        return (wx, wy, wz)
        return (0.0, 0.0, 0.0)
    except Exception as e:
        dprint(f"get_my_air_omega error: {e}", force=False)
        return (0.0, 0.0, 0.0)


def get_ground_omega(scanner, unit_ptr):
    return (0.0, 0.0, 0.0)


# ==========================================
# Ballistics Helpers
# ==========================================
def get_bullet_speed(scanner, cgame_base):
    try:
        raw_weapon_ptr = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if not raw_weapon_ptr: return 0.0
        weapon_ptr = struct.unpack("<Q", raw_weapon_ptr)[0]
        if not is_valid_ptr(weapon_ptr): return 0.0
        
        speed_data = scanner.read_mem(weapon_ptr + OFF_BULLET_SPEED, 4)
        if not speed_data: return 0.0
        speed = struct.unpack("<f", speed_data)[0]
        if math.isfinite(speed) and 50.0 < speed < 3000.0: return speed
        return 0.0
    except Exception as e: 
        return 0.0

def get_pince_segment(pid, segment_idx=4):
    segments = []
    try:
        with open(f"/proc/{pid}/maps", "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 6 and 'aces' in parts[-1] and not '.so' in parts[-1]:
                    start_addr = int(parts[0].split('-')[0], 16)
                    if start_addr not in segments: segments.append(start_addr)
        if len(segments) > segment_idx: return segments[segment_idx]
        elif segments: return segments[-1]
    except Exception as e:
        print("get_bullet_speed: ", e)
    return 0

def get_sight_compensation_factor(scanner, base_addr):
    pid = scanner.pid if hasattr(scanner, 'pid') else None
    if not pid: return 0.0
    aces_4_base = get_pince_segment(pid, 4)
    if aces_4_base == 0: return 0.0
    
    for chain in SIGHT_POINTER_CHAINS:
        try:
            raw_base_ptr = scanner.read_mem(aces_4_base + chain[0], 8)
            if not raw_base_ptr: continue
            ptr = struct.unpack("<Q", raw_base_ptr)[0]
            if not is_valid_ptr(ptr): continue
            
            valid_chain = True
            for offset in chain[1:-1]:
                raw_ptr = scanner.read_mem(ptr + offset, 8)
                if not raw_ptr: valid_chain = False; break
                ptr = struct.unpack("<Q", raw_ptr)[0]
                if not is_valid_ptr(ptr): valid_chain = False; break
            if not valid_chain: continue
            
            data = scanner.read_mem(ptr + chain[-1], 4)
            if data:
                val = struct.unpack("<f", data)[0]
                if val < 0.0: return 0.0
                elif math.isfinite(val) and 0.0 <= val <= 10000.0: return val
        except Exception as e: 
            print("get_sight_compensation_factor: ", e)
            continue
    return 0.0

def get_bullet_mass(scanner, cgame_base):
    try:
        w_ptr_raw = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if not w_ptr_raw: return 0.0
        w_ptr = struct.unpack("<Q", w_ptr_raw)[0]
        if not is_valid_ptr(w_ptr): return 0.0
        
        data = scanner.read_mem(w_ptr + OFF_BULLET_MASS, 4)
        if data:
            mass = struct.unpack("<f", data)[0]
            if math.isfinite(mass) and 0.005 <= mass <= 200.0: return mass
        return 0.0
    except: return 0.0

def get_bullet_caliber(scanner, cgame_base):
    try:
        w_ptr_raw = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if not w_ptr_raw: return 0.0
        w_ptr = struct.unpack("<Q", w_ptr_raw)[0]
        if not is_valid_ptr(w_ptr): return 0.0
        
        data = scanner.read_mem(w_ptr + OFF_BULLET_CALIBER, 4)
        if data:
            caliber = struct.unpack("<f", data)[0]
            if math.isfinite(caliber) and 0.005 <= caliber <= 0.5: return caliber
        return 0.0
    except: return 0.0

def get_bullet_cd(scanner, cgame_base):
    try:
        w_ptr_raw = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if not w_ptr_raw: return 0.0
        w_ptr = struct.unpack("<Q", w_ptr_raw)[0]
        if not is_valid_ptr(w_ptr): return 0.0
        
        data = scanner.read_mem(w_ptr + OFF_BULLET_CD, 4)
        if data:
            cd = struct.unpack("<f", data)[0]
            if math.isfinite(cd) and 0.05 <= cd <= 2.0: return cd
        return 0.0
    except: return 0.0

_LAST_IMPACT_RAW = None
_LAST_IMPACT_CHANGE_TIME = 0.0
_LAST_MY_POS_FOR_CCIP = None
_LAST_SPEED_GOOD_TIME = 0.0

def get_direct_bomb_impact(scanner, cgame_base, unit_ptr=0, my_pos=None):
    """
    อ่านจุดตกกระทบของระเบิด/จรวดที่ Dagor Engine คำนวณไว้ในหน่วยความจำโดยตรง (+ 0x1CBC)
    พร้อมระบบตรวจจับ Candidate offsets และตรวจจับจุดตกค้าง (Freeze Vector)
    """
    global _LAST_IMPACT_RAW, _LAST_IMPACT_CHANGE_TIME, _LAST_MY_POS_FOR_CCIP
    if cgame_base == 0:
        return None
    try:
        weapon_ptr = 0
        # Priority 1: cgame_base + OFF_WEAPON_PTR (Primary global weapon container)
        if is_valid_ptr(cgame_base):
            raw_w = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
            if raw_w and len(raw_w) == 8:
                ptr_cand = struct.unpack("<Q", raw_w)[0]
                if is_valid_ptr(ptr_cand) and ptr_cand < 0x7FF000000000:
                    weapon_ptr = ptr_cand

        # Priority 2: Fallback to unit_ptr + OFF_WEAPON_PTR if cgame_base didn't return valid heap pointer
        if not is_valid_ptr(weapon_ptr) and is_valid_ptr(unit_ptr):
            raw_w = scanner.read_mem(unit_ptr + OFF_WEAPON_PTR, 8)
            if raw_w and len(raw_w) == 8:
                ptr_cand = struct.unpack("<Q", raw_w)[0]
                if is_valid_ptr(ptr_cand) and ptr_cand < 0x7FF000000000:
                    weapon_ptr = ptr_cand

        if not is_valid_ptr(weapon_ptr):
            return None

        # 1. ตรวจสอบ OFF_CCIP_IMPACT (0x1CCC) และ Fallback pylon offsets (0x1CBC, 0x117C, 0x114C, 0x111C, 0x10EC, 0x1C9C)
        offsets_to_try = [
            OFF_CCIP_IMPACT,
            0x1CCC,
            0x1CBC,
            0x117C,
            0x114C,
            0x111C,
            0x10EC,
            0x1C9C,
        ]

        impact_cand = None
        for off in offsets_to_try:
            raw_impact = scanner.read_mem(weapon_ptr + off, 12)
            if not raw_impact or len(raw_impact) < 12:
                continue

            ix, iy, iz = struct.unpack("<fff", raw_impact)
            if not (math.isfinite(ix) and math.isfinite(iy) and math.isfinite(iz)):
                continue

            if abs(ix) >= 100000.0 or abs(iy) >= 100000.0 or abs(iz) >= 100000.0:
                continue

            if ix == 0.0 and iy == 0.0 and iz == 0.0:
                continue

            if my_pos:
                dx = ix - my_pos[0]
                dy = iy - my_pos[1]
                dz = iz - my_pos[2]
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist <= 5.0 or dist >= 50000.0:
                    continue

            impact_cand = (ix, iy, iz)
            break

        if not impact_cand:
            return None

        ix, iy, iz = impact_cand

        # 2. ระบบตรวจจับ Freeze / Stale Memory Vector
        # เมื่อเครื่องบินกำลังบินอยู่ ค่าจุดตกกระทบใน World Space ต้องมีการขยับอัปเดตเสมอ
        # หากพิกัดค้างเท่าเดิมแบบ 100% ขณะเครื่องบินบินผ่านระยะทาง > 50 เมตร นานเกิน 2.5 วินาที ให้ถือว่าจุดตกค้าง (ระเบิดหมด)
        now_time = time.time()
        current_impact_tuple = (ix, iy, iz)
        if _LAST_IMPACT_RAW != current_impact_tuple:
            _LAST_IMPACT_RAW = current_impact_tuple
            _LAST_IMPACT_CHANGE_TIME = now_time
            if my_pos:
                _LAST_MY_POS_FOR_CCIP = my_pos
        else:
            if my_pos and _LAST_MY_POS_FOR_CCIP:
                m_dx = my_pos[0] - _LAST_MY_POS_FOR_CCIP[0]
                m_dy = my_pos[1] - _LAST_MY_POS_FOR_CCIP[1]
                m_dz = my_pos[2] - _LAST_MY_POS_FOR_CCIP[2]
                my_moved_dist = math.sqrt(m_dx * m_dx + m_dy * m_dy + m_dz * m_dz)
                if my_moved_dist > 50.0 and (now_time - _LAST_IMPACT_CHANGE_TIME) > 2.5:
                    return None

        return (ix, iy, iz)
    except Exception:
        return None


def get_unit_invulnerable(scanner, u_ptr) -> Tuple[bool, float]:
    """
    🛡️ อ่านสถานะอมตะเกิดใหม่ (Spawn Protection) ของยูนิต
    คืนค่า (is_invul: bool, remaining_seconds: float)
    """
    if not u_ptr or not scanner:
        return False, 0.0
    try:
        raw = scanner.read_mem(u_ptr + OFF_INVUL_TIMER, OFF_INVULNERABLE - OFF_INVUL_TIMER + 1)
        if not raw:
            return False, 0.0
        timer = struct.unpack_from("<f", raw, 0)[0]
        invul_byte = raw[OFF_INVULNERABLE - OFF_INVUL_TIMER]
        is_invul = bool(invul_byte != 0 or timer > 0.05)
        return is_invul, max(0.0, float(timer))
    except Exception:
        return False, 0.0


def get_unit_is_real_player(scanner, u_ptr) -> bool:
    """
    👤 ตรวจสอบว่าเป็นผู้เล่นจริง (Human Player) หรือ AI Bot / ยูนิตเสริม
    คืนค่า True หากมี PlayerInfo pointer ที่ถูกต้อง, คืนค่า False หากเป็น AI Bot
    """
    if not u_ptr or not scanner:
        return False
    try:
        raw = scanner.read_mem(u_ptr + OFF_PLAYER_INFO, 8)
        if not raw:
            return False
        p_info = struct.unpack("<Q", raw)[0]
        return is_valid_ptr(p_info)
    except Exception:
        return False


def get_dynamic_weapon_info(scanner, cgame_base) -> Tuple[float, float, float, float]:
    """
    🔫 ดึงข้อมูล Ballistics & Caliber สดจาก CGame Weapon Container
    คืนค่า (speed_mps, mass_kg, caliber_mm, drag_cd)
    """
    if not cgame_base or not scanner:
        return 0.0, 0.0, 0.0, 0.0
    try:
        raw_w = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if not raw_w:
            return 0.0, 0.0, 0.0, 0.0
        w_ptr = struct.unpack("<Q", raw_w)[0]
        if not is_valid_ptr(w_ptr):
            return 0.0, 0.0, 0.0, 0.0
        raw_b = scanner.read_mem(w_ptr + OFF_BULLET_SPEED, 0x18)
        if not raw_b:
            return 0.0, 0.0, 0.0, 0.0
        speed = struct.unpack_from("<f", raw_b, 0)[0]
        mass = struct.unpack_from("<f", raw_b, OFF_BULLET_MASS - OFF_BULLET_SPEED)[0]
        caliber_m = struct.unpack_from("<f", raw_b, OFF_BULLET_CALIBER - OFF_BULLET_SPEED)[0]
        cd = struct.unpack_from("<f", raw_b, OFF_BULLET_CD - OFF_BULLET_SPEED)[0]
        return float(speed), float(mass), float(caliber_m * 1000.0), float(cd)
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


def is_unit_air_fast(scanner, u_ptr) -> bool:
    """
    ✈️ ตรวจสอบอย่างรวดเร็วระดับ O(1) ว่ายูนิตเป็นอากาศยานหรือไม่
    (Air/Heli จะมีค่าคงที่ 0x0000000200000001 ที่ offset 0x80)
    """
    if not u_ptr or not scanner:
        return False
    try:
        raw = scanner.read_mem(u_ptr + OFF_UNIT_TYPE, 8)
        if not raw or len(raw) < 8:
            return False
        val64 = struct.unpack("<Q", raw)[0]
        return val64 == 0x0000000200000001
    except Exception:
        return False



