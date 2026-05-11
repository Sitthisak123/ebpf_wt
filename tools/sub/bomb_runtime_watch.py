#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
import src.utils.mul as mul
from tools.ballistic_layout_dumper import try_get_active_weapon, read_u32, read_f32
from tools.sub.air_secondary_weapon_dumper import _scan_loadout_anchors


WATCH_SIZE = 0x180
CHILD_040_FOCUS_OFFSETS = tuple(range(0x90, 0xAC, 4))
WATCH_WARMUP_SEC = 1.0


def _hex0(v):
    try:
        return hex(int(v or 0))
    except Exception:
        return "0x0"


def _looks_like_runtime_ptr(ptr_text):
    try:
        ptr = int(str(ptr_text or "0"), 16)
    except Exception:
        return False
    return ptr >= 0x100000


def _is_readable_ptr(scanner, ptr_text, size=0x20):
    try:
        ptr = int(str(ptr_text or "0"), 16)
    except Exception:
        return False
    if ptr <= 0:
        return False
    data = scanner.read_mem(ptr, size)
    return bool(data and len(data) >= min(size, 0x10))


def _entry_text_blob(summary):
    parts = []
    head = str(summary.get("head_text") or "").strip()
    if head:
        parts.append(head)
    for item in summary.get("inline_strings") or []:
        txt = str(item.get("text") or "").strip()
        if txt:
            parts.append(txt)
    return " | ".join(parts).lower()


def _is_bomb_semantic_blob(blob):
    blob = str(blob or "").lower()
    keys = (
        "bomb",
        "pylon",
        "ammo",
        "weapon",
        "count",
        "preset",
        "loadout",
        "mask",
    )
    return any(k in blob for k in keys)


def _pick_best_anchor(anchors):
    best = None
    for a in anchors:
        text = str(a.get("text") or "").lower()
        score = int(a.get("score") or 0)
        if "bomb" in text:
            score += 20
        child_230 = None
        for child in a.get("child_objects", []):
            if child.get("parent_off") == "0x230":
                child_230 = child
                break
        ptr_entries = child_230.get("ptr_code_entries", []) if child_230 else []
        valid_entries = [e for e in ptr_entries if 0 <= int(e.get("code_a") or -1) <= 64 and 0 <= int(e.get("code_b") or -1) <= 64]
        score += len(valid_entries) * 10
        candidate = (score, -int(a.get("unit_off", "0x0"), 16), a)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _pick_best_entry_child(scanner, anchor):
    best = None
    for child in anchor.get("child_objects", []):
        if not _looks_like_runtime_ptr(child.get("ptr")) or not _is_readable_ptr(scanner, child.get("ptr")):
            continue
        entries = child.get("ptr_code_entries", [])
        valid = [
            e for e in entries
            if 0 <= int(e.get("code_a") or -1) <= 64
            and 0 <= int(e.get("code_b") or -1) <= 64
            and not (int(e.get("code_a") or 0) == 0 and int(e.get("code_b") or 0) == 0)
        ]
        meaningful = []
        semantic_score = 0
        for e in valid:
            summary = e.get("summary") or {}
            if summary.get("head_text") or summary.get("inline_strings") or summary.get("int_candidates") or summary.get("float_candidates"):
                meaningful.append(e)
            blob = _entry_text_blob(summary)
            if "pylon" in blob:
                semantic_score += 80
            if "bomb" in blob:
                semantic_score += 40
            if "_ammo" in blob or "ammo" in blob:
                semantic_score += 10
            if ".blk" in blob:
                semantic_score -= 80
            if "attachable_wear" in blob or "hands_item" in blob:
                semantic_score -= 120
            if "driver_optics" in blob:
                semantic_score -= 40
        child_head = str(child.get("head_text") or "").lower()
        if ".blk" in child_head:
            semantic_score -= 120
        child_blob_parts = [child_head]
        for item in child.get("inline_strings") or []:
            child_blob_parts.append(str(item.get("text") or "").lower())
        child_blob = " | ".join(child_blob_parts)
        if "totalbombcount" in child_blob:
            semantic_score += 140
        if "haspresetweapons" in child_blob:
            semantic_score += 80
        if "weaponmask" in child_blob:
            semantic_score += 60
        score = len(meaningful) * 20 + len(valid) * 5 + semantic_score
        score += len(child.get("float_rows", []))
        score += len(child.get("int_candidates", [])) // 4
        candidate = (score, -int(child.get("parent_off", "0x0"), 16), child)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _rank_child_candidates(scanner, anchor):
    ranked = []
    for child in anchor.get("child_objects", []):
        if not _looks_like_runtime_ptr(child.get("ptr")) or not _is_readable_ptr(scanner, child.get("ptr")):
            continue
        entries = child.get("ptr_code_entries", [])
        valid = [
            e for e in entries
            if 0 <= int(e.get("code_a") or -1) <= 64
            and 0 <= int(e.get("code_b") or -1) <= 64
            and not (int(e.get("code_a") or 0) == 0 and int(e.get("code_b") or 0) == 0)
        ]
        score = len(valid) * 10
        score += len(child.get("int_candidates", [])) // 2
        score += len(child.get("float_candidates", []))
        blob_parts = [str(child.get("head_text") or "").lower()]
        for item in child.get("inline_strings") or []:
            blob_parts.append(str(item.get("text") or "").lower())
        blob = " | ".join(blob_parts)
        if "pylon" in blob:
            score += 40
        if "ammo" in blob or "bone_flag" in blob:
            score += 8
        if "totalbombcount" in blob:
            score += 160
        if "haspresetweapons" in blob:
            score += 100
        if "weaponmask" in blob:
            score += 80
        if "bomb" in blob:
            score += 60
        if "presetweapon" in blob or "weaponry" in blob or "cannon" in blob:
            score += 40
        if ".blk" in blob or "textarea" in blob:
            score -= 80
        ranked.append((score, -int(child.get("parent_off", "0x0"), 16), child))
    ranked.sort(reverse=True)
    return [item[2] for item in ranked]


