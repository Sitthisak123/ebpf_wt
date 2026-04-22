import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from glob import glob


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.ammo_family import resolve_ammo_family

DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
DEFAULT_INPUT = os.path.join(DUMPS_DIR, "hitpoint_calibration_samples.jsonl")
DEFAULT_CONFIG_PATH = os.path.join(CONFIG_DIR, "vertical_baseline_table.json")


def _latest_input_path():
    deduped = sorted(glob(os.path.join(DUMPS_DIR, "hitpoint_calibration_samples.deduped_*.jsonl")))
    if deduped:
        return deduped[-1]
    return DEFAULT_INPUT


def _load_records(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                doc["_line_no"] = idx
                records.append(doc)
            except Exception:
                continue
    return records


def _ammo_bucket(rec):
    return resolve_ammo_family(rec)["bucket"]


def _x_offset(rec):
    vals = rec.get("calibration_offset") or [0.0, 0.0]
    try:
        return float(vals[0])
    except Exception:
        return 0.0


def _effective_y_offset(rec):
    if "effective_vertical_correction" in rec:
        return float(rec.get("effective_vertical_correction", 0.0) or 0.0)
    if "vertical_correction" in rec:
        return float(rec.get("vertical_correction", 0.0) or 0.0)
    vals = rec.get("calibration_offset") or [0.0, 0.0]
    try:
        return float(vals[1])
    except Exception:
        return 0.0


def _group_key(rec):
    return (
        rec.get("my_unit_key", ""),
        rec.get("target_unit_key", rec.get("unit_key", "")),
        round(float(rec.get("speed", 0.0) or 0.0), 3),
        round(float(rec.get("caliber", 0.0) or 0.0), 6),
        round(float(rec.get("camera_parallax", 0.0) or 0.0), 3),
    )


def _profile_signature(rec):
    return (
        rec.get("my_unit_key", "") or "",
        round(float(rec.get("speed", 0.0) or 0.0), 3),
        round(float(rec.get("caliber", 0.0) or 0.0), 6),
        round(float(rec.get("camera_parallax", 0.0) or 0.0), 3),
    )


def _profile_key(my_key, speed, caliber, camera_parallax):
    return (
        f"{my_key}"
        f"|speed={float(speed):.3f}"
        f"|caliber={float(caliber):.6f}"
        f"|parallax={float(camera_parallax):.3f}"
    )


def _is_duplicate(prev, cur, distance_eps, vertical_eps, x_eps, time_eps):
    prev_t = float(prev.get("captured_at", 0.0) or 0.0)
    cur_t = float(cur.get("captured_at", 0.0) or 0.0)
    if abs(cur_t - prev_t) > time_eps:
        return False

    prev_d = float(prev.get("distance", 0.0) or 0.0)
    cur_d = float(cur.get("distance", 0.0) or 0.0)
    if abs(cur_d - prev_d) > distance_eps:
        return False

    if abs(_effective_y_offset(cur) - _effective_y_offset(prev)) > vertical_eps:
        return False

    if abs(_x_offset(cur) - _x_offset(prev)) > x_eps:
        return False

    return True


def _dedupe(records, distance_eps, vertical_eps, x_eps, time_eps):
    kept = []
    dropped = []
    last_by_group = {}

    for rec in records:
        key = _group_key(rec)
        prev = last_by_group.get(key)
        if prev is not None and _is_duplicate(prev, rec, distance_eps, vertical_eps, x_eps, time_eps):
            dropped.append(rec)
            continue
        kept.append(rec)
        last_by_group[key] = rec
    return kept, dropped


def _distance_bucket(distance, step):
    step = max(float(step), 1.0)
    lo = int(distance // step) * int(step)
    hi = lo + int(step)
    return lo, hi


def _mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_table(records, distance_step, min_points):
    grouped = defaultdict(list)
    for rec in records:
        my_key = rec.get("my_unit_key", "") or ""
        if not my_key:
            continue
        bucket = _ammo_bucket(rec)
        _target_key = rec.get("target_unit_key", rec.get("unit_key", "")) or ""
        _sig_my_key, sig_speed, sig_caliber, sig_parallax = _profile_signature(rec)
        lo, _hi = _distance_bucket(float(rec.get("distance", 0.0) or 0.0), distance_step)
        grouped[(bucket, my_key, sig_speed, sig_caliber, sig_parallax, lo)].append(rec)

    bucket_rows = defaultdict(list)
    for (bucket, my_key, sig_speed, sig_caliber, sig_parallax, bucket_lo), items in grouped.items():
        avg_distance = _mean([float(r.get("distance", 0.0) or 0.0) for r in items])
        avg_vertical = _mean([_effective_y_offset(r) for r in items])
        avg_speed = _mean([float(r.get("speed", 0.0) or 0.0) for r in items])
        avg_caliber = _mean([float(r.get("caliber", 0.0) or 0.0) for r in items])
        row = {
            "distance": round(avg_distance, 3),
            "vertical": round(avg_vertical, 3),
            "count": len(items),
            "speed": round(avg_speed, 3),
            "caliber": round(avg_caliber, 6),
        }
        bucket_rows[(bucket, my_key, sig_speed, sig_caliber, sig_parallax)].append(row)

    table = {}
    summary_rows = []
    for (bucket, my_key, sig_speed, sig_caliber, sig_parallax), rows in sorted(bucket_rows.items()):
        rows = sorted(rows, key=lambda item: item["distance"])
        if len(rows) < min_points:
            continue
        curve = [[row["distance"], row["vertical"]] for row in rows]
        avg_speed = _mean([row["speed"] for row in rows])
        avg_caliber = _mean([row["caliber"] for row in rows])
        profile_key = _profile_key(my_key, sig_speed, sig_caliber, sig_parallax)
        table.setdefault(bucket, {})[profile_key] = {
            "my_unit_key": my_key,
            "speed": round(avg_speed, 3),
            "caliber": round(avg_caliber, 6),
            "camera_parallax": round(sig_parallax, 3),
            "mass": round(_mean([float(r.get("mass", 0.0) or 0.0) for r in items]), 6),
            "bullet_type_idx": int(_mean([float(r.get("bullet_type_idx", -1) or -1) for r in items])) if items else -1,
            "cannon_size": round(resolve_ammo_family(items[0]).get("cannon_size", 0.0), 6) if items else 0.0,
            "ammo_family": resolve_ammo_family(items[0]).get("family", "other") if items else "other",
            "curve": curve,
        }
        summary_rows.append({
            "ammo_bucket": bucket,
            "ammo_family": resolve_ammo_family(items[0]).get("family", "other") if items else "other",
            "my_unit_key": my_key,
            "profile_key": profile_key,
            "speed": round(avg_speed, 3),
            "caliber": round(avg_caliber, 6),
            "mass": round(_mean([float(r.get("mass", 0.0) or 0.0) for r in items]), 6),
            "bullet_type_idx": int(_mean([float(r.get("bullet_type_idx", -1) or -1) for r in items])) if items else -1,
            "camera_parallax": round(sig_parallax, 3),
            "points": len(curve),
            "curve": curve,
        })

    return table, summary_rows


def _write_outputs(input_path, kept, dropped, table, summary_rows, config_path, args):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    deduped_path = os.path.join(DUMPS_DIR, f"{base_name}.autodedup_{stamp}.jsonl")
    summary_txt = os.path.join(DUMPS_DIR, f"{base_name}.baseline_builder_{stamp}.txt")

    with open(deduped_path, "w", encoding="utf-8") as f:
        for rec in kept:
            out = {k: v for k, v in rec.items() if k != "_line_no"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    config_doc = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "hitpoint_calibration_autobuild",
        "updated_by_tool": "vertical_baseline_config_builder",
        "source_input": input_path,
        "records_kept": len(kept),
        "records_dropped": len(dropped),
        "distance_step": float(args.distance_step),
        "min_points": int(args.min_points),
        "dedupe": {
            "distance_eps": float(args.distance_eps),
            "vertical_eps": float(args.vertical_eps),
            "x_eps": float(args.x_eps),
            "time_eps": float(args.time_eps),
        },
        "table": table,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_doc, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" VERTICAL BASELINE CONFIG BUILDER")
    lines.append("==================================================")
    lines.append(f"Input        : {input_path}")
    lines.append(f"Kept         : {len(kept)}")
    lines.append(f"Dropped      : {len(dropped)}")
    lines.append(f"DistanceStep : {float(args.distance_step):.1f}")
    lines.append(f"MinPoints    : {int(args.min_points)}")
    lines.append(f"Config       : {config_path}")
    lines.append(f"Deduped      : {deduped_path}")
    lines.append("")
    lines.append("[Profiles]")
    for row in summary_rows:
        lines.append(
            f"  ammo={row['ammo_bucket']} | family={row['ammo_family']} | my={row['my_unit_key']} | "
            f"profile={row['profile_key']} | speed={row['speed']:.1f} | "
            f"caliber={row['caliber']:.6f} | mass={row['mass']:.6f} | bullet_type={row['bullet_type_idx']} | "
            f"parallax={row['camera_parallax']:.3f} | "
            f"points={row['points']} | curve={row['curve']}"
        )
    lines.append("")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return deduped_path, summary_txt


def main():
    parser = argparse.ArgumentParser(description="Auto-dedupe hitpoint samples and build vertical baseline config JSON.")
    parser.add_argument("--input", default=_latest_input_path())
    parser.add_argument("--output", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--distance-step", type=float, default=200.0)
    parser.add_argument("--min-points", type=int, default=2)
    parser.add_argument("--distance-eps", type=float, default=3.0)
    parser.add_argument("--vertical-eps", type=float, default=0.3)
    parser.add_argument("--x-eps", type=float, default=0.3)
    parser.add_argument("--time-eps", type=float, default=8.0)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[-] Missing input: {args.input}")
        return 1

    records = _load_records(args.input)
    kept, dropped = _dedupe(
        records,
        distance_eps=float(args.distance_eps),
        vertical_eps=float(args.vertical_eps),
        x_eps=float(args.x_eps),
        time_eps=float(args.time_eps),
    )
    table, summary_rows = _build_table(
        kept,
        distance_step=float(args.distance_step),
        min_points=int(args.min_points),
    )
    deduped_path, summary_txt = _write_outputs(
        args.input,
        kept,
        dropped,
        table,
        summary_rows,
        args.output,
        args,
    )

    profile_count = sum(len(bucket) for bucket in table.values())
    print("==================================================")
    print(" VERTICAL BASELINE CONFIG BUILDER")
    print("==================================================")
    print(f"[+] Input   : {args.input}")
    print(f"[+] Kept    : {len(kept)}")
    print(f"[+] Dropped : {len(dropped)}")
    print(f"[+] Profiles: {profile_count}")
    print(f"[+] Config  : {args.output}")
    print(f"[+] Deduped : {deduped_path}")
    print(f"[+] TEXT    : {summary_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
