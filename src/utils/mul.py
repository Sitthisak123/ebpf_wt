import struct
import math
import os

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

OFF_CAMERA_PTR      = 0
OFF_VIEW_MATRIX     = 0

OFF_UNIT_X          = 0
OFF_UNIT_ROTATION   = 0
OFF_UNIT_BBMIN      = 0
OFF_UNIT_BBMAX      = 0

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

OFF_AIR_UNITS       = (0x340, True)
OFF_AIR_MOVEMENT    = 0x0018      # 🎯 Air-specific movement ptr from air kinematics dumpers
OFF_AIR_VEL         = 0x0318      # 🎯 Velocity (FLOAT Vector 12-byte)
OFF_AIR_OMEGA       = 0x3F8       # 🌪️ Angular Velocity (ยังคงเป็นค่านี้)

OFF_GROUND_UNITS    = (0x358, False)
OFF_GROUND_MOVEMENT = 0x0D18  
OFF_GROUND_VEL      = 0x003C
OFF_GROUND_OMEGA    = 0
# 🔫 ระบบขีปนาวุธ (BALLISTICS - อัปเดตจาก Deep Scan ล่าสุด)
OFF_WEAPON_PTR      = 0x3f0        # 🎯 อัปเดตจากผลสแกน Ballistic
OFF_BULLET_SPEED    = 0x2048     # 🎯 ความเร็วต้น (Muzzle Velocity)
OFF_BULLET_MASS     = 0x2054      # ⚖️ มวลกระสุน (Relative -8 จาก Speed)
OFF_BULLET_CALIBER  = 0x2058   # 📏 คาดว่าเป็น Caliber (0.016 หรือค่าใกล้เคียง)
OFF_BULLET_CD       = 0x205C        # 💨 คาดว่าเป็น Drag Coeff (0.95)
OFF_WEAPON_BARREL   = 0x480  # 🎯 ตัวคูณทิศทางลำกล้อง

SIGHT_POINTER_CHAINS = [
    [0x13C50, -0x64C0, 0x1780, 0x1C28],
    [0x123E0, -0x37B8, 0x1780, 0x1C28],
    [0x13260, -0x4680, 0x1780, 0x1C28],
    [0x133D0, -0x4E40, 0x13D0, 0x7088],
    [0x13B88, -0x5140, 0x13D0, 0x7088],
    [0x13E68, -0x75F0, 0x13D0, 0x7088]
]

def is_valid_ptr(p): 
    return 0x10000 < p < 0xFFFFFFFFFFFFFFFF


UNIT_KIND_CACHE = {}
LAST_CGAME_PTR = 0
LAST_VIEW_MATRIX = None
UNIT_FILTER_CACHE = {}

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
    "dummy_plane",
)

NON_PLAYABLE_NAME_HINTS = (
    "dummy",
    "windmill",
    "airfield",
    "_noground",
)

NON_PLAYABLE_PATH_BLOCKLIST = (
    "air_defence/",
    "/air_defence/",
    "structures/",
    "/structures/",
    "dummy_plane",
)


