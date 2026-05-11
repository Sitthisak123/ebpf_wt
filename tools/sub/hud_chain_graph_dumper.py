#!/usr/bin/env python3
import json
import os
import struct
import sys
import time
from collections import deque
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
import src.utils.mul as mul


GLOBAL_ROOTS = (
    ("hud_ref_a", 0x6CD49E8),
    ("hud_ref_b", 0x6C0FEA8),
    ("hud_ref_c", 0x6CDB9B8),
)
SCAN_WINDOW = 0x1000
PTR_STRIDE = 0x8
MAX_DEPTH = 3
MAX_NODES = 600


def _hex0(v):
    try:
        return hex(int(v or 0))
    except Exception:
        return "0x0"


def _read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def _read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<f", raw)[0]


def _looks_like_ptr(ptr):
    return ptr >= 0x100000 and mul.is_valid_ptr(ptr)


def _is_readable_ptr(scanner, ptr, size=0x20):
    if not _looks_like_ptr(ptr):
        return False
    raw = scanner.read_mem(ptr, size)
    return bool(raw and len(raw) >= min(size, 0x10))


def _read_inline_ascii(scanner, ptr, size=96):
    if not _looks_like_ptr(ptr):
        return ""
    raw = scanner.read_mem(ptr, size)
    if not raw:
        return ""
    try:
        text = raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""
    if len(text) < 2 or not any(ch.isalnum() for ch in text):
        return ""
    return text


def _extract_inline_strings(raw, min_len=4, limit=10):
    out = []
    for off in range(len(raw)):
        if not (32 <= raw[off] < 127):
            continue
        if off > 0 and 32 <= raw[off - 1] < 127:
            continue
        end = off
        while end < len(raw) and 32 <= raw[end] < 127:
            end += 1
        if end - off < min_len:
            continue
        if end < len(raw) and raw[end] != 0:
            continue
        try:
            text = raw[off:end].decode("utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not any(ch.isalnum() for ch in text):
            continue
        out.append({"off": _hex0(off), "text": text})
        if len(out) >= limit:
            break
    return out


def _node_summary(scanner, ptr):
    raw = scanner.read_mem(ptr, 0x180) or b""
    head = _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96) or ""
    inline = _extract_inline_strings(raw, min_len=4, limit=10)
    ints = []
    for off in range(0, min(len(raw), 0x120), 4):
        u = _read_u32(scanner, ptr + off)
        if u in (0, 1, 2, 3, 4, 5, 6, 8, 9, 13, 32, 64, 79, 97, 114, 201, 250, 500):
            ints.append({"off": _hex0(off), "u32": int(u)})
    return {
        "ptr": _hex0(ptr),
        "head_text": head,
        "inline_strings": inline,
        "int_hits": ints[:16],
    }


def _node_score(summary):
    blob_parts = [str(summary.get("head_text") or "").lower()]
    for item in summary.get("inline_strings") or []:
        blob_parts.append(str(item.get("text") or "").lower())
    blob = " | ".join(blob_parts)
    score = 0
    for key, weight in (
        ("hud", 20),
        ("bomb", 18),
        ("weapon", 12),
        ("slot", 12),
        ("trigger", 10),
        ("ccip", 18),
        ("target", 8),
        ("release", 14),
        ("guidance", 8),
        ("ammo", 6),
    ):
        if key in blob:
            score += weight
    if summary.get("head_text"):
        score += 4
    score += min(len(summary.get("inline_strings") or []), 6)
    return score


