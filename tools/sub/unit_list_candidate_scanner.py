import json
import math
import os
import struct
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")
SCAN_START = 0x0
SCAN_END = 0x8000
SCAN_STEP = 0x8
MAX_COUNT = 2048
MAX_SAMPLE = 512
PROFILE_SAMPLE = 512
VEHICLE_SAMPLE_LIMIT = 64

COUNT_OFFSETS = (0x8, 0x10, 0x14, 0x18, 0x20, 0x24, 0x28)
SEED_LIST_SPECS = (
    ("ACTIVE_310", 0x310, 0x14),
    ("WORLD_328_10", 0x328, 0x10),
    ("WORLD_328_14", 0x328, 0x14),
    ("WORLD_340_10", 0x340, 0x10),
    ("WORLD_340_14", 0x340, 0x14),
    ("OLD_GROUND_358", 0x358, 0x10),
)
PROP_HINTS = (
    "structure",
    "structures/",
    "air_defence",
    "fortification",
    "dummy",
    "building",
    "hangar",
    "airfield",
    "decor",
    "effect",
)
VEHICLE_HINTS = (
    "exp_tank",
    "exp_heavy_tank",
    "exp_tank_destroyer",
    "exp_spaa",
    "exp_fighter",
    "exp_bomber",
    "exp_assault",
    "exp_helicopter",
    "exp_ship",
    "tank",
    "spaa",
    "fighter",
    "bomber",
    "helicopter",
)


def read_u8(scanner, addr):
    raw = scanner.read_mem(addr, 1)
    if not raw or len(raw) < 1:
        return 0
    return raw[0]


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def read_i32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<i", raw)[0]


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_f32x3(scanner, addr):
    raw = scanner.read_mem(addr, 12)
    if not raw or len(raw) < 12:
        return None
    vals = struct.unpack("<fff", raw)
    if not all(math.isfinite(v) for v in vals):
        return None
    return vals


def is_plausible_pos(pos):
    if not pos:
        return False
    x, y, z = pos
    if abs(x) < 0.001 and abs(y) < 0.001 and abs(z) < 0.001:
        return False
    return abs(x) < 200000.0 and abs(y) < 200000.0 and abs(z) < 200000.0


def classify_profile(profile, dna):
    blob = " ".join((
        str((profile or {}).get("tag") or ""),
        str((profile or {}).get("path") or ""),
        str((profile or {}).get("unit_key") or ""),
        str((profile or {}).get("display_name") or ""),
        str((dna or {}).get("family") or ""),
        str((dna or {}).get("name_key") or ""),
        str((dna or {}).get("short_name") or ""),
    )).lower()
    if any(h in blob for h in PROP_HINTS):
        return "prop"
    if any(h in blob for h in VEHICLE_HINTS):
        return "vehicle"
    return "unknown"


def read_ptr_array(scanner, array_ptr, count):
    ptr_data = scanner.read_mem(array_ptr, count * 8)
    if not ptr_data or len(ptr_data) < count * 8:
        return []
    out = []
    for idx in range(count):
        ptr = struct.unpack_from("<Q", ptr_data, idx * 8)[0]
        if mul.is_valid_ptr(ptr):
            out.append(ptr)
    return out


