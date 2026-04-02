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

BALLISTIC_PERSISTENCE_PATH = os.path.join(PROJECT_ROOT, "config", "ballistic_layout_persistence.json")

MUZZLE_VELOCITY_OFF = 0x2048
WEAPON_SCAN_START = 0x2030
WEAPON_SCAN_END = 0x20B0
WEAPON_SCAN_STEP = 4
PROPS_BASE_SCAN_START = 0x2040
PROPS_BASE_SCAN_END = 0x2080
PROPS_BASE_SCAN_STEP = 4

WEAPON_PTR_SCAN_START = 0x300
WEAPON_PTR_SCAN_END = 0x600
WEAPON_PTR_SCAN_STEP = 8

FIELD_RULES = {
    "speed": {"low": 50.0, "high": 3000.0},
    "mass": {"low": 0.005, "high": 200.0},
    "caliber": {"low": 0.001, "high": 0.5},
    "cx": {"low": 0.01, "high": 3.0},
    "maxDistance": {"low": 100.0, "high": 50000.0},
    "velRange": {"low": 10.0, "high": 4000.0},
}

LAYOUTS = [
    {
        "name": "layout_new_guess",
        "speed": 0x00,
        "mass": 0x0C,
        "caliber": 0x10,
        "cx": 0x14,
        "maxDistance": 0x18,
        "velRange_x": 0x24,
        "velRange_y": 0x28,
    },
    {
        "name": "layout_old_guess",
        "speed": -0x08,
        "mass": 0x04,
        "caliber": 0x08,
        "cx": 0x0C,
        "maxDistance": 0x10,
        "velRange_x": 0x24,
        "velRange_y": 0x28,
    },
]


def layout_to_absolute_offsets(best_layout):
    if not best_layout:
        return None

    layout_name = best_layout.get("layout")
    base_off = best_layout.get("base_off")
    if layout_name is None or base_off is None:
        return None

    layout_spec = None
    for item in LAYOUTS:
        if item["name"] == layout_name:
            layout_spec = item
            break
    if layout_spec is None:
        return None

    return {
        "layout_name": layout_name,
        "base_off": base_off,
        "speed_off": base_off + layout_spec["speed"],
        "mass_off": base_off + layout_spec["mass"],
        "caliber_off": base_off + layout_spec["caliber"],
        "cx_off": base_off + layout_spec["cx"],
        "max_distance_off": base_off + layout_spec["maxDistance"],
        "vel_range_x_off": base_off + layout_spec["velRange_x"],
        "vel_range_y_off": base_off + layout_spec["velRange_y"],
    }


