import argparse
import json
import math
import os
import re
import struct
import sys
import time
from datetime import datetime

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    keyboard = None
    HAS_KEYBOARD = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
SCREEN_CENTER_X = SCREEN_WIDTH * 0.5
SCREEN_CENTER_Y = SCREEN_HEIGHT * 0.5
MATRIX_OFFSETS = list(range(0x100, 0x301, 0x10))
MAX_UNITS = 64
MAX_TOP = 20
MAX_REASONABLE_W = 100000.0
VIEW_MATRIX_CANDIDATE_PERSISTENCE_PATH = os.path.join("config", "view_matrix_candidate_persistence.json")
DEFAULT_STEPS = 3
DEFAULT_SAMPLES_PER_STEP = 5
DEFAULT_TOP_KEEP = (12, 4)
DEFAULT_PROMOTE_THRESHOLD = 3
PROJECTION_MODES = (
    ("xyz_col", False, (0, 1, 2)),
    ("xzy_col", False, (0, 2, 1)),
    ("yxz_col", False, (1, 0, 2)),
    ("yzx_col", False, (1, 2, 0)),
    ("zxy_col", False, (2, 0, 1)),
    ("zyx_col", False, (2, 1, 0)),
    ("xyz_row", True, (0, 1, 2)),
    ("xzy_row", True, (0, 2, 1)),
    ("yxz_row", True, (1, 0, 2)),
    ("yzx_row", True, (1, 2, 0)),
    ("zxy_row", True, (2, 0, 1)),
    ("zyx_row", True, (2, 1, 0)),
)
AXIS_SIGN_VARIANTS = (
    ("+++", (1.0, 1.0, 1.0)),
    ("-++", (-1.0, 1.0, 1.0)),
    ("+-+", (1.0, -1.0, 1.0)),
    ("++-", (1.0, 1.0, -1.0)),
    ("--+", (-1.0, -1.0, 1.0)),
    ("-+-", (-1.0, 1.0, -1.0)),
    ("+--", (1.0, -1.0, -1.0)),
    ("---", (-1.0, -1.0, -1.0)),
)


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_u8(scanner, addr):
    raw = scanner.read_mem(addr, 1)
    if not raw or len(raw) < 1:
        return -1
    return raw[0]


def read_matrix(scanner, camera_ptr, matrix_off):
    raw = scanner.read_mem(camera_ptr + matrix_off, 64)
    if not raw or len(raw) < 64:
        return None
    values = struct.unpack("<16f", raw[:64])
    if len(values) != 16 or not all(math.isfinite(v) for v in values):
        return None
    if any(abs(v) > 1e6 for v in values):
        return None
    if sum(1 for v in values if abs(v) > 1e-6) < 6:
        return None
    return values


def project_with_mode(matrix, pos, row_major, perm, signs):
    if matrix is None or pos is None:
        return None
    x, y, z = pos
    coords = (x, y, z)
    px = coords[perm[0]] * signs[0]
    py = coords[perm[1]] * signs[1]
    pz = coords[perm[2]] * signs[2]
    if row_major:
        w = (px * matrix[12]) + (py * matrix[13]) + (pz * matrix[14]) + matrix[15]
        clip_x = (px * matrix[0]) + (py * matrix[1]) + (pz * matrix[2]) + matrix[3]
        clip_y = (px * matrix[4]) + (py * matrix[5]) + (pz * matrix[6]) + matrix[7]
    else:
        w = (px * matrix[3]) + (py * matrix[7]) + (pz * matrix[11]) + matrix[15]
        clip_x = (px * matrix[0]) + (py * matrix[4]) + (pz * matrix[8]) + matrix[12]
        clip_y = (px * matrix[1]) + (py * matrix[5]) + (pz * matrix[9]) + matrix[13]
    if not math.isfinite(w) or abs(w) < 0.01:
        return None
    ndc_x = clip_x / w
    ndc_y = clip_y / w
    if not (math.isfinite(ndc_x) and math.isfinite(ndc_y)):
        return None
    sx = (SCREEN_WIDTH * 0.5) * (1.0 + ndc_x)
    sy = (SCREEN_HEIGHT * 0.5) * (1.0 - ndc_y)
    if not (math.isfinite(sx) and math.isfinite(sy)):
        return None
    return {
        "sx": round(float(sx), 2),
        "sy": round(float(sy), 2),
        "w": round(abs(float(w)), 4),
        "on_screen": 0.0 <= sx <= SCREEN_WIDTH and 0.0 <= sy <= SCREEN_HEIGHT,
        "center_dist": round(math.hypot(sx - SCREEN_CENTER_X, sy - SCREEN_CENTER_Y), 2),
    }