def _collect_runtime_seeds(scanner, base_addr, unit_ptr):
    seeds = []
    seen = set()

    def _add(label, ptr, source):
        if not _is_readable_ptr(scanner, ptr, 0x20):
            return
        if ptr in seen:
            return
        seen.add(ptr)
        seeds.append({
            "label": label,
            "global_off": source,
            "ptr": ptr,
        })

    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    _add("cgame_live", cgame_ptr, "dynamic")

    _add("my_unit", unit_ptr or 0, "dynamic")

    if unit_ptr:
        info_ptr = _read_ptr(scanner, unit_ptr + mul.OFF_UNIT_INFO)
        _add("my_unit_info", info_ptr, f"my_unit+{_hex0(mul.OFF_UNIT_INFO)}")

    if cgame_ptr:
        camera_ptr = _read_ptr(scanner, cgame_ptr + mul.OFF_CAMERA_PTR)
        _add("camera_ptr", camera_ptr, f"cgame+{_hex0(mul.OFF_CAMERA_PTR)}")
        nested_camera_ptr = _read_ptr(scanner, camera_ptr) if camera_ptr else 0
        _add("camera_nested", nested_camera_ptr, "camera_ptr+0x0")
        weapon_ptr = _read_ptr(scanner, cgame_ptr + mul.OFF_WEAPON_PTR)
        _add("weapon_ptr", weapon_ptr, f"cgame+{_hex0(mul.OFF_WEAPON_PTR)}")

    for label, off in GLOBAL_ROOTS:
        ptr = _read_ptr(scanner, base_addr + off)
        _add(label, ptr, _hex0(off))

    return seeds


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    unit_ptr, _my_team = mul.get_local_team(scanner, base_addr)
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr or 0) or {}

    seeds = _collect_runtime_seeds(scanner, base_addr, unit_ptr or 0)

    visited = set()
    queue = deque()
    nodes = []
    edges = []
    for seed in seeds:
        queue.append((seed["label"], seed["global_off"], seed["ptr"], 0, []))

    while queue and len(nodes) < MAX_NODES:
        seed_label, seed_off, ptr, depth, path = queue.popleft()
        if ptr in visited:
            continue
        visited.add(ptr)
        summary = _node_summary(scanner, ptr)
        node = {
            "seed": seed_label,
            "seed_off": seed_off,
            "ptr": _hex0(ptr),
            "depth": depth,
            "path": path,
            "summary": summary,
            "score": _node_score(summary),
        }
        nodes.append(node)
        if depth >= MAX_DEPTH:
            continue
        for off in range(0, SCAN_WINDOW, PTR_STRIDE):
            child = _read_ptr(scanner, ptr + off)
            if not _is_readable_ptr(scanner, child, 0x20):
                continue
            child_path = path + [{"from": _hex0(ptr), "field_off": _hex0(off), "to": _hex0(child)}]
            queue.append((seed_label, seed_off, child, depth + 1, child_path))
            edges.append({"from": _hex0(ptr), "field_off": _hex0(off), "to": _hex0(child)})

    nodes.sort(key=lambda n: (-n["score"], n["depth"], n["ptr"]))
    top_nodes = nodes[:80]

    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr or 0),
        "unit_key": str(dna.get("name_key") or ""),
        "short_name": str(dna.get("short_name") or ""),
        "family": str(dna.get("family") or ""),
        "seeds": [{"label": s["label"], "global_off": s["global_off"], "ptr": _hex0(s["ptr"])} for s in seeds],
        "top_nodes": top_nodes,
        "edge_count": len(edges),
    }

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"hud_chain_graph_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"hud_chain_graph_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("=" * 58)
    lines.append(" HUD CHAIN GRAPH DUMPER")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']}")
    lines.append(f"unit_key={payload['unit_key']} short_name={payload['short_name']} family={payload['family']}")
    lines.append("")
    lines.append("[seeds]")
    for s in payload["seeds"]:
        lines.append(f"  {s['label']} off={s['global_off']} ptr={s['ptr']}")
    lines.append("")
    lines.append("[top-nodes]")
    for idx, node in enumerate(payload["top_nodes"][:40]):
        lines.append(
            f"  [{idx}] score={node['score']} depth={node['depth']} seed={node['seed']} "
            f"seed_off={node['seed_off']} ptr={node['ptr']} head={node['summary'].get('head_text') or '-'}"
        )
        if node.get("path"):
            for step in node["path"][:6]:
                lines.append(f"      {step['from']} + {step['field_off']} -> {step['to']}")
        inline = node["summary"].get("inline_strings") or []
        if inline:
            joined = ", ".join(f"{x['text']}@{x['off']}" for x in inline[:6])
            lines.append(f"      inline_strings: {joined}")
        ints = node["summary"].get("int_hits") or []
        if ints:
            joined = ", ".join(f"{x['u32']}@{x['off']}" for x in ints[:8])
            lines.append(f"      int_hits: {joined}")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    print("\n" + "=" * 58)
    print(" HUD CHAIN GRAPH DUMPER")
    print("=" * 58)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
