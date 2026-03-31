import json
import math
import re
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from main import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul
from src.utils.scanner import init_dynamic_offsets


STRING_HINTS = (
    "air",
    "plane",
    "helicopter",
    "heli",
    "jet",
    "tank",
    "ground",
    "ship",
    "boat",
    "fighter",
    "bomber",
    "attacker",
    "exp_",
    "ussr_",
    "germ_",
    "us_",
    "uk_",
    "jp_",
    "cn_",
    "it_",
    "fr_",
    "sw_",
    "il_",
)

SUSPICIOUS_HINTS = (
    "air_defence",
    "structures",
    "dummy",
    "windmill",
    "fortification",
    "exp_aaa",
    "exp_structure",
    "exp_zero",
)

UNIT_FLAG_SCAN_RANGES = [
    (0x000, 0x600, 1, "byte"),
    (0x900, 0x1800, 1, "byte"),
]

INFO_STRING_OFFSETS = list(range(0x00, 0x180, 8))
UNIT_PTR_STRING_SCAN_START = 0x00
UNIT_PTR_STRING_SCAN_END = 0x1800
UNIT_PTR_STRING_SCAN_STEP = 0x8

MAX_CANDIDATES_PER_GROUP = 40
MAX_PRINTED_INFO_STRINGS = 450
MAX_PRINTED_PTR_OFFSETS = 80
TOP_PLAYER_NAME_OFFSETS = 8

PLAYER_NON_NAME_HINTS = (
    "gamedata",
    "tankmodels",
    "air_defence",
    "structures",
    "flightmodels",
    "exp_",
    ".blk",
    "dummy",
    "fortification",
    "battleship",
    "cruiser",
    "fighter",
    "helicopter",
    "light tank",
    "medium tank",
    "heavy tank",
)

PLAYER_MODEL_PREFIXES = (
    "us_",
    "germ_",
    "ussr_",
    "uk_",
    "jp_",
    "cn_",
    "it_",
    "fr_",
    "sw_",
    "il_",
    "air_",
    "exp_",
)


