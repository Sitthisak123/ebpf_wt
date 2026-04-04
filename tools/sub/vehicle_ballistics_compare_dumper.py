import json
import math
import os
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

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
    if not math.isfinite(value):
        return None
    return value


def round_vec3(vec, ndigits=4):
    if not vec:
        return None
    return [round(float(v), ndigits) for v in vec]


def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_len(v):
    return math.sqrt((v[0] * v[0]) + (v[1] * v[1]) + (v[2] * v[2]))


def vec_norm(v):
    length = vec_len(v)
    if length <= 1e-8:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def fmt_sci(value):
    if value is None:
        return "None"
    try:
        return f"{float(value):.6e}"
    except Exception:
        return str(value)


def current_weapon_ptr(scanner, unit_ptr, cgame_ptr):
    weapon_ptr = 0
    source = "none"
    if mul.is_valid_ptr(unit_ptr):
        weapon_ptr = read_u64(scanner, unit_ptr + mul.OFF_WEAPON_PTR)
        source = "unit+OFF_WEAPON_PTR"
    if not mul.is_valid_ptr(weapon_ptr) and mul.is_valid_ptr(cgame_ptr):
        weapon_ptr = read_u64(scanner, cgame_ptr + mul.OFF_WEAPON_PTR)
        source = "cgame+OFF_WEAPON_PTR"
    return weapon_ptr, source


def read_live_profile(scanner, weapon_ptr):
    if not mul.is_valid_ptr(weapon_ptr):
        return {}
    model_enum = read_u32(scanner, weapon_ptr + MODEL_ENUM_OFF)
    speed = read_f32(scanner, weapon_ptr + 0x2050)
    mass = read_f32(scanner, weapon_ptr + 0x205C)
    caliber = read_f32(scanner, weapon_ptr + 0x2060)
    cx = read_f32(scanner, weapon_ptr + 0x2064)
    max_distance = read_f32(scanner, weapon_ptr + 0x2068)
    vel_lo = read_f32(scanner, weapon_ptr + 0x207C)
    vel_hi = read_f32(scanner, weapon_ptr + 0x2080)
    return {
        "model_enum": model_enum,
        "model_label": MODEL_ENUM_LABELS.get(model_enum, f"model_{model_enum}_unknown"),
        "speed": speed,
        "mass": mass,
        "caliber": caliber,
        "cx": cx,
        "maxDistance": max_distance,
        "velRange_x": vel_lo,
        "velRange_y": vel_hi,
    }


def reconstruct_runtime_seed(profile):
    speed = float(profile.get("speed") or 0.0)
    mass = float(profile.get("mass") or 0.0)
    caliber = float(profile.get("caliber") or 0.0)
    cx = float(profile.get("cx") or 0.0)
    area = math.pi * ((caliber * 0.5) ** 2) if caliber > 0.0 else 0.0
    drag_k = ((cx * area) / mass) if mass > 0.0 and area > 0.0 else 0.0
    mach_like = speed / 343.0 if speed > 0.0 else 0.0
    return {
        "seed_area": area,
        "seed_drag_k": drag_k,
        "seed_mach_like": mach_like,
    }