def dist3(a, b):
    if not a or not b:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def sample_unit(scanner, u_ptr, my_unit=0, my_team=0, my_pos=None):
    pos = read_f32x3(scanner, u_ptr + mul.OFF_UNIT_X)
    dist = dist3(pos, my_pos)
    info_ptr = read_u64(scanner, u_ptr + mul.OFF_UNIT_INFO) if mul.OFF_UNIT_INFO else 0
    team = read_u8(scanner, u_ptr + mul.OFF_UNIT_TEAM) if mul.OFF_UNIT_TEAM else 0
    state = read_i32(scanner, u_ptr + mul.OFF_UNIT_STATE) if mul.OFF_UNIT_STATE else 0
    profile = {}
    dna = {}
    cls = "unknown"
    try:
        profile = mul.get_unit_filter_profile(scanner, u_ptr) or {}
        dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
        cls = classify_profile(profile, dna)
    except Exception:
        cls = "unknown"
    return {
        "ptr": hex(u_ptr),
        "is_my_unit": bool(my_unit and u_ptr == my_unit),
        "is_my_team": bool(my_team and team == my_team),
        "team": team,
        "state": state,
        "pos": tuple(round(v, 2) for v in pos) if pos else None,
        "dist": round(dist, 1) if dist is not None else None,
        "info": hex(info_ptr) if info_ptr else "0x0",
        "class": cls,
        "kind": profile.get("kind", ""),
        "skip": bool(profile.get("skip", False)),
        "skip_reason": profile.get("reason", ""),
        "tag": profile.get("tag", ""),
        "path": profile.get("path", ""),
        "short_name": dna.get("short_name", ""),
        "family": dna.get("family", ""),
    }


def vehicle_kind_from_sample(sample):
    kind = (sample.get("kind") or "").lower()
    family = (sample.get("family") or "").lower()
    tag = (sample.get("tag") or "").lower()
    blob = " ".join((kind, family, tag))
    if "fighter" in blob or "bomber" in blob or "helicopter" in blob or "assault" in blob or "attacker" in blob:
        return "air"
    if "tank" in blob or "spaa" in blob or "destroyer" in blob or "ship" in blob or "boat" in blob:
        return "ground"
    return "unknown"


def summarize_vehicle_samples(samples, my_team=0):
    summary = {
        "air": 0,
        "ground": 0,
        "unknown": 0,
        "hostile_air": 0,
        "hostile_ground": 0,
        "friendly_air": 0,
        "friendly_ground": 0,
        "my_unit": 0,
    }
    for sample in samples:
        kind = vehicle_kind_from_sample(sample)
        summary[kind] += 1
        if sample.get("is_my_unit"):
            summary["my_unit"] += 1
        if my_team and sample.get("team") == my_team:
            if kind in ("air", "ground"):
                summary[f"friendly_{kind}"] += 1
        elif kind in ("air", "ground"):
            summary[f"hostile_{kind}"] += 1
    return summary


def collect_seed_units(scanner, cgame_ptr, my_unit=0, my_team=0, my_pos=None):
    seeds = {}
    sources = []
    for label, list_off, count_off in SEED_LIST_SPECS:
        array_ptr = read_u64(scanner, cgame_ptr + list_off)
        count = read_u32(scanner, cgame_ptr + list_off + count_off)
        source = {
            "label": label,
            "list_off": hex(list_off),
            "count_off": hex(count_off),
            "array_ptr": hex(array_ptr) if array_ptr else "0x0",
            "count": count,
            "sampled": 0,
            "vehicle_count": 0,
        }
        if not mul.is_valid_ptr(array_ptr) or not (0 < count <= MAX_COUNT):
            sources.append(source)
            continue
        ptrs = read_ptr_array(scanner, array_ptr, min(count, MAX_COUNT))
        seen = set()
        for ptr in ptrs:
            if ptr in seen:
                continue
            seen.add(ptr)
            sample = sample_unit(scanner, ptr, my_unit, my_team, my_pos)
            if sample["class"] != "vehicle":
                continue
            source["vehicle_count"] += 1
            cur = seeds.setdefault(sample["ptr"], sample)
            cur.setdefault("seed_sources", []).append(label)
        source["sampled"] = len(seen)
        sources.append(source)
    return seeds, sources


