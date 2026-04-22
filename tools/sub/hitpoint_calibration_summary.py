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


def _latest_deduped_path():
    paths = sorted(glob(os.path.join(DUMPS_DIR, "hitpoint_calibration_samples.deduped_*.jsonl")))
    return paths[-1] if paths else os.path.join(DUMPS_DIR, "hitpoint_calibration_samples.jsonl")


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


def _x_offset(rec):
    vals = rec.get("calibration_offset") or [0.0, 0.0]
    try:
        return float(vals[0])
    except Exception:
        return 0.0


def _y_offset(rec):
    if "vertical_correction" in rec:
        return float(rec.get("vertical_correction", 0.0) or 0.0)
    vals = rec.get("calibration_offset") or [0.0, 0.0]
    try:
        return float(vals[1])
    except Exception:
        return 0.0


def _distance_bucket(distance, step):
    step = max(float(step), 1.0)
    lo = int(distance // step) * int(step)
    hi = lo + int(step)
    return f"{lo:04d}-{hi:04d}m"


def _ammo_bucket(rec):
    return resolve_ammo_family(rec)["bucket"]


def _mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_group_summaries(records, distance_step):
    by_bucket = defaultdict(list)
    by_target = defaultdict(list)
    by_ammo = defaultdict(list)

    for rec in records:
        my_key = rec.get("my_unit_key", "")
        target_key = rec.get("target_unit_key", rec.get("unit_key", ""))
        ammo_bucket = _ammo_bucket(rec)
        distance = float(rec.get("distance", 0.0) or 0.0)
        dist_bucket = _distance_bucket(distance, distance_step)

        by_bucket[(my_key, ammo_bucket, dist_bucket)].append(rec)
        by_target[(my_key, ammo_bucket, target_key)].append(rec)
        by_ammo[(my_key, ammo_bucket)].append(rec)

    return by_bucket, by_target, by_ammo


def _summary_payload(records, distance_step):
    by_bucket, by_target, by_ammo = _build_group_summaries(records, distance_step)

    bucket_rows = []
    for key, items in sorted(by_bucket.items()):
        my_key, ammo_bucket, dist_bucket = key
        bucket_rows.append({
            "my_unit_key": my_key,
            "ammo_bucket": ammo_bucket,
            "distance_bucket": dist_bucket,
            "count": len(items),
            "avg_vertical_correction": round(_mean([_y_offset(r) for r in items]), 4),
            "avg_weakspot_x": round(_mean([_x_offset(r) for r in items]), 4),
            "avg_distance": round(_mean([float(r.get("distance", 0.0) or 0.0) for r in items]), 3),
            "targets": sorted({r.get("target_unit_key", r.get("unit_key", "")) for r in items}),
        })

    target_rows = []
    for key, items in sorted(by_target.items()):
        my_key, ammo_bucket, target_key = key
        target_rows.append({
            "my_unit_key": my_key,
            "ammo_bucket": ammo_bucket,
            "target_unit_key": target_key,
            "count": len(items),
            "avg_vertical_correction": round(_mean([_y_offset(r) for r in items]), 4),
            "avg_weakspot_x": round(_mean([_x_offset(r) for r in items]), 4),
            "avg_distance": round(_mean([float(r.get("distance", 0.0) or 0.0) for r in items]), 3),
        })

    ammo_rows = []
    for key, items in sorted(by_ammo.items()):
        my_key, ammo_bucket = key
        ammo_rows.append({
            "my_unit_key": my_key,
            "ammo_bucket": ammo_bucket,
            "count": len(items),
            "avg_vertical_correction": round(_mean([_y_offset(r) for r in items]), 4),
            "avg_weakspot_x": round(_mean([_x_offset(r) for r in items]), 4),
            "avg_distance": round(_mean([float(r.get("distance", 0.0) or 0.0) for r in items]), 3),
        })

    return {
        "records_total": len(records),
        "distance_step": distance_step,
        "by_distance_bucket": bucket_rows,
        "by_target": target_rows,
        "by_ammo": ammo_rows,
    }


def _write_outputs(input_path, payload):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    json_path = os.path.join(DUMPS_DIR, f"{base_name}.summary_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"{base_name}.summary_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" HITPOINT CALIBRATION SUMMARY")
    lines.append("==================================================")
    lines.append(f"Input         : {input_path}")
    lines.append(f"Records       : {payload['records_total']}")
    lines.append(f"Distance Step : {payload['distance_step']} m")
    lines.append("")

    lines.append("[By Ammo]")
    for row in payload["by_ammo"]:
        lines.append(
            f"  my={row['my_unit_key']} | ammo={row['ammo_bucket']} | count={row['count']} | "
            f"avgY={row['avg_vertical_correction']:.3f} | avgX={row['avg_weakspot_x']:.3f} | "
            f"avgDist={row['avg_distance']:.1f}"
        )
    lines.append("")

    lines.append("[By Distance Bucket]")
    for row in payload["by_distance_bucket"]:
        lines.append(
            f"  my={row['my_unit_key']} | ammo={row['ammo_bucket']} | dist={row['distance_bucket']} | "
            f"count={row['count']} | avgY={row['avg_vertical_correction']:.3f} | "
            f"avgX={row['avg_weakspot_x']:.3f} | targets={','.join(row['targets'])}"
        )
    lines.append("")

    lines.append("[By Target]")
    for row in payload["by_target"]:
        lines.append(
            f"  my={row['my_unit_key']} | ammo={row['ammo_bucket']} | target={row['target_unit_key']} | "
            f"count={row['count']} | avgY={row['avg_vertical_correction']:.3f} | "
            f"avgX={row['avg_weakspot_x']:.3f} | avgDist={row['avg_distance']:.1f}"
        )
    lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, txt_path


def main():
    parser = argparse.ArgumentParser(description="Summarize hitpoint calibration samples.")
    parser.add_argument("--input", default=_latest_deduped_path())
    parser.add_argument("--distance-step", type=float, default=200.0)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[-] Missing input: {args.input}")
        return 1

    records = _load_records(args.input)
    payload = _summary_payload(records, float(args.distance_step))
    json_path, txt_path = _write_outputs(args.input, payload)

    print("==================================================")
    print(" HITPOINT CALIBRATION SUMMARY")
    print("==================================================")
    print(f"[+] Input : {args.input}")
    print(f"[+] Count : {payload['records_total']}")
    print(f"[+] JSON  : {json_path}")
    print(f"[+] TEXT  : {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
