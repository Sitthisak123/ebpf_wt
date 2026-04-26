import json
import os
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")

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


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_i32(scanner, addr, default=0):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return default
    return struct.unpack("<i", raw)[0]


def read_cstr(scanner, ptr, max_len=96):
    if not mul.is_valid_ptr(ptr):
        return ""
    raw = scanner.read_mem(ptr, max_len)
    if not raw:
        return ""
    try:
        text = raw.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""
    return text


def family_label(unit_family):
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
    }
    return labels.get(unit_family, "??")


def resolve_family_local(family_name, profile_tag, profile_path, unit_key, name_key, short_name, is_air):
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

    if "battleship" in token or "battlecruiser" in token:
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


def token_flags(*parts):
    token = " ".join(str(p or "") for p in parts).lower()
    return {
        "has_light": any(k in token for k in ("light_tank", "light tank", "exp_light_tank", "exp_tank_light")),
        "has_medium": "medium_tank" in token or "medium tank" in token,
        "has_heavy": "heavy_tank" in token or "heavy tank" in token,
        "has_td": "tank_destroyer" in token or "tank_destr" in token,
        "has_spaa": "spaa" in token,
        "has_tank": "tank" in token,
    }


def build_unit_record(scanner, unit_ptr, default_is_air):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    status = mul.get_unit_status(scanner, unit_ptr) or (0, -1, "", -1)
    info_ptr = read_u64(scanner, unit_ptr + mul.OFF_UNIT_INFO)
    info_family_ptr = read_u64(scanner, info_ptr + mul.OFF_INFO_FAMILY) if mul.is_valid_ptr(info_ptr) else 0
    info_short_ptr = read_u64(scanner, info_ptr + mul.OFF_INFO_SHORT_NAME) if mul.is_valid_ptr(info_ptr) else 0
    info_key_ptr = read_u64(scanner, info_ptr + mul.OFF_INFO_NAME_KEY) if mul.is_valid_ptr(info_ptr) else 0
    info_class_id = read_i32(scanner, info_ptr + mul.OFF_INFO_STATUS, -1) if mul.is_valid_ptr(info_ptr) else -1

    family_name = (dna.get("family") or "").strip()
    short_name = (dna.get("short_name") or "").strip()
    name_key = (dna.get("name_key") or "").strip()
    profile_tag = (profile.get("tag") or "").strip()
    profile_path = (profile.get("path") or "").strip()
    profile_unit_key = (profile.get("unit_key") or "").strip()
    profile_kind = profile.get("kind")

    is_air = bool(default_is_air)
    if profile_kind == "air":
        is_air = True
    elif profile_kind == "ground":
        is_air = False

    resolved_family = resolve_family_local(
        family_name,
        profile_tag,
        profile_path,
        profile_unit_key,
        name_key,
        short_name,
        is_air,
    )
    flags = token_flags(family_name, profile_tag, profile_path, profile_unit_key, name_key, short_name)

    return {
        "ptr": hex(unit_ptr),
        "team": status[0],
        "state": status[1],
        "unit_name_status": status[2],
        "reload_val": status[3],
        "is_air_default": bool(default_is_air),
        "is_air_effective": bool(is_air),
        "dna": {
            "short_name": short_name,
            "name_key": name_key,
            "family": family_name,
            "class_id": dna.get("class_id"),
            "nation_id": dna.get("nation_id"),
            "invul": dna.get("is_invul"),
        },
        "profile": {
            "display_name": profile.get("display_name") or "",
            "tag": profile_tag,
            "path": profile_path,
            "unit_key": profile_unit_key,
            "kind": profile_kind,
            "skip": bool(profile.get("skip")),
            "reason": profile.get("reason") or "",
        },
        "raw_info": {
            "info_ptr": hex(info_ptr) if info_ptr else "0x0",
            "family_ptr": hex(info_family_ptr) if info_family_ptr else "0x0",
            "short_ptr": hex(info_short_ptr) if info_short_ptr else "0x0",
            "name_key_ptr": hex(info_key_ptr) if info_key_ptr else "0x0",
            "class_id_info": info_class_id,
            "family_from_ptr": read_cstr(scanner, info_family_ptr),
            "short_from_ptr": read_cstr(scanner, info_short_ptr),
            "name_key_from_ptr": read_cstr(scanner, info_key_ptr),
        },
        "resolver": {
            "resolved_family_enum": resolved_family,
            "resolved_family_label": family_label(resolved_family),
        },
        "token_flags": flags,
    }