def write_ballistic_layout_persistence(payload):
    best_layout = payload.get("best_layout") or {}
    if not best_layout:
        return None
    if best_layout.get("score", -999) < 20:
        return None

    offsets = layout_to_absolute_offsets(best_layout)
    if not offsets:
        return None

    doc = {
        "updated_at": datetime.now().isoformat(),
        "pid": payload.get("pid", 0),
        "image_base": payload.get("image_base", 0),
        "weapon_source": payload.get("weapon_source"),
        "best_layout_score": best_layout.get("score", -999),
        "layout": offsets,
        "best_layout_snapshot": {
            "speed": best_layout.get("speed"),
            "mass": best_layout.get("mass"),
            "caliber": best_layout.get("caliber"),
            "cx": best_layout.get("cx"),
            "maxDistance": best_layout.get("maxDistance"),
            "velRange_x": best_layout.get("velRange_x"),
            "velRange_y": best_layout.get("velRange_y"),
        },
    }

    with open(BALLISTIC_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return BALLISTIC_PERSISTENCE_PATH


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


def score_field_value(field_name, value):
    rule = FIELD_RULES[field_name]
    if not is_reasonable_float(value, rule["low"], rule["high"]):
        return -999

    score = 10
    if field_name == "cx":
        if value > 1.5:
            score -= 5
        elif value <= 1.0:
            score += 2
    elif field_name == "caliber":
        if value <= 0.03:
            score += 2
    elif field_name == "speed":
        if value >= 1200.0:
            score += 2
    elif field_name == "maxDistance":
        if value >= 5000.0:
            score += 1
    return score


def score_props(props):
    if not props:
        return -999

    score = 0
    for field in ("speed", "mass", "caliber", "cx", "maxDistance"):
        score += max(score_field_value(field, props.get(field)), -20)

    vel_x = props.get("velRange_x")
    vel_y = props.get("velRange_y")
    if is_reasonable_float(vel_x, FIELD_RULES["velRange"]["low"], FIELD_RULES["velRange"]["high"]):
        score += 3
    if is_reasonable_float(vel_y, FIELD_RULES["velRange"]["low"], FIELD_RULES["velRange"]["high"]) and vel_y >= (vel_x or 0.0):
        score += 3
    else:
        score -= 2

    mass = props.get("mass")
    cx = props.get("cx")
    if is_reasonable_float(mass, 0.0, 1000.0) and is_reasonable_float(cx, 0.0, 1000.0):
        if abs(mass - cx) <= 0.02:
            score -= 6
    return score


def decode_layout(scanner, base_addr, layout):
    props = {"layout": layout["name"], "base_addr": base_addr}
    for field, off in layout.items():
        if field == "name":
            continue
        props[field] = read_f32(scanner, base_addr + off)
    props["score"] = score_props(props)
    return props


def read_weapon_window(scanner, weapon_ptr):
    raw = scanner.read_mem(weapon_ptr + WEAPON_SCAN_START, WEAPON_SCAN_END - WEAPON_SCAN_START) or b""
    values = []
    for off in range(WEAPON_SCAN_START, WEAPON_SCAN_END, WEAPON_SCAN_STEP):
        value = read_f32(scanner, weapon_ptr + off)
        values.append({
            "off": off,
            "addr": weapon_ptr + off,
            "value": value,
        })
    return raw, values


def collect_field_candidates(window_values):
    candidates = {}
    for field in ("speed", "mass", "caliber", "cx", "maxDistance"):
        entries = []
        for item in window_values:
            score = score_field_value(field, item["value"])
            if score < 0:
                continue
            entries.append({
                "off": item["off"],
                "addr": item["addr"],
                "value": item["value"],
                "score": score,
            })
        entries.sort(key=lambda e: (-e["score"], e["off"]))
        candidates[field] = entries[:12]

    vel_entries = []
    for lo in window_values:
        if not is_reasonable_float(lo["value"], FIELD_RULES["velRange"]["low"], FIELD_RULES["velRange"]["high"]):
            continue
        for hi in window_values:
            if hi["off"] <= lo["off"]:
                continue
            if not is_reasonable_float(hi["value"], FIELD_RULES["velRange"]["low"], FIELD_RULES["velRange"]["high"]):
                continue
            if hi["value"] < lo["value"]:
                continue
            pair_score = 10 - min((hi["off"] - lo["off"]) // 4, 6)
            vel_entries.append({
                "lo_off": lo["off"],
                "lo_addr": lo["addr"],
                "lo_value": lo["value"],
                "hi_off": hi["off"],
                "hi_addr": hi["addr"],
                "hi_value": hi["value"],
                "score": pair_score,
            })
    vel_entries.sort(key=lambda e: (-e["score"], e["lo_off"], e["hi_off"]))
    candidates["velRange"] = vel_entries[:16]
    return candidates


def collect_layout_candidates(scanner, weapon_ptr):
    candidates = []
    for base_off in range(PROPS_BASE_SCAN_START, PROPS_BASE_SCAN_END, PROPS_BASE_SCAN_STEP):
        base_addr = weapon_ptr + base_off
        for layout in LAYOUTS:
            props = decode_layout(scanner, base_addr, layout)
            props["base_off"] = base_off
            candidates.append(props)
    candidates.sort(key=lambda c: (-c["score"], c["base_off"], c["layout"]))
    return candidates[:16]


def is_plausible_weapon_block(scanner, weapon_ptr):
    if not mul.is_valid_ptr(weapon_ptr):
        return False, {"reason": "invalid_ptr"}

    raw, window_values = read_weapon_window(scanner, weapon_ptr)
    nonzero = sum(1 for b in raw if b != 0)
    layouts = collect_layout_candidates(scanner, weapon_ptr)
    best_layout = layouts[0] if layouts else None
    muzzle_velocity = read_f32(scanner, weapon_ptr + MUZZLE_VELOCITY_OFF)

    ok = False
    if is_reasonable_float(muzzle_velocity, 50.0, 3000.0):
        ok = True
    if best_layout and best_layout["score"] >= 20:
        ok = True
    if nonzero >= 12 and best_layout and best_layout["score"] >= 10:
        ok = True

    return ok, {
        "muzzle_velocity": muzzle_velocity,
        "nonzero_bytes": nonzero,
        "best_layout_score": best_layout["score"] if best_layout else -999,
        "best_layout": best_layout,
    }


def scan_weapon_ptr_candidates(scanner, base_ptr):
    candidates = []
    if not mul.is_valid_ptr(base_ptr):
        return candidates

    seen = set()
    for off in range(WEAPON_PTR_SCAN_START, WEAPON_PTR_SCAN_END, WEAPON_PTR_SCAN_STEP):
        ptr = read_u64(scanner, base_ptr + off)
        if not mul.is_valid_ptr(ptr) or ptr in seen:
            continue
        seen.add(ptr)
        ok, meta = is_plausible_weapon_block(scanner, ptr)
        if not ok:
            continue
        candidates.append({
            "source_off": off,
            "weapon_ptr": ptr,
            "meta": meta,
        })

    candidates.sort(
        key=lambda item: (
            -(item["meta"].get("best_layout_score") or -999),
            -int(is_reasonable_float(item["meta"].get("muzzle_velocity"), 50.0, 3000.0)),
            -(item["meta"].get("nonzero_bytes") or 0),
            item["source_off"],
        )
    )
    return candidates


def try_get_active_weapon(scanner, base_addr):
    unit_ptr, _ = mul.get_local_team(scanner, base_addr)
    if not mul.is_valid_ptr(unit_ptr):
        return 0, 0, "controlled_unit_invalid", []

    scan_notes = []

    weapon_ptr = read_u64(scanner, unit_ptr + mul.OFF_WEAPON_PTR)
    ok, meta = is_plausible_weapon_block(scanner, weapon_ptr)
    scan_notes.append({"source": "unit+OFF_WEAPON_PTR", "weapon_ptr": weapon_ptr, "ok": ok, "meta": meta})
    if ok:
        return unit_ptr, weapon_ptr, "unit+OFF_WEAPON_PTR", scan_notes

    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    if not mul.is_valid_ptr(cgame_ptr):
        return unit_ptr, 0, "cgame_invalid", scan_notes

    weapon_ptr = read_u64(scanner, cgame_ptr + mul.OFF_WEAPON_PTR)
    ok, meta = is_plausible_weapon_block(scanner, weapon_ptr)
    scan_notes.append({"source": "cgame+OFF_WEAPON_PTR", "weapon_ptr": weapon_ptr, "ok": ok, "meta": meta})
    if ok:
        return unit_ptr, weapon_ptr, "cgame+OFF_WEAPON_PTR", scan_notes

    unit_candidates = scan_weapon_ptr_candidates(scanner, unit_ptr)
    scan_notes.append({"source": "unit_scan", "count": len(unit_candidates)})
    if unit_candidates:
        best = unit_candidates[0]
        return unit_ptr, best["weapon_ptr"], f"unit_scan+{hex(best['source_off'])}", scan_notes

    cgame_candidates = scan_weapon_ptr_candidates(scanner, cgame_ptr)
    scan_notes.append({"source": "cgame_scan", "count": len(cgame_candidates)})
    if cgame_candidates:
        best = cgame_candidates[0]
        return unit_ptr, best["weapon_ptr"], f"cgame_scan+{hex(best['source_off'])}", scan_notes

    return unit_ptr, 0, "weapon_not_found", scan_notes


def dump_weapon_block(scanner, weapon_ptr):
    weapon_raw, window_values = read_weapon_window(scanner, weapon_ptr)
    field_candidates = collect_field_candidates(window_values)
    layout_candidates = collect_layout_candidates(scanner, weapon_ptr)
    best_layout = layout_candidates[0] if layout_candidates else None

    return {
        "weapon_ptr": weapon_ptr,
        "muzzle_velocity_addr": weapon_ptr + MUZZLE_VELOCITY_OFF,
        "muzzle_velocity": read_f32(scanner, weapon_ptr + MUZZLE_VELOCITY_OFF),
        "weapon_window_hex": hex_dump(weapon_raw, WEAPON_SCAN_START) if weapon_raw else "",
        "window_values": window_values,
        "field_candidates": field_candidates,
        "layout_candidates": layout_candidates,
        "best_layout": best_layout,
    }


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

    if payload.get("scan_notes"):
        lines.append("WEAPON POINTER PROBE")
        for item in payload["scan_notes"]:
            if "weapon_ptr" in item:
                lines.append(
                    f"  {item['source']}: ptr={hex(item['weapon_ptr']) if item['weapon_ptr'] else '0x0'} "
                    f"ok={item.get('ok')} meta={item.get('meta')}"
                )
            else:
                lines.append(f"  {item['source']}: count={item.get('count', 0)}")
        lines.append("")

    if payload.get("weapon_ptr"):
        lines.extend(
            [
                f"Muzzle Velocity @ {hex(payload['muzzle_velocity_addr'])}: {payload['muzzle_velocity']}",
                "",
                "BEST LAYOUT",
                json.dumps(payload.get("best_layout"), indent=2, ensure_ascii=False),
                "",
                "FIELD CANDIDATES",
            ]
        )
        for field in ("speed", "mass", "caliber", "cx", "maxDistance"):
            lines.append(f"  [{field}]")
            for item in payload["field_candidates"].get(field, [])[:8]:
                lines.append(
                    f"    off={hex(item['off'])} addr={hex(item['addr'])} "
                    f"value={item['value']} score={item['score']}"
                )
        lines.append("  [velRange]")
        for item in payload["field_candidates"].get("velRange", [])[:8]:
            lines.append(
                f"    lo={hex(item['lo_off'])}:{item['lo_value']} "
                f"hi={hex(item['hi_off'])}:{item['hi_value']} score={item['score']}"
            )

        lines.extend(
            [
                "",
                "TOP LAYOUT CANDIDATES",
            ]
        )
        for idx, cand in enumerate(payload.get("layout_candidates", [])[:8], 1):
            lines.append(
                f"[{idx}] base_off={hex(cand['base_off'])} layout={cand['layout']} score={cand['score']} "
                f"speed={cand.get('speed')} mass={cand.get('mass')} caliber={cand.get('caliber')} "
                f"cx={cand.get('cx')} maxDistance={cand.get('maxDistance')} "
                f"velRange=({cand.get('velRange_x')}, {cand.get('velRange_y')})"
            )

        lines.extend(
            [
                "",
                f"WEAPON WINDOW HEX [weapon + {hex(WEAPON_SCAN_START)}, size {hex(WEAPON_SCAN_END - WEAPON_SCAN_START)}]",
                payload["weapon_window_hex"],
            ]
        )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, txt_path


def _round_sig(value, digits=4):
    if value is None:
        return None
    return round(float(value), digits)


def build_profile_signature(payload):
    best = payload.get("best_layout") or {}
    return {
        "weapon_ptr": payload.get("weapon_ptr", 0),
        "speed": _round_sig(best.get("speed"), 2),
        "mass": _round_sig(best.get("mass"), 3),
        "caliber": _round_sig(best.get("caliber"), 4),
        "cx": _round_sig(best.get("cx"), 3),
        "maxDistance": _round_sig(best.get("maxDistance"), 1),
        "velRange_x": _round_sig(best.get("velRange_x"), 1),
        "velRange_y": _round_sig(best.get("velRange_y"), 1),
        "layout": best.get("layout"),
        "base_off": best.get("base_off"),
    }


def signatures_differ(old_sig, new_sig):
    if not old_sig:
        return True
    for key in ("weapon_ptr", "speed", "mass", "caliber", "cx", "maxDistance", "velRange_x", "velRange_y", "layout", "base_off"):
        if old_sig.get(key) != new_sig.get(key):
            return True
    return False


def diff_weapon_window(prev_payload, curr_payload):
    prev_values = {item["off"]: item["value"] for item in prev_payload.get("window_values", [])}
    curr_values = {item["off"]: item["value"] for item in curr_payload.get("window_values", [])}
    diffs = []
    for off in sorted(set(prev_values.keys()) | set(curr_values.keys())):
        old = prev_values.get(off)
        new = curr_values.get(off)
        if old is None or new is None:
            continue
        if abs(float(new) - float(old)) < 1e-6:
            continue
        diffs.append({
            "off": off,
            "old": old,
            "new": new,
            "delta": new - old,
        })
    diffs.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return diffs


def write_watch_session_files(session):
    os.makedirs("dumps", exist_ok=True)
    stamp = session["stamp"]
    json_path = os.path.join("dumps", f"origin_dragoff_watch_{stamp}.json")
    txt_path = os.path.join("dumps", f"origin_dragoff_watch_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)

    lines = [
        "ORIGIN DRAGOFF WATCH",
        "=" * 80,
        f"PID: {session['pid']}",
        f"Image Base: {hex(session['image_base'])}",
        f"Start: {session['started_at']}",
        f"Snapshots: {len(session['snapshots'])}",
        "",
    ]

    for idx, snap in enumerate(session["snapshots"], 1):
        sig = snap.get("signature", {})
        lines.append(
            f"[{idx}] t={snap['timestamp']} weapon={hex(sig.get('weapon_ptr') or 0)} "
            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} "
            f"cx={sig.get('cx')} maxDist={sig.get('maxDistance')} "
            f"velRange=({sig.get('velRange_x')}, {sig.get('velRange_y')}) "
            f"layout={sig.get('layout')} base_off={hex(sig.get('base_off') or 0)}"
        )
        lines.append(f"    json={snap.get('json_path')}")
        lines.append(f"    txt={snap.get('txt_path')}")
        lines.append(f"    reason={snap.get('reason')}")
        for item in snap.get("window_diff", [])[:16]:
            lines.append(
                f"    diff off={hex(item['off'])} old={item['old']} new={item['new']} delta={item['delta']}"
            )
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, txt_path


def capture_payload(scanner, base_addr):
    unit_ptr, weapon_ptr, weapon_source, scan_notes = try_get_active_weapon(scanner, base_addr)
    payload = {
        "pid": getattr(scanner, "pid", 0),
        "image_base": base_addr,
        "unit_ptr": unit_ptr,
        "weapon_ptr": weapon_ptr,
        "weapon_source": weapon_source,
        "scan_notes": scan_notes,
    }
    if mul.is_valid_ptr(weapon_ptr):
        payload.update(dump_weapon_block(scanner, weapon_ptr))
    return payload


def run_watch_mode(scanner, base_addr, poll_interval=0.35):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = {
        "stamp": stamp,
        "pid": getattr(scanner, "pid", 0),
        "image_base": base_addr,
        "started_at": datetime.now().isoformat(),
        "poll_interval": poll_interval,
        "snapshots": [],
    }

    print("[*] Watch mode active. เปลี่ยน ammo แล้ว dumper จะจับ snapshot ใหม่อัตโนมัติ")
    print("[*] กด Ctrl+C เพื่อหยุดและเขียน session log")

    prev_payload = None
    prev_sig = None
    seen_signatures = set()

    try:
        while True:
            payload = capture_payload(scanner, base_addr)
            if not mul.is_valid_ptr(payload.get("weapon_ptr", 0)):
                time.sleep(poll_interval)
                continue

            sig = build_profile_signature(payload)
            sig_key = json.dumps(sig, sort_keys=True, ensure_ascii=False)
            if signatures_differ(prev_sig, sig) and sig_key not in seen_signatures:
                payload["signature"] = sig
                json_path, txt_path = write_dump_files(payload)
                persistence_path = write_ballistic_layout_persistence(payload)
                window_diff = diff_weapon_window(prev_payload or {}, payload)
                reason = "initial_capture" if prev_sig is None else "ballistic_profile_changed"
                session["snapshots"].append({
                    "timestamp": datetime.now().isoformat(),
                    "signature": sig,
                    "json_path": json_path,
                    "txt_path": txt_path,
                    "persistence_path": persistence_path,
                    "reason": reason,
                    "window_diff": window_diff,
                })
                seen_signatures.add(sig_key)
                print(
                    f"[+] Snapshot #{len(session['snapshots'])}: "
                    f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} "
                    f"cx={sig.get('cx')} velRange=({sig.get('velRange_x')}, {sig.get('velRange_y')})"
                )
                if window_diff:
                    top = window_diff[0]
                    print(f"    top diff: off={hex(top['off'])} {top['old']} -> {top['new']}")
                if persistence_path:
                    print(f"    persistence: {persistence_path}")

            prev_payload = payload
            prev_sig = sig
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\n[*] Watch stopped by user.")
    finally:
        json_path, txt_path = write_watch_session_files(session)
        print(f"[+] WATCH JSON: {json_path}")
        print(f"[+] WATCH TEXT: {txt_path}")


def main():
    print("=" * 80)
    print("ORIGIN DRAGOFF DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/ballistic_layout_dumper.py")
    print("  sudo venv/bin/python tools/ballistic_layout_dumper.py --watch")
    print("-" * 80)

    scanner = None
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        init_dynamic_offsets(scanner, base_addr)
        watch_mode = ("--watch" in sys.argv) or ("-w" in sys.argv)
        if watch_mode:
            run_watch_mode(scanner, base_addr)
            return

        payload = capture_payload(scanner, base_addr)
        unit_ptr = payload["unit_ptr"]
        weapon_ptr = payload["weapon_ptr"]
        weapon_source = payload["weapon_source"]

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

        best_layout = payload.get("best_layout") or {}
        print(f"[*] Weapon Ptr: {hex(weapon_ptr)} ({weapon_source})")
        print(f"[*] Muzzle Velocity @ {hex(payload['muzzle_velocity_addr'])}: {payload['muzzle_velocity']}")
        if best_layout:
            print(
                f"[*] Best Layout: base_off={hex(best_layout.get('base_off', 0))} "
                f"layout={best_layout.get('layout')} score={best_layout.get('score')}"
            )
            print(
                f"    speed={best_layout.get('speed')} mass={best_layout.get('mass')} "
                f"caliber={best_layout.get('caliber')} cx={best_layout.get('cx')} "
                f"maxDistance={best_layout.get('maxDistance')} "
                f"velRange=({best_layout.get('velRange_x')}, {best_layout.get('velRange_y')})"
            )
        else:
            print("[*] Best Layout: none")

        for field in ("speed", "mass", "caliber", "cx", "maxDistance"):
            candidates = payload["field_candidates"].get(field, [])
            if candidates:
                top = candidates[0]
                print(f"[*] Top {field}: off={hex(top['off'])} value={top['value']} score={top['score']}")
        vel_candidates = payload["field_candidates"].get("velRange", [])
        if vel_candidates:
            top = vel_candidates[0]
            print(
                f"[*] Top velRange: lo={hex(top['lo_off'])}:{top['lo_value']} "
                f"hi={hex(top['hi_off'])}:{top['hi_value']} score={top['score']}"
            )

        json_path, txt_path = write_dump_files(payload)
        persistence_path = write_ballistic_layout_persistence(payload)
        print("-" * 80)
        print(f"[+] JSON: {json_path}")
        print(f"[+] TEXT: {txt_path}")
        if persistence_path:
            print(f"[+] PERSISTENCE: {persistence_path}")

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
