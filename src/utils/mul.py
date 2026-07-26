import struct
import math
import os
import time

try:
    from src.utils.debug import dprint
except Exception:
    def dprint(msg, force=False):
        return

# ===================================================
# 🎯 2026 VERIFIED OFFSETS (อัปเดตล่าสุด)
# ===================================================
GHIDRA_BASE         = 0x400000
DAT_MANAGER         = 0x941b280
MANAGER_OFFSET      = DAT_MANAGER - GHIDRA_BASE
MANAGER_CANDIDATE_OFFSETS = []
DAT_CONTROLLED_UNIT = 0x981dfc8

OFF_CAMERA_PTR      = 0x670
OFF_VIEW_MATRIX     = 0x1D8

OFF_UNIT_X          = 0x0D00
OFF_UNIT_ROTATION   = OFF_UNIT_X - 0x24
OFF_UNIT_BBMIN      = 0x0258
OFF_UNIT_BBMAX      = 0x0264
_BBOX_FALLBACK_LOGGED = set()

# 🟢 สถานะและข้อมูลของยูนิต (เพิ่งอัปเดตใหม่)
OFF_UNIT_STATE      = 0         # สถานะรถถัง (เป็น/ตาย)
OFF_UNIT_TEAM       = 0         # ทีม (มิตร/ศัตรู)
OFF_UNIT_INFO       = 0xfc0        # 🎯 ฐานข้อมูล Unit Info
OFF_INFO_NAME_KEY   = 0x40         # 📛 Key สำหรับชื่อจริง (Localized)
OFF_INFO_SHORT_NAME = 0x28         # 🏷️ ชื่อย่อยูนิต (เช่น T-34-85)
OFF_INFO_FAMILY     = 0x38         # 📂 ตระกูลยูนิต (เช่น exp_tank)
OFF_INFO_STATUS     = 0x290        # 📊 สถานะพิเศษ (Class ID)
OFF_UNIT_NATION     = 0x98c        # 🏳️ ID ประเทศ
OFF_UNIT_INVUL      = 0xe58        # 🛡️ สถานะอมตะ (Is Invulnerable)
OFF_UNIT_CLASS_PTR  = 0      # 🎯 Pointer ไปหาประเภทรถ (เช่น Light tank, Medium tank)

OFF_UNIT_TYPE_PTR   = 0      # 🎯 Pointer ไปหาชนิด (เช่น exp_tank)
OFF_UNIT_NAME_PTR   = 0      # 🎯 Pointer ไปหาชื่อย่อ (เช่น ussr_2s38)
OFF_UNIT_RELOADING  = 0
OFF_UNIT_RELOAD     = 0

OFF_ACTIVE_UNITS    = (0x310, False, 0x14)  # Air/clean subset.
OFF_ACTIVE_EXTRA_UNIT_LISTS = (
    (0x328, False, 0x10),  # Ground-ish subset; combined with 0x310 covers more units than either alone.
)
ENABLE_WORLD_UNIT_LIST_FALLBACK = False
OFF_AIR_UNITS       = (0x340, True)
OFF_AIR_MOVEMENT    = 0x0018      # 🎯 Air-specific movement ptr from air kinematics dumpers
OFF_AIR_VEL         = 0x0318      # 🎯 Velocity (FLOAT Vector 12-byte)
OFF_AIR_OMEGA       = 0x3F8       # 🌪️ Angular Velocity (ยังคงเป็นค่านี้)
OFF_MY_AIR_VEL      = 0x0068      # My air velocity: DOUBLE vec3 at move_ptr + 0x0068 (47.5Hz)
OFF_MY_AIR_MOVEMENT = 0x0D10      # My air movement pointer from tick-rate scan