def reset_runtime_caches(clear_view=False):
    global LAST_CGAME_PTR, LAST_VIEW_MATRIX
    UNIT_KIND_CACHE.clear()
    UNIT_FILTER_CACHE.clear()
    if clear_view:
        LAST_CGAME_PTR = 0
        LAST_VIEW_MATRIX = None


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
    path = _read_info_string(scanner, info_ptr, 0x18, 128) or _read_info_string(scanner, info_ptr, 0x10, 128) or ""
    unit_key = _read_info_string(scanner, info_ptr, 0x40, 96) or _read_info_string(scanner, info_ptr, 0x08, 96) or ""

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
    else:
        kind = get_unit_kind_from_info(scanner, u_ptr)

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

    # Extra guard for static/non-combat objects that may occasionally bypass tag/path parsing.
    if not skip and kind == "ground":
        mov_ptr = _read_ptr(scanner, u_ptr + OFF_GROUND_MOVEMENT)
        if not is_valid_ptr(mov_ptr):
            skip = True
            reason = "no_ground_mov"

    display_name = unit_key or _name_from_path(path)
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
    cacheable = bool(tag or path or unit_key or skip or kind) and reason != "no_ground_mov"
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
            "mov_off": lambda: OFF_AIR_MOVEMENT,
            "vel_off": lambda: OFF_AIR_VEL,
            "fmt": "fff",
            "max_speed": 2500.0,
        },
        "fallbacks": [
            {"label": "AIR_SCAN", "mov_off": 0x0AD8, "vel_off": 0x0040, "fmt": "ddd", "max_speed": 2500.0},
            {"label": "AIR_OLD", "mov_off": 0x1B90, "vel_off": 0x0BE0, "fmt": "fff", "max_speed": 2500.0},
            {"label": "GROUND_SCAN", "mov_off": 0x0D18, "vel_off": 0x003C, "fmt": "fff", "max_speed": 200.0},
            {"label": "GROUND_ALT", "mov_off": 0x0D18, "vel_off": 0x0068, "fmt": "ddd", "max_speed": 200.0},
            {"label": "GROUND_ALT2", "mov_off": 0x0D10, "vel_off": 0x0068, "fmt": "ddd", "max_speed": 200.0},
        ],
    },
    "ground": {
        "requested_label": "GROUND",
        "primary": {
            "label": "GROUND_PRIMARY",
            "mov_off": 0x1DF8,
            "vel_off": 0x54,
            "fmt": "fff",
            "max_speed": 200.0,
        },
        "fallbacks": [
            {"label": "GROUND_ALT", "mov_off": 0x0D18, "vel_off": 0x40, "fmt": "fff", "max_speed": 200.0},
            {"label": "GROUND_ALT2", "mov_off": lambda: OFF_GROUND_MOVEMENT, "vel_off": 0x68, "fmt": "ddd", "max_speed": 200.0},
        ],
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


def _debug_velocity_failure(reason, u_ptr, spec, raw_ptr=None, base_ptr=None, data=None, decoded=None):
    decoded_str = "None"
    if decoded is not None:
        decoded_str = f"({decoded[0]:.4f}, {decoded[1]:.4f}, {decoded[2]:.4f})"
    raw_ptr_hex = _format_bytes_hex(raw_ptr, 8)
    data_hex = _format_bytes_hex(data, spec["size"])
    base_ptr_str = hex(base_ptr) if isinstance(base_ptr, int) and base_ptr > 0 else str(base_ptr)
    dprint(
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
        force=False,
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

    return decoded, None


def _read_velocity_by_profile(scanner, u_ptr, profile_name):
    if u_ptr == 0:
        return (0.0, 0.0, 0.0)

    profile = VELOCITY_PROFILES[profile_name]
    requested_label = profile["requested_label"]
    attempts = []

    for idx, spec in enumerate(_iter_velocity_specs(profile_name)):
        result, failure = _try_read_velocity(scanner, u_ptr, spec)
        if result is not None:
            if idx > 0:
                dprint(
                    "VEL FALLBACK HIT"
                    f" | requested_type={requested_label}"
                    f" | unit={hex(u_ptr)}"
                    f" | using={spec['label']}"
                    f" | mov_off={hex(spec['mov_off'])}"
                    f" | vel_off={hex(spec['vel_off'])}"
                    f" | fmt={spec['fmt']}"
                    f" | decoded=({result[0]:.4f}, {result[1]:.4f}, {result[2]:.4f})",
                    force=False,
                )
            return result
        attempts.append((spec, failure))

    if attempts:
        spec, failure = attempts[0]
        reason, raw_ptr, base_ptr, data, decoded = failure
        _debug_velocity_failure(reason, u_ptr, spec, raw_ptr=raw_ptr, base_ptr=base_ptr, data=data, decoded=decoded)
        dprint(
            "VEL FALLBACKS EXHAUSTED"
            f" | requested_type={requested_label}"
            f" | unit={hex(u_ptr)}"
            f" | tried="
            + ", ".join(
                f"{s['label']}@{hex(s['mov_off'])}/{hex(s['vel_off'])}:{s['fmt']}:{f[0]}"
                for s, f in attempts
            ),
            force=False,
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
    global LAST_VIEW_MATRIX
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
                return values

    return LAST_VIEW_MATRIX

def get_unit_pos(scanner, u_ptr):
    if u_ptr == 0: return None
    data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not data or len(data) < 12: return None
    val1, val2, val3 = struct.unpack("<fff", data)
    if not (math.isfinite(val1) and math.isfinite(val2) and math.isfinite(val3)): return None
    return (val1, val2, val3)

def get_all_units(scanner, cgame_base):
    if cgame_base == 0: return []
    units = []
    for off, is_air in [OFF_AIR_UNITS, OFF_GROUND_UNITS]:
        raw_array_ptr = scanner.read_mem(cgame_base + off, 8)
        raw_count = scanner.read_mem(cgame_base + off + 16, 4) 
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
        kind = get_unit_kind_from_info(scanner, u_ptr)
        if kind == "air":
            is_air = True
        elif kind == "ground":
            is_air = False
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
    bmin_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 12) if OFF_UNIT_BBMIN else None
    bmax_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMAX, 12) if OFF_UNIT_BBMAX else None

    if bmin_data and len(bmin_data) == 12 and bmax_data and len(bmax_data) == 12:
        bmin = struct.unpack("<fff", bmin_data)
        bmax = struct.unpack("<fff", bmax_data)

        # ตรวจสอบความถูกต้องเบื้องต้น (Sanity Check)
        dx, dy, dz = bmax[0]-bmin[0], bmax[1]-bmin[1], bmax[2]-bmin[2]
        if 0.5 < dx < 100.0 and 0.2 < dy < 40.0 and 0.5 < dz < 100.0:
            return pos, bmin, bmax, R

    # เผื่อ build ที่วาง BBMIN/BBMAX ติดกันจริง ค่อยลองอ่านรวดเดียวเป็น fallback
    bbox_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 24) if OFF_UNIT_BBMIN else None
    if bbox_data and len(bbox_data) == 24:
        bmin = struct.unpack_from("<fff", bbox_data, 0)
        bmax = struct.unpack_from("<fff", bbox_data, 12)
        dx, dy, dz = bmax[0]-bmin[0], bmax[1]-bmin[1], bmax[2]-bmin[2]
        if 0.5 < dx < 100.0 and 0.2 < dy < 40.0 and 0.5 < dz < 100.0:
            return pos, bmin, bmax, R

    # Fallback กรณีอ่านไม่ได้ (ใช้ค่ากลางมาตรฐาน)
    if is_air:
        best_bmin, best_bmax = (-8.0, -2.0, -6.0), (8.0, 3.0, 6.0)
    else:
        best_bmin, best_bmax = (-1.8, -0.8, -3.0), (1.8, 1.6, 3.0)

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

    # Ground mapping confirmed in-game:
    # X = front, Z = left, Y = height
    # Current raw matrix comes in swapped for X/Z, so fix it here once.
    if not is_air:
        ax, az = az, ax

    return ax, ay, az