def unit_label(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    short_name = (dna.get("short_name") or "").strip()
    name_key = (dna.get("name_key") or "").strip()
    family = (dna.get("family") or "").strip()
    if short_name and short_name != "None":
        return short_name
    if name_key and name_key != "None":
        return name_key
    if family and family != "None":
        return family
    return hex(unit_ptr)


def _normalize_target_text(text):
    if not text:
        return ""
    text = text.replace("\xa0", " ").lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def build_enemy_rows(scanner, cgame_ptr, my_unit, my_team):
    rows = []
    for u_ptr, is_air in mul.get_all_units(scanner, cgame_ptr)[:MAX_UNITS]:
        if not mul.is_valid_ptr(u_ptr) or u_ptr == my_unit:
            continue
            
        pos = mul.get_unit_pos(scanner, u_ptr)
        
        # 🎯 กรองพิกัด 0,0,0: ถ้าดึงพิกัดไม่ได้ หรือแกน x, y, z เป็นศูนย์ทั้งหมด (ยูนิตผี) ให้ข้ามทันที!
        if not pos or (abs(pos[0]) < 0.001 and abs(pos[1]) < 0.001 and abs(pos[2]) < 0.001):
            continue
            
        dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
        short_name = (dna.get("short_name") or "").strip()
        name_key = (dna.get("name_key") or "").strip()
        family = (dna.get("family") or "").strip()
        team = read_u8(scanner, u_ptr + mul.OFF_UNIT_TEAM) if mul.OFF_UNIT_TEAM else -1
        
        rows.append({
            "unit_ptr": u_ptr,
            "label": unit_label(scanner, u_ptr),
            "short_name": short_name,
            "name_key": name_key,
            "family": family,
            "is_air": bool(is_air),
            "team": team,
            "is_enemy": (my_team > 0 and team > 0 and team != my_team),
            "pos": pos,
        })
    return rows


def score_candidate(matrix_off, mode_name, sign_name, row_major, perm, signs, matrix, enemy_rows):
    best_enemy = None
    best_ground = None
    best_air = None
    on_screen_enemies = 0
    spread_x = []
    spread_y = []
    
    for row in enemy_rows:
        projected = project_with_mode(matrix, row["pos"], row_major, perm, signs)
        if not projected:
            continue
        if projected["w"] > MAX_REASONABLE_W:
            continue
        if projected["on_screen"]:
            spread_x.append(projected["sx"])
            spread_y.append(projected["sy"])
            if row["is_enemy"]:
                on_screen_enemies += 1
                candidate_enemy = {
                    "unit_ptr": hex(row["unit_ptr"]),
                    "label": row["label"],
                    "is_air": row["is_air"],
                    "projection": projected,
                }
                if best_enemy is None or projected["center_dist"] < best_enemy["projection"]["center_dist"]:
                    best_enemy = candidate_enemy
                if row["is_air"]:
                    if best_air is None or projected["center_dist"] < best_air["projection"]["center_dist"]:
                        best_air = candidate_enemy
                else:
                    if best_ground is None or projected["center_dist"] < best_ground["projection"]["center_dist"]:
                        best_ground = candidate_enemy

    if best_enemy is None:
        return None

    # ========================================================
    # 🚨 THE BLACK HOLE FILTER (ป้องกันเมทริกซ์ปลอมยุบพิกัด) 🚨
    # ========================================================
    span_bonus = 0.0
    if len(spread_x) >= 2 and len(spread_y) >= 2:
        range_x = max(spread_x) - min(spread_x)
        range_y = max(spread_y) - min(spread_y)
        
        # ถ้ายูนิตในแมพ 2 ตัวขึ้นไป ถูกจับมากองรวมกันในรัศมีแคบกว่า 10 พิกเซล = เมทริกซ์ปลอมชัวร์ โยนทิ้ง!
        if range_x < 10.0 and range_y < 10.0:
            return None 
            
        if len(spread_x) >= 4:
            span_bonus = min(range_x / 120.0, 20.0) + min(range_y / 120.0, 20.0)

    score = (4000.0 - best_enemy["projection"]["center_dist"]) + (on_screen_enemies * 10.0) + span_bonus
    
    return {
        "matrix_off": hex(matrix_off),
        "projection_mode": mode_name,
        "axis_signs": sign_name,
        "axis_values": signs,
        "score": round(score, 3),
        "best_enemy": best_enemy,
        "best_ground": best_ground,
        "best_air": best_air,
        "on_screen_enemies": on_screen_enemies,
        "spread_bonus": round(span_bonus, 3),
    }


def _filter_rows(rows, target_filter):
    if not target_filter:
        return rows, False, []
    needle = _normalize_target_text(target_filter)
    if not needle:
        return rows, False, []
    filtered = []
    matched_labels = []
    for row in rows:
        fields = [
            row.get("label", ""),
            row.get("short_name", ""),
            row.get("name_key", ""),
            row.get("family", ""),
        ]
        normalized = [_normalize_target_text(value) for value in fields if value]
        if any(needle in hay for hay in normalized):
            filtered.append(row)
            matched_labels.append({
                "label": row.get("label"),
                "short_name": row.get("short_name"),
                "name_key": row.get("name_key"),
                "family": row.get("family"),
            })
    return (filtered if filtered else rows), bool(filtered), matched_labels


def _normalize_combo(matrix_off, mode_name, sign_name):
    return (int(matrix_off), str(mode_name), str(sign_name))


def _candidate_combo_key(candidate):
    return _normalize_combo(int(candidate["matrix_off"], 16), candidate["projection_mode"], candidate["axis_signs"])


def _combo_to_doc(combo):
    # ค้นหาค่า tuple ของเครื่องหมายจาก AXIS_SIGN_VARIANTS
    signs = next((s for n, s in AXIS_SIGN_VARIANTS if n == combo[2]), (1.0, 1.0, 1.0))
    return {
        "matrix_off": hex(combo[0]),
        "projection_mode": combo[1],
        "axis_signs": combo[2],
        "axis_values": signs  # 🎯 เพิ่มบรรทัดนี้
    }


def _load_candidate_persistence():
    if not os.path.exists(VIEW_MATRIX_CANDIDATE_PERSISTENCE_PATH):
        return {
            "promote_threshold": DEFAULT_PROMOTE_THRESHOLD,
            "observations": [],
            "candidate_stats": {},
            "global_candidate": None,
        }
    try:
        with open(VIEW_MATRIX_CANDIDATE_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            raise ValueError("persistence is not a dict")
        doc.setdefault("promote_threshold", DEFAULT_PROMOTE_THRESHOLD)
        doc.setdefault("observations", [])
        doc.setdefault("candidate_stats", {})
        doc.setdefault("global_candidate", None)
        return doc
    except Exception:
        return {
            "promote_threshold": DEFAULT_PROMOTE_THRESHOLD,
            "observations": [],
            "candidate_stats": {},
            "global_candidate": None,
        }


def _save_candidate_persistence(doc):
    os.makedirs(os.path.dirname(VIEW_MATRIX_CANDIDATE_PERSISTENCE_PATH), exist_ok=True)
    with open(VIEW_MATRIX_CANDIDATE_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def _update_candidate_persistence(payload, target_filter, promote_threshold):
    top = (payload.get("top_candidates") or [{}])[0]
    best_ground = (payload.get("best_ground") or [{}])[0]
    chosen = best_ground if best_ground else top
    target_entity = (chosen.get("best_ground") or chosen.get("best_enemy") or chosen.get("best_air") or {})
    if not chosen or not chosen.get("matrix_off") or not chosen.get("projection_mode") or not chosen.get("axis_signs"):
        return None

    combo = (
        int(chosen["matrix_off"], 16),
        chosen["projection_mode"],
        chosen["axis_signs"],
    )
    combo_key = f"{hex(combo[0])}|{combo[1]}|{combo[2]}"
    doc = _load_candidate_persistence()
    doc["promote_threshold"] = max(1, int(promote_threshold))

    stat = doc["candidate_stats"].setdefault(combo_key, {
        "matrix_off": hex(combo[0]),
        "projection_mode": combo[1],
        "axis_signs": combo[2],
        "wins": 0,
        "targets": {},
        "last_target": None,
        "last_seen": None,
    })
    stat["wins"] += 1
    target_name = (target_filter or target_entity.get("label") or "unknown").strip()
    stat["targets"][target_name] = stat["targets"].get(target_name, 0) + 1
    stat["last_target"] = target_name
    stat["last_seen"] = payload.get("timestamp")

    observation = {
        "timestamp": payload.get("timestamp"),
        "target_filter": target_filter,
        "winner": _combo_to_doc(combo),
        "winner_label": target_entity.get("label"),
        "winner_center_dist": ((target_entity.get("projection") or {}).get("center_dist")),
    }
    doc["observations"].append(observation)
    doc["observations"] = doc["observations"][-50:]

    promoted = False
    if stat["wins"] >= doc["promote_threshold"]:
        doc["global_candidate"] = {
            "matrix_off": hex(combo[0]),
            "projection_mode": combo[1],
            "axis_signs": combo[2],
            "wins": stat["wins"],
            "source": "aim_match_multistep",
            "promoted_at": payload.get("timestamp"),
        }
        promoted = True

    _save_candidate_persistence(doc)
    return {
        "combo": _combo_to_doc(combo),
        "wins": stat["wins"],
        "target_count": len(stat["targets"]),
        "promote_threshold": doc["promote_threshold"],
        "promoted": promoted,
        "global_candidate": doc.get("global_candidate"),
        "path": VIEW_MATRIX_CANDIDATE_PERSISTENCE_PATH,
    }


def capture_payload(scanner, base_addr, target_filter=None, combo_filter=None):
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    camera_ptr = read_u64(scanner, cgame_ptr + mul.OFF_CAMERA_PTR) if mul.is_valid_ptr(cgame_ptr) else 0
    rows = build_enemy_rows(scanner, cgame_ptr, my_unit, my_team) if (mul.is_valid_ptr(cgame_ptr) and mul.is_valid_ptr(my_unit)) else []
    scored_rows, filter_applied, matched_labels = _filter_rows(rows, target_filter)
    candidates = []

    if mul.is_valid_ptr(camera_ptr):
        for matrix_off in MATRIX_OFFSETS:
            if combo_filter and not any(combo[0] == matrix_off for combo in combo_filter):
                continue
            matrix = read_matrix(scanner, camera_ptr, matrix_off)
            if matrix is None:
                continue
            for mode_name, row_major, perm in PROJECTION_MODES:
                if combo_filter and not any(combo[0] == matrix_off and combo[1] == mode_name for combo in combo_filter):
                    continue
                for sign_name, signs in AXIS_SIGN_VARIANTS:
                    if combo_filter and _normalize_combo(matrix_off, mode_name, sign_name) not in combo_filter:
                        continue
                    candidate = score_candidate(matrix_off, mode_name, sign_name, row_major, perm, signs, matrix, scored_rows)
                    if candidate:
                        candidates.append(candidate)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    ground_candidates = [row for row in candidates if row.get("best_ground")]
    ground_candidates.sort(key=lambda item: item["best_ground"]["projection"]["center_dist"])
    air_candidates = [row for row in candidates if row.get("best_air")]
    air_candidates.sort(key=lambda item: item["best_air"]["projection"]["center_dist"])
    payload = {
        "timestamp": datetime.now().isoformat(),
        "chosen": {
            "my_unit": hex(my_unit) if my_unit else "0x0",
            "my_team": my_team,
            "cgame_ptr": hex(cgame_ptr) if cgame_ptr else "0x0",
            "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
            "current_matrix_off": hex(getattr(mul, "LAST_VIEW_MATRIX_OFF", 0)) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "current_projection_mode": (getattr(mul, "LAST_VIEW_PROJECTION_MODE", None) or {}).get("name"),
            "enemy_rows": len(rows),
            "target_filter": target_filter,
            "target_filter_applied": filter_applied,
            "scored_rows": len(scored_rows),
            "target_filter_matches": matched_labels,
        },
        "top_candidates": candidates[:MAX_TOP],
        "best_ground": ground_candidates[:10],
        "best_air": air_candidates[:10],
    }
    return payload


def _aggregate_payloads(payloads):
    combo_stats = {}
    for payload in payloads:
        for candidate in payload.get("top_candidates", []):
            combo = _candidate_combo_key(candidate)
            stat = combo_stats.setdefault(combo, {
                "matrix_off": candidate["matrix_off"],
                "projection_mode": candidate["projection_mode"],
                "axis_signs": candidate["axis_signs"],
                "hits": 0,
                "score_sum": 0.0,
                "center_sum": 0.0,
                "best_center": None,
                "labels": {},
            })
            stat["hits"] += 1
            stat["score_sum"] += float(candidate.get("score", 0.0))
            best_entity = candidate.get("best_ground") or candidate.get("best_enemy") or candidate.get("best_air") or {}
            proj = best_entity.get("projection") or {}
            center = float(proj.get("center_dist", 999999.0))
            stat["center_sum"] += center
            if stat["best_center"] is None or center < stat["best_center"]:
                stat["best_center"] = center
            label = best_entity.get("label") or "unknown"
            stat["labels"][label] = stat["labels"].get(label, 0) + 1

    ranked = []
    for _, stat in combo_stats.items():
        avg_score = stat["score_sum"] / max(1, stat["hits"])
        avg_center = stat["center_sum"] / max(1, stat["hits"])
        best_label = max(stat["labels"].items(), key=lambda item: item[1])[0] if stat["labels"] else "unknown"
        
        # 🎯 ดึงตัวเลขจากแกนมาใส่ในตอนจัดอันดับ
        signs = next((s for n, s in AXIS_SIGN_VARIANTS if n == stat["axis_signs"]), (1.0, 1.0, 1.0))
        
        ranked.append({
            "matrix_off": stat["matrix_off"],
            "projection_mode": stat["projection_mode"],
            "axis_signs": stat["axis_signs"],
            "axis_values": signs,         # 🎯 เพิ่มบรรทัดนี้
            "hits": stat["hits"],
            "avg_score": round(avg_score, 3),
            "avg_center_dist": round(avg_center, 3),
            "best_center_dist": round(float(stat["best_center"] or 0.0), 3),
            "dominant_label": best_label,
        })
    ranked.sort(key=lambda item: (-item["hits"], item["avg_center_dist"], -item["avg_score"]))
    return ranked


def _collect_step_payloads(scanner, base_addr, target_filter, samples, combo_filter=None, delay=0.05):
    payloads = []
    for _ in range(samples):
        payloads.append(capture_payload(scanner, base_addr, target_filter, combo_filter=combo_filter))
        time.sleep(delay)
    return payloads


def run_multistep_capture(scanner, base_addr, target_filter, steps=DEFAULT_STEPS, samples_per_step=DEFAULT_SAMPLES_PER_STEP):
    history = []
    combo_filter = None
    keep_plan = list(DEFAULT_TOP_KEEP)

    for step_idx in range(steps):
        payloads = _collect_step_payloads(scanner, base_addr, target_filter, samples_per_step, combo_filter=combo_filter)
        ranked = _aggregate_payloads(payloads)
        keep_n = keep_plan[step_idx] if step_idx < len(keep_plan) else 1
        kept = ranked[:keep_n]
        combo_filter = {_normalize_combo(int(item["matrix_off"], 16), item["projection_mode"], item["axis_signs"]) for item in kept}
        history.append({
            "step": step_idx + 1,
            "samples": len(payloads),
            "filter_size": len(combo_filter) if combo_filter else 0,
            "ranked": ranked[:MAX_TOP],
        })

    final_payload = capture_payload(scanner, base_addr, target_filter, combo_filter=combo_filter)
    final_payload["multistep"] = history
    final_payload["chosen"]["multistep_steps"] = steps
    final_payload["chosen"]["samples_per_step"] = samples_per_step
    final_payload["chosen"]["final_combo_filter"] = [
        {
            "matrix_off": hex(combo[0]),
            "projection_mode": combo[1],
            "axis_signs": combo[2],
        }
        for combo in sorted(combo_filter or [])
    ]
    return final_payload


def write_dump(payload):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"view_matrix_aim_match_{stamp}.json")
    txt_path = os.path.join("dumps", f"view_matrix_aim_match_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "VIEW MATRIX AIM MATCH DUMPER",
        "=" * 80,
        f"Timestamp: {payload.get('timestamp')}",
        "",
        "CHOSEN",
        json.dumps(payload.get("chosen", {}), indent=2, ensure_ascii=False),
        "",
        "CANDIDATE PERSISTENCE",
        json.dumps(payload.get("candidate_persistence", {}), indent=2, ensure_ascii=False),
        "",
        "MULTISTEP",
        json.dumps(payload.get("multistep", []), indent=2, ensure_ascii=False),
        "",
        "TOP CANDIDATES",
        json.dumps(payload.get("top_candidates", []), indent=2, ensure_ascii=False),
        "",
        "BEST GROUND",
        json.dumps(payload.get("best_ground", []), indent=2, ensure_ascii=False),
        "",
        "BEST AIR",
        json.dumps(payload.get("best_air", []), indent=2, ensure_ascii=False),
        "",
    ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target", type=str, default="", help="substring of the intended target label/name")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="number of coarse-to-final scan steps")
    parser.add_argument("--samples-per-step", type=int, default=DEFAULT_SAMPLES_PER_STEP, help="snapshots per scan step")
    parser.add_argument("--promote-threshold", type=int, default=DEFAULT_PROMOTE_THRESHOLD, help="wins required before promoting a combo as global candidate")
    args = parser.parse_args()

    print("=" * 80)
    print("VIEW MATRIX AIM MATCH DUMPER")
    print("=" * 80)
    print("Aim a target near screen center, then press:")
    print("  F6  = capture")
    print("  F10 = abort")
    print(f"Multi-step: steps={args.steps} samples/step={args.samples_per_step}")
    print(f"Promote threshold: {args.promote_threshold}")
    if args.target:
        print(f"Target filter: {args.target}")
    print("-" * 80)
    print("")

    if not HAS_KEYBOARD:
        print("[-] keyboard module not available. install with: pip install keyboard")
        return

    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบ process ของเกม 'aces'")
        return
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    try:
        init_dynamic_offsets(scanner, base_addr)
        while True:
            if keyboard.is_pressed("f10"):
                print("[-] Aborted by user.")
                return
            if keyboard.is_pressed("f6"):
                while keyboard.is_pressed("f6"):
                    time.sleep(0.05)
                payload = run_multistep_capture(
                    scanner,
                    base_addr,
                    args.target,
                    steps=max(1, args.steps),
                    samples_per_step=max(1, args.samples_per_step),
                )
                payload["candidate_persistence"] = _update_candidate_persistence(
                    payload,
                    args.target,
                    promote_threshold=max(1, args.promote_threshold),
                )
                json_path, txt_path = write_dump(payload)
                top = (payload.get("top_candidates") or [{}])[0]
                top_ground = (payload.get("best_ground") or [{}])[0]
                persistence = payload.get("candidate_persistence") or {}
                print(
                    f"[+] Best: matrix={top.get('matrix_off')} mode={top.get('projection_mode')} "
                    f"sign={top.get('axis_signs')} target={(top.get('best_enemy') or {}).get('label')} "
                    f"dist={((top.get('best_enemy') or {}).get('projection') or {}).get('center_dist')}"
                )
                if top_ground:
                    print(
                        f"[+] Best Ground: matrix={top_ground.get('matrix_off')} mode={top_ground.get('projection_mode')} "
                        f"sign={top_ground.get('axis_signs')} val={top_ground.get('axis_values')} target={(top_ground.get('best_ground') or {}).get('label')} "
                        f"dist={((top_ground.get('best_ground') or {}).get('projection') or {}).get('center_dist')}"
                    )
                if persistence:
                    print(
                        f"[+] Candidate persistence: wins={persistence.get('wins')} "
                        f"targets={persistence.get('target_count')} "
                        f"threshold={persistence.get('promote_threshold')} "
                        f"promoted={'Y' if persistence.get('promoted') else 'N'}"
                    )
                    print(f"[+] Persistence: {persistence.get('path')}")
                print(f"[+] JSON: {json_path}")
                print(f"[+] TEXT: {txt_path}")
                return
            time.sleep(0.05)
    finally:
        scanner.close()


if __name__ == "__main__":
    main()
