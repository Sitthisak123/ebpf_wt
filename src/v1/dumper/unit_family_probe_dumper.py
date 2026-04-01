import json
import os
import struct
from datetime import datetime

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    OFF_UNIT_INFO,
    get_all_units,
    get_cgame_base,
    get_local_team,
    get_unit_detailed_dna,
    get_unit_filter_profile,
    get_unit_pos,
    get_unit_status,
)


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


def read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def resolve_is_air_now(default_is_air, family_name, profile_tag, profile_path):
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


def resolve_unit_family_enum(family_name, profile_tag, profile_path, unit_key, name_key, short_name, is_air):
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
    if "tank_destroyer" in token or "tank_destr" in token:
        return UNIT_FAMILY_GROUND_TANK_DESTROYER
    if "heavy_tank" in token:
        return UNIT_FAMILY_GROUND_HEAVY_TANK
    if "tank" in token:
        return UNIT_FAMILY_GROUND_MEDIUM_TANK
    if not is_air:
        return UNIT_FAMILY_GROUND_MEDIUM_TANK
    return UNIT_FAMILY_UNKNOWN


def family_label(unit_family):
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


def dump_hex(data, start_offset=0):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_val = " ".join(f"{b:02x}" for b in chunk)
        ascii_val = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"0x{start_offset + i:04x} | {hex_val:<48} | {ascii_val}")
    return "\n".join(lines)


def main():
    print("=" * 68)
    print("🚀 UNIT FAMILY PROBE DUMPER")
    print("=" * 68)

    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if base_addr == 0:
        raise RuntimeError(f"พบ PID ของเกมแล้ว ({pid}) แต่หา base address ไม่เจอ")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame_base = get_cgame_base(scanner, base_addr)
    if cgame_base == 0:
        raise RuntimeError("ไม่พบ CGame")

    all_units = get_all_units(scanner, cgame_base)
    my_unit, my_team = get_local_team(scanner, base_addr)
    my_pos = get_unit_pos(scanner, my_unit) if my_unit else None

    rows = []
    for idx, (u_ptr, provisional_is_air) in enumerate(all_units):
        status = get_unit_status(scanner, u_ptr)
        if not status:
            continue

        team, state, unit_name, reload_val = status
        dna = get_unit_detailed_dna(scanner, u_ptr) or {}
        profile = get_unit_filter_profile(scanner, u_ptr) or {}
        pos = get_unit_pos(scanner, u_ptr)
        info_ptr = read_ptr(scanner, u_ptr + OFF_UNIT_INFO) if OFF_UNIT_INFO else 0

        family_name = (dna.get("family") or "").strip()
        name_key = (dna.get("name_key") or "").strip()
        short_name = (dna.get("short_name") or "").strip()
        profile_tag = (profile.get("tag") or "").strip()
        profile_path = (profile.get("path") or "").strip()
        unit_key = (profile.get("unit_key") or "").strip()

        resolved_is_air_now = resolve_is_air_now(
            provisional_is_air,
            family_name,
            profile_tag,
            profile_path,
        )
        unit_family = resolve_unit_family_enum(
            family_name,
            profile_tag,
            profile_path,
            unit_key,
            name_key,
            short_name,
            resolved_is_air_now,
        )

        dist = -1.0
        if my_pos and pos:
            dx = pos[0] - my_pos[0]
            dy = pos[1] - my_pos[1]
            dz = pos[2] - my_pos[2]
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5

        info_hex = ""
        if info_ptr:
            raw_info = scanner.read_mem(info_ptr, 0x80)
            if raw_info:
                info_hex = dump_hex(raw_info)

        rows.append({
            "index": idx,
            "u_ptr": hex(u_ptr),
            "info_ptr": hex(info_ptr) if info_ptr else "0x0",
            "team": team,
            "state": state,
            "unit_name": unit_name,
            "short_name": short_name,
            "name_key": name_key,
            "family": family_name,
            "profile_tag": profile_tag,
            "profile_path": profile_path,
            "profile_unit_key": unit_key,
            "profile_kind": profile.get("kind"),
            "profile_skip": profile.get("skip"),
            "profile_reason": profile.get("reason"),
            "provisional_is_air": provisional_is_air,
            "resolved_is_air_now": resolved_is_air_now,
            "unit_family_enum": unit_family,
            "unit_family_label": family_label(unit_family),
            "position": pos,
            "distance_m": dist,
            "class_id": dna.get("class_id", -1),
            "nation_id": dna.get("nation_id", -1),
            "info_hex": info_hex,
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("dumps", exist_ok=True)
    json_path = f"dumps/unit_family_probe_{timestamp}.json"
    txt_path = f"dumps/unit_family_probe_{timestamp}.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("UNIT FAMILY PROBE DUMP\n")
        f.write("=" * 96 + "\n\n")
        for row in rows:
            f.write(
                f"[{row['index']:03d}] ptr={row['u_ptr']} info={row['info_ptr']} "
                f"team={row['team']} state={row['state']} dist={row['distance_m']:.1f}m\n"
            )
            f.write(
                f"  name='{row['unit_name']}' short='{row['short_name']}' key='{row['name_key']}'\n"
            )
            f.write(
                f"  family='{row['family']}' tag='{row['profile_tag']}' kind='{row['profile_kind']}' "
                f"path='{row['profile_path']}'\n"
            )
            f.write(
                f"  provisional_is_air={row['provisional_is_air']} "
                f"resolved_is_air_now={row['resolved_is_air_now']} "
                f"family_label={row['unit_family_label']} enum={row['unit_family_enum']}\n"
            )
            if row["info_hex"]:
                f.write("  --- INFO HEX (0x80 bytes) ---\n")
                f.write(row["info_hex"] + "\n")
            f.write("-" * 96 + "\n")

    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