def get_unit_label(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    short_name = dna.get("short_name") or ""
    name_key = dna.get("name_key") or ""
    family = dna.get("family") or ""
    display_name = profile.get("display_name") or ""
    label = short_name if short_name and short_name != "None" else display_name
    if not label:
        label = name_key if name_key and name_key != "None" else f"unit_{hex(unit_ptr)}"
    return {
        "label": label,
        "short_name": short_name,
        "name_key": name_key,
        "family": family,
        "profile_tag": profile.get("tag", ""),
        "profile_kind": profile.get("kind"),
    }


def build_payload(scanner, base_addr):
    unit_ptr, _ = mul.get_local_team(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    payload = {
        "pid": getattr(scanner, "pid", 0),
        "image_base": base_addr,
        "unit_ptr": unit_ptr,
        "cgame_ptr": cgame_ptr,
    }
    if not mul.is_valid_ptr(unit_ptr):
        return payload

    payload["unit_info"] = get_unit_label(scanner, unit_ptr)

    box_data = mul.get_unit_3d_box_data(scanner, unit_ptr, is_air=False)
    if box_data:
        unit_pos, bmin, bmax, rot = box_data
        payload["unit_pos"] = round_vec3(unit_pos)
        payload["bbox"] = {
            "bmin": round_vec3(bmin),
            "bmax": round_vec3(bmax),
        }
        barrel = mul.get_weapon_barrel(scanner, unit_ptr, unit_pos, rot)
        if barrel:
            barrel_base, barrel_tip = barrel
            barrel_vec = vec_sub(barrel_tip, barrel_base)
            payload["barrel"] = {
                "base_world": round_vec3(barrel_base),
                "tip_world": round_vec3(barrel_tip),
                "dir_world": round_vec3(vec_norm(barrel_vec)),
                "length": round(vec_len(barrel_vec), 4),
                "base_from_unit": round_vec3(vec_sub(barrel_base, unit_pos)),
                "tip_from_unit": round_vec3(vec_sub(barrel_tip, unit_pos)),
            }

    zeroing = mul.get_sight_compensation_factor(scanner, base_addr)
    payload["zeroing"] = zeroing

    weapon_ptr, weapon_source = current_weapon_ptr(scanner, unit_ptr, cgame_ptr)
    payload["weapon_ptr"] = weapon_ptr
    payload["weapon_source"] = weapon_source
    if mul.is_valid_ptr(weapon_ptr):
        live = read_live_profile(scanner, weapon_ptr)
        payload["live_profile"] = live
        payload["runtime_seed"] = reconstruct_runtime_seed(live)
    return payload


def payload_signature(payload):
    info = payload.get("unit_info") or {}
    live = payload.get("live_profile") or {}
    seed = payload.get("runtime_seed") or {}
    barrel = payload.get("barrel") or {}
    return {
        "unit_ptr": payload.get("unit_ptr"),
        "label": info.get("label"),
        "name_key": info.get("name_key"),
        "model_enum": live.get("model_enum"),
        "speed": live.get("speed"),
        "mass": live.get("mass"),
        "caliber": live.get("caliber"),
        "cx": live.get("cx"),
        "drag_k": seed.get("seed_drag_k"),
        "zeroing": payload.get("zeroing"),
        "barrel_base_from_unit": barrel.get("base_from_unit"),
        "barrel_tip_from_unit": barrel.get("tip_from_unit"),
    }


def is_valid_snapshot(payload):
    if not mul.is_valid_ptr(payload.get("unit_ptr", 0)):
        return False
    info = payload.get("unit_info") or {}
    live = payload.get("live_profile") or {}
    if not info.get("label"):
        return False
    if live.get("speed") is None or live.get("mass") is None or live.get("caliber") is None or live.get("cx") is None:
        return False
    if "barrel" not in payload:
        return False
    return True


def signatures_equal(a, b):
    if not a or not b:
        return False
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def summarize_by_vehicle(history):
    grouped = defaultdict(list)
    for item in history.get("snapshots", []):
        payload = item.get("payload") or {}
        info = payload.get("unit_info") or {}
        label = info.get("label") or "unknown"
        grouped[label].append(payload)

    summary = {}
    for label, items in grouped.items():
        latest = items[-1]
        live = latest.get("live_profile") or {}
        seed = latest.get("runtime_seed") or {}
        barrel = latest.get("barrel") or {}
        summary[label] = {
            "snapshots": len(items),
            "latest_unit_ptr": latest.get("unit_ptr"),
            "name_key": (latest.get("unit_info") or {}).get("name_key"),
            "family": (latest.get("unit_info") or {}).get("family"),
            "model_enum": live.get("model_enum"),
            "model_label": live.get("model_label"),
            "speed": live.get("speed"),
            "mass": live.get("mass"),
            "caliber": live.get("caliber"),
            "cx": live.get("cx"),
            "drag_k": seed.get("seed_drag_k"),
            "zeroing": latest.get("zeroing"),
            "barrel_base_from_unit": barrel.get("base_from_unit"),
            "barrel_tip_from_unit": barrel.get("tip_from_unit"),
            "barrel_dir_world": barrel.get("dir_world"),
            "barrel_length": barrel.get("length"),
        }
    return summary


def build_comparison_summary(vehicle_summary):
    labels = sorted(vehicle_summary.keys())
    comparisons = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            left = vehicle_summary[labels[i]]
            right = vehicle_summary[labels[j]]
            left_zero = float(left.get("zeroing") or 0.0)
            right_zero = float(right.get("zeroing") or 0.0)
            left_drag = float(left.get("drag_k") or 0.0)
            right_drag = float(right.get("drag_k") or 0.0)
            left_base = left.get("barrel_base_from_unit") or [0.0, 0.0, 0.0]
            right_base = right.get("barrel_base_from_unit") or [0.0, 0.0, 0.0]
            left_tip = left.get("barrel_tip_from_unit") or [0.0, 0.0, 0.0]
            right_tip = right.get("barrel_tip_from_unit") or [0.0, 0.0, 0.0]
            comparisons.append({
                "left": labels[i],
                "right": labels[j],
                "delta_zeroing": round(right_zero - left_zero, 4),
                "delta_drag_k": right_drag - left_drag,
                "delta_barrel_base_from_unit": [round(float(right_base[k]) - float(left_base[k]), 4) for k in range(3)],
                "delta_barrel_tip_from_unit": [round(float(right_tip[k]) - float(left_tip[k]), 4) for k in range(3)],
            })
    return comparisons


def write_dump(payload):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"vehicle_ballistics_compare_dump_{stamp}.json")
    txt_path = os.path.join("dumps", f"vehicle_ballistics_compare_dump_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "VEHICLE BALLISTICS COMPARE DUMPER",
        "=" * 80,
        json.dumps(payload, indent=2, ensure_ascii=False),
    ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def write_watch_dump(history):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"vehicle_ballistics_compare_watch_{stamp}.json")
    txt_path = os.path.join("dumps", f"vehicle_ballistics_compare_watch_{stamp}.txt")
    history["vehicle_summary"] = summarize_by_vehicle(history)
    history["comparison_summary"] = build_comparison_summary(history["vehicle_summary"])

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    lines = [
        "VEHICLE BALLISTICS COMPARE WATCH",
        "=" * 80,
        "SNAPSHOTS",
        "-" * 80,
    ]
    for idx, item in enumerate(history.get("snapshots", []), 1):
        sig = item.get("signature") or {}
        lines.append(
            f"[{idx}] {sig.get('label')} | model={sig.get('model_enum')} "
            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} "
            f"cx={sig.get('cx')} drag_k={sig.get('drag_k')} zero={sig.get('zeroing')} "
            f"barrel_base={sig.get('barrel_base_from_unit')} barrel_tip={sig.get('barrel_tip_from_unit')}"
        )

    lines.extend([
        "",
        "VEHICLE SUMMARY",
        "-" * 80,
    ])
    for label, summary in history.get("vehicle_summary", {}).items():
        lines.append(f"{label}")
        lines.append(json.dumps(summary, indent=2, ensure_ascii=False))

    lines.extend([
        "",
        "COMPARISON SUMMARY",
        "-" * 80,
    ])
    for item in history.get("comparison_summary", []):
        lines.append(
            f"{item['left']}  <->  {item['right']} | "
            f"zeroing_delta={item['delta_zeroing']} | "
            f"drag_k_delta={fmt_sci(item['delta_drag_k'])} | "
            f"base_delta={item['delta_barrel_base_from_unit']} | "
            f"tip_delta={item['delta_barrel_tip_from_unit']}"
        )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def main():
    print("=" * 80)
    print("VEHICLE BALLISTICS COMPARE DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/vehicle_ballistics_compare_dumper.py")
    print("  sudo venv/bin/python tools/vehicle_ballistics_compare_dumper.py --watch")
    print("-" * 80)

    scanner = None
    try:
        watch_mode = "--watch" in sys.argv[1:]
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        init_dynamic_offsets(scanner, base_addr)

        if watch_mode:
            print("[*] Watch mode active. เปลี่ยนคันหรือเปลี่ยน ammo แล้ว dumper จะจับ snapshot ใหม่อัตโนมัติ")
            print("[*] กด Ctrl+C เพื่อหยุดและเขียน session log")
            history = {"snapshots": []}
            prev_sig = None
            snapshot_idx = 0
            try:
                while True:
                    payload = build_payload(scanner, base_addr)
                    if not is_valid_snapshot(payload):
                        prev_sig = None
                        time.sleep(WATCH_POLL_SECONDS)
                        continue
                    sig = payload_signature(payload)
                    if prev_sig is None or not signatures_equal(prev_sig, sig):
                        snapshot_idx += 1
                        history["snapshots"].append({
                            "captured_at": datetime.now().isoformat(),
                            "signature": sig,
                            "payload": payload,
                        })
                        print(
                            f"[+] Snapshot #{snapshot_idx}: {sig.get('label')} | model={sig.get('model_enum')} "
                            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} "
                            f"cx={sig.get('cx')} drag_k={fmt_sci(sig.get('drag_k'))} "
                            f"zero={sig.get('zeroing')} barrel_base={sig.get('barrel_base_from_unit')}"
                        )
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
