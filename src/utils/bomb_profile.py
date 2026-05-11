import copy
import json
import math


LOADOUT_PRESET_OFF = 0x7C0


def _as_float(value, default=0.0):
    try:
        value = float(value or 0.0)
    except Exception:
        return float(default)
    return value if math.isfinite(value) else float(default)


def _as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def normalize_bomb_profile_entry(name, raw):
    raw = raw or {}
    return {
        "preset_name": str(name or ""),
        "unit_key": str(raw.get("unit_key") or ""),
        "display_name": str(raw.get("display_name") or name or ""),
        "initial_count": _as_int(raw.get("initial_count", 0), 0),
        "bomb_mass": _as_float(raw.get("bomb_mass", 0.0), 0.0),
        "explosive_mass": _as_float(raw.get("explosive_mass", 0.0), 0.0),
        "armor_pen": _as_float(raw.get("armor_pen", 0.0), 0.0),
        "explode_radius": _as_float(raw.get("explode_radius", 0.0), 0.0),
        "fragment_radius": _as_float(raw.get("fragment_radius", 0.0), 0.0),
        "drag_profile": str(raw.get("drag_profile") or ""),
        "notes": str(raw.get("notes") or ""),
    }


def normalize_bomb_profile_table(doc):
    root = doc.get("profiles") if isinstance(doc, dict) and "profiles" in doc else doc
    if not isinstance(root, dict):
        return {}
    out = {}
    for name, raw in root.items():
        entry = normalize_bomb_profile_entry(name, raw if isinstance(raw, dict) else {})
        if entry["preset_name"]:
            out[entry["preset_name"]] = entry
    return out


def read_runtime_bomb_preset(scanner, unit_ptr, read_u64, read_inline_ascii, read_c_string):
    if not scanner or not unit_ptr:
        return {"preset_ptr": 0, "preset_name": ""}
    try:
        preset_ptr = int(read_u64(scanner, unit_ptr + LOADOUT_PRESET_OFF) or 0)
    except Exception:
        preset_ptr = 0
    preset_name = ""
    if preset_ptr:
        try:
            preset_name = str(read_inline_ascii(scanner, preset_ptr, 128) or read_c_string(scanner, preset_ptr, 128) or "")
        except Exception:
            preset_name = ""
    return {
        "preset_ptr": preset_ptr,
        "preset_name": preset_name,
    }


def resolve_bomb_profile_from_name(preset_name, table):
    table = table or {}
    name = str(preset_name or "").strip()
    entry = table.get(name)
    if not entry:
        return {
            "preset_name": name,
            "matched": False,
            "match_source": "none",
            "profile": {},
        }
    return {
        "preset_name": name,
        "matched": True,
        "match_source": "table",
        "profile": copy.deepcopy(entry),
    }


def resolve_runtime_bomb_profile(scanner, unit_ptr, table, read_u64, read_inline_ascii, read_c_string):
    runtime = read_runtime_bomb_preset(scanner, unit_ptr, read_u64, read_inline_ascii, read_c_string)
    resolved = resolve_bomb_profile_from_name(runtime.get("preset_name", ""), table)
    resolved["preset_ptr"] = int(runtime.get("preset_ptr", 0) or 0)
    return resolved
