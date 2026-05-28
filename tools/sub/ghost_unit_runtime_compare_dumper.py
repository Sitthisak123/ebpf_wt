#!/usr/bin/env python3
import json
import math
import os
import struct
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
from src.utils.mul import (
    OFF_GROUND_MOVEMENT,
    OFF_UNIT_INFO,
    OFF_UNIT_STATE,
    get_air_velocity,
    get_all_units,
    get_ground_velocity,
    get_unit_bbox,
    get_unit_detailed_dna,
    get_unit_pos,
    get_unit_status,
    get_unit_filter_profile,
    get_cgame_base,
    is_valid_ptr,
)

GHOST_NAME_HINTS = ("m901", "us_m901_itv")
UNIT_SCAN_SIZE = 0x2600
INFO_SCAN_SIZE = 0x800
SCAN_STEP = 4
TOP_CANDIDATES = 80
WATCH_OFFSETS = (0x1A0, 0x127C, 0x1004)
SAME_POS_BUCKET_M = 1.0
SAME_POS_MIN_SIZE = 2


def _read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _read_block(scanner, addr, size):
    raw = scanner.read_mem(addr, size)
    if not raw or len(raw) < size:
        return b""
    return raw


def _safe_round3(v):
    try:
        return round(float(v), 3)
    except Exception:
        return 0.0


def _vec3(v):
    if not v or len(v) < 3:
        return [0.0, 0.0, 0.0]
    return [_safe_round3(v[0]), _safe_round3(v[1]), _safe_round3(v[2])]


def _is_ground_record(rec):
    blob = " ".join((
        str(rec.get("family", "")),
        str(rec.get("profile_tag", "")),
        str(rec.get("profile_kind", "")),
        str(rec.get("profile_path", "")),
    )).lower()
    return not rec.get("is_air") and any(k in blob for k in ("tank", "spaa", "destroyer"))


def _is_ghost_record(rec):
    blob = " ".join((
        str(rec.get("short_name", "")),
        str(rec.get("unit_key", "")),
        str(rec.get("profile_path", "")),
    )).lower()
    return any(h in blob for h in GHOST_NAME_HINTS)


def _pos_bucket(pos, bucket_m=SAME_POS_BUCKET_M):
    if not pos or len(pos) < 3:
        return None
    if bucket_m <= 0:
        bucket_m = 1.0
    return tuple(int(round(float(v) / bucket_m)) for v in pos[:3])


def _is_zero_pos(pos):
    if not pos or len(pos) < 3:
        return True
    return all(abs(float(v)) < 0.01 for v in pos[:3])


def _speed(vec):
    if not vec or len(vec) < 3:
        return 0.0
    return math.sqrt(sum(float(v) * float(v) for v in vec[:3]))


def _name_hint_record(rec):
    blob = " ".join((
        str(rec.get("short_name", "")),
        str(rec.get("unit_key", "")),
        str(rec.get("profile_path", "")),
    )).lower()
    return any(h in blob for h in GHOST_NAME_HINTS)


def ghost_candidate_reasons(rec):
    reasons = []
    if _name_hint_record(rec):
        reasons.append("name_hint")
    if _is_zero_pos(rec.get("pos")):
        reasons.append("zero_pos")
    if int(rec.get("state", 0)) != 0:
        reasons.append(f"state:{rec.get('state')}")
    return reasons


def watch_reasons(rec):
    reasons = []
    if rec.get("is_air") and not rec.get("mov_ptr_valid"):
        reasons.append("invalid_air_mov")
    elif _is_ground_record(rec) and not rec.get("mov_ptr_valid"):
        reasons.append("invalid_ground_mov")
    if _speed(rec.get("vel")) < 0.01:
        reasons.append("static_vel")
    return reasons


def _is_ghost_candidate_record(rec):
    return bool(ghost_candidate_reasons(rec))


def _bbox_size(scanner, u_ptr):
    try:
        bbox = get_unit_bbox(scanner, u_ptr)
        if not bbox:
            return [0.0, 0.0, 0.0]
        bmin, bmax = bbox
        return [
            _safe_round3((bmax[0] - bmin[0])),
            _safe_round3((bmax[1] - bmin[1])),
            _safe_round3((bmax[2] - bmin[2])),
        ]
    except Exception:
        return [0.0, 0.0, 0.0]