def _find_watch_targets(scanner, unit_ptr):
    anchors = _scan_loadout_anchors(scanner, unit_ptr)
    anchor = _pick_best_anchor(anchors)
    if not anchor:
        return None, []

    targets = []

    ranked_children = _rank_child_candidates(scanner, anchor)
    if not ranked_children:
        targets.append({
            "label": "preset_root",
            "ptr": int(anchor["ptr"], 16),
            "head": anchor.get("text", ""),
            "unit_off": anchor.get("unit_off", "unknown"),
        })
        return anchor, targets

    entry_table_child = _pick_best_entry_child(scanner, anchor)
    if entry_table_child and any(
        not (int(rec.get("code_a") or 0) == 0 and int(rec.get("code_b") or 0) == 0)
        for rec in entry_table_child.get("ptr_code_entries", [])
    ):
        targets.append({
            "label": "entry_table",
            "ptr": int(entry_table_child["ptr"], 16),
            "head": entry_table_child.get("head_text", ""),
            "parent_off": entry_table_child.get("parent_off", ""),
        })

    forced_parent_offsets = {"0x40", "0x48", "0x160", "0x210"}
    chosen_children = []
    used_ptrs = set()
    for child in ranked_children:
        if child["ptr"] == (entry_table_child or {}).get("ptr"):
            continue
        if child["ptr"] in used_ptrs:
            continue
        if child.get("parent_off") in forced_parent_offsets:
            chosen_children.append(child)
            used_ptrs.add(child["ptr"])

    if not chosen_children:
        for child in ranked_children:
            if child["ptr"] == (entry_table_child or {}).get("ptr"):
                continue
            chosen_children.append(child)
            break

    for child in chosen_children[:3]:
        t = {
            "label": f"child_{child.get('parent_off','0x0')}",
            "ptr": int(child["ptr"], 16),
            "head": child.get("head_text", ""),
            "parent_off": child.get("parent_off", ""),
        }
        if child.get("parent_off") == "0x40":
            t["watch_offsets"] = [_hex0(off) for off in CHILD_040_FOCUS_OFFSETS]
        targets.append(t)

    if not targets:
        targets.append({
            "label": "preset_root",
            "ptr": int(anchor["ptr"], 16),
            "head": anchor.get("text", ""),
            "unit_off": anchor.get("unit_off", "unknown"),
        })

    seen = set()
    uniq = []
    for t in targets:
        if t["ptr"] in seen:
            continue
        seen.add(t["ptr"])
        uniq.append(t)
    return anchor, uniq


def _snapshot_object(scanner, ptr, size=WATCH_SIZE, only_offsets=None):
    raw = scanner.read_mem(ptr, size) or b""
    u32s = {}
    f32s = {}
    offset_iter = range(0, len(raw), 4)
    if only_offsets:
        wanted = set(int(x) for x in only_offsets)
        offset_iter = [off for off in offset_iter if off in wanted]
    for off in offset_iter:
        u32s[off] = read_u32(scanner, ptr + off)
        f = read_f32(scanner, ptr + off)
        if f is not None and -500000.0 <= f <= 500000.0:
            f32s[off] = f
    return {"u32s": u32s, "f32s": f32s}