def analyze_candidate(scanner, cgame_ptr, list_off, count_off, seed_ptrs=None, my_unit=0, my_team=0, my_pos=None, is_known=False):
    array_ptr = read_u64(scanner, cgame_ptr + list_off)
    count = read_u32(scanner, cgame_ptr + list_off + count_off)
    if not mul.is_valid_ptr(array_ptr) or not (0 < count <= MAX_COUNT):
        return None

    ptrs = read_ptr_array(scanner, array_ptr, min(count, MAX_COUNT))
    if not ptrs:
        return None

    seen = set()
    unique_ptrs = []
    for ptr in ptrs:
        if ptr not in seen:
            seen.add(ptr)
            unique_ptrs.append(ptr)

    seed_ptrs = seed_ptrs or set()
    unique_ptr_hex = {hex(ptr) for ptr in unique_ptrs}
    seed_overlap_ptrs = sorted(unique_ptr_hex & seed_ptrs)
    seed_missing_ptrs = sorted(seed_ptrs - unique_ptr_hex)

    pos_ok = 0
    info_ok = 0
    team_ok = 0
    vehicle_count = 0
    prop_count = 0
    unknown_count = 0
    samples = []
    vehicle_samples = []

    for idx, u_ptr in enumerate(unique_ptrs[:MAX_SAMPLE]):
        pos = read_f32x3(scanner, u_ptr + mul.OFF_UNIT_X)
        pos_valid = is_plausible_pos(pos)
        if pos_valid:
            pos_ok += 1

        info_ptr = read_u64(scanner, u_ptr + mul.OFF_UNIT_INFO) if mul.OFF_UNIT_INFO else 0
        info_valid = mul.is_valid_ptr(info_ptr)
        if info_valid:
            info_ok += 1

        team = read_u8(scanner, u_ptr + mul.OFF_UNIT_TEAM) if mul.OFF_UNIT_TEAM else 0
        team_valid = 0 < team < 32
        if team_valid:
            team_ok += 1

        cls = "unknown"
        profile = {}
        dna = {}
        if idx < PROFILE_SAMPLE and (info_valid or pos_valid):
            try:
                profile = mul.get_unit_filter_profile(scanner, u_ptr) or {}
                dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
                cls = classify_profile(profile, dna)
            except Exception:
                cls = "unknown"

        if cls == "vehicle":
            vehicle_count += 1
            if len(vehicle_samples) < VEHICLE_SAMPLE_LIMIT:
                sample = sample_unit(scanner, u_ptr, my_unit, my_team, my_pos)
                sample["class"] = cls
                vehicle_samples.append(sample)
        elif cls == "prop":
            prop_count += 1
        else:
            unknown_count += 1

        if len(samples) < 12:
            sample = sample_unit(scanner, u_ptr, my_unit, my_team, my_pos)
            sample["class"] = cls
            samples.append({
                "ptr": hex(u_ptr),
                "is_my_unit": bool(my_unit and u_ptr == my_unit),
                "is_my_team": bool(my_team and team == my_team),
                "team": team,
                "state": sample.get("state", 0),
                "pos": tuple(round(v, 2) for v in pos) if pos else None,
                "dist": sample.get("dist"),
                "info": hex(info_ptr) if info_ptr else "0x0",
                "class": cls,
                "kind": profile.get("kind", ""),
                "skip": bool(profile.get("skip", False)),
                "skip_reason": profile.get("reason", ""),
                "tag": profile.get("tag", ""),
                "path": profile.get("path", ""),
                "short_name": dna.get("short_name", ""),
                "family": dna.get("family", ""),
            })

    sample_n = max(1, len(unique_ptrs[:MAX_SAMPLE]))
    vehicle_ratio = vehicle_count / max(1, vehicle_count + prop_count + unknown_count)
    prop_ratio = prop_count / max(1, vehicle_count + prop_count + unknown_count)
    clean_ratio = vehicle_count / max(1, vehicle_count + prop_count + unknown_count)
    pos_ratio = pos_ok / sample_n
    info_ratio = info_ok / sample_n
    team_ratio = team_ok / sample_n
    seed_total = max(1, len(seed_ptrs))
    seed_overlap_ratio = len(seed_overlap_ptrs) / seed_total

    score = 0.0
    score += pos_ratio * 30.0
    score += info_ratio * 30.0
    score += team_ratio * 15.0
    score += vehicle_ratio * 40.0
    score -= prop_ratio * 45.0
    if count > 180:
        score -= min((count - 180) / 10.0, 45.0)
    if seed_ptrs:
        score += seed_overlap_ratio * 60.0
    if is_known:
        score += 2.0

    vehicle_summary = summarize_vehicle_samples(vehicle_samples, my_team)
    balanced_score = (seed_overlap_ratio * 100.0) + (clean_ratio * 40.0) - (prop_ratio * 35.0)
    complete_score = (seed_overlap_ratio * 100.0) - min(len(seed_missing_ptrs), 250) * 0.1
    clean_score = (clean_ratio * 100.0) + (seed_overlap_ratio * 25.0) - (prop_ratio * 50.0)
    return {
        "list_off": hex(list_off),
        "count_off": hex(count_off),
        "array_ptr": hex(array_ptr),
        "count": count,
        "sampled": sample_n,
        "unique_sampled": len(unique_ptrs),
        "score": round(score, 3),
        "pos_ok": pos_ok,
        "info_ok": info_ok,
        "team_ok": team_ok,
        "vehicle_count": vehicle_count,
        "prop_count": prop_count,
        "unknown_count": unknown_count,
        "vehicle_ratio": round(vehicle_ratio, 3),
        "prop_ratio": round(prop_ratio, 3),
        "clean_ratio": round(clean_ratio, 3),
        "balanced_score": round(balanced_score, 3),
        "complete_score": round(complete_score, 3),
        "clean_score": round(clean_score, 3),
        "vehicle_summary": vehicle_summary,
        "seed_overlap_count": len(seed_overlap_ptrs),
        "seed_missing_count": len(seed_missing_ptrs),
        "seed_overlap_ratio": round(seed_overlap_ratio, 3),
        "seed_overlap_ptrs": seed_overlap_ptrs[:128],
        "seed_missing_ptrs": seed_missing_ptrs[:128],
        "known_current": is_known,
        "samples": samples,
        "vehicle_samples": vehicle_samples,
    }