def build_record(scanner, u_ptr, is_air):
    status = get_unit_status(scanner, u_ptr) or (0, -1, "", -1)
    team, state, unit_name, reload_val = status
    dna = get_unit_detailed_dna(scanner, u_ptr) or {}
    profile = get_unit_filter_profile(scanner, u_ptr) or {}
    pos = get_unit_pos(scanner, u_ptr)
    info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO)
    mov_ptr = _read_ptr(scanner, u_ptr + OFF_GROUND_MOVEMENT)
    vel = get_air_velocity(scanner, u_ptr) if is_air else get_ground_velocity(scanner, u_ptr)
    state_raw = scanner.read_mem(u_ptr + OFF_UNIT_STATE, 0x20) or b""

    rec = {
        "ptr": hex(u_ptr),
        "is_air": bool(is_air),
        "team": int(team),
        "state": int(state),
        "reload_val": int(reload_val),
        "unit_name": str(unit_name or ""),
        "short_name": str(dna.get("short_name") or profile.get("short_name") or ""),
        "unit_key": str(dna.get("name_key") or profile.get("unit_key") or ""),
        "family": str(dna.get("family") or profile.get("tag") or ""),
        "class_id": int(dna.get("class_id", -1) or -1),
        "nation_id": int(dna.get("nation_id", -1) or -1),
        "is_invul": bool(dna.get("is_invul")),
        "info_ptr": hex(info_ptr) if info_ptr else "0x0",
        "info_ptr_valid": bool(is_valid_ptr(info_ptr)),
        "mov_ptr": hex(mov_ptr) if mov_ptr else "0x0",
        "mov_ptr_valid": bool(is_valid_ptr(mov_ptr)),
        "pos": _vec3(pos),
        "vel": _vec3(vel),
        "bbox_size": _bbox_size(scanner, u_ptr),
        "state_raw_hex": state_raw.hex(),
        "profile_tag": str(profile.get("tag") or ""),
        "profile_path": str(profile.get("path") or ""),
        "profile_kind": str(profile.get("kind") or ""),
        "ghost_suspect": False,
    }

    rec["ghost_candidate_reasons"] = ghost_candidate_reasons(rec)
    rec["watch_reasons"] = watch_reasons(rec)
    rec["ghost_suspect"] = bool(rec["ghost_candidate_reasons"])
    return rec


def _decode_at(raw, off, fmt):
    size = struct.calcsize(fmt)
    if off < 0 or off + size > len(raw):
        return None
    try:
        return struct.unpack_from(fmt, raw, off)[0]
    except Exception:
        return None


def _value_blob(raw, off):
    vals = {
        "u8": _decode_at(raw, off, "<B"),
        "i8": _decode_at(raw, off, "<b"),
        "u16": _decode_at(raw, off, "<H"),
        "i16": _decode_at(raw, off, "<h"),
        "u32": _decode_at(raw, off, "<I"),
        "i32": _decode_at(raw, off, "<i"),
        "u64": _decode_at(raw, off, "<Q"),
        "f32": _decode_at(raw, off, "<f"),
    }
    if vals["f32"] is not None and not math.isfinite(vals["f32"]):
        vals["f32"] = None
    return vals


def _format_val(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, int):
        return v
    return v


def read_watch_fields(scanner, u_ptr):
    fields = {}
    for off in WATCH_OFFSETS:
        raw = scanner.read_mem(u_ptr + off, 8)
        if not raw or len(raw) < 8:
            fields[hex(off)] = None
            continue
        vals = _value_blob(raw, 0)
        fields[hex(off)] = {
            "u8": vals["u8"],
            "u16": vals["u16"],
            "u32": vals["u32"],
            "i32": vals["i32"],
            "f32": _format_val(vals["f32"]),
        }
    return fields


def _score_field(ghost_vals, real_vals, type_name):
    if not ghost_vals or not real_vals:
        return None
    ghost_set = set(ghost_vals)
    real_set = set(real_vals)
    if len(ghost_set) != 1:
        return None
    ghost_val = next(iter(ghost_set))
    if ghost_val in real_set:
        return None
    if type_name == "f32" and isinstance(ghost_val, float):
        if abs(ghost_val) > 1e8:
            return None
    real_unique = len(real_set)
    return {
        "score": 1000 - min(real_unique, 50),
        "ghost_value": _format_val(ghost_val),
        "real_values": [_format_val(v) for v in sorted(real_set, key=lambda x: str(x))[:12]],
        "real_unique": real_unique,
    }


