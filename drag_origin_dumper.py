import json
import os
import struct
from datetime import datetime

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


MUZZLE_VELOCITY_OFF = 0x2048
PROJ_BALLISTICS_OFF = 0x2050

PROJ_BALLISTICS_FIELDS = [
    ("unk_00", 0x00, "f"),
    ("mass", 0x04, "f"),
    ("caliber", 0x08, "f"),
    ("cx", 0x0C, "f"),
    ("maxDistance", 0x10, "f"),
    ("unk_14", 0x14, "f"),
    ("unk_18", 0x18, "f"),
    ("splinterMass_x", 0x1C, "f"),
    ("splinterMass_y", 0x20, "f"),
    ("velRange_x", 0x24, "f"),
    ("velRange_y", 0x28, "f"),
]

POINTER_SCAN_LIMIT = 0x400
OWNER_SUBSCAN_LIMIT = 0x100


def hex_dump(data, base_offset=0):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"0x{base_offset + i:04X} | {hex_part:<47} | {ascii_part}")
    return "\n".join(lines)


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    value = struct.unpack("<f", raw)[0]
    if not (value == value):
        return None
    return value


def is_reasonable_float(value, low=None, high=None):
    if value is None:
        return False
    if not (value == value):
        return False
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def decode_proj_ballistics(scanner, struct_addr):
    decoded = {}
    for name, off, fmt in PROJ_BALLISTICS_FIELDS:
        size = struct.calcsize("<" + fmt)
        raw = scanner.read_mem(struct_addr + off, size)
        if not raw or len(raw) < size:
            decoded[name] = None
            continue
        decoded[name] = struct.unpack("<" + fmt, raw)[0]
    return decoded


def score_props_match(reference, candidate):
    score = 0
    matched = []

    checks = [
        ("mass", 0.001),
        ("caliber", 0.0005),
        ("cx", 0.001),
        ("maxDistance", 2.0),
    ]

    for field, tolerance in checks:
        ref_value = reference.get(field)
        cand_value = candidate.get(field)
        if not is_reasonable_float(ref_value) or not is_reasonable_float(cand_value):
            continue
        if abs(ref_value - cand_value) <= tolerance:
            score += 3
            matched.append(field)

    if is_reasonable_float(candidate.get("mass"), 0.0001, 200.0):
        score += 1
    if is_reasonable_float(candidate.get("caliber"), 0.001, 1.0):
        score += 1
    if is_reasonable_float(candidate.get("cx"), 0.0001, 10.0):
        score += 1
    if is_reasonable_float(candidate.get("maxDistance"), 0.0, 100000.0):
        score += 1

    return score, matched


def find_upstream_owner_candidates(scanner, weapon_ptr, reference_props):
    candidates = []
    seen = set()

    for ptr_off in range(0, POINTER_SCAN_LIMIT, 8):
        ptr_value = read_u64(scanner, weapon_ptr + ptr_off)
        if not mul.is_valid_ptr(ptr_value):
            continue

        for suboff in range(0, OWNER_SUBSCAN_LIMIT, 4):
            struct_addr = ptr_value + suboff
            if struct_addr in seen:
                continue
            seen.add(struct_addr)

            candidate_props = decode_proj_ballistics(scanner, struct_addr)
            score, matched = score_props_match(reference_props, candidate_props)
            if score < 8:
                continue

            raw = scanner.read_mem(struct_addr, 0x30) or b""
            candidates.append(
                {
                    "weapon_ptr_field_off": ptr_off,
                    "owner_ptr": ptr_value,
                    "embedded_struct_off": suboff,
                    "struct_addr": struct_addr,
                    "score": score,
                    "matched_fields": matched,
                    "proj_ballistics_fields": candidate_props,
                    "proj_ballistics_hex": hex_dump(raw, suboff) if raw else "",
                }
            )

    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["embedded_struct_off"],
            item["weapon_ptr_field_off"],
        )
    )
    return candidates[:12]


