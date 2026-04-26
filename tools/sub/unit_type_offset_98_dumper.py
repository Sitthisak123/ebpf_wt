import json
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
UNIT_TYPE_OFF = 0x98
INTEREST_KEYS = (
    "germ_pzkpfw_ii_ausf_c",
    "germ_pzkpfw_iv_ausf_c",
    "ussr_pt_76b",
    "germ_pzkpfw_v_ausf_d_panther",
)


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def read_i32(scanner, addr, default=0):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return default
    return struct.unpack("<i", raw)[0]


def read_blob_hex(scanner, addr, size):
    raw = scanner.read_mem(addr, size)
    if not raw:
        return ""
    return raw.hex()


def read_ascii(scanner, ptr, max_len=96):
    if not mul.is_valid_ptr(ptr):
        return ""
    raw = scanner.read_mem(ptr, max_len)
    if not raw:
        return ""
    try:
        text = raw.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""
    if len(text) < 2:
        return ""
    if not any(ch.isalnum() for ch in text):
        return ""
    return text


def read_utf16(scanner, ptr, max_len=96):
    if not mul.is_valid_ptr(ptr):
        return ""
    raw = scanner.read_mem(ptr, max_len)
    if not raw:
        return ""
    try:
        text = raw.decode("utf-16-le", errors="ignore").split("\x00")[0].strip()
    except Exception:
        return ""
    if len(text) < 2:
        return ""
    if not any(ch.isalnum() for ch in text):
        return ""
    return text


def candidate_strings(scanner, ptr):
    out = []
    if not mul.is_valid_ptr(ptr):
        return out
    direct_ascii = read_ascii(scanner, ptr)
    direct_utf16 = read_utf16(scanner, ptr)
    if direct_ascii:
        out.append({"addr": hex(ptr), "kind": "ascii", "text": direct_ascii})
    if direct_utf16 and direct_utf16 != direct_ascii:
        out.append({"addr": hex(ptr), "kind": "utf16", "text": direct_utf16})

    for off in (0x0, 0x8, 0x10, 0x18, 0x20, 0x28):
        child = read_u64(scanner, ptr + off)
        if not mul.is_valid_ptr(child):
            continue
        child_ascii = read_ascii(scanner, child)
        child_utf16 = read_utf16(scanner, child)
        if child_ascii:
            out.append({"addr": hex(child), "kind": f"ptr+{hex(off)}:ascii", "text": child_ascii})
        if child_utf16 and child_utf16 != child_ascii:
            out.append({"addr": hex(child), "kind": f"ptr+{hex(off)}:utf16", "text": child_utf16})
    return out


def deref_chain(scanner, ptr, depth=4):
    chain = []
    cur = ptr
    seen = set()
    for level in range(depth):
        if not mul.is_valid_ptr(cur) or cur in seen:
            break
        seen.add(cur)
        u64_0 = read_u64(scanner, cur + 0x0)
        u64_8 = read_u64(scanner, cur + 0x8)
        u32_0 = read_u32(scanner, cur + 0x0)
        i32_0 = read_i32(scanner, cur + 0x0, 0)
        chain.append({
            "level": level,
            "ptr": hex(cur),
            "raw_0x00_0x20": read_blob_hex(scanner, cur, 0x20),
            "u64_0": hex(u64_0) if u64_0 else "0x0",
            "u64_8": hex(u64_8) if u64_8 else "0x0",
            "u32_0": u32_0,
            "i32_0": i32_0,
            "strings": candidate_strings(scanner, cur),
        })
        if mul.is_valid_ptr(u64_0) and u64_0 != cur:
            cur = u64_0
        elif mul.is_valid_ptr(u64_8) and u64_8 != cur:
            cur = u64_8
        else:
            break
    return chain


def is_interest(rec):
    key = ((rec.get("dna") or {}).get("name_key") or "").lower()
    return key in INTEREST_KEYS