def scan_diff_region(scanner, label, ghost_ptrs, real_ptrs, size):
    ghost_blocks = {ptr: _read_block(scanner, ptr, size) for ptr in ghost_ptrs if is_valid_ptr(ptr)}
    real_blocks = {ptr: _read_block(scanner, ptr, size) for ptr in real_ptrs if is_valid_ptr(ptr)}
    ghost_blocks = {ptr: raw for ptr, raw in ghost_blocks.items() if raw}
    real_blocks = {ptr: raw for ptr, raw in real_blocks.items() if raw}
    candidates = []
    types = ("u8", "i8", "u16", "i16", "u32", "i32", "u64", "f32")
    for off in range(0, size, SCAN_STEP):
        ghost_blobs = [_value_blob(raw, off) for raw in ghost_blocks.values()]
        real_blobs = [_value_blob(raw, off) for raw in real_blocks.values()]
        for type_name in types:
            ghost_vals = [b[type_name] for b in ghost_blobs if b[type_name] is not None]
            real_vals = [b[type_name] for b in real_blobs if b[type_name] is not None]
            scored = _score_field(ghost_vals, real_vals, type_name)
            if not scored:
                continue
            candidates.append({
                "region": label,
                "offset": hex(off),
                "type": type_name,
                **scored,
            })
    candidates.sort(key=lambda r: (r["score"], -r["real_unique"]), reverse=True)
    return candidates[:TOP_CANDIDATES]


def build_diff_report(scanner, units):
    ghosts = [rec for rec in units if _is_ghost_candidate_record(rec)]
    real_ground = [
        rec for rec in units
        if _is_ground_record(rec) and not _is_ghost_candidate_record(rec) and not rec.get("is_invul")
    ]
    ghost_unit_ptrs = [int(rec["ptr"], 16) for rec in ghosts]
    real_unit_ptrs = [int(rec["ptr"], 16) for rec in real_ground]
    ghost_info_ptrs = [int(rec["info_ptr"], 16) for rec in ghosts if rec.get("info_ptr_valid")]
    real_info_ptrs = [int(rec["info_ptr"], 16) for rec in real_ground if rec.get("info_ptr_valid")]
    return {
        "ghosts": ghosts,
        "real_ground": real_ground,
        "watch_offsets": [hex(off) for off in WATCH_OFFSETS],
        "watch": [
            {
                "ptr": rec["ptr"],
                "short_name": rec["short_name"],
                "unit_key": rec["unit_key"],
                "team": rec["team"],
                "state": rec["state"],
                "is_air": rec["is_air"],
                "family": rec["family"],
                "is_ghost": _is_ghost_candidate_record(rec),
                "ghost_candidate_reasons": ghost_candidate_reasons(rec),
                "watch_reasons": watch_reasons(rec),
                "fields": read_watch_fields(scanner, int(rec["ptr"], 16)),
            }
            for rec in units
        ],
        "unit_candidates": scan_diff_region(scanner, "unit", ghost_unit_ptrs, real_unit_ptrs, UNIT_SCAN_SIZE),
        "info_candidates": scan_diff_region(scanner, "info", ghost_info_ptrs, real_info_ptrs, INFO_SCAN_SIZE),
    }