OFF_GROUND_UNITS    = (0x358, False)
OFF_GROUND_MOVEMENT = 0x1118
OFF_GROUND_VEL      = 0x00FC
OFF_GROUND_OMEGA    = 0
FILTER_ZERO_POS_UNITS = True
# 🔫 ระบบขีปนาวุธ (BALLISTICS - อัปเดตจาก layout_old_guess Persistence)
OFF_WEAPON_PTR      = 0x3f0        # 🎯 อัปเดตจากผลสแกน Ballistic
OFF_BULLET_SPEED    = 0x2050     # 🎯 ความเร็วต้น (Muzzle Velocity - 8272)
OFF_BULLET_MASS     = 0x205C      # ⚖️ มวลกระสุน (8284)
OFF_BULLET_CALIBER  = 0x2060   # 📏 Caliber (8288)
OFF_BULLET_CD       = 0x2064        # 💨 Drag Coeff (8292)

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
    return 0x10000 < p < 0xFFFFFFFFFFFFFFFF


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
            "label": "AIR_PRIMARY",
            "mov_off": lambda: 0x0000,
            "vel_off": lambda: 0x3A58,
            "fmt": "fff",
            "max_speed": 12000.0,
        },
        "fallbacks": [
            {"label": "GROUND_ALT", "mov_off": 0x0D10, "vel_off": 0x0068, "fmt": "ddd", "max_speed": 12000.0},
        ],
    },
    "ground": {
        "requested_label": "GROUND",
        "primary": {
            "label": "GROUND_PRIMARY",
            "mov_off": lambda: OFF_GROUND_MOVEMENT,
            "vel_off": lambda: OFF_GROUND_VEL,
            "fmt": "fff",
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

    for unit_off, _ in (OFF_AIR_UNITS, OFF_GROUND_UNITS):
        raw_array_ptr = scanner.read_mem(cgame_ptr + unit_off, 8)
        raw_count = scanner.read_mem(cgame_ptr + unit_off + 16, 4)
        if not raw_array_ptr or len(raw_array_ptr) < 8 or not raw_count or len(raw_count) < 4:
            continue

        array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
        count = struct.unpack("<I", raw_count)[0]

        if 0 <= count <= 2048:
            score += 1
        if count > 0 and count < 2048 and is_valid_ptr(array_ptr):
            score += 2
            total_units += count

            sample_n = min(count, 48)
            ptr_data = scanner.read_mem(array_ptr, sample_n * 8)
            if ptr_data and len(ptr_data) >= sample_n * 8:
                valid_units = 0
                for i in range(sample_n):
                    u_ptr = struct.unpack_from("<Q", ptr_data, i * 8)[0]
                    if is_valid_ptr(u_ptr):
                        valid_units += 1
                if valid_units:
                    score += min(valid_units, 10)

    if total_units > 0:
        score += min(total_units, 80) // 8

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
        if 0x670 not in cam_offsets:
            cam_offsets.append(0x670)
        matrix_offsets = [OFF_VIEW_MATRIX]
        if 0x1C0 not in matrix_offsets:
            matrix_offsets.append(0x1C0)

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
                    if non_zero >= 6 and all(math.isfinite(v) and abs(v) <= 1e6 for v in values):
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
        return non_zero >= 6

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
    if 0x670 not in cam_offsets:
        cam_offsets.append(0x670)

    matrix_offsets = [OFF_VIEW_MATRIX]
    if 0x1C0 not in matrix_offsets:
        matrix_offsets.append(0x1C0)

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
        else:
            continue
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
        
        # ถ้ายูนิตอยู่หลังกล้อง ให้ตัดทิ้ง
        if w < 0.01 or not math.isfinite(w): 
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
    target_bone_index = -1
    wtm_ptr = 0

    try:
        current_info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO) if OFF_UNIT_INFO else 0
        if u_ptr in scanner.bone_cache:
            cache = scanner.bone_cache[u_ptr]
            cache_expired = False
            if cache.get('info_ptr') and current_info_ptr and cache.get('info_ptr') != current_info_ptr:
                cache_expired = True
            if not cache_expired:
                reuse_count = int(cache.get('reuse_count', 0) or 0) + 1
                cache['reuse_count'] = reuse_count
                if reuse_count >= 240:
                    cache_expired = True
            if cache_expired:
                del scanner.bone_cache[u_ptr]
            else:
                # Dynamic WTM matrix array: tree_ptr + 0x00
                cached_tree = cache.get('tree_ptr', 0)
                cached_wtm_off = cache.get('wtm_off', 0x00)
                if cached_tree and is_valid_ptr(cached_tree):
                    wtm_raw = scanner.read_mem(cached_tree + cached_wtm_off, 8)
                    if wtm_raw:
                        w_ptr = struct.unpack("<Q", wtm_raw)[0]
                        if is_valid_ptr(w_ptr):
                            target_idx = cache['bone_idx']
                            matrix_data = scanner.read_mem(w_ptr + (target_idx * 64), 64)
                            if matrix_data and len(matrix_data) == 64:
                                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30)
                                if math.isfinite(bx) and math.isfinite(by) and math.isfinite(bz) and abs(bx) < 5000 and abs(by) < 5000 and abs(bz) < 5000:
                                    wtm_ptr = w_ptr
                                    target_bone_index = target_idx
                                else:
                                    del scanner.bone_cache[u_ptr]
                            else:
                                del scanner.bone_cache[u_ptr]
                        else:
                            del scanner.bone_cache[u_ptr]
                    else:
                        del scanner.bone_cache[u_ptr]
        if u_ptr not in scanner.bone_cache:
            try:
                import src.utils.scanner as scanner_mod
                persisted = scanner_mod._load_barrel_persistence()
                if persisted:
                    animchar_off = persisted.get("animchar_off")
                    wtm_off = persisted.get("wtm_off", 0x00)
                    bone_idx = persisted.get("bone_idx")
                    raw_ptr = scanner.read_mem(u_ptr + animchar_off, 8)
                    if raw_ptr:
                        tree_ptr = struct.unpack("<Q", raw_ptr)[0]
                        if is_valid_ptr(tree_ptr):
                            wtm_base_raw = scanner.read_mem(tree_ptr + wtm_off, 8)
                            if wtm_base_raw:
                                w_ptr = struct.unpack("<Q", wtm_base_raw)[0]
                                if is_valid_ptr(w_ptr):
                                    matrix_data = scanner.read_mem(w_ptr + (bone_idx * 64), 64)
                                    if matrix_data and len(matrix_data) == 64:
                                        fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00)
                                        bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30)
                                        f_len = (fx*fx + fy*fy + fz*fz) ** 0.5
                                        if math.isfinite(bx) and math.isfinite(fx) and (0.5 < f_len < 2.0):
                                            wtm_ptr = w_ptr
                                            target_bone_index = bone_idx
                                            scanner.bone_cache[u_ptr] = {
                                                "tree_ptr": tree_ptr,
                                                "wtm_off": wtm_off,
                                                "bone_idx": bone_idx,
                                                "info_ptr": current_info_ptr,
                                            }
            except Exception:
                pass

        if wtm_ptr == 0 or target_bone_index == -1:
            best_score, best_idx = -1, -1
            
            u_ptr_tree = 0
            best_tree_off = 0
            best_sub_off = 0
            for off in [0x238, 0x1F0, 0x1FD8, 0x2E20, 0x2F38, 0x1E8, 0x1E0, 0x1D8, 0x200, 0x210, 0x228, 0x1C8, 0x3E8, 0x400, 0x13B0]:
                raw_ptr = scanner.read_mem(u_ptr + off, 8)
                if not raw_ptr: continue
                tree_ptr = struct.unpack("<Q", raw_ptr)[0]
                if not is_valid_ptr(tree_ptr): continue
                
                for sub_off in [0x40, 0x20, 0xB0]:
                    raw_name = scanner.read_mem(tree_ptr + sub_off, 8)
                    if not raw_name: continue
                    name_ptr = struct.unpack("<Q", raw_name)[0]
                    if not is_valid_ptr(name_ptr): continue
                    names_block = scanner.read_mem(name_ptr, 0x4000)
                    if not names_block: continue
                        
                    for i in range(400):
                        try:
                            str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                            if str_offset == 0 or str_offset >= len(names_block): continue
                            end_idx = names_block.find(b'\x00', str_offset)
                            if end_idx != -1:
                                bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').lower().strip()
                                score = -1
                                if "bone_gun_barrel" in bone_name: score = 100
                                elif "gun_barrel" in bone_name: score = 80
                                elif "bone_gun" in bone_name and bone_name == "bone_gun": score = 70
                                elif "bone_gun" in bone_name: score = 60
                                elif "barrel" in bone_name: score = 40
                                if any(b in bone_name for b in ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root"]): score = -100
                                if score > best_score:
                                    best_score = score
                                    best_idx = i
                                    u_ptr_tree = tree_ptr
                                    best_tree_off = off
                                    best_sub_off = sub_off
                                if best_score >= 100: break
                        except: pass
                    if best_score >= 100: break
                if best_score >= 100: break

            if best_idx != -1:
                wtm_found = False
                for wtm_off in [0x00, 0x10]:
                    wtm_base_raw = scanner.read_mem(u_ptr_tree + wtm_off, 8)
                    if not wtm_base_raw: continue
                    w_ptr = struct.unpack("<Q", wtm_base_raw)[0]
                    if not is_valid_ptr(w_ptr): continue
                    
                    matrix_data = scanner.read_mem(w_ptr + (best_idx * 64), 64)
                    if matrix_data and len(matrix_data) == 64:
                        fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00) # Row 0 (X axis / barrel forward)
                        bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30) # Row 3 (Local Pos)
                        if math.isfinite(bx) and math.isfinite(by) and math.isfinite(bz) and math.isfinite(fx):
                            f_len = (fx*fx + fy*fy + fz*fz) ** 0.5
                            if (abs(bx) > 0.1 or abs(by) > 0.1 or abs(bz) > 0.1) and abs(bx) < 15 and abs(by) < 15 and abs(bz) < 15 and 0.5 < f_len < 2.0:
                                wtm_ptr = w_ptr
                                target_bone_index = best_idx
                                scanner.bone_cache[u_ptr] = {
                                    "tree_ptr": u_ptr_tree,
                                    "wtm_off": wtm_off,
                                    "bone_idx": best_idx,
                                    "info_ptr": current_info_ptr,
                                }
                                wtm_found = True
                                break

        if wtm_ptr != 0 and target_bone_index != -1:
            matrix_data = scanner.read_mem(wtm_ptr + (target_bone_index * 64), 64)
            if matrix_data and len(matrix_data) == 64:
                fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00) # Row 0 (X axis / barrel forward)
                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30) # Row 3 (Local Pos) 
                if math.isfinite(bx) and math.isfinite(by) and math.isfinite(bz):
                    if abs(bx) < 0.1 and abs(by) < 0.1 and abs(bz) < 0.1:
                        return None
                        
                    if not math.isfinite(fx) or not math.isfinite(fy) or not math.isfinite(fz):
                        return None
                        
                    f_len = (fx*fx + fy*fy + fz*fz) ** 0.5
                    if not (0.5 < f_len < 2.0) or abs(bx) > 30 or abs(by) > 30 or abs(bz) > 30:
                        return None
                        
                    length = 8.0 
                    if abs(bx) > 500.0 or abs(by) > 500.0: # Keeping this as a fallback just in case
                        return (bx, by, bz), (bx + (fx * length), by + (fy * length), bz + (fz * length))
                    else:
                        def to_world(lx, ly, lz):
                            return (lx*unit_rot_matrix[0] + ly*unit_rot_matrix[3] + lz*unit_rot_matrix[6] + unit_pos[0],
                                    lx*unit_rot_matrix[1] + ly*unit_rot_matrix[4] + lz*unit_rot_matrix[7] + unit_pos[1],
                                    lx*unit_rot_matrix[2] + ly*unit_rot_matrix[5] + lz*unit_rot_matrix[8] + unit_pos[2])
                        return to_world(bx, by, bz), to_world(bx + (fx * length), by + (fy * length), bz + (fz * length))
    except Exception as e:
        pass
    return None


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