def _diff_snapshot(prev, curr):
    changes = []
    for off in sorted(curr["u32s"]):
        a = prev["u32s"].get(off)
        b = curr["u32s"].get(off)
        if a != b:
            changes.append({"kind": "u32", "off": _hex0(off), "before": int(a or 0), "after": int(b or 0)})
    for off in sorted(curr["f32s"]):
        a = prev["f32s"].get(off)
        b = curr["f32s"].get(off)
        if a is None or b is None:
            continue
        if abs(a - b) > 1e-6:
            changes.append({"kind": "f32", "off": _hex0(off), "before": round(float(a), 6), "after": round(float(b), 6)})
    return changes


def _offset_summary(all_changes):
    summary = {}
    for item in all_changes:
        if item.get("label") != "child_0x40":
            continue
        for ch in item.get("changes", []):
            off = ch.get("off")
            rec = summary.setdefault(off, {
                "u32_transitions": 0,
                "f32_transitions": 0,
                "values": [],
            })
            if ch.get("kind") == "u32":
                rec["u32_transitions"] += 1
                rec["values"].append((ch.get("before"), ch.get("after")))
            elif ch.get("kind") == "f32":
                rec["f32_transitions"] += 1
    return summary


def main():
    print("\n" + "=" * 55)
    print("🚀 [SYSTEM BOOT] กำลัง watch หา Bomb Runtime changes...")
    print("=" * 55)

    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    unit_ptr, _weapon_ptr, _weapon_source, _scan_notes = try_get_active_weapon(scanner, base_addr)
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}

    anchor, targets = _find_watch_targets(scanner, unit_ptr)

    print("\n" + "=" * 58)
    print(" BOMB RUNTIME WATCH")
    print("=" * 58)
    print(f"unit={_hex0(unit_ptr)} unit_key={dna.get('name_key') or ''} short_name={dna.get('short_name') or ''}")
    if anchor:
        print(f"anchor_ptr={anchor.get('ptr')} text={anchor.get('text','')} unit_off={anchor.get('unit_off','unknown')}")
    for idx, t in enumerate(targets):
        extra = ""
        if "code_a" in t:
            extra = f" code=({t['code_a']},{t['code_b']})"
        print(f"[{idx}] {t['label']} ptr={_hex0(t['ptr'])} head={t.get('head','')}{extra}")
    print("[*] Watch mode active. ปล่อย bomb แล้วรอ change log.")

    prev = {
        t["ptr"]: _snapshot_object(
            scanner,
            t["ptr"],
            only_offsets=[int(x, 16) for x in t.get("watch_offsets", [])] if t.get("watch_offsets") else None,
        )
        for t in targets
    }
    all_changes = []
    start = time.time()
    quiet_rounds = 0
    while True:
        time.sleep(0.15)
        any_change = False
        now = time.time()
        for t in targets:
            ptr = t["ptr"]
            curr = _snapshot_object(
                scanner,
                ptr,
                only_offsets=[int(x, 16) for x in t.get("watch_offsets", [])] if t.get("watch_offsets") else None,
            )
            changes = _diff_snapshot(prev[ptr], curr)
            if changes and (now - start) >= WATCH_WARMUP_SEC:
                any_change = True
                quiet_rounds = 0
                print(f"\n[change] t={now-start:.2f}s label={t['label']} ptr={_hex0(ptr)}")
                for ch in changes[:24]:
                    print(f"  {ch['kind']} {ch['off']}: {ch['before']} -> {ch['after']}")
                all_changes.append({
                    "t": round(now - start, 3),
                    "label": t["label"],
                    "ptr": _hex0(ptr),
                    "changes": changes[:64],
                })
            prev[ptr] = curr
        if not any_change:
            quiet_rounds += 1
        if quiet_rounds >= 80:
            break

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "unit_key": str(dna.get("name_key") or ""),
        "short_name": str(dna.get("short_name") or ""),
        "anchor": anchor,
        "targets": targets,
        "changes": all_changes,
        "child_0x40_offset_summary": _offset_summary(all_changes),
    }
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"bomb_runtime_watch_{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[+] JSON: {json_path}")


if __name__ == "__main__":
    main()