def dump_weapon_block(scanner, weapon_ptr):
    weapon_raw = scanner.read_mem(weapon_ptr + 0x2040, 0x60) or b""
    props_addr = weapon_ptr + PROJ_BALLISTICS_OFF
    props_raw = scanner.read_mem(props_addr, 0x30) or b""

    muzzle_velocity = read_f32(scanner, weapon_ptr + MUZZLE_VELOCITY_OFF)
    proj_props = decode_proj_ballistics(scanner, props_addr)
    upstream_candidates = find_upstream_owner_candidates(scanner, weapon_ptr, proj_props)

    return {
        "weapon_ptr": weapon_ptr,
        "muzzle_velocity_addr": weapon_ptr + MUZZLE_VELOCITY_OFF,
        "muzzle_velocity": muzzle_velocity,
        "proj_ballistics_addr": props_addr,
        "proj_ballistics_fields": proj_props,
        "upstream_owner_candidates": upstream_candidates,
        "weapon_window_hex": hex_dump(weapon_raw, 0x2040) if weapon_raw else "",
        "proj_ballistics_hex": hex_dump(props_raw, 0x0000) if props_raw else "",
    }


def try_get_active_weapon(scanner, base_addr):
    unit_ptr, _ = mul.get_local_team(scanner, base_addr)
    if not mul.is_valid_ptr(unit_ptr):
        return 0, 0, "controlled_unit_invalid"

    weapon_ptr = read_u64(scanner, unit_ptr + mul.OFF_WEAPON_PTR)
    if mul.is_valid_ptr(weapon_ptr):
        return unit_ptr, weapon_ptr, "unit+OFF_WEAPON_PTR"

    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    if not mul.is_valid_ptr(cgame_ptr):
        return unit_ptr, 0, "cgame_invalid"

    weapon_ptr = read_u64(scanner, cgame_ptr + mul.OFF_WEAPON_PTR)
    if mul.is_valid_ptr(weapon_ptr):
        return unit_ptr, weapon_ptr, "cgame+OFF_WEAPON_PTR"

    return unit_ptr, 0, "weapon_not_found"


def write_dump_files(payload):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"origin_dragoff_dump_{stamp}.json")
    txt_path = os.path.join("dumps", f"origin_dragoff_dump_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "ORIGIN DRAGOFF DUMPER",
        "=" * 80,
        f"PID: {payload['pid']}",
        f"Image Base: {hex(payload['image_base'])}",
        f"Controlled Unit: {hex(payload['unit_ptr']) if payload['unit_ptr'] else '0x0'}",
        f"Weapon Source: {payload['weapon_source']}",
        f"Weapon Ptr: {hex(payload['weapon_ptr']) if payload['weapon_ptr'] else '0x0'}",
        "",
    ]

    if payload["weapon_ptr"]:
        fields = payload["proj_ballistics_fields"]
        lines.extend(
            [
                f"Muzzle Velocity @ {hex(payload['muzzle_velocity_addr'])}: {payload['muzzle_velocity']}",
                f"ProjBallisticsProperties @ {hex(payload['proj_ballistics_addr'])}",
                f"  unk_00       : {fields['unk_00']}",
                f"  mass         : {fields['mass']}",
                f"  caliber      : {fields['caliber']}",
                f"  cx           : {fields['cx']}",
                f"  maxDistance  : {fields['maxDistance']}",
                f"  unk_14       : {fields['unk_14']}",
                f"  unk_18       : {fields['unk_18']}",
                f"  splinterMass : ({fields['splinterMass_x']}, {fields['splinterMass_y']})",
                f"  velRange     : ({fields['velRange_x']}, {fields['velRange_y']})",
                "",
                "WEAPON WINDOW HEX [weapon + 0x2040, size 0x60]",
                payload["weapon_window_hex"],
                "",
                "PROJ BALLISTICS HEX [struct + 0x00, size 0x30]",
                payload["proj_ballistics_hex"],
            ]
        )
        candidates = payload.get("upstream_owner_candidates") or []
        if candidates:
            lines.extend(
                [
                    "",
                    "UPSTREAM OWNER CANDIDATES",
                ]
            )
            for idx, cand in enumerate(candidates, 1):
                cfields = cand["proj_ballistics_fields"]
                lines.extend(
                    [
                        (
                            f"[{idx}] field_off={hex(cand['weapon_ptr_field_off'])} "
                            f"owner_ptr={hex(cand['owner_ptr'])} "
                            f"embedded_off={hex(cand['embedded_struct_off'])} "
                            f"struct_addr={hex(cand['struct_addr'])} "
                            f"score={cand['score']} matched={','.join(cand['matched_fields'])}"
                        ),
                        (
                            f"    mass={cfields['mass']} caliber={cfields['caliber']} "
                            f"cx={cfields['cx']} maxDistance={cfields['maxDistance']}"
                        ),
                    ]
                )
                if cand["proj_ballistics_hex"]:
                    lines.append(cand["proj_ballistics_hex"])

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, txt_path


