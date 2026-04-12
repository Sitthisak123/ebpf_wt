import argparse
import collections
import os
import struct
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


def read_u16(scanner, addr):
    raw = scanner.read_mem(addr, 2)
    if not raw or len(raw) < 2:
        return None
    return struct.unpack("<H", raw)[0]


def read_i16(scanner, addr):
    raw = scanner.read_mem(addr, 2)
    if not raw or len(raw) < 2:
        return None
    return struct.unpack("<h", raw)[0]


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<I", raw)[0]


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return None
    return struct.unpack("<Q", raw)[0]


def read_cstr(scanner, addr, max_len=128):
    if not addr or addr <= 0x10000:
        return None
    raw = scanner.read_mem(addr, max_len)
    if not raw:
        return None
    return raw.split(b"\x00")[0].decode("utf-8", errors="ignore")


def decode_utf16ish(raw):
    if not raw:
        return None
    buf = raw[:0x80]
    end = None
    for i in range(0, len(buf) - 1, 2):
        if buf[i] == 0 and buf[i + 1] == 0:
            end = i
            break
    if end is None:
        end = len(buf) - (len(buf) % 2)
    if end < 4:
        return None
    chunk = buf[:end]
    try:
        text = chunk.decode("utf-16le", errors="ignore").strip("\x00")
    except Exception:
        return None
    if not text:
        return None
    printable = sum(1 for ch in text if 32 <= ord(ch) < 127)
    if printable < max(2, len(text) // 2):
        return None
    return text


def filter_printable(text):
    if not text:
        return None
    filtered = "".join(ch for ch in text if 32 <= ord(ch) < 127)
    return filtered or None


def decode_asciiish(raw):
    if not raw:
        return None
    text = raw.split(b"\x00")[0].decode("utf-8", errors="ignore").strip("\x00")
    if not text:
        return None
    printable = sum(1 for ch in text if 32 <= ord(ch) < 127)
    if printable < max(2, len(text) // 2):
        return None
    return text


def collect_string_candidates(scanner, ptr, depth=0, seen=None):
    if seen is None:
        seen = set()
    results = []
    if not is_valid_ptr(ptr) or ptr in seen or depth > 2:
        return results
    seen.add(ptr)
    raw = scanner.read_mem(ptr, 0x40) or b""
    ascii_text = decode_asciiish(raw)
    utf16_text = decode_utf16ish(raw)
    utf16_printable = filter_printable(utf16_text)
    if ascii_text or utf16_printable:
        results.append({
            "ptr": ptr,
            "ascii": ascii_text,
            "utf16": utf16_printable,
            "depth": depth,
        })
    for i in range(0, min(len(raw), 0x20), 8):
        qv = struct.unpack_from("<Q", raw, i)[0]
        if is_valid_ptr(qv):
            results.extend(collect_string_candidates(scanner, qv, depth + 1, seen))
    return results


def decode_stringish(scanner, ptr):
    result = {
        "direct": None,
        "direct_utf16": None,
        "direct_utf16_printable": None,
        "indirect_ptr": None,
        "indirect": None,
        "indirect_utf16": None,
        "indirect_utf16_printable": None,
        "nested_ptrs": [],
        "nested_candidates": [],
        "raw16": "",
    }
    if not is_valid_ptr(ptr):
        return result
    raw = scanner.read_mem(ptr, 0x20) or b""
    if raw:
        result["raw16"] = raw[:0x20].hex()
        result["direct"] = decode_asciiish(raw)
        result["direct_utf16"] = decode_utf16ish(raw)
        result["direct_utf16_printable"] = filter_printable(result["direct_utf16"])
    qwords = []
    for i in range(0, min(len(raw), 0x20), 8):
        qv = struct.unpack_from("<Q", raw, i)[0]
        qwords.append(qv)
        if is_valid_ptr(qv):
            result["nested_ptrs"].append(qv)
    for inner in qwords:
        if not is_valid_ptr(inner):
            continue
        inner_raw = scanner.read_mem(inner, 0x40) or b""
        inner_ascii = decode_asciiish(inner_raw)
        inner_utf16 = decode_utf16ish(inner_raw)
        inner_utf16_printable = filter_printable(inner_utf16)
        if inner_ascii or inner_utf16_printable:
            result["nested_candidates"].append({
                "ptr": inner,
                "ascii": inner_ascii,
                "utf16": inner_utf16_printable,
            })
        if result["indirect_ptr"] is None:
            result["indirect_ptr"] = inner
            result["indirect"] = inner_ascii or read_cstr(scanner, inner)
            result["indirect_utf16"] = inner_utf16
            result["indirect_utf16_printable"] = inner_utf16_printable
        if result["indirect"] or result["indirect_utf16"]:
            break
    result["nested_candidates"] = collect_string_candidates(scanner, ptr)
    return result


def hex0(value):
    if value is None:
        return "None"
    return hex(int(value))


def is_valid_ptr(value):
    return isinstance(value, int) and mul.is_valid_ptr(value)


def score_manager_shape(scanner, ptr):
    if not is_valid_ptr(ptr):
        return -1, {}

    sub = read_u64(scanner, ptr + 0x350)
    reg_names = read_u64(scanner, ptr + 0x578)
    reg_count = read_u64(scanner, ptr + 0x580)
    remap_count = read_u32(scanner, ptr + 0x640)
    holder_vec = read_u64(scanner, ptr + 0x88)
    desc_vec = read_u64(scanner, ptr + 0x658)

    info = {
        "sub_350": sub,
        "reg_names": reg_names,
        "reg_count": reg_count,
        "remap_count": remap_count,
        "holder_vec": holder_vec,
        "desc_vec": desc_vec,
    }

    score = 0
    if is_valid_ptr(sub):
        score += 3
    if is_valid_ptr(reg_names):
        score += 2
    if isinstance(reg_count, int) and 0 <= reg_count < 0x10000:
        score += 2
    if isinstance(remap_count, int) and 0 <= remap_count < 0x10000:
        score += 2
    if is_valid_ptr(holder_vec):
        score += 2
    if is_valid_ptr(desc_vec):
        score += 2
    return score, info


def resolve_manager(scanner, base, manager_ptr_arg=None, manager_offset_arg=None):
    if manager_ptr_arg:
        ptr = int(str(manager_ptr_arg), 0)
        return {
            "mode": "direct_ptr",
            "global_addr": None,
            "offset": None,
            "manager": ptr,
            "score": None,
            "shape": {},
        }

    candidates = []

    candidate_offsets = []
    if manager_offset_arg is not None:
        candidate_offsets.append(int(str(manager_offset_arg), 0))
    else:
        seen = set()
        for off in [getattr(mul, "MANAGER_OFFSET", 0)] + list(getattr(mul, "MANAGER_CANDIDATE_OFFSETS", []) or []):
            try:
                off = int(off)
            except Exception:
                continue
            if off <= 0 or off in seen:
                continue
            seen.add(off)
            candidate_offsets.append(off)

    for off in candidate_offsets:
        global_addr = base + off
        ptr = read_u64(scanner, global_addr)
        score, shape = score_manager_shape(scanner, ptr) if is_valid_ptr(ptr) else (-1, {})
        candidates.append({
            "mode": "global_slot",
            "global_addr": global_addr,
            "offset": off,
            "manager": ptr or 0,
            "score": score,
            "shape": shape,
        })

    my_unit, _ = mul.get_local_team(scanner, base)
    if is_valid_ptr(my_unit):
        for label, off, deref in [
            ("controlled_plus_20d0_ptr", 0x20D0, True),
            ("controlled_plus_1068_ptr", 0x1068, True),
            ("controlled_plus_1068_raw", 0x1068, False),
        ]:
            source_addr = my_unit + off
            ptr = read_u64(scanner, source_addr) if deref else source_addr
            score, shape = score_manager_shape(scanner, ptr) if is_valid_ptr(ptr) else (-1, {})
            candidates.append({
                "mode": label,
                "global_addr": source_addr,
                "offset": off,
                "manager": ptr or 0,
                "score": score,
                "shape": shape,
                "my_unit": my_unit,
            })

    valid = [c for c in candidates if is_valid_ptr(c.get("manager"))]
    if valid:
        best = max(valid, key=lambda c: (int(c.get("score") or -1), 1 if "controlled" in c.get("mode", "") else 0))
        return best

    return {
        "mode": "failed",
        "global_addr": None,
        "offset": candidate_offsets[0] if candidate_offsets else None,
        "manager": 0,
        "score": None,
        "shape": {},
    }


def print_header(title):
    print("=" * 72)
    print(title)
    print("=" * 72)


def _round_vec3(values, ndigits=4):
    if not values:
        return None
    return [round(float(v), ndigits) for v in values]


def dump_barrel_bridge(scanner, my_unit):
    if not is_valid_ptr(my_unit):
        return None
    box = mul.get_unit_3d_box_data(scanner, my_unit, False)
    if not box:
        print("[barrel-bridge] box=None")
        return None
    unit_pos, _bmin, _bmax, rot = box
    barrel = mul.get_weapon_barrel(scanner, my_unit, unit_pos, rot)
    if not barrel:
        print("[barrel-bridge] barrel=None")
        return {
            "unit_pos": unit_pos,
            "barrel_base": None,
            "barrel_tip": None,
            "dir": None,
        }
    base, tip = barrel
    direction = (
        float(tip[0] - base[0]),
        float(tip[1] - base[1]),
        float(tip[2] - base[2]),
    )
    print(
        f"[barrel-bridge] unit_pos={_round_vec3(unit_pos)} "
        f"barrel_base={_round_vec3(base)} barrel_tip={_round_vec3(tip)} "
        f"dir={_round_vec3(direction)}"
    )
    return {
        "unit_pos": unit_pos,
        "barrel_base": base,
        "barrel_tip": tip,
        "dir": direction,
    }


def dump_triples(scanner, manager, limit):
    base = manager + 0x408
    data_ptr = read_u64(scanner, base + 0x00)
    count_u32 = read_u32(scanner, base + 0x08)
    cap_u32 = read_u32(scanner, base + 0x0C)
    live_rows = 0
    word2_hist = collections.Counter()
    rows = []
    print(
        f"[triples @ manager+0x408] base={hex0(base)} data={hex0(data_ptr)} "
        f"count_u32={count_u32} cap_u32={cap_u32}"
    )
    if data_ptr and count_u32:
        total = int(count_u32)
        want = min(total, int(limit))
        raw = scanner.read_mem(data_ptr, total * 6)
        if raw:
            total_rows = min(len(raw) // 6, total)
            for idx in range(total_rows):
                off = idx * 6
                word0, word1, word2 = struct.unpack_from("<HHH", raw, off)
                rows.append((idx, word0, word1, word2))
                if (word0, word1, word2) != (0xFFFF, 0xFFFF, 0xFFFF):
                    live_rows += 1
                    word2_hist[word2] += 1
                if idx < want:
                    print(
                        f"  triple[{idx:02d}] word0={word0:5d} word1={word1:5d} word2={word2:5d} "
                        f"| hex=({word0:#06x}, {word1:#06x}, {word2:#06x})"
                    )
            if word2_hist:
                top = ", ".join(f"{k}:{v}" for k, v in word2_hist.most_common(12))
                print(f"  word2_hist_top={top}")
            return {
                "data_ptr": data_ptr,
                "count": count_u32,
                "cap": cap_u32,
                "live_rows": live_rows,
                "word2_hist": dict(word2_hist),
                "rows": rows,
            }

    sub = read_u64(scanner, manager + 0x350)
    if not sub:
        print("[-] fallback manager+0x350 -> subobject = 0")
        return {
            "data_ptr": None,
            "count": count_u32,
            "cap": cap_u32,
            "live_rows": 0,
            "word2_hist": {},
            "rows": [],
        }

    data_ptr = read_u64(scanner, sub + 0x148)
    count = read_u32(scanner, sub + 0x150)
    print(f"[triples fallback @ *(manager+0x350)+0x148] sub={hex0(sub)} data={hex0(data_ptr)} count={count}")
    if not data_ptr or not count:
        return {
            "data_ptr": data_ptr,
            "count": count,
            "cap": None,
            "live_rows": 0,
            "word2_hist": {},
            "rows": [],
        }

    want = min(int(count), int(limit))
    raw = scanner.read_mem(data_ptr, want * 6)
    if not raw:
        print("[-] failed to read triple data")
        return

    for idx in range(0, min(len(raw) // 6, want)):
        off = idx * 6
        word0, word1, word2 = struct.unpack_from("<HHH", raw, off)
        print(
            f"  triple[{idx:02d}] word0={word0:5d} word1={word1:5d} word2={word2:5d} "
            f"| hex=({word0:#06x}, {word1:#06x}, {word2:#06x})"
        )
        if (word0, word1, word2) != (0xFFFF, 0xFFFF, 0xFFFF):
            live_rows += 1
    return {
        "data_ptr": data_ptr,
        "count": count,
        "cap": None,
        "live_rows": live_rows,
        "word2_hist": {},
        "rows": [],
    }


def dump_alt_triple_container(scanner, manager, limit):
    base = read_u64(scanner, manager + 0x350) or 0
    data_ptr = read_u64(scanner, base + 0x148) if base else None
    count_u32 = read_u32(scanner, base + 0x150) if base else None
    cap_u32 = read_u32(scanner, base + 0x154) if base else None
    print(
        f"[alt-triples @ *(manager+0x350)+0x148] base={hex0(base)} data={hex0(data_ptr)} "
        f"count_u32={count_u32} cap_u32={cap_u32}"
    )
    if not data_ptr or not count_u32:
        return
    want = min(int(count_u32), int(limit))
    raw = scanner.read_mem(data_ptr, want * 6)
    if not raw:
        print("[-] failed to read alt triple data")
        return
    for idx in range(0, min(len(raw) // 6, want)):
        off = idx * 6
        word0, word1, word2 = struct.unpack_from("<HHH", raw, off)
        print(
            f"  alt_triple[{idx:02d}] word0={word0:5d} word1={word1:5d} word2={word2:5d} "
            f"| hex=({word0:#06x}, {word1:#06x}, {word2:#06x})"
        )


def dump_selector_container(scanner, manager):
    base = manager + 0x350
    q0 = read_u64(scanner, base + 0x00)
    q1 = read_u64(scanner, base + 0x08)
    q2 = read_u64(scanner, base + 0x10)
    q3 = read_u64(scanner, base + 0x18)
    raw = scanner.read_mem(base, 0x20) or b""
    print(
        f"[selector-container around manager+0x350] q0={hex0(q0)} q1={hex0(q1)} "
        f"q2={hex0(q2)} q3={hex0(q3)}"
    )
    if raw:
        print(f"  raw={raw.hex()}")


def dump_registry(scanner, manager, seat, limit):
    reg = manager + 0x578 + (seat * 0x20)
    entries_ptr = read_u64(scanner, reg + 0x00)
    aux_qword = read_u64(scanner, reg + 0x08)
    count_u32 = read_u32(scanner, reg + 0x10)
    cap_u32 = read_u32(scanner, reg + 0x14)
    aux_ptr = read_u64(scanner, reg + 0x18)
    raw = scanner.read_mem(reg, 0x20) or b""
    print(
        f"[registry seat={seat}] reg={hex0(reg)} entries_ptr={hex0(entries_ptr)} "
        f"aux_qword={hex0(aux_qword)} count_u32={count_u32} cap_u32={cap_u32} aux_ptr={hex0(aux_ptr)}"
    )
    if raw:
        print(f"  raw={raw.hex()}")
    if aux_ptr:
        aux_raw = scanner.read_mem(aux_ptr, 0x40) or b""
        if aux_raw:
            print(f"  aux_raw={aux_raw.hex()}")
            aux_str = aux_raw.split(b'\\x00')[0].decode('utf-8', errors='ignore')
            print(f"  aux_cstr={aux_str!r}")
    if not entries_ptr or not count_u32:
        return {
            "entries_ptr": entries_ptr,
            "count": count_u32,
            "cap": cap_u32,
            "decoded_names": 0,
            "value_u16_seen": [],
        }

    want = min(int(count_u32), int(limit))
    decoded_names = 0
    value_u16_seen = []
    for idx in range(want):
        entry = entries_ptr + idx * 0x10
        entry_raw = scanner.read_mem(entry, 0x10) or b""
        name_ptr = read_u64(scanner, entry + 0x00)
        value_u32 = read_u32(scanner, entry + 0x08)
        value_u16 = read_u16(scanner, entry + 0x08)
        value_hi_u16 = read_u16(scanner, entry + 0x0A)
        name = read_cstr(scanner, name_ptr) if name_ptr else None
        nameish = decode_stringish(scanner, name_ptr) if name_ptr else {}
        print(
            f"  registry[{idx:02d}] name_ptr={hex0(name_ptr)} name={name!r} "
            f"value_u32={value_u32} low_u16={value_u16} hi_u16={value_hi_u16} raw={entry_raw.hex()}"
        )
        if nameish:
            if nameish.get("indirect") or nameish.get("direct") or nameish.get("indirect_utf16_printable") or nameish.get("direct_utf16_printable"):
                decoded_names += 1
            if value_u16 is not None:
                value_u16_seen.append(value_u16)
            print(
                f"    stringish direct={nameish.get('direct')!r} "
                f"direct_utf16={nameish.get('direct_utf16')!r} "
                f"direct_utf16_printable={nameish.get('direct_utf16_printable')!r} "
                f"indirect_ptr={hex0(nameish.get('indirect_ptr'))} "
                f"indirect={nameish.get('indirect')!r} "
                f"indirect_utf16={nameish.get('indirect_utf16')!r} "
                f"indirect_utf16_printable={nameish.get('indirect_utf16_printable')!r} "
                f"nested_ptrs={[hex0(x) for x in nameish.get('nested_ptrs', [])]} "
                f"raw16={nameish.get('raw16')}"
            )
            if nameish.get("nested_candidates"):
                parts = []
                for cand in nameish["nested_candidates"]:
                    parts.append(
                        f"{hex0(cand['ptr'])}:ascii={cand.get('ascii')!r},utf16={cand.get('utf16')!r}"
                    )
                print(f"    nested_candidates={parts}")
    return {
        "entries_ptr": entries_ptr,
        "count": count_u32,
        "cap": cap_u32,
        "decoded_names": decoded_names,
        "value_u16_seen": value_u16_seen,
    }


def inspect_registry_brief(scanner, manager, seat, sample_entries=2):
    reg = manager + 0x578 + (seat * 0x20)
    entries_ptr = read_u64(scanner, reg + 0x00)
    count_u32 = read_u32(scanner, reg + 0x10) or 0
    values = []
    names = []
    if not entries_ptr or count_u32 <= 0:
        return {
            "seat": seat,
            "count": count_u32,
            "values": values,
            "names": names,
        }

    want = min(int(count_u32), int(sample_entries))
    for idx in range(want):
        entry = entries_ptr + idx * 0x10
        name_ptr = read_u64(scanner, entry + 0x00)
        value_u16 = read_u16(scanner, entry + 0x08)
        if value_u16 is not None:
            values.append(value_u16)
        if name_ptr:
            nameish = decode_stringish(scanner, name_ptr)
            picked = None
            for cand in nameish.get("nested_candidates", []):
                if cand.get("ascii"):
                    picked = cand["ascii"]
                    break
                if cand.get("utf16"):
                    picked = cand["utf16"]
                    break
            if not picked:
                picked = (
                    nameish.get("indirect")
                    or nameish.get("indirect_utf16_printable")
                    or nameish.get("direct")
                    or nameish.get("direct_utf16_printable")
                )
            if picked:
                names.append(picked)
    return {
        "seat": seat,
        "count": count_u32,
        "values": values,
        "names": names,
    }


def dump_remap_cache(scanner, manager, limit):
    data_ptr = read_u64(scanner, manager + 0x630)
    count_a = read_u32(scanner, manager + 0x640)
    count_b = read_u32(scanner, manager + 0x644)
    print(f"[remap-cache] data={hex0(data_ptr)} u32@640={count_a} u32@644={count_b}")
    count = None
    if isinstance(count_a, int) and isinstance(count_b, int):
        if 0 < count_a <= 0x10000 and (count_b == 0 or count_b >= count_a):
            count = count_a
        elif 0 < count_b <= 0x10000:
            count = count_b
    if not data_ptr or not count:
        return {
            "data_ptr": data_ptr,
            "count": count,
            "all_one_f32": False,
        }
    want = min(int(count), int(limit))
    raw = scanner.read_mem(data_ptr, want * 4)
    if not raw:
        print("[-] failed to read remap cache")
        return
    values_u32 = [struct.unpack_from("<I", raw, i * 4)[0] for i in range(len(raw) // 4)]
    values_f32 = [struct.unpack_from("<f", raw, i * 4)[0] for i in range(len(raw) // 4)]
    print(f"  preview_u32={values_u32}")
    print(f"  preview_f32={values_f32}")
    all_one_f32 = bool(values_f32) and all(abs(v - 1.0) < 1e-6 for v in values_f32)
    return {
        "data_ptr": data_ptr,
        "count": count,
        "all_one_f32": all_one_f32,
    }


def dump_holder(scanner, manager, seat, limit):
    holder_vec = read_u64(scanner, manager + 0x88)
    seat_holder = read_u64(scanner, holder_vec + seat * 8) if holder_vec else None
    print(
        f"[holder seat={seat}] holder_vec={hex0(holder_vec)} "
        f"seat_holder={hex0(seat_holder)}"
    )
    if not seat_holder:
        return {
            "holder_vec": holder_vec,
            "seat_holder": seat_holder,
            "count": 0,
            "anchor": None,
            "all_one_tail": False,
        }

    data_ptr = read_u64(scanner, seat_holder + 0x10)
    count = read_u32(scanner, seat_holder + 0x18)
    anchor = read_u64(scanner, seat_holder + 0x24)
    print(
        f"  data_ptr={hex0(data_ptr)} count={count} "
        f"anchor/world={hex0(anchor)} stride_matrix=0x78 state_tail=count*0x78"
    )
    if not data_ptr or not count:
        return {
            "holder_vec": holder_vec,
            "seat_holder": seat_holder,
            "count": count or 0,
            "anchor": anchor,
            "all_one_tail": False,
        }

    tail_ptr = data_ptr + int(count) * 0x78
    want = min(int(count), int(limit))
    raw = scanner.read_mem(tail_ptr, want * 4)
    if not raw:
        print("[-] failed to read holder state tail")
        return
    values = [struct.unpack_from("<I", raw, i * 4)[0] for i in range(len(raw) // 4)]
    print(f"  state_tail_preview={values}")
    all_one_tail = bool(values) and all(v == 1065353216 for v in values)
    return {
        "holder_vec": holder_vec,
        "seat_holder": seat_holder,
        "count": count,
        "anchor": anchor,
        "all_one_tail": all_one_tail,
    }


def dump_target_descriptor_context(scanner, manager, rows, target_word2_values):
    if not rows or not target_word2_values:
        return
    meta_ptr = read_u64(scanner, manager + 0x3D8)
    lookup_ptr = read_u64(scanner, manager + 0x648)
    print()
    print(f"[descriptor-context] meta_ptr={hex0(meta_ptr)} lookup_ptr={hex0(lookup_ptr)}")
    shown = 0
    for idx, w0, w1, w2 in rows:
        if w2 not in target_word2_values:
            continue
        rec_addr = (meta_ptr + w0 * 0x14) if meta_ptr else None
        rec_raw = scanner.read_mem(rec_addr, 0x14) if rec_addr else None
        flag_byte = read_u16(scanner, rec_addr + 2) if rec_addr else None
        lookup_val = read_u32(scanner, lookup_ptr + w0 * 4) if lookup_ptr else None
        print(
            f"  target idx={idx} word0={w0} word1={w1} word2={w2} "
            f"meta_rec={hex0(rec_addr)} flags16={flag_byte} lookup_u32={lookup_val} "
            f"raw={(rec_raw.hex() if rec_raw else None)}"
        )
        if rec_addr:
            print("    neighborhood:")
            for delta in range(-2, 3):
                n_w0 = w0 + delta
                if n_w0 < 0:
                    continue
                n_addr = meta_ptr + n_w0 * 0x14
                n_raw = scanner.read_mem(n_addr, 0x14) or b""
                if len(n_raw) < 0x0A:
                    continue
                n_flags = struct.unpack_from("<H", n_raw, 0x02)[0]
                n_word0 = struct.unpack_from("<H", n_raw, 0x04)[0]
                n_word1 = struct.unpack_from("<H", n_raw, 0x06)[0]
                n_word2 = struct.unpack_from("<H", n_raw, 0x08)[0]
                print(
                    f"      w0={n_w0:3d} delta={delta:+d} flags={n_flags:#06x} "
                    f"m_word0={n_word0:5d} m_word1={n_word1:5d} m_word2={n_word2:5d} raw={n_raw.hex()}"
                )
        shown += 1
        if shown >= 8:
            break


def dump_word2_block(scanner, manager, rows, target_word2_values):
    if not rows or not target_word2_values:
        return
    vals = sorted(set(target_word2_values))
    if not vals:
        return
    lo = max(0, min(vals) - 2)
    hi = max(vals) + 2
    matched = [(idx, w0, w1, w2) for (idx, w0, w1, w2) in rows if lo <= w2 <= hi]
    if not matched:
        return
    print()
    print(f"[word2-block] range={lo}..{hi} matched_rows={len(matched)}")
    for idx, w0, w1, w2 in matched[:24]:
        print(f"  idx={idx:3d} word0={w0:5d} word1={w1:5d} word2={w2:5d}")


def dump_contiguous_families(rows, min_len=3, max_groups=16):
    live_rows = [(idx, w0, w1, w2) for (idx, w0, w1, w2) in rows if (w0, w1, w2) != (0xFFFF, 0xFFFF, 0xFFFF)]
    if not live_rows:
        return
    groups = []
    current = [live_rows[0]]
    for row in live_rows[1:]:
        p_idx, p_w0, p_w1, p_w2 = current[-1]
        idx, w0, w1, w2 = row
        if idx == p_idx + 1 and w0 == p_w0 + 1 and w1 == p_w1 + 1 and w2 == p_w2 + 1:
            current.append(row)
        else:
            if len(current) >= min_len:
                groups.append(current)
            current = [row]
    if len(current) >= min_len:
        groups.append(current)
    if not groups:
        return
    groups.sort(key=len, reverse=True)
    print()
    print(f"[contiguous-families] groups>={min_len} count={len(groups)}")
    for group in groups[:max_groups]:
        start = group[0]
        end = group[-1]
        print(
            f"  len={len(group):2d} "
            f"idx={start[0]}..{end[0]} "
            f"word0={start[1]}..{end[1]} "
            f"word1={start[2]}..{end[2]} "
            f"word2={start[3]}..{end[3]}"
        )
    return groups


def dump_auto_family_scan(scanner, manager, groups, max_groups):
    if not groups or max_groups <= 0:
        return
    print()
    print(f"[auto-family-scan] top_groups={min(len(groups), max_groups)}")
    for group in groups[:max_groups]:
        start = group[0]
        end = group[-1]
        dump_explicit_word2_range(scanner, manager, group, start[3], end[3], max_rows=32)


def dump_target_superfamily(scanner, manager, rows, target_word2_values):
    if not rows or not target_word2_values:
        return
    live_rows = [(idx, w0, w1, w2) for (idx, w0, w1, w2) in rows if (w0, w1, w2) != (0xFFFF, 0xFFFF, 0xFFFF)]
    if not live_rows:
        return
    groups = []
    current = [live_rows[0]]
    for row in live_rows[1:]:
        p_idx, p_w0, p_w1, p_w2 = current[-1]
        idx, w0, w1, w2 = row
        if idx == p_idx + 1 and w0 == p_w0 + 1 and w1 == p_w1 + 1 and w2 == p_w2 + 1:
            current.append(row)
        else:
            groups.append(current)
            current = [row]
    groups.append(current)

    target_vals = set(target_word2_values)
    picked = None
    for group in groups:
        g_word2 = {row[3] for row in group}
        if target_vals & g_word2:
            picked = group
            break
    if not picked:
        return

    meta_ptr = read_u64(scanner, manager + 0x3D8)
    print()
    start = picked[0]
    end = picked[-1]
    print(
        f"[target-superfamily] len={len(picked)} "
        f"idx={start[0]}..{end[0]} word0={start[1]}..{end[1]} "
        f"word1={start[2]}..{end[2]} word2={start[3]}..{end[3]}"
    )
    for idx, w0, w1, w2 in picked[:32]:
        rec_addr = (meta_ptr + w0 * 0x14) if meta_ptr else None
        flags = read_u16(scanner, rec_addr + 2) if rec_addr else None
        print(
            f"  idx={idx:3d} word0={w0:5d} word1={w1:5d} word2={w2:5d} "
            f"flags={flags if flags is not None else 'None'} meta_rec={hex0(rec_addr)}"
        )


def dump_explicit_word2_range(scanner, manager, rows, lo, hi, max_rows=48):
    if not rows:
        return
    matched = [(idx, w0, w1, w2) for (idx, w0, w1, w2) in rows if lo <= w2 <= hi]
    print()
    print(f"[explicit-word2-range] range={lo}..{hi} matched_rows={len(matched)}")
    if not matched:
        return
    meta_ptr = read_u64(scanner, manager + 0x3D8)
    lookup_ptr = read_u64(scanner, manager + 0x648)
    lookup_hist = collections.Counter()
    for idx, w0, w1, w2 in matched[:max_rows]:
        rec_addr = (meta_ptr + w0 * 0x14) if meta_ptr else None
        flags = read_u16(scanner, rec_addr + 2) if rec_addr else None
        lookup_u32 = read_u32(scanner, lookup_ptr + w0 * 4) if lookup_ptr else None
        if lookup_u32 is not None:
            lookup_hist[lookup_u32] += 1
        print(
            f"  idx={idx:3d} word0={w0:5d} word1={w1:5d} word2={w2:5d} "
            f"flags={flags if flags is not None else 'None'} "
            f"lookup_u32={lookup_u32 if lookup_u32 is not None else 'None'} "
            f"meta_rec={hex0(rec_addr)}"
        )
    flags_hist = collections.Counter()
    for _, w0, _, _ in matched:
        rec_addr = (meta_ptr + w0 * 0x14) if meta_ptr else None
        flags = read_u16(scanner, rec_addr + 2) if rec_addr else None
        flags_hist[flags] += 1
    start = matched[0]
    end = matched[-1]
    print(
        f"  summary: idx={start[0]}..{end[0]} word0={start[1]}..{end[1]} "
        f"word1={start[2]}..{end[2]} word2={start[3]}..{end[3]} "
        f"flags_hist={dict(flags_hist)} lookup_hist={dict(lookup_hist)}"
    )


def dump_seat_scan(scanner, manager, rows, seat_max):
    if seat_max <= 0:
        return
    hist = collections.Counter()
    for _, _, _, w2 in rows:
        if w2 != 0xFFFF:
            hist[w2] += 1
    print()
    print(f"[seat-scan] seats=0..{seat_max - 1}")
    for seat in range(seat_max):
        info = inspect_registry_brief(scanner, manager, seat)
        holder_vec = read_u64(scanner, manager + 0x88)
        seat_holder = read_u64(scanner, holder_vec + seat * 8) if holder_vec else None
        holder_count = read_u32(scanner, seat_holder + 0x18) if seat_holder else 0
        value_hits = [f"{val}:{hist.get(val, 0)}" for val in sorted(set(info["values"])) if val is not None]
        names = ", ".join(info["names"][:4]) if info["names"] else "-"
        hits = ", ".join(value_hits) if value_hits else "-"
        print(
            f"  seat={seat} reg_count={info['count']} holder_count={holder_count or 0} "
            f"values=[{hits}] names=[{names}]"
        )


def print_readiness_summary(seat, triples_info, registry_info, remap_info, holder_info):
    triple_live = int((triples_info or {}).get("live_rows") or 0)
    registry_count = int((registry_info or {}).get("count") or 0)
    decoded_names = int((registry_info or {}).get("decoded_names") or 0)
    remap_count = int((remap_info or {}).get("count") or 0)
    holder_count = int((holder_info or {}).get("count") or 0)
    all_one_tail = bool((holder_info or {}).get("all_one_tail"))
    all_one_f32 = bool((remap_info or {}).get("all_one_f32"))

    ready_score = 0
    if triple_live > 0:
        ready_score += 2
    if holder_count > 0:
        ready_score += 2
    if registry_count > 0:
        ready_score += 1
    if decoded_names > 0:
        ready_score += 1
    if remap_count > 0:
        ready_score += 1
    if all_one_tail:
        ready_score -= 1
    if all_one_f32:
        ready_score -= 1

    if ready_score >= 4:
        verdict = "READY"
    elif ready_score >= 2:
        verdict = "PARTIAL"
    else:
        verdict = "LOADING/WEAK"

    print()
    print(
        f"[readiness seat={seat}] verdict={verdict} score={ready_score} "
        f"triple_live={triple_live} holder_count={holder_count} registry_count={registry_count} "
        f"decoded_names={decoded_names} remap_count={remap_count} "
        f"holder_tail_all_1={all_one_tail} remap_all_1={all_one_f32}"
    )
    registry_values = sorted(set((registry_info or {}).get("value_u16_seen") or []))
    word2_hist = (triples_info or {}).get("word2_hist") or {}
    if registry_values:
        matches = ", ".join(f"{val}:{word2_hist.get(val, 0)}" for val in registry_values)
        print(f"[correlation seat={seat}] registry_low_u16 -> triple_word2_count :: {matches}")
        rows = (triples_info or {}).get("rows") or []
        for val in registry_values:
            matched = [(idx, w0, w1, w2) for (idx, w0, w1, w2) in rows if w2 == val]
            if matched:
                preview = ", ".join(
                    f"idx={idx}/w0={w0}/w1={w1}/w2={w2}" for idx, w0, w1, w2 in matched[:8]
                )
                print(f"[word2-target seat={seat}] target={val} rows: {preview}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Real-time MemRead probe for DynamicHitPoint-related manager fields without saving files."
    )
    parser.add_argument("--manager", help="Direct manager pointer override, e.g. 0x7fff12345678")
    parser.add_argument("--manager-offset", help="Global manager slot offset override, e.g. 0x901b280")
    parser.add_argument("--seat", type=int, default=0, help="Seat index for registry/holder probes")
    parser.add_argument("--triple-limit", type=int, default=12, help="Preview triple count")
    parser.add_argument("--registry-limit", type=int, default=12, help="Preview registry count")
    parser.add_argument("--remap-limit", type=int, default=12, help="Preview remap cache count")
    parser.add_argument("--holder-limit", type=int, default=12, help="Preview holder state count")
    parser.add_argument("--watch-ms", type=int, default=0, help="Refresh interval in milliseconds; 0 = one-shot")
    parser.add_argument("--word2-range", help="Optional explicit word2 range, e.g. 457:481")
    parser.add_argument("--scan-seats", type=int, default=0, help="Briefly scan seats 0..N-1 for registry/holder correlation")
    parser.add_argument("--auto-family-scan", type=int, default=0, help="Automatically dump top N contiguous families")
    return parser.parse_args()


def parse_word2_range(text):
    if not text or ":" not in text:
        return None
    left, right = text.split(":", 1)
    try:
        lo = int(left, 0)
        hi = int(right, 0)
    except Exception:
        return None
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def main():
    args = parse_args()
    explicit_word2_range = parse_word2_range(args.word2_range)

    pid = get_game_pid()
    if not pid:
        print("[-] War Thunder process not found")
        return 1

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)
    resolved = resolve_manager(scanner, base, args.manager, args.manager_offset)
    manager = int(resolved.get("manager") or 0)
    if not is_valid_ptr(manager):
        print("[-] Failed to resolve manager pointer")
        print(
            f"    mode={resolved.get('mode')} offset={hex0(resolved.get('offset'))} "
            f"global_addr={hex0(resolved.get('global_addr'))} manager={hex0(manager)}"
        )
        scanner.close()
        return 1

    try:
        while True:
            print_header("DYNAMIC HITPOINT REALTIME PROBE")
            print(
                f"pid={pid} base={hex0(base)} manager={hex0(manager)} seat={args.seat} "
                f"| resolve_mode={resolved.get('mode')} global_addr={hex0(resolved.get('global_addr'))} "
                f"offset={hex0(resolved.get('offset'))} score={resolved.get('score')}"
            )
            if resolved.get("my_unit"):
                print(f"my_unit={hex0(resolved.get('my_unit'))}")
                dna = mul.get_unit_detailed_dna(scanner, resolved.get("my_unit")) or {}
                print(
                    f"unit_key={dna.get('name_key', 'None')} short_name={dna.get('short_name', 'None')} "
                    f"family={dna.get('family', 'None')} nation_id={dna.get('nation_id', -1)}"
                )
                dump_barrel_bridge(scanner, resolved.get("my_unit"))
            shape = resolved.get("shape") or {}
            if shape:
                print(
                    f"shape: sub_350={hex0(shape.get('sub_350'))} reg_names={hex0(shape.get('reg_names'))} "
                    f"reg_count={shape.get('reg_count')} remap_count={shape.get('remap_count')} "
                    f"holder_vec={hex0(shape.get('holder_vec'))} desc_vec={hex0(shape.get('desc_vec'))}"
                )
            triples_info = dump_triples(scanner, manager, args.triple_limit)
            print()
            dump_alt_triple_container(scanner, manager, args.triple_limit)
            print()
            dump_selector_container(scanner, manager)
            print()
            registry_info = dump_registry(scanner, manager, args.seat, args.registry_limit)
            print()
            remap_info = dump_remap_cache(scanner, manager, args.remap_limit)
            print()
            holder_info = dump_holder(scanner, manager, args.seat, args.holder_limit)
            print_readiness_summary(args.seat, triples_info, registry_info, remap_info, holder_info)
            dump_target_descriptor_context(
                scanner,
                manager,
                (triples_info or {}).get("rows") or [],
                sorted(set((registry_info or {}).get("value_u16_seen") or [])),
            )
            dump_word2_block(
                scanner,
                manager,
                (triples_info or {}).get("rows") or [],
                sorted(set((registry_info or {}).get("value_u16_seen") or [])),
            )
            groups = dump_contiguous_families((triples_info or {}).get("rows") or [])
            dump_target_superfamily(
                scanner,
                manager,
                (triples_info or {}).get("rows") or [],
                sorted(set((registry_info or {}).get("value_u16_seen") or [])),
            )
            if explicit_word2_range:
                dump_explicit_word2_range(
                    scanner,
                    manager,
                    (triples_info or {}).get("rows") or [],
                    explicit_word2_range[0],
                    explicit_word2_range[1],
                )
            if args.auto_family_scan > 0:
                dump_auto_family_scan(scanner, manager, groups or [], args.auto_family_scan)
            if args.scan_seats > 0:
                dump_seat_scan(
                    scanner,
                    manager,
                    (triples_info or {}).get("rows") or [],
                    args.scan_seats,
                )
            if args.watch_ms <= 0:
                break
            time.sleep(max(args.watch_ms, 1) / 1000.0)
            print()
    finally:
        scanner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