def build_same_position_report(scanner, units):
    buckets = {}
    for rec in units:
        bucket = _pos_bucket(rec.get("pos"))
        if bucket is None:
            continue
        buckets.setdefault(bucket, []).append(rec)

    groups = []
    for bucket, rows in buckets.items():
        if len(rows) < SAME_POS_MIN_SIZE:
            continue
        ghosts = [rec for rec in rows if _is_ghost_candidate_record(rec)]
        ground_rows = [rec for rec in rows if _is_ground_record(rec)]
        real_rows = [rec for rec in ground_rows if not _is_ghost_candidate_record(rec)]
        group = {
            "bucket": list(bucket),
            "bucket_m": SAME_POS_BUCKET_M,
            "count": len(rows),
            "ghost_count": len(ghosts),
            "ground_count": len(ground_rows),
            "units": rows,
            "unit_candidates": [],
            "info_candidates": [],
        }
        if ghosts and real_rows:
            ghost_unit_ptrs = [int(rec["ptr"], 16) for rec in ghosts]
            real_unit_ptrs = [int(rec["ptr"], 16) for rec in real_rows]
            ghost_info_ptrs = [int(rec["info_ptr"], 16) for rec in ghosts if rec.get("info_ptr_valid")]
            real_info_ptrs = [int(rec["info_ptr"], 16) for rec in real_rows if rec.get("info_ptr_valid")]
            group["unit_candidates"] = scan_diff_region(scanner, "unit", ghost_unit_ptrs, real_unit_ptrs, UNIT_SCAN_SIZE)[:30]
            group["info_candidates"] = scan_diff_region(scanner, "info", ghost_info_ptrs, real_info_ptrs, INFO_SCAN_SIZE)[:30]
        groups.append(group)

    groups.sort(key=lambda g: (g["ghost_count"], g["ground_count"], g["count"]), reverse=True)
    return groups


def read_watch_fields_from_payload(payload, ptr):
    diff = payload.get("diff") or {}
    for row in diff.get("watch", []):
        if row.get("ptr") != ptr:
            continue
        parts = []
        for off in diff.get("watch_offsets", []):
            vals = (row.get("fields") or {}).get(off) or {}
            parts.append(f"{off}:u8={vals.get('u8')} u32={vals.get('u32')}")
        return " | ".join(parts)
    return ""