def world_to_screen(matrix, pos_x, pos_y, pos_z, screen_width, screen_height):
    try:
        # 🛡️ แก้จาก vm เป็น matrix
        if not matrix or any(not math.isfinite(v) for v in matrix):
            return None
            
        w = (pos_x * matrix[3]) + (pos_y * matrix[7]) + (pos_z * matrix[11]) + matrix[15]
        if w < 0.01 or not math.isfinite(w): return None
        
        clip_x = (pos_x * matrix[0]) + (pos_y * matrix[4]) + (pos_z * matrix[8]) + matrix[12]
        clip_y = (pos_x * matrix[1]) + (pos_y * matrix[5]) + (pos_z * matrix[9]) + matrix[13]
        
        ndc_x = clip_x / w
        ndc_y = clip_y / w
        
        screen_x = (screen_width / 2) * (1 + ndc_x)
        screen_y = (screen_height / 2) * (1 - ndc_y)
        
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
        if u_ptr in scanner.bone_cache:
            cache = scanner.bone_cache[u_ptr]
            anim_char_raw = scanner.read_mem(u_ptr + cache['anim_off'], 8)
            if anim_char_raw: 
                anim_char = struct.unpack("<Q", anim_char_raw)[0]
                if is_valid_ptr(anim_char):
                    wtm_raw = scanner.read_mem(anim_char + 0x0, 8)
                    if wtm_raw:
                        w_ptr = struct.unpack("<Q", wtm_raw)[0]
                        if is_valid_ptr(w_ptr):
                            target_idx = cache['bone_idx']
                            matrix_data = scanner.read_mem(w_ptr + (target_idx * 64), 64)
                            if matrix_data:
                                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30)
                                if abs(bx) < 5000 and abs(by) < 5000:
                                    wtm_ptr = w_ptr
                                    target_bone_index = target_idx
                                else: del scanner.bone_cache[u_ptr]
                            else: del scanner.bone_cache[u_ptr]

        # (ในไฟล์ mul.py ภายใต้ฟังก์ชัน get_weapon_barrel)
        if wtm_ptr == 0 or target_bone_index == -1:
            best_score, best_idx = -1, -1
            
            # 🎯 1. อัปเดต List ค้นหาชื่อกระดูก (เพิ่ม 0x3E8, 0x400, 0x13B0)
            for off in [0x1E8, 0x1E0, 0x1F0, 0x1D8, 0x200, 0x210, 0x228, 0x1C8, 0x3E8, 0x400, 0x13B0]:
                raw_ptr = scanner.read_mem(u_ptr + off, 8)
                if not raw_ptr: continue
                tree_ptr = struct.unpack("<Q", raw_ptr)[0]
                if not is_valid_ptr(tree_ptr): continue
                raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
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
                            elif "bone_gun" in bone_name: score = 60
                            elif "barrel" in bone_name: score = 40
                            if any(b in bone_name for b in ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root"]): score = -100
                            if score > best_score: best_score, best_idx = score, i
                    except: pass
                if best_idx != -1: break

            if best_idx != -1:
                # 🎯 2. อัปเดต List ค้นหา Matrix Array (เพิ่ม 0x230 ไว้หน้าสุด, ตามด้วย 0x400, 0x3E8)
                for a_off in [0x230, 0x228, 0x220, 0x218, 0x240, 0x200, 0x250, 0x3E8, 0x400, 0x13B0]:
                    anim_raw = scanner.read_mem(u_ptr + a_off, 8)
                    if anim_raw:
                        anim_char = struct.unpack("<Q", anim_raw)[0]
                        if is_valid_ptr(anim_char):
                            # รองรับการซ้อน 2 ชั้นทั้งแบบ 0x0 และ 0x78 ตามที่ท่านสแกนเจอ
                            for sub_matrix_off in [0x0, 0x78]: 
                                wtm_raw = scanner.read_mem(anim_char + sub_matrix_off, 8)
                                if wtm_raw:
                                    w_ptr = struct.unpack("<Q", wtm_raw)[0]
                                    if is_valid_ptr(w_ptr):
                                        wtm_ptr = w_ptr
                                        target_bone_index = best_idx
                                        scanner.bone_cache[u_ptr] = {'anim_off': a_off, 'bone_idx': best_idx}
                                        break
                            if wtm_ptr != 0: break

        if wtm_ptr != 0 and target_bone_index != -1:
            matrix_data = scanner.read_mem(wtm_ptr + (target_bone_index * 64), 64)
            if matrix_data and len(matrix_data) == 64:
                fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00) 
                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30) 
                if math.isfinite(bx) and math.isfinite(fx):
                    if abs(bx) < 0.1 and abs(by) < 0.1 and abs(bz) < 0.1: return None
                    length = 30.0 
                    if abs(bx) > 500.0 or abs(by) > 500.0:
                        return (bx, by, bz), (bx + (fx * length), by + (fy * length), bz + (fz * length))
                    else:
                        def to_world(lx, ly, lz):
                            return (lx*unit_rot_matrix[0] + ly*unit_rot_matrix[3] + lz*unit_rot_matrix[6] + unit_pos[0],
                                    lx*unit_rot_matrix[1] + ly*unit_rot_matrix[4] + lz*unit_rot_matrix[7] + unit_pos[1],
                                    lx*unit_rot_matrix[2] + ly*unit_rot_matrix[5] + lz*unit_rot_matrix[8] + unit_pos[2])
                        return to_world(bx, by, bz), to_world(bx + (fx * length), by + (fy * length), bz + (fz * length))
    except Exception as e:
        print("get_weapon_barrel: ", e)
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
    try:
        return _read_velocity_by_profile(scanner, u_ptr, "air")
    except Exception as e:
        dprint(f"VEL READ EXCEPTION | unit={hex(u_ptr)} | type=AIR | error={e}", force=False)
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