def build_summary(records):
    by_class_id = defaultdict(list)
    by_family = defaultdict(list)
    by_tag = defaultdict(list)
    by_resolved = defaultdict(list)

    for rec in records:
        dna = rec.get("dna") or {}
        profile = rec.get("profile") or {}
        resolver = rec.get("resolver") or {}
        by_class_id[str(dna.get("class_id"))].append(rec["ptr"])
        by_family[str(dna.get("family") or "")].append(rec["ptr"])
        by_tag[str(profile.get("tag") or "")].append(rec["ptr"])
        key = f"{resolver.get('resolved_family_label','??')}:{resolver.get('resolved_family_enum', 0)}"
        by_resolved[key].append(rec["ptr"])

    return {
        "class_id_counts": {k: len(v) for k, v in sorted(by_class_id.items(), key=lambda item: (item[0]))},
        "family_counts": {k: len(v) for k, v in sorted(by_family.items(), key=lambda item: (item[0]))},
        "profile_tag_counts": {k: len(v) for k, v in sorted(by_tag.items(), key=lambda item: (item[0]))},
        "resolved_family_counts": {k: len(v) for k, v in sorted(by_resolved.items(), key=lambda item: (item[0]))},
    }


def write_outputs(payload):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"unit_class_type_compare_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"unit_class_type_compare_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" UNIT CLASS TYPE COMPARE DUMPER")
    lines.append("==================================================")
    meta = payload.get("meta") or {}
    lines.append(f"PID        : {meta.get('pid')}")
    lines.append(f"Base       : {meta.get('base_addr')}")
    lines.append(f"CGame      : {meta.get('cgame_ptr')}")
    lines.append(f"My Unit    : {meta.get('my_unit_ptr')}")
    lines.append(f"Count      : {len(payload.get('units', []))}")
    lines.append("")
    lines.append("SUMMARY")
    lines.append(json.dumps(payload.get("summary", {}), indent=2, ensure_ascii=False))
    lines.append("")

    for i, rec in enumerate(payload.get("units", []), 1):
        dna = rec["dna"]
        profile = rec["profile"]
        raw_info = rec["raw_info"]
        resolver = rec["resolver"]
        flags = rec["token_flags"]
        lines.append(f"[{i}] {dna.get('short_name') or '-'} | {dna.get('name_key') or '-'} | ptr={rec['ptr']}")
        lines.append(
            f"    air/default/effective : {rec['is_air_default']} / {rec['is_air_effective']} | "
            f"team={rec['team']} state={rec['state']}"
        )
        lines.append(
            f"    dna                  : family={dna.get('family')} | class_id={dna.get('class_id')} | nation={dna.get('nation_id')}"
        )
        lines.append(
            f"    profile              : tag={profile.get('tag')} | kind={profile.get('kind')} | unit_key={profile.get('unit_key')}"
        )
        lines.append(f"    profile_path         : {profile.get('path')}")
        lines.append(
            f"    raw_info             : class_id_info={raw_info.get('class_id_info')} | "
            f"family_ptr={raw_info.get('family_ptr')} -> {raw_info.get('family_from_ptr')}"
        )
        lines.append(
            f"    raw_short/key        : short={raw_info.get('short_from_ptr')} | key={raw_info.get('name_key_from_ptr')}"
        )
        lines.append(
            f"    resolved             : {resolver.get('resolved_family_label')} ({resolver.get('resolved_family_enum')})"
        )
        lines.append(
            f"    flags                : light={flags['has_light']} medium={flags['has_medium']} heavy={flags['has_heavy']} "
            f"td={flags['has_td']} spaa={flags['has_spaa']} tank={flags['has_tank']}"
        )
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, txt_path


def main():
    pid = get_game_pid()
    if not pid:
        print("[-] War Thunder process not found")
        return 1

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame = mul.get_cgame_base(scanner, base)
    if not cgame:
        print("[-] Failed to resolve cgame")
        return 1

    my_unit, _my_team = mul.get_local_team(scanner, base)
    units = mul.get_all_units(scanner, cgame)

    records = []
    for unit_ptr, is_air in units:
        try:
            records.append(build_unit_record(scanner, unit_ptr, is_air))
        except Exception:
            continue

    records.sort(key=lambda r: (
        str((r.get("dna") or {}).get("family") or ""),
        int((r.get("dna") or {}).get("class_id") or -1),
        str((r.get("dna") or {}).get("short_name") or ""),
        r["ptr"],
    ))

    payload = {
        "meta": {
            "timestamp": datetime.now().isoformat(),
            "pid": pid,
            "base_addr": hex(base),
            "cgame_ptr": hex(cgame),
            "my_unit_ptr": hex(my_unit) if my_unit else "0x0",
        },
        "summary": build_summary(records),
        "units": records,
    }

    json_path, txt_path = write_outputs(payload)
    print("==================================================")
    print(" UNIT CLASS TYPE COMPARE DUMPER")
    print("==================================================")
    print(f"[+] Units dumped: {len(records)}")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