def render_text(payload):
    lines = []
    lines.append("=" * 50)
    lines.append(" GHOST UNIT RUNTIME COMPARE DUMPER")
    lines.append("=" * 50)
    lines.append(f"[+] Units dumped: {len(payload['units'])}")
    lines.append("")
    for rec in payload["units"]:
        flags = []
        if rec["state"] >= 1:
            flags.append("DEAD")
        if rec["ghost_suspect"]:
            flags.append("GHOST?")
        flag_str = f" [{' '.join(flags)}]" if flags else ""
        lines.append(
            f"- {rec['short_name'] or rec['unit_name'] or rec['unit_key']} "
            f"| ptr={rec['ptr']} | team={rec['team']} state={rec['state']} reload={rec['reload_val']}{flag_str}"
        )
        lines.append(
            f"  key={rec['unit_key']} | family={rec['family']} | air={rec['is_air']} | invul={rec['is_invul']}"
        )
        lines.append(
            f"  info={rec['info_ptr']} valid={rec['info_ptr_valid']} | mov={rec['mov_ptr']} valid={rec['mov_ptr_valid']}"
        )
        lines.append(
            f"  pos={rec['pos']} | vel={rec['vel']} | bbox={rec['bbox_size']}"
        )
        lines.append(
            f"  profile={rec['profile_tag']} | kind={rec['profile_kind']} | path={rec['profile_path']}"
        )
        lines.append(f"  state_raw={rec['state_raw_hex']}")
        lines.append("")
    diff = payload.get("diff") or {}
    lines.append("=" * 50)
    lines.append(" GHOST CANDIDATE DIFF")
    lines.append("=" * 50)
    lines.append(f"Ghost candidates: {len(diff.get('ghosts', []))}")
    for rec in diff.get("ghosts", []):
        lines.append(
            f"  candidate {rec['ptr']} {rec['short_name']} key={rec['unit_key']} "
            f"state={rec['state']} ghost={','.join(rec.get('ghost_candidate_reasons', []))} "
            f"watch={','.join(rec.get('watch_reasons', []))} path={rec['profile_path']}"
        )
    lines.append(f"Real ground baseline: {len(diff.get('real_ground', []))}")
    for rec in diff.get("real_ground", []):
        lines.append(f"  real  {rec['ptr']} {rec['short_name']} state={rec['state']} team={rec['team']}")
    lines.append("")
    lines.append("[ghost-flag-watch]")
    for rec in diff.get("watch", []):
        mark = "CAND" if rec.get("is_ghost") else ("AIR" if rec.get("is_air") else "GROUND")
        fields = []
        for off in diff.get("watch_offsets", []):
            vals = (rec.get("fields") or {}).get(off) or {}
            fields.append(f"{off}:u8={vals.get('u8')} u32={vals.get('u32')} f32={vals.get('f32')}")
        lines.append(
            f"- [{mark}] {rec['ptr']} {rec['short_name']} team={rec['team']} state={rec['state']} "
            f"family={rec['family']} ghost={','.join(rec.get('ghost_candidate_reasons', []))} "
            f"watch={','.join(rec.get('watch_reasons', []))} | "
            + " | ".join(fields)
        )
    lines.append("")
    same_pos = payload.get("same_position") or []
    lines.append("=" * 50)
    lines.append(" SAME POSITION GROUPS")
    lines.append("=" * 50)
    lines.append(f"Groups: {len(same_pos)} | bucket_m={SAME_POS_BUCKET_M}")
    for idx, group in enumerate(same_pos[:20], 1):
        lines.append(
            f"[group {idx}] bucket={group['bucket']} count={group['count']} "
            f"ghosts={group['ghost_count']} ground={group['ground_count']}"
        )
        for rec in group.get("units", []):
            mark = "CAND" if _is_ghost_candidate_record(rec) else ("AIR" if rec.get("is_air") else "GROUND")
            fields = read_watch_fields_from_payload(payload, rec["ptr"])
            lines.append(
                f"  - [{mark}] {rec['ptr']} {rec['short_name']} team={rec['team']} state={rec['state']} "
                f"pos={rec['pos']} vel={rec['vel']} mov={rec['mov_ptr']} valid={rec['mov_ptr_valid']} "
                f"ghost={','.join(rec.get('ghost_candidate_reasons', []))} "
                f"watch={','.join(rec.get('watch_reasons', []))} flags={fields}"
            )
        if group.get("unit_candidates"):
            lines.append("  [same-pos unit candidates]")
            for cand in group["unit_candidates"][:12]:
                lines.append(
                    f"    - unit+{cand['offset']} {cand['type']} "
                    f"ghost={cand['ghost_value']} real={cand['real_values']}"
                )
        if group.get("info_candidates"):
            lines.append("  [same-pos info candidates]")
            for cand in group["info_candidates"][:12]:
                lines.append(
                    f"    - info+{cand['offset']} {cand['type']} "
                    f"ghost={cand['ghost_value']} real={cand['real_values']}"
                )
        lines.append("")
    for section, title in (("unit_candidates", "unit_ptr fields"), ("info_candidates", "info_ptr fields")):
        lines.append(f"[{title}]")
        for cand in diff.get(section, [])[:30]:
            lines.append(
                f"- {cand['region']}+{cand['offset']} {cand['type']} "
                f"ghost={cand['ghost_value']} real_unique={cand['real_unique']} real={cand['real_values']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    print("\n" + "=" * 55)
    print("🚀 [SYSTEM BOOT] กำลังสแกนหา Offsets ด้วย AI สถิติ...")
    print("=" * 55)

    pid = get_game_pid()
    base = get_game_base_address(pid)
    if not pid or not base:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)
    cgame = get_cgame_base(scanner, base)
    if not is_valid_ptr(cgame):
        raise RuntimeError("cgame not found")

    units = []
    for u_ptr, is_air in get_all_units(scanner, cgame):
        try:
            units.append(build_record(scanner, u_ptr, is_air))
        except Exception:
            continue
    diff = build_diff_report(scanner, units)
    same_position = build_same_position_report(scanner, units)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs("dumps", exist_ok=True)
    payload = {
        "pid": pid,
        "base": hex(base),
        "cgame": hex(cgame),
        "generated_at": stamp,
        "units": units,
        "diff": diff,
        "same_position": same_position,
    }
    json_path = os.path.join("dumps", f"ghost_unit_runtime_compare_{stamp}.json")
    txt_path = os.path.join("dumps", f"ghost_unit_runtime_compare_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print("\n" + "=" * 50)
    print(" GHOST UNIT RUNTIME COMPARE DUMPER")
    print("=" * 50)
    print(f"[+] Units dumped: {len(units)}")
    print(f"[+] Ghost candidates: {len(diff.get('ghosts', []))} | Real ground baseline: {len(diff.get('real_ground', []))}")
    print(f"[+] Same-position groups: {len(same_position)}")
    print(f"[+] JSON: {os.path.abspath(json_path)}")
    print(f"[+] TEXT: {os.path.abspath(txt_path)}")


if __name__ == "__main__":
    main()