def get_unit_status(scanner, u_ptr):
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
        info_raw = scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8) 
        if info_raw:
            info_ptr = struct.unpack("<Q", info_raw)[0]
            if is_valid_ptr(info_ptr):
                name_ptr_raw = scanner.read_mem(info_ptr + OFF_UNIT_NAME_PTR, 8) 
                if name_ptr_raw:
                    name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                    if is_valid_ptr(name_ptr):
                        str_data = scanner.read_mem(name_ptr, 64)
                        if str_data:
                            raw_str = str_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
                            unit_name = "".join([c for c in raw_str if c.isalnum() or c in '-_'])
                                
        # 🎯 ดึงสถานะ Reload (ตอนนี้เป็น 1 ไบต์: 0-16)
        reload_raw = scanner.read_mem(u_ptr + OFF_UNIT_RELOAD, 1)
        reload_val = struct.unpack("<B", reload_raw)[0] if reload_raw else -1
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
            "state": -1
        }
        
        # 1. NATION ID
        nation_raw = scanner.read_mem(u_ptr + OFF_UNIT_NATION, 4)
        dna["nation_id"] = struct.unpack("<i", nation_raw)[0] if nation_raw else -1
        
        # 2. INVULNERABLE
        invul_raw = scanner.read_mem(u_ptr + OFF_UNIT_INVUL, 1)
        dna["is_invul"] = bool(invul_raw[0]) if invul_raw else False
        
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
def get_air_velocity(scanner, u_ptr):
    """
    [2026 VERIFIED 60Hz] ดึงความเร็วเครื่องบิน 3 มิติแบบ High-Tick (Smooth)
    ใช้ระบบ Waterfall ลำดับความสำคัญจากผล Dumper ที่ดีที่สุด
    """
    try:
        # 🌟 1. [60Hz] อ่านตรงจาก Unit Pointer (0x3A58) - ไวที่สุด!
        vel_raw = scanner.read_mem(u_ptr + 0x3A58, 12)
        if vel_raw:
            vx, vy, vz = struct.unpack("<fff", vel_raw)
            if any(abs(v) > 0.01 for v in (vx, vy, vz)) and all(abs(v) < 2000.0 for v in (vx, vy, vz)):
                return (vx, vy, vz)

        # 🌟 2. [60Hz] สำรอง อ่านตรงจาก Unit Pointer (0x3F48)
        vel_raw = scanner.read_mem(u_ptr + 0x3F48, 12)
        if vel_raw:
            vx, vy, vz = struct.unpack("<fff", vel_raw)
            if any(abs(v) > 0.01 for v in (vx, vy, vz)) and all(abs(v) < 2000.0 for v in (vx, vy, vz)):
                return (vx, vy, vz)

        # 🌟 3. เข้าสู่ชั้น Move Pointer (ลึกขึ้น 1 สเต็ป)
        move_raw = scanner.read_mem(u_ptr + 0x0018, 8)
        if move_raw:
            move_ptr = struct.unpack("<Q", move_raw)[0]
            if move_ptr > 0x10000:
                
                # 🌟 3.1 [60Hz] ผ่าน Move Pointer (0x137C)
                vel_raw = scanner.read_mem(move_ptr + 0x137C, 12)
                if vel_raw:
                    vx, vy, vz = struct.unpack("<fff", vel_raw)
                    if any(abs(v) > 0.01 for v in (vx, vy, vz)) and all(abs(v) < 2000.0 for v in (vx, vy, vz)):
                        return (vx, vy, vz)
                dprint(f"Air Velocity Fallback to 5Hz", force=True)
                # 🌟 4. [5Hz] FALLBACK: ตัว Network แม่แบบ (0x318)
                vel_raw = scanner.read_mem(move_ptr + 0x0318, 12)
                if vel_raw:
                    vx, vy, vz = struct.unpack("<fff", vel_raw)
                    if any(abs(v) > 0.01 for v in (vx, vy, vz)) and all(abs(v) < 2000.0 for v in (vx, vy, vz)):
                        return (vx, vy, vz)

        return (0.0, 0.0, 0.0)
    except Exception as e:
        dprint(f"VEL READ EXCEPTION | unit={hex(u_ptr)} | type=AIR | error={e}", force=False)
        return (0.0, 0.0, 0.0)

