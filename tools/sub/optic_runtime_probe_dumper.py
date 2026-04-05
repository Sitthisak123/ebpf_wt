import argparse
import json
import math
import os
import struct
import sys
import time
from datetime import datetime


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")

DIRECT_WORLD_CANDIDATES = {
    "turret_world_1e6c": 0x1E6C,
    "gun_world_2638": 0x2638,
}


def _read_vec3(scanner, addr):
    raw = scanner.read_mem(addr, 12)
    if not raw or len(raw) != 12:
        return None
    values = struct.unpack("<fff", raw)
    if not all(math.isfinite(v) for v in values):
        return None
    return values


def _round_vec(values, ndigits=4):
    return [round(float(v), ndigits) for v in values]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])


def _world_to_local(delta_world, axes):
    ax, ay, az = axes
    return (
        _dot(delta_world, ax),
        _dot(delta_world, ay),
        _dot(delta_world, az),
    )


def _calc_stats(samples):
    if not samples:
        return None
    dims = len(samples[0])
    means = []
    variances = []
    for i in range(dims):
        vals = [float(s[i]) for s in samples]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) * (v - mean) for v in vals) / len(vals)
        means.append(mean)
        variances.append(var)
    return {
        "count": len(samples),
        "mean": _round_vec(means, 6),
        "variance": _round_vec(variances, 8),
        "stddev": _round_vec([math.sqrt(max(v, 0.0)) for v in variances], 6),
    }


def _capture_once(scanner, base, cgame, my_unit):
    dna = mul.get_unit_detailed_dna(scanner, my_unit) or {}
    box = mul.get_unit_3d_box_data(scanner, my_unit, False)
    if not box:
        return None

    unit_pos, bmin, bmax, rot = box
    axes = mul.get_local_axes_from_rotation(rot, False)
    unit_dims = (
        float(bmax[0] - bmin[0]),
        float(bmax[1] - bmin[1]),
        float(bmax[2] - bmin[2]),
    )

    camera_ptr = 0
    camera_world = None
    camera_local = None
    if cgame:
        raw = scanner.read_mem(cgame + mul.OFF_CAMERA_PTR, 8)
        if raw and len(raw) == 8:
            camera_ptr = struct.unpack("<Q", raw)[0]
            if mul.is_valid_ptr(camera_ptr):
                camera_world = _read_vec3(scanner, camera_ptr + 0x58)
                if camera_world:
                    camera_local = _world_to_local(_sub(camera_world, unit_pos), axes)

    barrel = mul.get_weapon_barrel(scanner, my_unit, unit_pos, rot)
    barrel_base = barrel[0] if barrel else None
    barrel_tip = barrel[1] if barrel else None
    barrel_base_local = _world_to_local(_sub(barrel_base, unit_pos), axes) if barrel_base else None
    barrel_tip_local = _world_to_local(_sub(barrel_tip, unit_pos), axes) if barrel_tip else None

    camera_minus_barrel = None
    if camera_local and barrel_base_local:
        camera_minus_barrel = (
            camera_local[0] - barrel_base_local[0],
            camera_local[1] - barrel_base_local[1],
            camera_local[2] - barrel_base_local[2],
        )

    direct_world = {}
    for name, off in DIRECT_WORLD_CANDIDATES.items():
        vec = _read_vec3(scanner, my_unit + off)
        payload = {
            "offset": hex(off),
            "world": _round_vec(vec) if vec else None,
            "local_from_unit": _round_vec(_world_to_local(_sub(vec, unit_pos), axes)) if vec else None,
        }
        direct_world[name] = payload

    return {
        "captured_at": time.time(),
        "my_unit_ptr": hex(my_unit),
        "my_unit_key": dna.get("name_key") or "",
        "my_short_name": dna.get("short_name") or "",
        "my_family": dna.get("family") or "",
        "cgame_ptr": hex(cgame) if cgame else "0x0",
        "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
        "unit_pos": _round_vec(unit_pos),
        "unit_bbox_bmin": _round_vec(bmin),
        "unit_bbox_bmax": _round_vec(bmax),
        "unit_dims": _round_vec(unit_dims),
        "axes": {
            "forward": _round_vec(axes[0], 5),
            "up": _round_vec(axes[1], 5),
            "left": _round_vec(axes[2], 5),
        },
        "camera_world": _round_vec(camera_world) if camera_world else None,
        "camera_local": _round_vec(camera_local) if camera_local else None,
        "barrel_base_world": _round_vec(barrel_base) if barrel_base else None,
        "barrel_tip_world": _round_vec(barrel_tip) if barrel_tip else None,
        "barrel_base_local": _round_vec(barrel_base_local) if barrel_base_local else None,
        "barrel_tip_local": _round_vec(barrel_tip_local) if barrel_tip_local else None,
        "camera_minus_barrel_local": _round_vec(camera_minus_barrel) if camera_minus_barrel else None,
        "direct_world_candidates": direct_world,
    }


