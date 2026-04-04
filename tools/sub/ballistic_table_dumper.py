import json
import os
import struct
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

ROOT_CHAIN_OFFSETS = (0x20A0, 0x20A8, 0x20B0)
ROOT_CHILD_SLOTS = 8
OBJECT_DUMP_SIZE = 0x60
TABLE_DUMP_SIZE = 0x60
TABLE_RUNTIME_DUMP_SIZE = 0x1C0
TABLE_DATA_PREVIEW_FLOATS = 24
ROOT_RECURSE_DEPTH = 3
ROOT_RECURSE_PTR_SLOTS = 8
IMAGE_BASE_STATIC = 0x400000
DAT_09910558 = 0x09910558
GLOBAL_TABLE_MANAGER_SIZE = 0x198
GLOBAL_TABLE_SLOTS = (
    (0x118, 0x120),
    (0x128, 0x130),
    (0x138, 0x140),
    (0x148, 0x150),
    (0x158, 0x160),
    (0x178, 0x180),
)
WATCH_POLL_SECONDS = 0.35
MODEL_ENUM_OFF = 0x2058
MODEL_ENUM_LABELS = {
    0: "model_0_direct",
    1: "model_1_rho_v2",
    2: "model_2_rho_only",
    3: "model_3_curve_dd0",
    4: "model_4_direct_alt",
    5: "model_5_curve_c80",
    6: "model_6_special_mach",
}


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    value = struct.unpack("<f", raw)[0]
    if value != value:
        return None
    return value


def is_reasonable_float(value, low=None, high=None):
    if value is None:
        return False
    if value != value:
        return False
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def hex_dump(data, base_offset=0):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"0x{base_offset + i:04X} | {hex_part:<47} | {ascii_part}")
    return "\n".join(lines)


def current_weapon_ptr(scanner, base_addr):
    unit_ptr, _ = mul.get_local_team(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)

    weapon_ptr = 0
    source = "none"
    if mul.is_valid_ptr(unit_ptr):
        weapon_ptr = read_u64(scanner, unit_ptr + mul.OFF_WEAPON_PTR)
        source = "unit+OFF_WEAPON_PTR"
    if not mul.is_valid_ptr(weapon_ptr) and mul.is_valid_ptr(cgame_ptr):
        weapon_ptr = read_u64(scanner, cgame_ptr + mul.OFF_WEAPON_PTR)
        source = "cgame+OFF_WEAPON_PTR"
    return unit_ptr, cgame_ptr, weapon_ptr, source


def read_current_profile(scanner, weapon_ptr):
    if not mul.is_valid_ptr(weapon_ptr):
        return {}
    model_enum = read_u32(scanner, weapon_ptr + MODEL_ENUM_OFF)
    return {
        "model_enum": model_enum,
        "model_label": MODEL_ENUM_LABELS.get(model_enum, f"model_{model_enum}_unknown"),
        "speed": read_f32(scanner, weapon_ptr + 0x2050),
        "mass": read_f32(scanner, weapon_ptr + 0x205C),
        "caliber": read_f32(scanner, weapon_ptr + 0x2060),
        "cx": read_f32(scanner, weapon_ptr + 0x2064),
        "maxDistance": read_f32(scanner, weapon_ptr + 0x2068),
        "velRange_x": read_f32(scanner, weapon_ptr + 0x207C),
        "velRange_y": read_f32(scanner, weapon_ptr + 0x2080),
    }


def runtime_addr(base_addr, static_addr):
    return base_addr + (static_addr - IMAGE_BASE_STATIC)


def decode_ballistic_object(scanner, ptr):
    if not mul.is_valid_ptr(ptr):
        return None
    raw = scanner.read_mem(ptr, OBJECT_DUMP_SIZE) or b""
    return {
        "ptr": ptr,
        "model_enum": read_u32(scanner, ptr + 0x00),
        "mass": read_f32(scanner, ptr + 0x04),
        "caliber": read_f32(scanner, ptr + 0x08),
        "cx": read_f32(scanner, ptr + 0x0C),
        "maxDistance": read_f32(scanner, ptr + 0x10),
        "stucking": read_u32(scanner, ptr + 0x14),
        "stuckingAngleCos": read_f32(scanner, ptr + 0x18),
        "splinterMass_x": read_f32(scanner, ptr + 0x1C),
        "splinterMass_y": read_f32(scanner, ptr + 0x20),
        "velRange_x": read_f32(scanner, ptr + 0x24),
        "velRange_y": read_f32(scanner, ptr + 0x28),
        "table_ref": read_u64(scanner, ptr + 0x30),
        "table_gate": read_u32(scanner, ptr + 0x38),
        "raw_hex": hex_dump(raw, 0) if raw else "",
    }


