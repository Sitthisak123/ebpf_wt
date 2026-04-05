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


DM_CHAINS = [
    {"name": "unit_1070_58_a0", "root": 0x1070, "mid": 0x58, "list": 0xA0, "count": 0xB0},
    {"name": "unit_1048_58_a0", "root": 0x1048, "mid": 0x58, "list": 0xA0, "count": 0xB0},
]

DM_STRUCT_SIZE = 208
DM_NAME_OFF = 0xC0
DM_POS_OFF = 0x34
DM_BBMIN_OFF = 0x40
DM_BBMAX_OFF = 0x4C

SIGHT_HINTS = ("optic", "sight", "camera", "gunner", "periscope", "scope")
BARREL_HINTS = ("barrel", "gun", "cannon", "muzzle")
BAD_HINTS = ("mg", "machine", "smoke", "fuel", "water", "track", "wheel", "suspension", "root")


def _read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) != 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) != 4:
        return 0
    return struct.unpack("<I", raw)[0]


def _read_vec3(scanner, addr):
    raw = scanner.read_mem(addr, 12)
    if not raw or len(raw) != 12:
        return None
    vals = struct.unpack("<fff", raw)
    if not all(math.isfinite(v) for v in vals):
        return None
    return vals


def _read_cstr(scanner, ptr, max_len=128):
    if not mul.is_valid_ptr(ptr):
        return ""
    raw = scanner.read_mem(ptr, max_len)
    if not raw:
        return ""
    end = raw.find(b"\x00")
    if end >= 0:
        raw = raw[:end]
    try:
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _round_vec(values, ndigits=4):
    return [round(float(v), ndigits) for v in values]