def scan_candidates(scanner, cgame_ptr, seed_ptrs=None, my_unit=0, my_team=0, my_pos=None):
    known_offsets = {
        int(mul.OFF_AIR_UNITS[0]),
        int(mul.OFF_GROUND_UNITS[0]),
    }
    for off, _is_air in getattr(mul, "OFF_EXTRA_UNIT_LISTS", ()):
        known_offsets.add(int(off))
    results = []
    seen_keys = set()
    for list_off in range(SCAN_START, SCAN_END, SCAN_STEP):
        for count_off in COUNT_OFFSETS:
            rec = analyze_candidate(
                scanner,
                cgame_ptr,
                list_off,
                count_off,
                seed_ptrs=seed_ptrs,
                my_unit=my_unit,
                my_team=my_team,
                my_pos=my_pos,
                is_known=list_off in known_offsets,
            )
            if not rec:
                continue
            key = (rec["array_ptr"], rec["count"], rec["count_off"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append(rec)
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def _best_candidate_by_offset(results):
    best = {}
    for rec in results:
        off = rec["list_off"]
        cur = best.get(off)
        if cur is None or float(rec["score"]) > float(cur["score"]):
            best[off] = rec
    return best


def _vehicle_ptr_set(rec):
    out = set()
    for sample in rec.get("vehicle_samples") or rec.get("samples", []):
        if sample.get("class") == "vehicle":
            out.add(sample.get("ptr"))
    return out


def build_overlap_report(results, offsets=("0x310", "0x328", "0x340")):
    best = _best_candidate_by_offset(results)
    selected = [best[off] for off in offsets if off in best]
    rows = []
    for rec in selected:
        ptrs = _vehicle_ptr_set(rec)
        other_ptrs = set()
        for other in selected:
            if other is rec:
                continue
            other_ptrs |= _vehicle_ptr_set(other)
        rows.append({
            "list_off": rec["list_off"],
            "count_off": rec["count_off"],
            "count": rec["count"],
            "score": rec["score"],
            "vehicle_sample_count": len(ptrs),
            "unique_vehicle_sample_count": len(ptrs - other_ptrs),
            "overlap_vehicle_sample_count": len(ptrs & other_ptrs),
            "unique_samples": [
                sample for sample in (rec.get("vehicle_samples") or rec.get("samples", []))
                if sample.get("class") == "vehicle" and sample.get("ptr") in (ptrs - other_ptrs)
            ][:8],
        })

    pair_rows = []
    for i, left in enumerate(selected):
        left_set = _vehicle_ptr_set(left)
        for right in selected[i + 1:]:
            right_set = _vehicle_ptr_set(right)
            pair_rows.append({
                "a": left["list_off"],
                "b": right["list_off"],
                "a_vehicle_sample_count": len(left_set),
                "b_vehicle_sample_count": len(right_set),
                "overlap": len(left_set & right_set),
                "a_only": len(left_set - right_set),
                "b_only": len(right_set - left_set),
            })
    return {
        "offsets": offsets,
        "rows": rows,
        "pairs": pair_rows,
    }


def _ranked(results, key, limit=15):
    return sorted(results, key=lambda r: (r.get(key, 0), r.get("seed_overlap_count", 0), r.get("score", 0)), reverse=True)[:limit]


def _format_candidate_line(rec, seed_total):
    vs = rec.get("vehicle_summary", {})
    return (
        f"cgame+{rec['list_off']} count@+{rec['count_off']} count={rec['count']} "
        f"seed={rec['seed_overlap_count']}/{seed_total} miss={rec['seed_missing_count']} "
        f"veh={rec['vehicle_count']} prop={rec['prop_count']} unk={rec['unknown_count']} "
        f"balanced={rec.get('balanced_score', 0):.2f} complete={rec.get('complete_score', 0):.2f} "
        f"clean={rec.get('clean_score', 0):.2f} "
        f"hostileG/A={vs.get('hostile_ground', 0)}/{vs.get('hostile_air', 0)} "
        f"friendlyG/A={vs.get('friendly_ground', 0)}/{vs.get('friendly_air', 0)}"
    )


def _append_rank_section(lines, title, rows, seed_units):
    seed_total = len(seed_units)
    lines.append(f"[{title}]")
    for idx, rec in enumerate(rows, 1):
        lines.append(f"{idx:02d}. {_format_candidate_line(rec, seed_total)}")
        for ptr in rec.get("seed_missing_ptrs", [])[:8]:
            seed = seed_units.get(ptr, {})
            lines.append(
                f"    missing {ptr} name={seed.get('short_name')} "
                f"family={seed.get('family')} team={seed.get('team')} sources={','.join(seed.get('seed_sources', []))}"
            )
    lines.append("")


def write_outputs(cgame_ptr, results, seed_units=None, seed_sources=None, my_unit=0, my_team=0):
    seed_units = seed_units or {}
    seed_sources = seed_sources or []
    os.makedirs(DUMPS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"unit_list_candidate_scan_{ts}.json")
    txt_path = os.path.join(DUMPS_DIR, f"unit_list_candidate_scan_{ts}.txt")
    overlap = build_overlap_report(results)
    payload = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "cgame_ptr": hex(cgame_ptr),
        "my_unit": hex(my_unit) if my_unit else "0x0",
        "my_team": my_team,
        "scan_range": [hex(SCAN_START), hex(SCAN_END)],
        "seed_sources": seed_sources,
        "seed_units": seed_units,
        "rankings": {
            "balanced": _ranked(results, "balanced_score", 30),
            "complete": _ranked(results, "complete_score", 30),
            "clean": _ranked(results, "clean_score", 30),
        },
        "overlap": overlap,
        "results": results,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    lines = []
    lines.append("=" * 72)
    lines.append("UNIT LIST CANDIDATE SCANNER")
    lines.append("=" * 72)
    lines.append(f"CGame: {hex(cgame_ptr)}")
    lines.append(f"My Unit: {hex(my_unit) if my_unit else '0x0'} | Team: {my_team}")
    lines.append(f"Seed vehicle units: {len(seed_units)}")
    lines.append(f"Candidates: {len(results)}")
    lines.append("")
    lines.append("[seed-sources]")
    for src in seed_sources:
        lines.append(
            f"- {src['label']} cgame+{src['list_off']} count@+{src['count_off']} "
            f"count={src['count']} sampled={src['sampled']} veh={src['vehicle_count']} "
            f"array={src['array_ptr']}"
        )
    lines.append("")
    _append_rank_section(lines, "balanced-best", _ranked(results, "balanced_score"), seed_units)
    _append_rank_section(lines, "complete-best", _ranked(results, "complete_score"), seed_units)
    _append_rank_section(lines, "clean-best", _ranked(results, "clean_score"), seed_units)

    for idx, rec in enumerate(results[:30], 1):
        known = " CURRENT" if rec["known_current"] else ""
        vs = rec.get("vehicle_summary", {})
        lines.append(
            f"{idx:02d}. cgame+{rec['list_off']} count@+{rec['count_off']} count={rec['count']} "
            f"score={rec['score']:.2f}{known} seed={rec['seed_overlap_count']}/{len(seed_units)} "
            f"miss={rec['seed_missing_count']}"
        )
        lines.append(
            f"    array={rec['array_ptr']} sampled={rec['sampled']} "
            f"pos={rec['pos_ok']} info={rec['info_ok']} team={rec['team_ok']} "
            f"vehicle={rec['vehicle_count']} prop={rec['prop_count']} unknown={rec['unknown_count']}"
        )
        lines.append(
            f"    kind air={vs.get('air', 0)} ground={vs.get('ground', 0)} unknown={vs.get('unknown', 0)} "
            f"hostile_air={vs.get('hostile_air', 0)} hostile_ground={vs.get('hostile_ground', 0)} "
            f"friendly_air={vs.get('friendly_air', 0)} friendly_ground={vs.get('friendly_ground', 0)} "
            f"my={vs.get('my_unit', 0)}"
        )
        for sample in rec["samples"][:5]:
            lines.append(
                f"    - {sample['ptr']} team={sample['team']} state={sample.get('state')} "
                f"dist={sample.get('dist')} my={sample.get('is_my_unit')} class={sample['class']} "
                f"kind={sample.get('kind')} name={sample['short_name']} family={sample['family']} tag={sample['tag']}"
            )
        lines.append("")

    lines.append("[vehicle-detail-best]")
    for rec in results[:6]:
        lines.append(
            f"- cgame+{rec['list_off']} count@+{rec['count_off']} count={rec['count']} "
            f"seed={rec['seed_overlap_count']}/{len(seed_units)}"
        )
        for sample in rec.get("vehicle_samples", []):
            lines.append(
                f"    {sample['ptr']} team={sample['team']} state={sample.get('state')} "
                f"dist={sample.get('dist')} my={sample.get('is_my_unit')} my_team={sample.get('is_my_team')} "
                f"kind={vehicle_kind_from_sample(sample)} name={sample['short_name']} family={sample['family']} "
                f"tag={sample['tag']} skip={sample.get('skip')}:{sample.get('skip_reason')}"
            )
    lines.append("")

    lines.append("[list-overlap]")
    for row in overlap["rows"]:
        lines.append(
            f"- cgame+{row['list_off']} count@+{row['count_off']} count={row['count']} "
            f"score={row['score']:.2f} veh_sample={row['vehicle_sample_count']} "
            f"unique={row['unique_vehicle_sample_count']} overlap={row['overlap_vehicle_sample_count']}"
        )
        for sample in row["unique_samples"]:
            lines.append(
                f"    unique {sample['ptr']} name={sample['short_name']} "
                f"family={sample['family']} tag={sample['tag']}"
            )
    lines.append("")
    lines.append("[list-overlap-pairs]")
    for pair in overlap["pairs"]:
        lines.append(
            f"- {pair['a']} vs {pair['b']}: overlap={pair['overlap']} "
            f"{pair['a']}_only={pair['a_only']} {pair['b']}_only={pair['b_only']}"
        )
    lines.append("")

    lines.append("[seed-best]")
    for rec in sorted(results, key=lambda r: (r["seed_overlap_count"], r["score"]), reverse=True)[:15]:
        lines.append(
            f"- cgame+{rec['list_off']} count@+{rec['count_off']} count={rec['count']} "
            f"score={rec['score']:.2f} seed={rec['seed_overlap_count']}/{len(seed_units)} "
            f"veh={rec['vehicle_count']} prop={rec['prop_count']} unk={rec['unknown_count']}"
        )
        for ptr in rec["seed_missing_ptrs"][:5]:
            seed = seed_units.get(ptr, {})
            lines.append(
                f"    missing {ptr} name={seed.get('short_name')} "
                f"family={seed.get('family')} sources={','.join(seed.get('seed_sources', []))}"
            )
    lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return json_path, txt_path


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    if not mul.is_valid_ptr(cgame_ptr):
        raise RuntimeError("CGame pointer not found")
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    my_pos = mul.get_unit_pos(scanner, my_unit) if mul.is_valid_ptr(my_unit) else None

    print("=" * 72)
    print("UNIT LIST CANDIDATE SCANNER")
    print("=" * 72)
    print(f"CGame: {hex(cgame_ptr)}")
    print(f"My Unit: {hex(my_unit) if my_unit else '0x0'} | Team: {my_team}")
    print(f"Scan: cgame+{hex(SCAN_START)}..{hex(SCAN_END)}")
    print(f"Deep: count_offsets={','.join(hex(v) for v in COUNT_OFFSETS)} max_sample={MAX_SAMPLE}")
    seed_units, seed_sources = collect_seed_units(scanner, cgame_ptr, my_unit, my_team, my_pos)
    print(f"Seed vehicle units: {len(seed_units)}")
    results = scan_candidates(scanner, cgame_ptr, set(seed_units), my_unit, my_team, my_pos)
    json_path, txt_path = write_outputs(cgame_ptr, results, seed_units, seed_sources, my_unit, my_team)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    print("")
    for idx, rec in enumerate(results[:10], 1):
        known = " CURRENT" if rec["known_current"] else ""
        vs = rec.get("vehicle_summary", {})
        print(
            f"{idx:02d}. cgame+{rec['list_off']} count@+{rec['count_off']} "
            f"count={rec['count']} score={rec['score']:.2f}{known} "
            f"seed={rec['seed_overlap_count']}/{len(seed_units)} "
            f"veh={rec['vehicle_count']} prop={rec['prop_count']} unk={rec['unknown_count']} "
            f"bal={rec.get('balanced_score', 0):.1f} "
            f"hostile G/A={vs.get('hostile_ground', 0)}/{vs.get('hostile_air', 0)} "
            f"friendly G/A={vs.get('friendly_ground', 0)}/{vs.get('friendly_air', 0)}"
        )
    print("")
    print("[balanced-best]")
    for idx, rec in enumerate(_ranked(results, "balanced_score", 5), 1):
        print(f"{idx:02d}. {_format_candidate_line(rec, len(seed_units))}")


if __name__ == "__main__":
    main()