def get_my_air_velocity(scanner, my_unit_ptr):
    """
    [MY UNIT ONLY] ดึงความเร็วเครื่องบินเราเองแบบ High Precision
    ใช้ Move Ptr: 0x0D10 | Vel Offset: 0x0068 | Type: DOUBLE
    """
    try:
        # 1. อ่าน Move Pointer (0x0D10)
        move_raw = scanner.read_mem(my_unit_ptr + OFF_MY_AIR_MOVEMENT, 8)
        if move_raw:
            move_ptr = struct.unpack("<Q", move_raw)[0]
            if move_ptr > 0x10000:
                
                # 2. อ่าน Velocity แบบ DOUBLE (อ่าน 24 Bytes)
                vel_raw = scanner.read_mem(move_ptr + OFF_MY_AIR_VEL, 24)
                if vel_raw:
                    # 3. ถอดรหัสเป็นทศนิยม Double (<ddd)
                    vx, vy, vz = struct.unpack("<ddd", vel_raw)
                    
                    # กรองค่าขยะ
                    if any(abs(v) > 0.01 for v in (vx, vy, vz)) and all(abs(v) < 2000.0 for v in (vx, vy, vz)):
                        return (vx, vy, vz)
                        
        return (0.0, 0.0, 0.0)
    except Exception as e:
        return (0.0, 0.0, 0.0)