def main():
    print("=" * 80)
    print("ORIGIN DRAGOFF DUMPER")
    print("=" * 80)

    scanner = None
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        init_dynamic_offsets(scanner, base_addr)

        unit_ptr, weapon_ptr, weapon_source = try_get_active_weapon(scanner, base_addr)

        payload = {
            "pid": pid,
            "image_base": base_addr,
            "unit_ptr": unit_ptr,
            "weapon_ptr": weapon_ptr,
            "weapon_source": weapon_source,
        }

        print(f"[*] PID: {pid}")
        print(f"[*] Image Base: {hex(base_addr)}")
        print(f"[*] Controlled Unit: {hex(unit_ptr) if unit_ptr else '0x0'}")

        if not mul.is_valid_ptr(weapon_ptr):
            print(f"[-] Active weapon pointer not found ({weapon_source})")
            payload["error"] = weapon_source
            json_path, txt_path = write_dump_files(payload)
            print(f"[+] JSON: {json_path}")
            print(f"[+] TEXT: {txt_path}")
            return

        dump = dump_weapon_block(scanner, weapon_ptr)
        payload.update(dump)

        print(f"[*] Weapon Ptr: {hex(weapon_ptr)} ({weapon_source})")
        print(f"[*] Muzzle Velocity @ {hex(dump['muzzle_velocity_addr'])}: {dump['muzzle_velocity']}")
        print(f"[*] ProjBallisticsProperties @ {hex(dump['proj_ballistics_addr'])}")
        print(f"    mass        : {dump['proj_ballistics_fields']['mass']}")
        print(f"    caliber     : {dump['proj_ballistics_fields']['caliber']}")
        print(f"    cx          : {dump['proj_ballistics_fields']['cx']}  <-- dragOff origin")
        print(f"    maxDistance : {dump['proj_ballistics_fields']['maxDistance']}")
        print(
            f"    splinterMass: ({dump['proj_ballistics_fields']['splinterMass_x']}, "
            f"{dump['proj_ballistics_fields']['splinterMass_y']})"
        )
        print(
            f"    velRange    : ({dump['proj_ballistics_fields']['velRange_x']}, "
            f"{dump['proj_ballistics_fields']['velRange_y']})"
        )
        candidates = dump.get("upstream_owner_candidates") or []
        if candidates:
            print("[*] Upstream owner candidates:")
            for idx, cand in enumerate(candidates[:5], 1):
                print(
                    f"    [{idx}] field_off={hex(cand['weapon_ptr_field_off'])} "
                    f"owner={hex(cand['owner_ptr'])} "
                    f"embedded_off={hex(cand['embedded_struct_off'])} "
                    f"score={cand['score']} "
                    f"matched={','.join(cand['matched_fields'])}"
                )
        else:
            print("[*] Upstream owner candidates: none matched current heuristics")

        json_path, txt_path = write_dump_files(payload)
        print("-" * 80)
        print(f"[+] JSON: {json_path}")
        print(f"[+] TEXT: {txt_path}")

    except Exception as e:
        print(f"[-] Critical error: {e}")
    finally:
        if scanner and hasattr(scanner, "mem_fd"):
            try:
                os.close(scanner.mem_fd)
            except OSError:
                pass


if __name__ == "__main__":
    main()
