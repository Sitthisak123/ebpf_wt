import json
import math
import os
import sys
from datetime import datetime


SAMPLES_PATH = os.path.join("dumps", "hitpoint_calibration_samples.jsonl")
OUT_JSON = os.path.join("dumps", "hitpoint_correction_fit.json")
OUT_TXT = os.path.join("dumps", "hitpoint_correction_fit.txt")

# Filter obvious manual-test outliers before fitting.
MAX_ABS_X_OFFSET = 5.0
MAX_ABS_Y_OFFSET = 20.0
TARGET_MODEL_ENUM = 0
MIN_SUBCAL_SPEED = 1200.0
MAX_SUBCAL_CALIBER = 0.05


def load_samples(path):
    samples = []
    if not os.path.exists(path):
        return samples
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except Exception:
                continue
    return samples


def is_candidate(sample):
    try:
        if int(sample.get("model_enum", -1)) != TARGET_MODEL_ENUM:
            return False
        speed = float(sample.get("speed") or 0.0)
        caliber = float(sample.get("caliber") or 0.0)
        off_x = float((sample.get("calibration_offset") or [0.0, 0.0])[0])
        off_y = float((sample.get("calibration_offset") or [0.0, 0.0])[1])
    except Exception:
        return False
    if speed < MIN_SUBCAL_SPEED:
        return False
    if caliber <= 0.0 or caliber > MAX_SUBCAL_CALIBER:
        return False
    if abs(off_x) > MAX_ABS_X_OFFSET:
        return False
    if abs(off_y) > MAX_ABS_Y_OFFSET:
        return False
    return True


def feature_row(sample):
    speed = float(sample.get("speed") or 0.0)
    distance = float(sample.get("distance") or 0.0)
    caliber = float(sample.get("caliber") or 0.0)
    speed_delta = max(0.0, speed - 1500.0) / 100.0
    distance_km = distance / 1000.0
    caliber_delta = max(0.0, caliber - 0.016) / 0.001
    # y offset is usually negative when predicted hitpoint is too low; fit magnitude upward.
    y_up = -float((sample.get("calibration_offset") or [0.0, 0.0])[1])
    return [1.0, distance_km, speed_delta, distance_km * speed_delta, caliber_delta], y_up


def solve_linear_system(matrix, vector):
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return [0.0] * n
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
        pivot_val = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= pivot_val
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if abs(factor) < 1e-12:
                continue
            for j in range(col, n + 1):
                a[row][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def fit_least_squares(rows, ys):
    if not rows:
        return [0.0] * 5
    k = len(rows[0])
    xtx = [[0.0 for _ in range(k)] for _ in range(k)]
    xty = [0.0 for _ in range(k)]
    for row, y in zip(rows, ys):
        for i in range(k):
            xty[i] += row[i] * y
            for j in range(k):
                xtx[i][j] += row[i] * row[j]
    return solve_linear_system(xtx, xty)


def predict(coeffs, row):
    return sum(c * x for c, x in zip(coeffs, row))


def group_summary(samples):
    groups = {}
    for s in samples:
        speed = round(float(s.get("speed") or 0.0))
        key = str(int(speed))
        entry = groups.setdefault(key, {"count": 0, "avg_y_up": 0.0, "avg_dist": 0.0})
        y_up = -float((s.get("calibration_offset") or [0.0, 0.0])[1])
        dist = float(s.get("distance") or 0.0)
        entry["count"] += 1
        entry["avg_y_up"] += y_up
        entry["avg_dist"] += dist
    for entry in groups.values():
        if entry["count"] > 0:
            entry["avg_y_up"] /= entry["count"]
            entry["avg_dist"] /= entry["count"]
    return groups


def main():
    print("=" * 80)
    print("HITPOINT CORRECTION FIT")
    print("=" * 80)
    print(f"Samples: {SAMPLES_PATH}")
    print("-" * 80)

    raw_samples = load_samples(SAMPLES_PATH)
    filtered = [s for s in raw_samples if is_candidate(s)]
    rows = []
    ys = []
    for sample in filtered:
        row, y = feature_row(sample)
        rows.append(row)
        ys.append(y)

    coeffs = fit_least_squares(rows, ys)
    preds = [predict(coeffs, row) for row in rows]
    mae = (sum(abs(p - y) for p, y in zip(preds, ys)) / len(ys)) if ys else 0.0
    rmse = math.sqrt(sum((p - y) ** 2 for p, y in zip(preds, ys)) / len(ys)) if ys else 0.0

    payload = {
        "generated_at": datetime.now().isoformat(),
        "samples_total": len(raw_samples),
        "samples_used": len(filtered),
        "filter": {
            "target_model_enum": TARGET_MODEL_ENUM,
            "min_subcal_speed": MIN_SUBCAL_SPEED,
            "max_subcal_caliber": MAX_SUBCAL_CALIBER,
            "max_abs_x_offset": MAX_ABS_X_OFFSET,
            "max_abs_y_offset": MAX_ABS_Y_OFFSET,
        },
        "model": {
            "equation": "y_up = c0 + c1*distance_km + c2*speed_delta100 + c3*(distance_km*speed_delta100) + c4*caliber_delta_mm",
            "coefficients": {
                "c0": coeffs[0],
                "c1_distance_km": coeffs[1],
                "c2_speed_delta100": coeffs[2],
                "c3_distance_speed": coeffs[3],
                "c4_caliber_delta_mm": coeffs[4],
            },
            "mae": mae,
            "rmse": rmse,
        },
        "speed_groups": group_summary(filtered),
    }

    os.makedirs("dumps", exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "HITPOINT CORRECTION FIT",
        "=" * 80,
        f"samples_total={payload['samples_total']}",
        f"samples_used={payload['samples_used']}",
        "",
        "MODEL",
        "-" * 80,
        payload["model"]["equation"],
        json.dumps(payload["model"]["coefficients"], indent=2, ensure_ascii=False),
        f"mae={mae:.4f}",
        f"rmse={rmse:.4f}",
        "",
        "SPEED GROUPS",
        "-" * 80,
        json.dumps(payload["speed_groups"], indent=2, ensure_ascii=False),
    ]
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[+] JSON: {OUT_JSON}")
    print(f"[+] TEXT: {OUT_TXT}")
    print(f"[*] used {len(filtered)} / {len(raw_samples)} samples")
    print(f"[*] mae={mae:.4f} rmse={rmse:.4f}")


if __name__ == "__main__":
    main()