def score_candidate(candidate, live_profile):
    if not candidate:
        return -999.0
    score = 0.0
    for field in ("mass", "caliber", "cx", "maxDistance"):
        live = live_profile.get(field)
        cand = candidate.get(field)
        if live is None or cand is None:
            continue
        diff = abs(float(live) - float(cand))
        if diff < 1e-6:
            score += 20.0
        elif diff < 0.001:
            score += 10.0
        elif diff < 0.01:
            score += 5.0
        elif diff < 0.1:
            score += 1.0
    if candidate.get("table_ref") and mul.is_valid_ptr(candidate["table_ref"]):
        score += 5.0
    if candidate.get("table_gate"):
        score += 8.0
    model_enum = candidate.get("model_enum", 0)
    if 0 <= model_enum <= 16:
        score += 2.0
    vel_x = candidate.get("velRange_x")
    vel_y = candidate.get("velRange_y")
    if is_reasonable_float(vel_x, 10.0, 4000.0) and is_reasonable_float(vel_y, 10.0, 4000.0):
        score += 2.0
    return score


def read_float_array_preview(scanner, ptr, count):
    if not mul.is_valid_ptr(ptr) or count <= 0:
        return []
    raw = scanner.read_mem(ptr, count * 4) or b""
    if len(raw) < 4:
        return []
    out = []
    for i in range(0, min(len(raw), count * 4), 4):
        value = struct.unpack("<f", raw[i:i + 4])[0]
        if value == value:
            out.append(value)
        else:
            out.append(None)
    return out


def read_triplet_table(scanner, ptr, count):
    if not mul.is_valid_ptr(ptr) or count <= 0 or count > 0x10000:
        return None
    raw = scanner.read_mem(ptr, min(count, TABLE_DATA_PREVIEW_FLOATS) * 12) or b""
    preview = []
    for i in range(0, len(raw), 12):
        if len(raw[i:i + 12]) < 12:
            break
        a, b, c = struct.unpack("<fff", raw[i:i + 12])
        preview.append([a, b, c])
    return {
        "ptr": ptr,
        "count": count,
        "preview": preview,
    }


def read_table_runtime(scanner, ptr):
    if not mul.is_valid_ptr(ptr):
        return None
    raw = scanner.read_mem(ptr, TABLE_RUNTIME_DUMP_SIZE) or b""
    data_ptr = read_u64(scanner, ptr + 0x1A0)
    count = read_u32(scanner, ptr + 0x1A8)
    preview = []
    if mul.is_valid_ptr(data_ptr) and 0 < count <= 0x4000:
        preview = read_float_array_preview(scanner, data_ptr, min(TABLE_DATA_PREVIEW_FLOATS, count))
    return {
        "ptr": ptr,
        "data_ptr": data_ptr,
        "count": count,
        "data_preview": preview,
        "raw_hex": hex_dump(raw, 0) if raw else "",
    }


def read_global_table_manager(scanner, base_addr):
    global_ptr_addr = runtime_addr(base_addr, DAT_09910558)
    manager_ptr = read_u64(scanner, global_ptr_addr)
    info = {
        "global_ptr_addr": global_ptr_addr,
        "manager_ptr": manager_ptr,
        "manager_valid": bool(mul.is_valid_ptr(manager_ptr)),
    }
    if not info["manager_valid"]:
        return info

    raw = scanner.read_mem(manager_ptr, GLOBAL_TABLE_MANAGER_SIZE) or b""
    info["raw_hex"] = hex_dump(raw, 0) if raw else ""
    slots = []
    for ptr_off, count_off in GLOBAL_TABLE_SLOTS:
        table_ptr = read_u64(scanner, manager_ptr + ptr_off)
        count = read_u32(scanner, manager_ptr + count_off)
        slot = {
            "ptr_off": ptr_off,
            "count_off": count_off,
            "table_ptr": table_ptr,
            "count": count,
            "valid": bool(mul.is_valid_ptr(table_ptr) and 0 < count <= 0x10000),
        }
        if slot["valid"]:
            slot["triplets"] = read_triplet_table(scanner, table_ptr, count)
        slots.append(slot)
    info["slots"] = slots
    return info


