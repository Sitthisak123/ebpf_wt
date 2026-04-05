import argparse
import json
import os
from collections import defaultdict
from datetime import datetime


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")
DEFAULT_INPUT = os.path.join(DUMPS_DIR, "hitpoint_calibration_samples.jsonl")


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


def _group_key(rec):
    return (
        rec.get("my_unit_key", ""),
        rec.get("target_unit_key", rec.get("unit_key", "")),
        round(float(rec.get("speed", 0.0) or 0.0), 3),
        round(float(rec.get("caliber", 0.0) or 0.0), 6),
        round(float(rec.get("camera_parallax", 0.0) or 0.0), 3),
    )


def _x_offset(rec):
    offsets = rec.get("calibration_offset") or [0.0, 0.0]
    try:
        return float(offsets[0])
    except Exception:
        return 0.0


def _y_offset(rec):
    if "vertical_correction" in rec:
        return float(rec.get("vertical_correction", 0.0) or 0.0)
    offsets = rec.get("calibration_offset") or [0.0, 0.0]
    try:
        return float(offsets[1])
    except Exception:
        return 0.0


def _is_duplicate(prev, cur, distance_eps, vertical_eps, x_eps, time_eps):
    prev_t = float(prev.get("captured_at", 0.0) or 0.0)
    cur_t = float(cur.get("captured_at", 0.0) or 0.0)
    if abs(cur_t - prev_t) > time_eps:
        return False

    prev_d = float(prev.get("distance", 0.0) or 0.0)
    cur_d = float(cur.get("distance", 0.0) or 0.0)
    if abs(cur_d - prev_d) > distance_eps:
        return False

    if abs(_y_offset(cur) - _y_offset(prev)) > vertical_eps:
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


def _write_outputs(input_path, kept, dropped):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    clean_jsonl = os.path.join(DUMPS_DIR, f"{base_name}.deduped_{stamp}.jsonl")
    summary_txt = os.path.join(DUMPS_DIR, f"{base_name}.dedupe_summary_{stamp}.txt")

    with open(clean_jsonl, "w", encoding="utf-8") as f:
        for rec in kept:
            out = {k: v for k, v in rec.items() if k != "_line_no"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    grouped = defaultdict(list)
    for rec in kept:
        grouped[_group_key(rec)].append(rec)

    lines = []
    lines.append("==================================================")
    lines.append(" HITPOINT CALIBRATION DEDUPE")
    lines.append("==================================================")
    lines.append(f"Input   : {input_path}")
    lines.append(f"Kept    : {len(kept)}")
    lines.append(f"Dropped : {len(dropped)}")
    lines.append(f"Output  : {clean_jsonl}")
    lines.append("")

    lines.append("[Dropped Duplicates]")
    for rec in dropped[:200]:
        lines.append(
            f"  line={rec.get('_line_no')} | my={rec.get('my_unit_key','')} | "
            f"target={rec.get('target_unit_key', rec.get('unit_key',''))} | "
            f"dist={float(rec.get('distance',0.0) or 0.0):.3f} | "
            f"x={_x_offset(rec):.3f} | y={_y_offset(rec):.3f} | "
            f"spd={float(rec.get('speed',0.0) or 0.0):.1f} | cal={float(rec.get('caliber',0.0) or 0.0):.6f}"
        )
    lines.append("")

    lines.append("[Kept Groups]")
    for key, items in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3])):
        my_key, target_key, speed, caliber, parallax = key
        lines.append(
            f"  my={my_key} | target={target_key} | speed={speed:.1f} | caliber={caliber:.6f} | "
            f"parallax={parallax:.3f} | count={len(items)}"
        )
    lines.append("")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return clean_jsonl, summary_txt


def main():
    parser = argparse.ArgumentParser(description="Dedupe repeated hitpoint calibration samples.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--distance-eps", type=float, default=5.0)
    parser.add_argument("--vertical-eps", type=float, default=0.5)
    parser.add_argument("--x-eps", type=float, default=0.5)
    parser.add_argument("--time-eps", type=float, default=10.0)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[-] Missing input: {args.input}")
        return 1

    os.makedirs(DUMPS_DIR, exist_ok=True)
    records = _load_records(args.input)
    kept, dropped = _dedupe(
        records,
        distance_eps=float(args.distance_eps),
        vertical_eps=float(args.vertical_eps),
        x_eps=float(args.x_eps),
        time_eps=float(args.time_eps),
    )
    clean_jsonl, summary_txt = _write_outputs(args.input, kept, dropped)

    print("==================================================")
    print(" HITPOINT CALIBRATION DEDUPE")
    print("==================================================")
    print(f"[+] Input  : {args.input}")
    print(f"[+] Kept   : {len(kept)}")
    print(f"[+] Dropped: {len(dropped)}")
    print(f"[+] JSONL  : {clean_jsonl}")
    print(f"[+] TEXT   : {summary_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
