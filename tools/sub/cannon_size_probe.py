import json
import math
import os
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul
from tools.ballistic_layout_dumper import try_get_active_weapon


WATCH_POLL_SECONDS = 0.35
MODEL_ENUM_OFF = 0x2058
SPEED_OFF = 0x2050
MASS_OFF = 0x205C
CALIBER_OFF = 0x2060
CX_OFF = 0x2064
BULLET_TYPE_OFF = 0x584

SCAN_START = 0x2000
SCAN_END = 0x2200
SCAN_STEP = 4
POST_PTR_SCAN_START = 0x2088
POST_PTR_SCAN_END = 0x20B8
POST_PTR_SCAN_STEP = 8
REF_SCAN_BYTES = 0x100

CALIBER_MIN = 0.005
CALIBER_MAX = 0.5
STABILITY_EPS = 1e-5
LARGER_THAN_PROJECTILE_EPS = 5e-4
KNOWN_PROJECTILE_OFFS = {MASS_OFF, CALIBER_OFF, CX_OFF}


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_u8(scanner, addr):
    raw = scanner.read_mem(addr, 1)
    if not raw or len(raw) < 1:
        return 0
    return raw[0]


def read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    value = struct.unpack("<f", raw)[0]
    if not math.isfinite(value):
        return None
    return value