def build_record(scanner, unit_ptr, default_is_air):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    status = mul.get_unit_status(scanner, unit_ptr) or (0, -1, "", -1)
    raw_u64 = read_u64(scanner, unit_ptr + UNIT_TYPE_OFF)
    raw_u32 = read_u32(scanner, unit_ptr + UNIT_TYPE_OFF)
    raw_i32 = read_i32(scanner, unit_ptr + UNIT_TYPE_OFF, 0)

    rec = {
        "ptr": hex(unit_ptr),
        "team": status[0],
        "state": status[1],
        "is_air_default": bool(default_is_air),
        "dna": {
            "short_name": dna.get("short_name") or "",
            "name_key": dna.get("name_key") or "",
            "family": dna.get("family") or "",
            "class_id": dna.get("class_id"),
            "nation_id": dna.get("nation_id"),
        },
        "profile": {
            "tag": profile.get("tag") or "",
            "path": profile.get("path") or "",
            "unit_key": profile.get("unit_key") or "",
            "kind": profile.get("kind") or "",
        },
        "unit_type_0x98": {
            "raw_hex_0x20": read_blob_hex(scanner, unit_ptr + UNIT_TYPE_OFF, 0x20),
            "u64": hex(raw_u64) if raw_u64 else "0x0",
            "u32": raw_u32,
            "i32": raw_i32,
            "is_ptr_like": bool(mul.is_valid_ptr(raw_u64)),
            "direct_ascii": read_ascii(scanner, raw_u64) if mul.is_valid_ptr(raw_u64) else "",
            "direct_utf16": read_utf16(scanner, raw_u64) if mul.is_valid_ptr(raw_u64) else "",
            "chain": deref_chain(scanner, raw_u64, depth=4) if mul.is_valid_ptr(raw_u64) else [],
        },
    }
    rec["interest_match"] = is_interest(rec)
    return rec


def write_outputs(payload):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"unit_type_offset_98_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"unit_type_offset_98_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" UNIT TYPE OFFSET +0x98 DUMPER")
    lines.append("==================================================")
    meta = payload.get("meta") or {}
    lines.append(f"PID        : {meta.get('pid')}")
    lines.append(f"Base       : {meta.get('base_addr')}")
    lines.append(f"CGame      : {meta.get('cgame_ptr')}")
    lines.append(f"My Unit    : {meta.get('my_unit_ptr')}")
    lines.append(f"Offset     : {hex(UNIT_TYPE_OFF)}")
    lines.append(f"Count      : {len(payload.get('units', []))}")
    lines.append("")

    lines.append("INTEREST MATCHES")
    for rec in payload.get("units", []):
        if not rec.get("interest_match"):
            continue
        dna = rec["dna"]
        ut = rec["unit_type_0x98"]
        lines.append(f"- {dna.get('short_name')} | {dna.get('name_key')} | ptr={rec['ptr']}")
        lines.append(
            f"  family={dna.get('family')} class_id={dna.get('class_id')} "
            f"u64={ut.get('u64')} u32={ut.get('u32')} i32={ut.get('i32')} ptr_like={ut.get('is_ptr_like')}"
        )
        if ut.get("direct_ascii") or ut.get("direct_utf16"):
            lines.append(f"  direct_ascii={ut.get('direct_ascii')} | direct_utf16={ut.get('direct_utf16')}")
        for node in ut.get("chain", []):
            lines.append(
                f"  chain[{node['level']}] ptr={node['ptr']} u64_0={node['u64_0']} u64_8={node['u64_8']} "
                f"u32_0={node['u32_0']} i32_0={node['i32_0']}"
            )
            for s in node.get("strings", []):
                lines.append(f"    {s['kind']} @ {s['addr']} => {s['text']}")
        lines.append("")

    lines.append("SUMMARY")
    lines.append(json.dumps(payload.get("summary", {}), indent=2, ensure_ascii=False))
    lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, txt_path


def main():
    pid = get_game_pid()
    if not pid:
        print("[-] War Thunder process not found")
        return 1

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame = mul.get_cgame_base(scanner, base)
    if not cgame:
        print("[-] Failed to resolve cgame")
        return 1

    my_unit, _my_team = mul.get_local_team(scanner, base)
    units = mul.get_all_units(scanner, cgame)
    records = []
    ptr_like_counter = 0
    u32_counter = {}

    for unit_ptr, is_air in units:
        try:
            rec = build_record(scanner, unit_ptr, is_air)
        except Exception:
            continue
        records.append(rec)
        ut = rec["unit_type_0x98"]
        if ut.get("is_ptr_like"):
            ptr_like_counter += 1
        key = str(ut.get("u32"))
        u32_counter[key] = u32_counter.get(key, 0) + 1

    records.sort(key=lambda r: (
        0 if r.get("interest_match") else 1,
        str((r.get("dna") or {}).get("family") or ""),
        str((r.get("dna") or {}).get("name_key") or ""),
        r["ptr"],
    ))

    payload = {
        "meta": {
            "timestamp": datetime.now().isoformat(),
            "pid": pid,
            "base_addr": hex(base),
            "cgame_ptr": hex(cgame),
            "my_unit_ptr": hex(my_unit) if my_unit else "0x0",
        },
        "summary": {
            "units_total": len(records),
            "ptr_like_count": ptr_like_counter,
            "u32_counts": dict(sorted(u32_counter.items(), key=lambda item: int(item[0]))),
            "interest_keys": list(INTEREST_KEYS),
        },
        "units": records,
    }

    json_path, txt_path = write_outputs(payload)
    print("==================================================")
    print(" UNIT TYPE OFFSET +0x98 DUMPER")
    print("==================================================")
    print(f"[+] Units dumped: {len(records)}")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