def get_ground_velocity(scanner, u_ptr):
    try:
        return _read_velocity_by_profile(scanner, u_ptr, "ground")
    except Exception as e:
        dprint(f"VEL READ EXCEPTION | unit={hex(u_ptr)} | type=GROUND | error={e}", force=False)
        return (0.0, 0.0, 0.0)


# ==========================================
# Omega Helpers
# ==========================================
def get_air_omega(scanner, unit_ptr):
    try:
        mov_ptr_raw = scanner.read_mem(unit_ptr + OFF_AIR_MOVEMENT, 8)
        if not mov_ptr_raw: return (0.0, 0.0, 0.0)
        mov_ptr = struct.unpack("<Q", mov_ptr_raw)[0]
        if not is_valid_ptr(mov_ptr): return (0.0, 0.0, 0.0)
        
        omega_data = scanner.read_mem(mov_ptr + OFF_AIR_OMEGA, 12)
        if omega_data and len(omega_data) == 12:
            wx, wy, wz = struct.unpack("<fff", omega_data)
            if math.isfinite(wx) and math.isfinite(wy) and math.isfinite(wz):
                return (wx, wy, wz)
    except Exception as e: 
        print("get_air_omega", e)
    return (0.0, 0.0, 0.0)


def get_ground_omega(scanner, unit_ptr):
    return (0.0, 0.0, 0.0)


# ==========================================
# Ballistics Helpers
# ==========================================
def get_bullet_speed(scanner, cgame_base):
    try:
        raw_weapon_ptr = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if not raw_weapon_ptr: return 1000.0
        weapon_ptr = struct.unpack("<Q", raw_weapon_ptr)[0]
        if not is_valid_ptr(weapon_ptr): return 1000.0
        
        speed_data = scanner.read_mem(weapon_ptr + OFF_BULLET_SPEED, 4)
        if not speed_data: return 1000.0
        speed = struct.unpack("<f", speed_data)[0]
        if math.isfinite(speed) and 50.0 < speed < 3000.0: return speed
        return 1000.0
    except Exception as e: 
        print("get_bullet_speed: ", e)
        return 1000.0

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