def read_table_ref(scanner, ptr):
    if not mul.is_valid_ptr(ptr):
        return None
    raw = scanner.read_mem(ptr, TABLE_DUMP_SIZE) or b""
    children = []
    for idx in range(6):
        child_ptr = read_u64(scanner, ptr + (idx * 8))
        child = {
            "off": idx * 8,
            "ptr": child_ptr,
            "valid": bool(mul.is_valid_ptr(child_ptr)),
        }
        if child["valid"]:
            child_raw = scanner.read_mem(child_ptr, 0x30) or b""
            child["hex"] = hex_dump(child_raw, 0) if child_raw else ""
        children.append(child)
    return {
        "ptr": ptr,
        "runtime": read_table_runtime(scanner, ptr),
        "raw_hex": hex_dump(raw, 0) if raw else "",
        "children": children,
    }


def collect_reachable_ptrs(scanner, root_ptr, depth, seen, out):
    if depth < 0 or not mul.is_valid_ptr(root_ptr) or root_ptr in seen:
        return
    seen.add(root_ptr)
    out.append(root_ptr)
    for idx in range(ROOT_RECURSE_PTR_SLOTS):
        child_ptr = read_u64(scanner, root_ptr + (idx * 8))
        if mul.is_valid_ptr(child_ptr):
            collect_reachable_ptrs(scanner, child_ptr, depth - 1, seen, out)


def collect_candidates(scanner, weapon_ptr):
    live_profile = read_current_profile(scanner, weapon_ptr)
    roots = []
    seen_candidate_ptrs = set()
    candidates = []

    for off in ROOT_CHAIN_OFFSETS:
        root_ptr = read_u64(scanner, weapon_ptr + off)
        root = {
            "weapon_off": off,
            "root_ptr": root_ptr,
            "root_valid": bool(mul.is_valid_ptr(root_ptr)),
            "root_hex": "",
            "children": [],
        }
        if root["root_valid"]:
            root_raw = scanner.read_mem(root_ptr, TABLE_DUMP_SIZE) or b""
            root["root_hex"] = hex_dump(root_raw, 0) if root_raw else ""
            reachable_ptrs = []
            collect_reachable_ptrs(scanner, root_ptr, ROOT_RECURSE_DEPTH, set(), reachable_ptrs)
            root["reachable_ptrs"] = reachable_ptrs
            for idx in range(ROOT_CHILD_SLOTS):
                child_ptr = read_u64(scanner, root_ptr + (idx * 8))
                child = {
                    "off": idx * 8,
                    "ptr": child_ptr,
                    "valid": bool(mul.is_valid_ptr(child_ptr)),
                }
                if child["valid"] and child_ptr not in seen_candidate_ptrs:
                    seen_candidate_ptrs.add(child_ptr)
                    obj = decode_ballistic_object(scanner, child_ptr)
                    if obj:
                        obj["score"] = score_candidate(obj, live_profile)
                        obj["table"] = read_table_ref(scanner, obj.get("table_ref", 0))
                        candidates.append(obj)
                root["children"].append(child)
            for candidate_ptr in reachable_ptrs:
                if candidate_ptr in seen_candidate_ptrs:
                    continue
                seen_candidate_ptrs.add(candidate_ptr)
                obj = decode_ballistic_object(scanner, candidate_ptr)
                if obj:
                    obj["score"] = score_candidate(obj, live_profile)
                    obj["table"] = read_table_ref(scanner, obj.get("table_ref", 0))
                    candidates.append(obj)
        roots.append(root)

    candidates.sort(key=lambda item: (-item.get("score", -999.0), item["ptr"]))
    return live_profile, roots, candidates


def build_payload(scanner, base_addr):
    unit_ptr, cgame_ptr, weapon_ptr, source = current_weapon_ptr(scanner, base_addr)
    payload = {
        "pid": getattr(scanner, "pid", 0),
        "image_base": base_addr,
        "unit_ptr": unit_ptr,
        "cgame_ptr": cgame_ptr,
        "weapon_ptr": weapon_ptr,
        "weapon_source": source,
    }
    if mul.is_valid_ptr(weapon_ptr):
        live_profile, roots, candidates = collect_candidates(scanner, weapon_ptr)
        payload["live_profile"] = live_profile
        payload["roots"] = roots
        payload["candidates"] = candidates
    payload["global_table_manager"] = read_global_table_manager(scanner, base_addr)
    return payload


def snapshot_signature(payload):
    live = payload.get("live_profile") or {}
    global_mgr = payload.get("global_table_manager") or {}
    slots = []
    for slot in global_mgr.get("slots", []) or []:
        triplets = slot.get("triplets") or {}
        preview = triplets.get("preview") or []
        slots.append({
            "ptr_off": slot.get("ptr_off"),
            "table_ptr": slot.get("table_ptr"),
            "count": slot.get("count"),
            "preview": preview,
        })
    return {
        "model_enum": live.get("model_enum"),
        "model_label": live.get("model_label"),
        "speed": live.get("speed"),
        "mass": live.get("mass"),
        "caliber": live.get("caliber"),
        "cx": live.get("cx"),
        "maxDistance": live.get("maxDistance"),
        "slots": slots,
    }