def _write_outputs(payload):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"optic_runtime_probe_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"optic_runtime_probe_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" OPTIC RUNTIME PROBE DUMPER")
    lines.append("==================================================")
    meta = payload["meta"]
    lines.append(f"My Unit     : {meta['my_unit_ptr']} | {meta['my_unit_key']} | {meta['my_short_name']}")
    lines.append(f"Family      : {meta['my_family']}")
    lines.append(f"CGame       : {meta['cgame_ptr']}")
    lines.append(f"Camera Ptr  : {meta['camera_ptr']}")
    lines.append(f"Samples     : {meta['sample_count']}")
    lines.append("")

    if payload.get("summary", {}).get("camera_minus_barrel_local"):
        stats = payload["summary"]["camera_minus_barrel_local"]
        lines.append(
            f"[+] Cam-Barrel Δ mean: {stats['mean']} | stddev={stats['stddev']}"
        )
        lines.append("")

    first = payload["samples"][0] if payload["samples"] else None
    if first:
        lines.append(f"Unit Pos    : {first['unit_pos']}")
        lines.append(f"Unit Dims   : {first['unit_dims']}")
        lines.append(f"CameraWorld : {first['camera_world']}")
        lines.append(f"CameraLocal : {first['camera_local']}")
        lines.append(f"BarrelBaseL : {first['barrel_base_local']}")
        lines.append(f"BarrelTipL  : {first['barrel_tip_local']}")
        lines.append(f"Cam-BarrelL : {first['camera_minus_barrel_local']}")
        lines.append("")
        lines.append("[Direct World Candidates]")
        for name, rec in first["direct_world_candidates"].items():
            lines.append(f"- {name} @ {rec['offset']}")
            lines.append(f"  world : {rec['world']}")
            lines.append(f"  local : {rec['local_from_unit']}")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return json_path, txt_path


def main():
    parser = argparse.ArgumentParser(description="Dump runtime optics/camera/gun geometry candidates for my unit.")
    parser.add_argument("--samples", type=int, default=1, help="Number of consecutive samples to capture")
    parser.add_argument("--interval-ms", type=int, default=100, help="Delay between samples in milliseconds")
    args = parser.parse_args()

    pid = get_game_pid()
    if not pid:
        print("[-] War Thunder process not found")
        return 1

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame = mul.get_cgame_base(scanner, base)
    my_unit, _ = mul.get_local_team(scanner, base)
    if not my_unit:
        print("[-] Failed to resolve my unit")
        return 1

    samples = []
    for i in range(max(args.samples, 1)):
        snap = _capture_once(scanner, base, cgame, my_unit)
        if snap:
            samples.append(snap)
        if i + 1 < args.samples:
            time.sleep(max(args.interval_ms, 0) / 1000.0)

    if not samples:
        print("[-] No usable samples captured")
        return 1

    mean_input = [
        tuple(float(v) for v in s["camera_minus_barrel_local"])
        for s in samples
        if s.get("camera_minus_barrel_local") is not None
    ]
    summary = {
        "camera_minus_barrel_local": _calc_stats(mean_input),
    }
    meta = {
        "pid": pid,
        "base_addr": hex(base),
        "cgame_ptr": hex(cgame) if cgame else "0x0",
        "my_unit_ptr": samples[0]["my_unit_ptr"],
        "my_unit_key": samples[0]["my_unit_key"],
        "my_short_name": samples[0]["my_short_name"],
        "my_family": samples[0]["my_family"],
        "camera_ptr": samples[0]["camera_ptr"],
        "sample_count": len(samples),
    }
    payload = {"meta": meta, "summary": summary, "samples": samples}

    json_path, txt_path = _write_outputs(payload)

    print("==================================================")
    print(" OPTIC RUNTIME PROBE DUMPER")
    print("==================================================")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    if summary["camera_minus_barrel_local"]:
        stats = summary["camera_minus_barrel_local"]
        print(f"[+] Cam-Barrel Δ mean: {stats['mean']} | stddev={stats['stddev']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
