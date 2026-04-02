import json
import math
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
SEA_LEVEL_AIR_DENSITY = 1.225


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


def reconstruct_state_seed(profile):
    speed = float(profile.get("speed") or 0.0)
    mass = float(profile.get("mass") or 0.0)
    caliber = float(profile.get("caliber") or 0.0)
    cx = float(profile.get("cx") or 0.0)
    area = math.pi * ((caliber * 0.5) ** 2) if caliber > 0.0 else 0.0
    sectional_density = mass / area if area > 0.0 else 0.0
    drag_k = ((cx * area) / mass) if mass > 0.0 and area > 0.0 else 0.0
    base_k = 0.5 * SEA_LEVEL_AIR_DENSITY * drag_k if drag_k > 0.0 else 0.0
    mach_like = speed / 343.0 if speed > 0.0 else 0.0
    runtime_state_candidate = {
        "state_0x00_model_enum": int(profile.get("model_enum") or 0),
        "state_0x08_coeff_double": base_k,
        "state_0x14_dynamic_term": drag_k,
        "state_0x1C_step_index": 0,
        "state_0x20_pos_x": 0.0,
        "state_0x24_pos_y": 0.0,
        "state_0x28_pos_z": 0.0,
        "state_0x2C_vel_x": speed,
        "state_0x30_vel_y": 0.0,
        "state_0x34_vel_z": 0.0,
    }
    return {
        "state_model_enum": profile.get("model_enum"),
        "state_model_label": profile.get("model_label"),
        "seed_speed": speed,
        "seed_mass": mass,
        "seed_caliber": caliber,
        "seed_cx": cx,
        "seed_rho": SEA_LEVEL_AIR_DENSITY,
        "seed_area": area,
        "seed_sectional_density": sectional_density,
        "seed_drag_k": drag_k,
        "seed_base_k": base_k,
        "seed_mach_like": mach_like,
        "runtime_state_candidate": runtime_state_candidate,
    }


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
        live = read_live_profile(scanner, weapon_ptr)
        payload["live_profile"] = live
        payload["runtime_seed"] = reconstruct_state_seed(live)
    return payload


def snapshot_signature(payload):
    live = payload.get("live_profile") or {}
    seed = payload.get("runtime_seed") or {}
    state = seed.get("runtime_state_candidate") or {}
    return {
        "model_enum": live.get("model_enum"),
        "model_label": live.get("model_label"),
        "speed": live.get("speed"),
        "mass": live.get("mass"),
        "caliber": live.get("caliber"),
        "cx": live.get("cx"),
        "maxDistance": live.get("maxDistance"),
        "drag_k": seed.get("seed_drag_k"),
        "base_k": seed.get("seed_base_k"),
        "mach_like": seed.get("seed_mach_like"),
        "state_coeff": state.get("state_0x08_coeff_double"),
        "state_term": state.get("state_0x14_dynamic_term"),
    }


def signatures_equal(a, b):
    if not a or not b:
        return False
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def write_dump(payload):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"projectile_runtime_state_dump_{stamp}.json")
    txt_path = os.path.join("dumps", f"projectile_runtime_state_dump_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "PROJECTILE RUNTIME STATE DUMPER",
        "=" * 80,
        f"PID: {payload.get('pid')}",
        f"Image Base: {hex(payload.get('image_base', 0))}",
        f"Controlled Unit: {hex(payload.get('unit_ptr', 0)) if payload.get('unit_ptr') else '0x0'}",
        f"CGame: {hex(payload.get('cgame_ptr', 0)) if payload.get('cgame_ptr') else '0x0'}",
        f"Weapon Source: {payload.get('weapon_source')}",
        f"Weapon Ptr: {hex(payload.get('weapon_ptr', 0)) if payload.get('weapon_ptr') else '0x0'}",
        "",
        "LIVE PROFILE",
        json.dumps(payload.get("live_profile", {}), indent=2, ensure_ascii=False),
        "",
        "RUNTIME SEED",
        json.dumps(payload.get("runtime_seed", {}), indent=2, ensure_ascii=False),
        "",
    ]

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, txt_path


def write_watch_dump(history):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"projectile_runtime_state_watch_{stamp}.json")
    txt_path = os.path.join("dumps", f"projectile_runtime_state_watch_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    lines = [
        "PROJECTILE RUNTIME STATE WATCH",
        "=" * 80,
    ]
    for idx, item in enumerate(history.get("snapshots", []), 1):
        sig = item.get("signature") or {}
        lines.append(
            f"[{idx}] model={sig.get('model_enum')} ({sig.get('model_label')}) "
            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} "
            f"cx={sig.get('cx')} maxDist={sig.get('maxDistance')} drag_k={sig.get('drag_k')} "
            f"base_k={sig.get('base_k')} coeff={sig.get('state_coeff')} term={sig.get('state_term')} mach={sig.get('mach_like')}"
        )
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def main():
    print("=" * 80)
    print("PROJECTILE RUNTIME STATE DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/projectile_runtime_state_dumper.py")
    print("  sudo venv/bin/python tools/projectile_runtime_state_dumper.py --watch")
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
                        history["snapshots"].append({
                            "captured_at": datetime.now().isoformat(),
                            "signature": sig,
                            "payload": payload,
                        })
                        print(
                            f"[+] Snapshot #{snapshot_idx}: model={sig.get('model_enum')} ({sig.get('model_label')}) "
                            f"speed={sig.get('speed')} mass={sig.get('mass')} cal={sig.get('caliber')} "
                            f"cx={sig.get('cx')} drag_k={sig.get('drag_k')} "
                            f"base_k={sig.get('base_k')} coeff={sig.get('state_coeff')} term={sig.get('state_term')}"
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