def signatures_equal(a, b):
    if not a or not b:
        return False
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def format_slot_diff(prev_slot, cur_slot):
    changes = []
    if (prev_slot or {}).get("table_ptr") != (cur_slot or {}).get("table_ptr"):
        changes.append(
            f"ptr {hex((prev_slot or {}).get('table_ptr') or 0)} -> {hex((cur_slot or {}).get('table_ptr') or 0)}"
        )
    if (prev_slot or {}).get("count") != (cur_slot or {}).get("count"):
        changes.append(f"count {(prev_slot or {}).get('count')} -> {(cur_slot or {}).get('count')}")

    prev_preview = (prev_slot or {}).get("preview") or []
    cur_preview = (cur_slot or {}).get("preview") or []
    limit = min(len(prev_preview), len(cur_preview))
    for i in range(limit):
        if prev_preview[i] != cur_preview[i]:
            changes.append(f"triplet[{i}] {prev_preview[i]} -> {cur_preview[i]}")
            break
    if not changes and prev_preview != cur_preview:
        changes.append("preview changed")
    return changes


def write_watch_dump(history):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"ballistic_table_watch_{stamp}.json")
    txt_path = os.path.join("dumps", f"ballistic_table_watch_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    lines = [
        "BALLISTIC TABLE WATCH",
        "=" * 80,
    ]
    for idx, item in enumerate(history.get("snapshots", []), 1):
        sig = item.get("signature") or {}
        lines.append(
            f"[{idx}] model={sig.get('model_enum')} ({sig.get('model_label')}) "
            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} cx={sig.get('cx')} maxDist={sig.get('maxDistance')}"
        )
        for diff in item.get("slot_diffs", []):
            lines.append(
                f"  slot {hex(diff['ptr_off'])}: " + " | ".join(diff.get("changes") or ["changed"])
            )
        for slot in sig.get("slots", []):
            lines.append(
                f"  slot {hex(slot['ptr_off'])} ptr={hex(slot.get('table_ptr') or 0)} count={slot.get('count')} preview={slot.get('preview')[:3]}"
            )
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, txt_path


def write_dump(payload):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"ballistic_table_dump_{stamp}.json")
    txt_path = os.path.join("dumps", f"ballistic_table_dump_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "BALLISTIC TABLE DUMPER",
        "=" * 80,
        f"PID: {payload.get('pid')}",
        f"Image Base: {hex(payload.get('image_base', 0))}",
        f"Controlled Unit: {hex(payload.get('unit_ptr', 0)) if payload.get('unit_ptr') else '0x0'}",
        f"CGame: {hex(payload.get('cgame_ptr', 0)) if payload.get('cgame_ptr') else '0x0'}",
        f"Weapon Source: {payload.get('weapon_source')}",
        f"Weapon Ptr: {hex(payload.get('weapon_ptr', 0)) if payload.get('weapon_ptr') else '0x0'}",
        "",
    ]

    live = payload.get("live_profile", {})
    if live:
        lines.append("LIVE PROFILE")
        lines.append(json.dumps(live, indent=2, ensure_ascii=False))
        lines.append("")

    lines.append("ROOT CHAINS")
    for root in payload.get("roots", []):
        lines.append(
            f"  weapon_off={hex(root['weapon_off'])} root_ptr={hex(root['root_ptr']) if root.get('root_ptr') else '0x0'} valid={root.get('root_valid')}"
        )
        if root.get("root_hex"):
            lines.append(root["root_hex"])
        reachable_ptrs = root.get("reachable_ptrs") or []
        if reachable_ptrs:
            lines.append(f"    reachable_ptrs={len(reachable_ptrs)}")
        for child in root.get("children", []):
            lines.append(
                f"    child_off={hex(child['off'])} ptr={hex(child['ptr']) if child.get('ptr') else '0x0'} valid={child.get('valid')}"
            )
        lines.append("")

    lines.append("TOP CANDIDATES")
    for idx, item in enumerate(payload.get("candidates", [])[:12], 1):
        lines.append(
            f"[{idx}] ptr={hex(item['ptr'])} score={item.get('score')} model={item.get('model_enum')} gate={item.get('table_gate')} "
            f"mass={item.get('mass')} cal={item.get('caliber')} cx={item.get('cx')} maxDist={item.get('maxDistance')} "
            f"velRange=({item.get('velRange_x')}, {item.get('velRange_y')}) table_ref={hex(item.get('table_ref') or 0)}"
        )
        lines.append(item.get("raw_hex", ""))
        table = item.get("table")
        if table:
            lines.append(f"    TABLE REF: {hex(table['ptr'])}")
            lines.append(table.get("raw_hex", ""))
            runtime = table.get("runtime")
            if runtime:
                lines.append(
                    f"    TABLE RUNTIME: ptr={hex(runtime['ptr'])} data_ptr={hex(runtime.get('data_ptr') or 0)} count={runtime.get('count')}"
                )
                if runtime.get("data_preview"):
                    lines.append(f"    DATA PREVIEW: {runtime['data_preview']}")
                lines.append(runtime.get("raw_hex", ""))
            for child in table.get("children", []):
                lines.append(
                    f"      child_off={hex(child['off'])} ptr={hex(child['ptr']) if child.get('ptr') else '0x0'} valid={child.get('valid')}"
                )
                if child.get("hex"):
                    lines.append(child["hex"])
        lines.append("")

    global_mgr = payload.get("global_table_manager") or {}
    lines.append("GLOBAL TABLE MANAGER")
    lines.append(
        f"  global_ptr_addr={hex(global_mgr.get('global_ptr_addr') or 0)} manager_ptr={hex(global_mgr.get('manager_ptr') or 0)} valid={global_mgr.get('manager_valid')}"
    )
    if global_mgr.get("raw_hex"):
        lines.append(global_mgr["raw_hex"])
    for slot in global_mgr.get("slots", []) or []:
        lines.append(
            f"  slot ptr_off={hex(slot['ptr_off'])} count_off={hex(slot['count_off'])} table_ptr={hex(slot.get('table_ptr') or 0)} count={slot.get('count')} valid={slot.get('valid')}"
        )
        triplets = slot.get("triplets")
        if triplets:
            lines.append(f"    triplet_preview={triplets.get('preview')}")
    lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, txt_path