def _dot(a, b):
    return (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _local_to_world(unit_pos, axes, local_pos):
    ax, ay, az = axes
    return _add(
        unit_pos,
        _add(_mul(ax, local_pos[0]), _add(_mul(ay, local_pos[1]), _mul(az, local_pos[2]))),
    )


def _world_to_local(delta_world, axes):
    ax, ay, az = axes
    return (
        _dot(delta_world, ax),
        _dot(delta_world, ay),
        _dot(delta_world, az),
    )


def _name_score(name, hints):
    lower = name.lower()
    if not lower:
        return -1000
    if any(bad in lower for bad in BAD_HINTS):
        return -100
    score = 0
    for hint in hints:
        if hint in lower:
            score += 10
    return score


def _calc_mean_variance(samples):
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


def _build_suggested_parallax(sample_summary, unit_height):
    if not sample_summary:
        return None
    mean = sample_summary.get("mean") or []
    stddev = sample_summary.get("stddev") or []
    if len(mean) < 2 or len(stddev) < 2:
        return None
    delta_up_m = float(mean[1])
    up_stddev_m = float(stddev[1])
    pct_of_own_height = (delta_up_m / max(float(unit_height), 1e-6)) * 100.0
    return {
        "delta_up_m": round(delta_up_m, 6),
        "delta_up_stddev_m": round(up_stddev_m, 6),
        "own_height_m": round(float(unit_height), 6),
        "suggested_camera_parallax_pct": round(pct_of_own_height, 3),
        "sign": "negative" if pct_of_own_height < 0 else "positive",
        "stable_enough_for_hint": bool(up_stddev_m <= 0.05),
    }


def _iter_damage_model_entries(scanner, unit_ptr):
    results = []
    for chain in DM_CHAINS:
        root_ptr = _read_ptr(scanner, unit_ptr + chain["root"])
        mid_ptr = _read_ptr(scanner, root_ptr + chain["mid"]) if mul.is_valid_ptr(root_ptr) else 0
        list_ptr = _read_ptr(scanner, mid_ptr + chain["list"]) if mul.is_valid_ptr(mid_ptr) else 0
        count = _read_u32(scanner, mid_ptr + chain["count"]) if mul.is_valid_ptr(mid_ptr) else 0

        chain_payload = {
            "chain": chain["name"],
            "root_ptr": hex(root_ptr) if root_ptr else "0x0",
            "mid_ptr": hex(mid_ptr) if mid_ptr else "0x0",
            "list_ptr": hex(list_ptr) if list_ptr else "0x0",
            "count": int(count),
            "entries": [],
        }

        if not (mul.is_valid_ptr(list_ptr) and 0 < count <= 512):
            results.append(chain_payload)
            continue

        for idx in range(count):
            entry_addr = list_ptr + (idx * DM_STRUCT_SIZE)
            name_ptr = _read_ptr(scanner, entry_addr + DM_NAME_OFF)
            name = _read_cstr(scanner, name_ptr, 128)
            pos = _read_vec3(scanner, entry_addr + DM_POS_OFF)
            bbmin = _read_vec3(scanner, entry_addr + DM_BBMIN_OFF)
            bbmax = _read_vec3(scanner, entry_addr + DM_BBMAX_OFF)
            if not name and not pos:
                continue
            chain_payload["entries"].append(
                {
                    "index": idx,
                    "entry_addr": hex(entry_addr),
                    "name": name,
                    "local_pos": _round_vec(pos) if pos else None,
                    "bbmin": _round_vec(bbmin) if bbmin else None,
                    "bbmax": _round_vec(bbmax) if bbmax else None,
                }
            )
        results.append(chain_payload)
    return results


def _choose_best_entries(all_chains):
    entries = []
    for chain in all_chains:
        for entry in chain.get("entries", []):
            if entry.get("local_pos") is None:
                continue
            entries.append(entry)

    sight_candidates = []
    barrel_candidates = []
    for entry in entries:
        name = entry.get("name", "")
        sight_score = _name_score(name, SIGHT_HINTS)
        barrel_score = _name_score(name, BARREL_HINTS)
        if sight_score > 0:
            sight_candidates.append((sight_score, entry))
        if barrel_score > 0:
            barrel_candidates.append((barrel_score, entry))

    sight_candidates.sort(key=lambda x: (-x[0], x[1].get("name", "")))
    barrel_candidates.sort(key=lambda x: (-x[0], x[1].get("name", "")))
    return (
        sight_candidates[0][1] if sight_candidates else None,
        barrel_candidates[0][1] if barrel_candidates else None,
        sight_candidates[:10],
        barrel_candidates[:10],
    )


def _capture_snapshot(scanner, base, cgame, my_unit):
    my_box = mul.get_unit_3d_box_data(scanner, my_unit, False)
    if not my_box:
        return None

    unit_pos, bmin, bmax, rot = my_box
    axes = mul.get_local_axes_from_rotation(rot, False)
    unit_height = float(bmax[1] - bmin[1])

    barrel = mul.get_weapon_barrel(scanner, my_unit, unit_pos, rot)
    barrel_base = barrel[0] if barrel else None
    barrel_tip = barrel[1] if barrel else None
    barrel_base_local = _world_to_local(_sub(barrel_base, unit_pos), axes) if barrel_base else None
    barrel_tip_local = _world_to_local(_sub(barrel_tip, unit_pos), axes) if barrel_tip else None

    camera_payload = {}
    camera_local = None
    if cgame:
        camera_ptr = _read_ptr(scanner, cgame + mul.OFF_CAMERA_PTR)
        camera_pos = _read_vec3(scanner, camera_ptr + 0x58) if mul.is_valid_ptr(camera_ptr) else None
        if camera_pos:
            camera_local = _world_to_local(_sub(camera_pos, unit_pos), axes)
        camera_payload = {
            "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
            "camera_world": _round_vec(camera_pos) if camera_pos else None,
            "camera_from_unit_local": _round_vec(camera_local) if camera_local else None,
        }

    dm_chains = _iter_damage_model_entries(scanner, my_unit)
    best_sight, best_barrel_dm, top_sight, top_barrel = _choose_best_entries(dm_chains)

    parallax_estimate = {}
    if best_sight and barrel_base_local:
        sight_local = tuple(float(v) for v in best_sight["local_pos"])
        delta_local = (
            sight_local[0] - barrel_base_local[0],
            sight_local[1] - barrel_base_local[1],
            sight_local[2] - barrel_base_local[2],
        )
        parallax_estimate = {
            "sight_name": best_sight.get("name", ""),
            "sight_local": _round_vec(sight_local),
            "barrel_base_local": _round_vec(barrel_base_local),
            "delta_local_front_up_left": _round_vec(delta_local),
            "signed_vertical_m": round(delta_local[1], 4),
            "signed_vertical_pct_of_own_height": round((delta_local[1] / max(unit_height, 1e-6)) * 100.0, 3),
            "signed_lateral_m": round(delta_local[2], 4),
            "signed_forward_m": round(delta_local[0], 4),
        }

    camera_minus_barrel_local = None
    if camera_local and barrel_base_local:
        camera_minus_barrel_local = (
            camera_local[0] - barrel_base_local[0],
            camera_local[1] - barrel_base_local[1],
            camera_local[2] - barrel_base_local[2],
        )

    return {
        "unit_pos": unit_pos,
        "bmin": bmin,
        "bmax": bmax,
        "rot": rot,
        "axes": axes,
        "unit_height": unit_height,
        "barrel_base": barrel_base,
        "barrel_tip": barrel_tip,
        "barrel_base_local": barrel_base_local,
        "barrel_tip_local": barrel_tip_local,
        "camera_payload": camera_payload,
        "camera_local": camera_local,
        "camera_minus_barrel_local": camera_minus_barrel_local,
        "dm_chains": dm_chains,
        "best_sight": best_sight,
        "best_barrel_dm": best_barrel_dm,
        "top_sight": top_sight,
        "top_barrel": top_barrel,
        "parallax_estimate": parallax_estimate,
    }


def main():
    parser = argparse.ArgumentParser(description="Probe local camera/barrel geometry for camera parallax estimation.")
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

    snapshot = _capture_snapshot(scanner, base, cgame, my_unit)
    if not snapshot:
        print("[-] Failed to capture probe snapshot")
        return 1

    unit_pos = snapshot["unit_pos"]
    bmin = snapshot["bmin"]
    bmax = snapshot["bmax"]
    axes = snapshot["axes"]
    barrel_base = snapshot["barrel_base"]
    barrel_tip = snapshot["barrel_tip"]
    barrel_base_local = snapshot["barrel_base_local"]
    barrel_tip_local = snapshot["barrel_tip_local"]
    camera_payload = snapshot["camera_payload"]
    dm_chains = snapshot["dm_chains"]
    best_sight = snapshot["best_sight"]
    best_barrel_dm = snapshot["best_barrel_dm"]
    top_sight = snapshot["top_sight"]
    top_barrel = snapshot["top_barrel"]
    parallax_estimate = snapshot["parallax_estimate"]

    sample_records = []
    delta_samples = []
    if args.samples > 1:
        for idx in range(args.samples):
            snap = _capture_snapshot(scanner, base, cgame, my_unit)
            if snap:
                sample_rec = {
                    "index": idx,
                    "camera_local": _round_vec(snap["camera_local"]) if snap["camera_local"] else None,
                    "barrel_base_local": _round_vec(snap["barrel_base_local"]) if snap["barrel_base_local"] else None,
                    "camera_minus_barrel_local": _round_vec(snap["camera_minus_barrel_local"]) if snap["camera_minus_barrel_local"] else None,
                }
                sample_records.append(sample_rec)
                if snap["camera_minus_barrel_local"]:
                    delta_samples.append(snap["camera_minus_barrel_local"])
            if idx + 1 < args.samples and args.interval_ms > 0:
                time.sleep(args.interval_ms / 1000.0)

    sample_summary = _calc_mean_variance(delta_samples)
    suggested_parallax = _build_suggested_parallax(sample_summary, snapshot["unit_height"])

    payload = {
        "meta": {
            "pid": pid,
            "base_addr": hex(base),
            "cgame_ptr": hex(cgame) if cgame else "0x0",
            "my_unit_ptr": hex(my_unit),
            "camera_off": hex(mul.OFF_CAMERA_PTR),
            "view_matrix_off": hex(mul.OFF_VIEW_MATRIX),
            "unit_bbox_offs": {"bbmin": hex(mul.OFF_UNIT_BBMIN), "bbmax": hex(mul.OFF_UNIT_BBMAX)},
            "unit_rot_off": hex(mul.OFF_UNIT_ROTATION),
            "samples_requested": int(args.samples),
            "interval_ms": int(args.interval_ms),
        },
        "my_unit": {
            "short_name": (mul.get_unit_detailed_dna(scanner, my_unit) or {}).get("short_name", "Unknown"),
            "world_pos": _round_vec(unit_pos),
            "bbox": {
                "bmin": _round_vec(bmin),
                "bmax": _round_vec(bmax),
                "dims": _round_vec((bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2])),
            },
            "axes_front_up_left": {
                "front": _round_vec(axes[0]),
                "up": _round_vec(axes[1]),
                "left": _round_vec(axes[2]),
            },
        },
        "active_camera": camera_payload,
        "barrel": {
            "base_world": _round_vec(barrel_base) if barrel_base else None,
            "tip_world": _round_vec(barrel_tip) if barrel_tip else None,
            "base_local": _round_vec(barrel_base_local) if barrel_base_local else None,
            "tip_local": _round_vec(barrel_tip_local) if barrel_tip_local else None,
        },
        "damage_model_probe": {
            "chains": dm_chains,
            "best_sight_candidate": best_sight,
            "best_barrel_candidate": best_barrel_dm,
            "top_sight_candidates": [{"score": score, "name": entry.get("name", ""), "local_pos": entry.get("local_pos")} for score, entry in top_sight],
            "top_barrel_candidates": [{"score": score, "name": entry.get("name", ""), "local_pos": entry.get("local_pos")} for score, entry in top_barrel],
        },
        "parallax_estimate": parallax_estimate,
        "camera_minus_barrel_probe": {
            "current_local_delta_front_up_left": _round_vec(snapshot["camera_minus_barrel_local"]) if snapshot["camera_minus_barrel_local"] else None,
            "samples": sample_records,
            "summary": sample_summary,
        },
        "suggested_parallax": suggested_parallax,
    }

    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"camera_parallax_probe_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"camera_parallax_probe_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" CAMERA PARALLAX PROBE DUMPER")
    lines.append("==================================================")
    lines.append(f"My Unit        : {payload['meta']['my_unit_ptr']}")
    lines.append(f"CGame          : {payload['meta']['cgame_ptr']}")
    lines.append(f"Camera Off     : {payload['meta']['camera_off']} | ViewMatrix Off: {payload['meta']['view_matrix_off']}")
    lines.append(f"Unit           : {payload['my_unit']['short_name']}")
    lines.append(f"World Pos      : {payload['my_unit']['world_pos']}")
    lines.append(f"BBox Dims      : {payload['my_unit']['bbox']['dims']}")
    lines.append(f"Camera World   : {payload['active_camera'].get('camera_world')}")
    lines.append(f"Camera Local   : {payload['active_camera'].get('camera_from_unit_local')}")
    lines.append(f"Barrel Base    : {payload['barrel']['base_local']}")
    lines.append(f"Barrel Tip     : {payload['barrel']['tip_local']}")
    lines.append(f"Cam-Barrel Δ   : {payload['camera_minus_barrel_probe'].get('current_local_delta_front_up_left')}")
    lines.append("")
    lines.append("[Best Damage Model Candidates]")
    lines.append(f"  Sight  : {payload['damage_model_probe']['best_sight_candidate']}")
    lines.append(f"  Barrel : {payload['damage_model_probe']['best_barrel_candidate']}")
    lines.append("")
    lines.append("[Parallax Estimate]")
    if parallax_estimate:
        lines.append(f"  sight_name           : {parallax_estimate.get('sight_name')}")
        lines.append(f"  sight_local          : {parallax_estimate.get('sight_local')}")
        lines.append(f"  barrel_base_local    : {parallax_estimate.get('barrel_base_local')}")
        lines.append(f"  delta(front,up,left) : {parallax_estimate.get('delta_local_front_up_left')}")
        lines.append(f"  vertical_m           : {parallax_estimate.get('signed_vertical_m')}")
        lines.append(f"  vertical_pct_height  : {parallax_estimate.get('signed_vertical_pct_of_own_height')}")
        lines.append(f"  lateral_m            : {parallax_estimate.get('signed_lateral_m')}")
        lines.append(f"  forward_m            : {parallax_estimate.get('signed_forward_m')}")
    else:
        lines.append("  No usable sight/barrel pair found")
    lines.append("")
    lines.append("[Camera Minus Barrel Probe]")
    if sample_summary:
        lines.append(f"  samples              : {sample_summary.get('count')}")
        lines.append(f"  mean(front,up,left)  : {sample_summary.get('mean')}")
        lines.append(f"  variance             : {sample_summary.get('variance')}")
        lines.append(f"  stddev               : {sample_summary.get('stddev')}")
    else:
        lines.append("  No multi-sample summary")
    for rec in sample_records:
        lines.append(
            f"  sample[{rec['index']:02d}] cam={rec.get('camera_local')} | "
            f"barrel={rec.get('barrel_base_local')} | delta={rec.get('camera_minus_barrel_local')}"
        )
    lines.append("")
    lines.append("[Suggested Camera Parallax]")
    if suggested_parallax:
        lines.append(f"  delta_up_m                   : {suggested_parallax.get('delta_up_m')}")
        lines.append(f"  delta_up_stddev_m            : {suggested_parallax.get('delta_up_stddev_m')}")
        lines.append(f"  own_height_m                 : {suggested_parallax.get('own_height_m')}")
        lines.append(f"  suggested_camera_parallax_pct: {suggested_parallax.get('suggested_camera_parallax_pct')}")
        lines.append(f"  sign                         : {suggested_parallax.get('sign')}")
        lines.append(f"  stable_enough_for_hint       : {suggested_parallax.get('stable_enough_for_hint')}")
    else:
        lines.append("  No suggested parallax")
    lines.append("")

    for chain in dm_chains:
        lines.append(f"[Chain] {chain['chain']} | root={chain['root_ptr']} | mid={chain['mid_ptr']} | list={chain['list_ptr']} | count={chain['count']}")
        for entry in chain.get("entries", [])[:80]:
            lines.append(
                f"  idx={entry['index']:03d} | name={entry.get('name', '')} | "
                f"local_pos={entry.get('local_pos')} | bbmin={entry.get('bbmin')} | bbmax={entry.get('bbmax')}"
            )
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("==================================================")
    print(" CAMERA PARALLAX PROBE DUMPER")
    print("==================================================")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    if sample_summary:
        print(
            "[+] Cam-Barrel Δ mean: "
            f"{sample_summary.get('mean')} | stddev={sample_summary.get('stddev')}"
        )
    if suggested_parallax:
        print(
            "[+] Suggested camera_parallax: "
            f"{suggested_parallax.get('suggested_camera_parallax_pct')} "
            f"(sign={suggested_parallax.get('sign')} | stable={suggested_parallax.get('stable_enough_for_hint')})"
        )
    if parallax_estimate:
        print(
            "[+] Estimate: "
            f"sight={parallax_estimate.get('sight_name')} | "
            f"vertical_m={parallax_estimate.get('signed_vertical_m')} | "
            f"vertical_pct_height={parallax_estimate.get('signed_vertical_pct_of_own_height')}"
        )
    else:
        print("[!] No usable sight/barrel estimate found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