class Reporter:
    def __init__(self):
        self.lines = []

    def log(self, msg=""):
        print(msg)
        self.lines.append(msg)

    def save_text(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def read_ptr(scanner, address):
    raw = scanner.read_mem(address, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def safe_read_c_string(scanner, ptr, max_len=96):
    if not mul.is_valid_ptr(ptr):
        return None
    data = scanner.read_mem(ptr, max_len)
    if not data:
        return None
    raw = data.split(b"\x00")[0]
    if len(raw) < 3:
        return None
    try:
        text = raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if len(text) < 3:
        return None
    if not any(ch.isalnum() for ch in text):
        return None
    return text


def looks_like_player_name(text):
    if not text:
        return False
    t = text.strip()
    tl = t.lower()
    if len(t) < 3 or len(t) > 28:
        return False
    if "/" in t or "\\" in t:
        return False
    if any(h in tl for h in PLAYER_NON_NAME_HINTS):
        return False
    if tl.startswith(PLAYER_MODEL_PREFIXES):
        return False
    if re.fullmatch(r"[a-z0-9_]+", t):
        return False
    if not re.fullmatch(r"[A-Za-z0-9 _\-\[\]\.]+", t):
        return False
    if not any(ch.isalpha() for ch in t):
        return False
    return True


def get_unit_name_and_info(scanner, u_ptr):
    unit_name = "UNKNOWN"
    info_ptr = 0
    try:
        info_raw = scanner.read_mem(u_ptr + mul.OFF_UNIT_INFO, 8)
        if info_raw and len(info_raw) == 8:
            info_ptr = struct.unpack("<Q", info_raw)[0]
            if mul.is_valid_ptr(info_ptr):
                name_ptr_raw = scanner.read_mem(info_ptr + mul.OFF_UNIT_NAME_PTR, 8)
                if name_ptr_raw and len(name_ptr_raw) == 8:
                    name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                    text = safe_read_c_string(scanner, name_ptr, 64)
                    if text:
                        unit_name = "".join(c for c in text if c.isalnum() or c in "-_")
    except Exception:
        pass
    return unit_name, info_ptr


def get_local_label(u_ptr, my_unit, resolved_is_air):
    if u_ptr == my_unit:
        return "MY_AIR" if resolved_is_air else "MY_GROUND"
    return "AIR" if resolved_is_air else "GROUND"


def get_info_string(scanner, info_ptr, off):
    ptr = read_ptr(scanner, info_ptr + off)
    if not mul.is_valid_ptr(ptr):
        return ""
    text = safe_read_c_string(scanner, ptr, 96)
    return text or ""


def collect_units(scanner, base_addr):
    cgame_base = mul.get_cgame_base(scanner, base_addr)
    if cgame_base == 0:
        raise RuntimeError("ไม่พบ CGame")

    all_units = mul.get_all_units(scanner, cgame_base)
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    my_pos = mul.get_unit_pos(scanner, my_unit) if my_unit else None

    rows = []
    for u_ptr, provisional_is_air in all_units:
        status = mul.get_unit_status(scanner, u_ptr)
        if not status:
            continue

        team, state, unit_name, reload_val = status
        if state >= 1:
            continue

        if unit_name == "UNKNOWN":
            unit_name, info_ptr = get_unit_name_and_info(scanner, u_ptr)
        else:
            _, info_ptr = get_unit_name_and_info(scanner, u_ptr)

        profile = mul.get_unit_filter_profile(scanner, u_ptr)
        resolved_is_air = provisional_is_air
        if profile.get("kind") == "air":
            resolved_is_air = True
        elif profile.get("kind") == "ground":
            resolved_is_air = False

        pos = mul.get_unit_pos(scanner, u_ptr)
        dist = -1.0
        if my_pos and pos:
            dx = pos[0] - my_pos[0]
            dy = pos[1] - my_pos[1]
            dz = pos[2] - my_pos[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        vel = mul.get_air_velocity(scanner, u_ptr) if resolved_is_air else mul.get_ground_velocity(scanner, u_ptr)
        speed_kmh = math.sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2]) * 3.6

        mov_off = mul.OFF_AIR_MOVEMENT if resolved_is_air else mul.OFF_GROUND_MOVEMENT
        mov_ptr = read_ptr(scanner, u_ptr + mov_off)

        info_s10 = get_info_string(scanner, info_ptr, 0x10) if mul.is_valid_ptr(info_ptr) else ""
        info_s18 = get_info_string(scanner, info_ptr, 0x18) if mul.is_valid_ptr(info_ptr) else ""
        info_s38 = get_info_string(scanner, info_ptr, 0x38) if mul.is_valid_ptr(info_ptr) else ""
        info_s40 = get_info_string(scanner, info_ptr, 0x40) if mul.is_valid_ptr(info_ptr) else ""
        model_name = profile.get("display_name") or unit_name

        rows.append(
            {
                "u_ptr": u_ptr,
                "is_air": resolved_is_air,
                "label": get_local_label(u_ptr, my_unit, resolved_is_air),
                "team": team,
                "state": state,
                "reload": reload_val,
                "name": unit_name,
                "model_name": model_name,
                "info_ptr": info_ptr,
                "pos": pos,
                "dist_m": dist,
                "vel": vel,
                "speed_kmh": speed_kmh,
                "mov_ptr": mov_ptr,
                "kind": profile.get("kind"),
                "skip": bool(profile.get("skip")),
                "reason": profile.get("reason") or "",
                "tag": profile.get("tag") or "",
                "path": profile.get("path") or "",
                "unit_key": profile.get("unit_key") or "",
                "info_s10": info_s10,
                "info_s18": info_s18,
                "info_s38": info_s38,
                "info_s40": info_s40,
            }
        )
    return cgame_base, my_unit, my_team, rows


def print_unit_table(r, rows):
    r.log("=" * 160)
    r.log("🧬 UNIT KIND DUMPER")
    r.log("=" * 160)
    r.log(
        f"{'Label':<10} | {'Kind':<6} | {'Skip':<4} | {'Why':<14} | {'Team':<4} | "
        f"{'Dist(m)':>8} | {'Spd(km/h)':>9} | {'Unit Ptr':<12} | {'Info Ptr':<12} | {'Model/Name'}"
    )
    r.log("-" * 160)
    for row in rows:
        why = row.get("reason") or (row.get("tag") or "-")
        dist_txt = f"{row['dist_m']:.1f}" if row["dist_m"] >= 0 else "-"
        spd_txt = f"{row['speed_kmh']:.1f}"
        name_view = row.get("model_name") or row.get("name") or ""
        r.log(
            f"{row['label']:<10} | {str(row.get('kind') or '-'):<6} | {('Y' if row.get('skip') else 'N'):<4} | "
            f"{why[:14]:<14} | {row['team']:<4} | {dist_txt:>8} | {spd_txt:>9} | "
            f"{hex(row['u_ptr']):<12} | {hex(row['info_ptr']) if row['info_ptr'] else '-':<12} | {name_view}"
        )
    r.log("-" * 160)


def print_summary(r, rows):
    total = len(rows)
    skip_count = sum(1 for x in rows if x.get("skip"))
    play_count = total - skip_count
    air_count = sum(1 for x in rows if x.get("is_air"))
    ground_count = total - air_count
    team_counter = Counter(x.get("team") for x in rows)
    tag_counter = Counter((x.get("tag") or "-").lower() for x in rows)
    reason_counter = Counter((x.get("reason") or "-").lower() for x in rows)
    model_counter = Counter((x.get("model_name") or "-").lower() for x in rows if not x.get("skip"))

    r.log("\n📊 Summary")
    r.log("-" * 120)
    r.log(f"Total units: {total} | Playable-ish (Skip=N): {play_count} | Skipped: {skip_count}")
    r.log(f"Air: {air_count} | Ground: {ground_count}")
    r.log("Teams: " + ", ".join(f"{k}:{v}" for k, v in sorted(team_counter.items())))
    r.log("Top tags: " + ", ".join(f"{k}:{v}" for k, v in tag_counter.most_common(10)))
    r.log("Top skip reasons: " + ", ".join(f"{k}:{v}" for k, v in reason_counter.most_common(10)))
    r.log("Top playable models: " + ", ".join(f"{k}:{v}" for k, v in model_counter.most_common(15)))
    r.log("-" * 120)


def print_non_skipped_suspicious(r, rows):
    suspicious = []
    for row in rows:
        if row.get("skip"):
            continue
        text_pool = " | ".join(
            [
                row.get("name") or "",
                row.get("model_name") or "",
                row.get("tag") or "",
                row.get("path") or "",
                row.get("info_s10") or "",
                row.get("info_s18") or "",
                row.get("info_s38") or "",
                row.get("info_s40") or "",
            ]
        ).lower()
        if any(h in text_pool for h in SUSPICIOUS_HINTS):
            suspicious.append(row)

    if not suspicious:
        return

    r.log("\n⚠ Non-skipped suspicious units")
    r.log("-" * 140)
    for row in suspicious:
        r.log(
            f"{row['label']:<10} | ptr={hex(row['u_ptr'])} | team={row['team']} | "
            f"spd={row['speed_kmh']:.1f} | tag='{row.get('tag') or ''}' | model='{row.get('model_name') or ''}' | "
            f"path='{(row.get('path') or '')[:64]}'"
        )
    r.log("-" * 140)


def print_info_ptr_reuse(r, rows):
    grouped = defaultdict(list)
    for row in rows:
        info_ptr = row.get("info_ptr", 0)
        if mul.is_valid_ptr(info_ptr):
            grouped[info_ptr].append(row)

    hot = [(ptr, items) for ptr, items in grouped.items() if len(items) >= 3]
    if not hot:
        return

    hot.sort(key=lambda x: len(x[1]), reverse=True)
    r.log("\n🧠 Hot info_ptr reuse (count >= 3)")
    r.log("-" * 160)
    r.log(f"{'Info Ptr':<12} | {'Count':<5} | {'SkipY':<5} | {'Teams':<10} | {'Tags':<24} | {'Models'}")
    r.log("-" * 160)
    for ptr, items in hot[:30]:
        skip_y = sum(1 for x in items if x.get("skip"))
        teams = ",".join(str(v) for v in sorted({x.get("team") for x in items}))
        tags = ",".join(sorted({(x.get("tag") or "-").lower() for x in items}))
        models = ",".join(sorted({(x.get("model_name") or "-").lower() for x in items}))
        r.log(f"{hex(ptr):<12} | {len(items):<5} | {skip_y:<5} | {teams:<10} | {tags[:24]:<24} | {models[:70]}")
    r.log("-" * 160)


def _collect_group_bytes(scanner, rows, off):
    vals = []
    for row in rows:
        data = scanner.read_mem(row["u_ptr"] + off, 1)
        if not data or len(data) < 1:
            continue
        vals.append(data[0])
    return vals


def _print_split_candidates(r, title, candidates):
    r.log(f"\n📌 {title}")
    r.log("-" * 140)
    r.log(f"{'Offset':<10} | {'Type':<6} | {'A Values':<38} | {'B Values':<38} | {'Score':<5} | {'Note'}")
    r.log("-" * 140)
    if not candidates:
        r.log("[-] ยังไม่เจอ byte flag ที่แยกกลุ่มได้ชัดเจนใน range ที่สแกน")
        return
    for score, off, typ, a_set, b_set, note in candidates[:MAX_CANDIDATES_PER_GROUP]:
        a_text = ", ".join(hex(v) for v in a_set[:10])
        b_text = ", ".join(hex(v) for v in b_set[:10])
        r.log(f"{hex(off):<10} | {typ:<6} | {a_text:<38} | {b_text:<38} | {score:<5} | {note}")


def analyze_group_split(scanner, rows_a, rows_b):
    candidates = []
    if len(rows_a) < 2 or len(rows_b) < 2:
        return candidates

    for start, end, step, typ in UNIT_FLAG_SCAN_RANGES:
        for off in range(start, end, step):
            a_vals = _collect_group_bytes(scanner, rows_a, off)
            b_vals = _collect_group_bytes(scanner, rows_b, off)
            if len(a_vals) < 2 or len(b_vals) < 2:
                continue
            a_set = sorted(set(a_vals))
            b_set = sorted(set(b_vals))
            overlap = set(a_set) & set(b_set)
            if overlap:
                continue

            a_common = Counter(a_vals).most_common(1)[0][1]
            b_common = Counter(b_vals).most_common(1)[0][1]
            score = a_common + b_common
            note = "stable split" if len(a_set) == 1 and len(b_set) == 1 else "disjoint split"
            candidates.append((score, off, typ, a_set, b_set, note))

    candidates.sort(reverse=True)
    return candidates


def analyze_flag_offsets(scanner, r, rows):
    air_rows = [x for x in rows if x.get("is_air")]
    ground_rows = [x for x in rows if not x.get("is_air")]
    skip_rows = [x for x in rows if x.get("skip")]
    keep_rows = [x for x in rows if not x.get("skip")]

    air_ground = analyze_group_split(scanner, air_rows, ground_rows)
    _print_split_candidates(r, "Candidate Flag Offsets (air vs ground)", air_ground)

    skip_keep = analyze_group_split(scanner, skip_rows, keep_rows)
    _print_split_candidates(r, "Candidate Flag Offsets (skip vs playable)", skip_keep)


def scan_info_strings(scanner, r, rows):
    r.log("\n📝 Candidate Strings จาก info_ptr")
    r.log("-" * 140)
    printed = 0
    trimmed = 0
    seen = set()
    all_rows = []
    for row in rows:
        info_ptr = row.get("info_ptr", 0)
        if not mul.is_valid_ptr(info_ptr):
            continue
        for off in INFO_STRING_OFFSETS:
            ptr = read_ptr(scanner, info_ptr + off)
            text = safe_read_c_string(scanner, ptr, 120)
            if not text:
                continue
            lowered = text.lower()
            if not any(h in lowered for h in STRING_HINTS):
                continue
            key = (row["u_ptr"], off, text)
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(
                {
                    "label": row["label"],
                    "unit_ptr": row["u_ptr"],
                    "info_ptr": info_ptr,
                    "info_off": off,
                    "text": text,
                    "model": row.get("model_name") or "",
                }
            )
            printed += 1
            if printed <= MAX_PRINTED_INFO_STRINGS:
                r.log(
                    f"{row['label']:<10} | unit={hex(row['u_ptr'])} | info_off={hex(off):<6} | "
                    f"text='{text}' | model='{row.get('model_name') or ''}'"
                )
            else:
                trimmed += 1
    if printed == 0:
        r.log("[-] ยังไม่เจอ string ที่เข้าข่ายใน info_ptr + 0x00..0x178")
    elif trimmed > 0:
        r.log(f"... (ตัดแสดง {trimmed} บรรทัดใน console แต่ยังถูกบันทึกลงไฟล์ JSON)")
    return all_rows


def scan_unit_pointer_strings(scanner, rows):
    offset_hits = defaultdict(list)
    for off in range(UNIT_PTR_STRING_SCAN_START, UNIT_PTR_STRING_SCAN_END, UNIT_PTR_STRING_SCAN_STEP):
        for row in rows:
            ptr = read_ptr(scanner, row["u_ptr"] + off)
            if not mul.is_valid_ptr(ptr):
                continue
            text = safe_read_c_string(scanner, ptr, 96)
            if not text:
                continue
            offset_hits[off].append((row, text))

    summaries = []
    for off, hits in offset_hits.items():
        unit_count = len({h[0]["u_ptr"] for h in hits})
        if unit_count < 2:
            continue
        unique_texts = sorted(set(t for _, t in hits))
        player_like = sorted(set(t for _, t in hits if looks_like_player_name(t)))
        score = (len(player_like) * 8) + min(unit_count, 30) + min(len(unique_texts), 30)
        summaries.append(
            {
                "offset": off,
                "coverage": unit_count,
                "unique_count": len(unique_texts),
                "player_like_count": len(player_like),
                "examples": unique_texts[:8],
                "player_examples": player_like[:8],
                "score": score,
            }
        )

    summaries.sort(key=lambda x: (x["player_like_count"], x["coverage"], x["unique_count"], x["score"]), reverse=True)
    return summaries, offset_hits


def print_pointer_string_scan(r, summaries):
    r.log("\n🔍 Unit pointer-string scan (0x00..0x17F8 step 0x8)")
    r.log("-" * 160)
    r.log(
        f"{'Offset':<10} | {'Cover':<5} | {'Unique':<6} | {'PlayerLike':<10} | {'Examples':<72} | {'Player Examples'}"
    )
    r.log("-" * 160)
    if not summaries:
        r.log("[-] ไม่เจอ offset ที่อ่านเป็น pointer->string ได้ในช่วงที่สแกน")
        return
    for item in summaries[:MAX_PRINTED_PTR_OFFSETS]:
        examples = ", ".join(item["examples"])
        player_examples = ", ".join(item["player_examples"])
        r.log(
            f"{hex(item['offset']):<10} | {item['coverage']:<5} | {item['unique_count']:<6} | "
            f"{item['player_like_count']:<10} | {examples[:72]:<72} | {player_examples[:60]}"
        )


def print_player_name_candidates(r, rows, summaries, offset_hits):
    candidates = [x for x in summaries if x["player_like_count"] >= 2 and x["coverage"] >= 2]
    r.log("\n🧑‍✈️ Candidate player-name offsets")
    r.log("-" * 120)
    if not candidates:
        r.log("[-] ยังไม่เจอ offset ที่มีลักษณะเป็นชื่อผู้เล่นชัดเจน")
        return []

    r.log(f"{'Offset':<10} | {'Coverage':<8} | {'PlayerLike':<10} | Examples")
    r.log("-" * 120)
    for item in candidates[:TOP_PLAYER_NAME_OFFSETS]:
        ex = ", ".join(item["player_examples"][:6]) or ", ".join(item["examples"][:4])
        r.log(f"{hex(item['offset']):<10} | {item['coverage']:<8} | {item['player_like_count']:<10} | {ex}")

    top_offsets = [x["offset"] for x in candidates[:3]]
    r.log("\n🧾 Per-unit player-like strings (top offsets)")
    r.log("-" * 140)
    for row in rows:
        parts = []
        for off in top_offsets:
            text = None
            for hit_row, hit_text in offset_hits.get(off, []):
                if hit_row["u_ptr"] == row["u_ptr"]:
                    text = hit_text
                    break
            if text and looks_like_player_name(text):
                parts.append(f"{hex(off)}='{text}'")
        if parts:
            r.log(
                f"{row['label']:<10} | unit={hex(row['u_ptr'])} | team={row['team']} | "
                f"model='{row.get('model_name') or ''}' | " + " ; ".join(parts)
            )
    return top_offsets


def dump_selected_units(scanner, r, rows):
    interesting = []
    my_rows = [x for x in rows if x["label"].startswith("MY_")]
    if my_rows:
        interesting.extend(my_rows[:1])
    air_rows = [x for x in rows if x["is_air"] and not x["label"].startswith("MY_")]
    ground_rows = [x for x in rows if (not x["is_air"]) and not x["label"].startswith("MY_")]
    if air_rows:
        interesting.append(air_rows[0])
    if ground_rows:
        interesting.append(ground_rows[0])

    r.log("\n🔬 Detailed Dump (my unit + first air + first ground)")
    r.log("-" * 140)
    for row in interesting:
        r.log(
            f"\n[{row['label']}] unit={hex(row['u_ptr'])} | info={hex(row['info_ptr']) if row['info_ptr'] else '-'} "
            f"| team={row['team']} | model='{row.get('model_name') or ''}' | speed={row['speed_kmh']:.2f} km/h"
        )

        inspect_offsets = sorted(
            {
                0x18,
                0x1C,
                0x20,
                0x130,
                0x138,
                0x200,
                0x340,
                0x358,
                0xD10,
                0xD18,
                mul.OFF_UNIT_STATE,
                mul.OFF_UNIT_TEAM,
                mul.OFF_UNIT_INFO,
            }
        )
        for off in inspect_offsets:
            size = 8 if off in (0x18, 0x20, 0x340, 0x358, 0xD10, 0xD18, mul.OFF_UNIT_INFO) else 4
            data = scanner.read_mem(row["u_ptr"] + off, size)
            if not data or len(data) < size:
                continue
            if size == 8:
                val = struct.unpack("<Q", data)[0]
                text = hex(val)
            else:
                val = struct.unpack("<I", data)[0]
                text = hex(val)
            r.log(f" unit+{hex(off):<6} = {text}")

        info_ptr = row.get("info_ptr", 0)
        if mul.is_valid_ptr(info_ptr):
            for off in INFO_STRING_OFFSETS:
                ptr = read_ptr(scanner, info_ptr + off)
                text = safe_read_c_string(scanner, ptr, 96)
                if text and any(h in text.lower() for h in STRING_HINTS):
                    r.log(f" info+{hex(off):<6} -> '{text}'")


def save_report(r, meta, rows, summaries, player_offsets, info_string_rows):
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path("dumps")
    txt_path = out_dir / f"unit_kind_dump_{ts}.txt"
    json_path = out_dir / f"unit_kind_dump_{ts}.json"

    r.save_text(txt_path)

    payload = {
        "meta": meta,
        "rows": rows,
        "pointer_string_summaries": summaries[:200],
        "player_name_candidate_offsets": [hex(x) for x in player_offsets],
        "info_strings": info_string_rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return txt_path, json_path


def main():
    r = Reporter()
    r.log("[*] 🚀 เริ่ม UNIT KIND DUMPER (extended)...")
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)

    init_dynamic_offsets(scanner, base_addr)
    cgame_base, my_unit, my_team, rows = collect_units(scanner, base_addr)

    if not rows:
        r.log("[-] ไม่พบยูนิตให้วิเคราะห์")
        return

    r.log(f"[*] CGame = {hex(cgame_base)}")
    r.log(f"[*] MY_UNIT = {hex(my_unit) if my_unit else '0x0'} | MY_TEAM = {my_team}")

    print_unit_table(r, rows)
    print_summary(r, rows)
    print_non_skipped_suspicious(r, rows)
    print_info_ptr_reuse(r, rows)
    analyze_flag_offsets(scanner, r, rows)
    info_string_rows = scan_info_strings(scanner, r, rows)

    ptr_summaries, ptr_hits = scan_unit_pointer_strings(scanner, rows)
    print_pointer_string_scan(r, ptr_summaries)
    player_offsets = print_player_name_candidates(r, rows, ptr_summaries, ptr_hits)

    dump_selected_units(scanner, r, rows)

    meta = {
        "pid": pid,
        "base_addr": hex(base_addr),
        "cgame_base": hex(cgame_base),
        "my_unit": hex(my_unit) if my_unit else "0x0",
        "my_team": my_team,
        "row_count": len(rows),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    txt_path, json_path = save_report(r, meta, rows, ptr_summaries, player_offsets, info_string_rows)
    r.log("")
    r.log(f"[+] บันทึกรายงานแล้ว: {txt_path}")
    r.log(f"[+] บันทึก JSON แล้ว:   {json_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Exit")
    except Exception as e:
        print(f"[-] error: {e}")
        sys.exit(1)