def main():
    print("=" * 80)
    print("BALLISTIC TABLE DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/ballistic_table_dumper.py")
    print("  sudo venv/bin/python tools/ballistic_table_dumper.py --watch")
    print("-" * 80)

    scanner = None
    try:
        watch_mode = "--watch" in sys.argv[1:]
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        init_dynamic_offsets(scanner, base_addr)
        if watch_mode:
            print("[*] Watch mode active. เปลี่ยน ammo แล้ว dumper จะจับ snapshot ใหม่อัตโนมัติ")
            print("[*] กด Ctrl+C เพื่อหยุดและเขียน session log")
            history = {"snapshots": []}
            prev_sig = None
            snapshot_idx = 0
            try:
                while True:
                    payload = build_payload(scanner, base_addr)
                    sig = snapshot_signature(payload)
                    if prev_sig is None or not signatures_equal(prev_sig, sig):
                        snapshot_idx += 1
                        prev_slots = {s["ptr_off"]: s for s in (prev_sig or {}).get("slots", [])}
                        cur_slots = {s["ptr_off"]: s for s in sig.get("slots", [])}
                        slot_diffs = []
                        for ptr_off in sorted(set(prev_slots) | set(cur_slots)):
                            changes = format_slot_diff(prev_slots.get(ptr_off), cur_slots.get(ptr_off))
                            if changes:
                                slot_diffs.append({"ptr_off": ptr_off, "changes": changes})
                        history["snapshots"].append({
                            "captured_at": datetime.now().isoformat(),
                            "signature": sig,
                            "slot_diffs": slot_diffs,
                            "payload": payload,
                        })
                        print(
                            f"[+] Snapshot #{snapshot_idx}: model={sig.get('model_enum')} ({sig.get('model_label')}) "
                            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} cx={sig.get('cx')}"
                        )
                        for diff in slot_diffs[:6]:
                            print(f"    slot {hex(diff['ptr_off'])}: {' | '.join(diff['changes'])}")
                    prev_sig = sig
                    time.sleep(WATCH_POLL_SECONDS)
            except KeyboardInterrupt:
                print("[*] Watch stopped by user.")
                json_path, txt_path = write_watch_dump(history)
                print(f"[+] WATCH JSON: {json_path}")
                print(f"[+] WATCH TEXT: {txt_path}")
        else:
            payload = build_payload(scanner, base_addr)
            json_path, txt_path = write_dump(payload)
            print(f"[+] JSON: {json_path}")
            print(f"[+] TEXT: {txt_path}")
    except Exception as e:
        print(f"[-] Critical error: {e}")
    finally:
        if scanner:
            try:
                scanner.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