def current_weapon_ptr(scanner, base_addr):
    unit_ptr, weapon_ptr, source, _scan_notes = try_get_active_weapon(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    return unit_ptr, cgame_ptr, weapon_ptr, source


def read_live_profile(scanner, weapon_ptr):
    if not mul.is_valid_ptr(weapon_ptr):
        return {}
    model_enum = read_u64(scanner, weapon_ptr + MODEL_ENUM_OFF) & 0xFF
    bullet_type_idx = read_u8(scanner, weapon_ptr + BULLET_TYPE_OFF)
    speed = read_f32(scanner, weapon_ptr + SPEED_OFF)
    mass = read_f32(scanner, weapon_ptr + MASS_OFF)
    caliber = read_f32(scanner, weapon_ptr + CALIBER_OFF)
    cx = read_f32(scanner, weapon_ptr + CX_OFF)
    if not (speed is not None and 50.0 <= speed <= 3000.0):
        return {}
    if not (mass is not None and 0.001 <= mass <= 200.0):
        return {}
    if not (caliber is not None and CALIBER_MIN <= caliber <= CALIBER_MAX):
        return {}
    if not (cx is not None and 0.001 <= cx <= 5.0):
        return {}
    return {
        "model_enum": model_enum,
        "bullet_type_idx": bullet_type_idx,
        "speed": speed,
        "mass": mass,
        "caliber": caliber,
        "cx": cx,
    }


def read_caliber_like_window(scanner, weapon_ptr):
    items = []
    for off in range(SCAN_START, SCAN_END, SCAN_STEP):
        value = read_f32(scanner, weapon_ptr + off)
        if value is None:
            continue
        if CALIBER_MIN <= value <= CALIBER_MAX:
            items.append({
                "source": "weapon",
                "off": off,
                "addr": weapon_ptr + off,
                "value": value,
            })
    return items


def read_trailing_ptr_candidates(scanner, weapon_ptr):
    items = []
    seen = set()
    for off in range(POST_PTR_SCAN_START, POST_PTR_SCAN_END, POST_PTR_SCAN_STEP):
        ptr = read_u64(scanner, weapon_ptr + off)
        if not mul.is_valid_ptr(ptr) or ptr in seen:
            continue
        seen.add(ptr)
        for rel in range(0, REF_SCAN_BYTES, 4):
            value = read_f32(scanner, ptr + rel)
            if value is None:
                continue
            if CALIBER_MIN <= value <= CALIBER_MAX:
                items.append({
                    "source": f"ref@{hex(off)}",
                    "off": rel,
                    "root_off": off,
                    "root_ptr": ptr,
                    "addr": ptr + rel,
                    "value": value,
                })
    return items


def build_payload(scanner, base_addr):
    unit_ptr, cgame_ptr, weapon_ptr, source = current_weapon_ptr(scanner, base_addr)
    profile = read_live_profile(scanner, weapon_ptr)
    unit_profile = mul.get_unit_filter_profile(scanner, unit_ptr) if mul.is_valid_ptr(unit_ptr) else {}
    payload = {
        "pid": getattr(scanner, "pid", 0),
        "image_base": base_addr,
        "unit_ptr": unit_ptr,
        "cgame_ptr": cgame_ptr,
        "weapon_ptr": weapon_ptr,
        "weapon_source": source,
        "unit_key": unit_profile.get("unit_key", ""),
        "short_name": unit_profile.get("short_name", ""),
        "live_profile": profile,
        "caliber_candidates": (
            (read_caliber_like_window(scanner, weapon_ptr) + read_trailing_ptr_candidates(scanner, weapon_ptr))
            if (mul.is_valid_ptr(weapon_ptr) and profile) else []
        ),
    }
    return payload


def snapshot_signature(payload):
    live = payload.get("live_profile") or {}
    return (
        int(live.get("bullet_type_idx") or 0),
        round(float(live.get("speed") or 0.0), 3),
        round(float(live.get("mass") or 0.0), 4),
        round(float(live.get("caliber") or 0.0), 6),
        round(float(live.get("cx") or 0.0), 5),
    )


def analyze_candidates(snapshots):
    if not snapshots:
        return []

    by_key = defaultdict(list)
    sample_by_key = {}
    projectile_calibers = []
    for snap in snapshots:
        live = snap.get("live_profile") or {}
        projectile_calibers.append(float(live.get("caliber") or 0.0))
        for item in snap.get("caliber_candidates", []):
            key = (
                item.get("source", "weapon"),
                int(item.get("root_off", -1) if item.get("root_off") is not None else -1),
                int(item["off"]),
            )
            by_key[key].append(float(item["value"]))
            sample_by_key.setdefault(key, item)

    current_projectile = projectile_calibers[-1] if projectile_calibers else 0.0
    max_projectile = max(projectile_calibers) if projectile_calibers else 0.0
    min_projectile = min(projectile_calibers) if projectile_calibers else 0.0
    unique_projectiles = sorted({round(v, 6) for v in projectile_calibers if v > 0.0})

    suspects = []
    for key, values in sorted(by_key.items()):
        source, root_off, off = key
        if len(values) != len(snapshots):
            continue
        lo = min(values)
        hi = max(values)
        span = hi - lo
        stable = span <= STABILITY_EPS
        avg = sum(values) / len(values)
        larger_than_current = avg > (current_projectile + LARGER_THAN_PROJECTILE_EPS)
        larger_than_any = avg > (max_projectile + LARGER_THAN_PROJECTILE_EPS)
        touches_projectile_family = any(abs(avg - v) <= LARGER_THAN_PROJECTILE_EPS for v in projectile_calibers)
        score = 0
        if stable:
            score += 10
        if larger_than_current:
            score += 8
        if larger_than_any:
            score += 6
        if touches_projectile_family:
            score -= 3
        if 0.02 <= avg <= 0.18:
            score += 2
        sample_item = sample_by_key.get(key) or {}
        root_off = sample_item.get("root_off")
        root_ptr = sample_item.get("root_ptr", 0)
        is_known_projectile_field = (source == "weapon" and off in KNOWN_PROJECTILE_OFFS)
        if is_known_projectile_field:
            score -= 8
        suspects.append({
            "source": source,
            "off": off,
            "root_off": root_off,
            "root_ptr": root_ptr,
            "addr_last": snapshots[-1].get("weapon_ptr", 0) + off if snapshots[-1].get("weapon_ptr") else 0,
            "avg": avg,
            "min": lo,
            "max": hi,
            "span": span,
            "stable": stable,
            "larger_than_current_projectile": larger_than_current,
            "larger_than_all_projectiles": larger_than_any,
            "touches_projectile_family": touches_projectile_family,
            "is_known_projectile_field": is_known_projectile_field,
            "score": score,
            "values": [round(v, 6) for v in values],
            "projectile_calibers": unique_projectiles,
            "current_projectile": round(current_projectile, 6),
            "max_projectile": round(max_projectile, 6),
            "min_projectile": round(min_projectile, 6),
        })

    suspects.sort(
        key=lambda item: (
            -int(item["stable"]),
            -int(item["larger_than_all_projectiles"]),
            -int(item["larger_than_current_projectile"]),
            -item["score"],
            item["off"],
        )
    )
    return suspects


def write_dump(session):
    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"cannon_size_probe_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"cannon_size_probe_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)

    lines = [
        "CANNON SIZE PROBE",
        "=" * 80,
        f"unit_key={session.get('unit_key', '')}",
        f"short_name={session.get('short_name', '')}",
        f"snapshots={len(session.get('snapshots', []))}",
        "",
        "[Snapshots]",
    ]
    for idx, snap in enumerate(session.get("snapshots", []), 1):
        live = snap.get("live_profile") or {}
        lines.append(
            f"  [{idx}] bullet_type={live.get('bullet_type_idx')} speed={live.get('speed')} "
            f"mass={live.get('mass')} caliber={live.get('caliber')} cx={live.get('cx')} "
            f"candidates={len(snap.get('caliber_candidates', []))}"
        )
    lines.extend(["", "[Suspects]"])
    for item in session.get("suspects", [])[:24]:
        lines.append(
            f"  src={item['source']} off={hex(item['off'])} avg={item['avg']:.6f} span={item['span']:.6g} "
            f"stable={item['stable']} >current={item['larger_than_current_projectile']} "
            f">all={item['larger_than_all_projectiles']} known_proj={item['is_known_projectile_field']} score={item['score']} "
            f"values={item['values']}"
        )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def main():
    watch_mode = ("--watch" in sys.argv) or ("-w" in sys.argv)
    max_snaps = 4
    if "--max-snaps" in sys.argv:
        idx = sys.argv.index("--max-snaps")
        if idx + 1 < len(sys.argv):
            try:
                max_snaps = max(2, int(sys.argv[idx + 1]))
            except Exception:
                pass

    print("=" * 80)
    print("CANNON SIZE PROBE")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/sub/cannon_size_probe.py")
    print("  sudo venv/bin/python tools/sub/cannon_size_probe.py --watch --max-snaps 4")
    print("")

    pid = get_game_pid()
    if not pid:
        print("[-] Game process not found.")
        return 1

    scanner = MemoryScanner(pid)
    base_addr = get_game_base_address(pid)
    if not base_addr:
        print("[-] Could not resolve game base.")
        return 1

    try:
        init_dynamic_offsets(scanner, base_addr)
    except Exception:
        pass

    first = build_payload(scanner, base_addr)
    print(f"[*] PID={pid} base={hex(base_addr)} weapon={hex(first.get('weapon_ptr', 0)) if first.get('weapon_ptr') else '0x0'}")
    print(f"[*] unit_key={first.get('unit_key', '')} short_name={first.get('short_name', '')}")

    if not watch_mode:
        suspects = analyze_candidates([first])
        session = {
            "unit_key": first.get("unit_key", ""),
            "short_name": first.get("short_name", ""),
            "snapshots": [first],
            "suspects": suspects,
        }
        json_path, txt_path = write_dump(session)
        print("[*] Current projectile:", first.get("live_profile", {}))
        print("[*] Top suspects:")
        for item in suspects[:12]:
            print(
                f"  src={item['source']} off={hex(item['off'])} avg={item['avg']:.6f} "
                f"stable={item['stable']} >current={item['larger_than_current_projectile']} "
                f">all={item['larger_than_all_projectiles']} known_proj={item['is_known_projectile_field']}"
            )
        print(f"[*] json={json_path}")
        print(f"[*] txt={txt_path}")
        return 0

    print("[*] Watch mode active. สลับ ammo 2-4 แบบ แล้วรอให้ snapshot ครบ")
    seen = set()
    snapshots = []
    while len(snapshots) < max_snaps:
        payload = build_payload(scanner, base_addr)
        sig = snapshot_signature(payload)
        if not payload.get("live_profile"):
            time.sleep(WATCH_POLL_SECONDS)
            continue
        if sig not in seen:
            seen.add(sig)
            snapshots.append(payload)
            live = payload.get("live_profile", {})
            print(
                f"[snap {len(snapshots)}] bullet_type={live.get('bullet_type_idx')} "
                f"speed={live.get('speed')} mass={live.get('mass')} "
                f"caliber={live.get('caliber')} cx={live.get('cx')}"
            )
        time.sleep(WATCH_POLL_SECONDS)

    suspects = analyze_candidates(snapshots)
    session = {
        "unit_key": snapshots[-1].get("unit_key", ""),
        "short_name": snapshots[-1].get("short_name", ""),
        "snapshots": snapshots,
        "suspects": suspects,
    }
    json_path, txt_path = write_dump(session)
    print("[*] Top suspects:")
    for item in suspects[:12]:
        print(
            f"  src={item['source']} off={hex(item['off'])} avg={item['avg']:.6f} span={item['span']:.6g} "
            f"stable={item['stable']} >current={item['larger_than_current_projectile']} "
            f">all={item['larger_than_all_projectiles']} known_proj={item['is_known_projectile_field']} score={item['score']}"
        )
    print(f"[*] json={json_path}")
    print(f"[*] txt={txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
