import json
import os
import struct
import sys
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")
SCAN_MY_UNIT_SIZE = 0x1200
SCAN_INFO_PTR_SIZE = 0x320


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_i32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<i", raw)[0]


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0.0
    return struct.unpack("<f", raw)[0]


def field_value_tuple(rec):
    return (
        rec.get("i32"),
        rec.get("u32"),
        rec.get("u64"),
        rec.get("f32"),
    )


def value_text(rec):
    return f"i32={rec['i32']} u32={rec['u32']} u64={rec['u64']} f32={rec['f32']}"


def scan_region(scanner, base_ptr, size, region):
    records = []
    for off in range(0, size, 8):
        rec = {
            "region": region,
            "offset": hex(off),
            "addr": hex(base_ptr + off),
            "u64": hex(read_u64(scanner, base_ptr + off)),
            "i32": read_i32(scanner, base_ptr + off),
            "u32": read_u32(scanner, base_ptr + off),
            "f32": round(read_f32(scanner, base_ptr + off), 6),
        }
        records.append(rec)
    return records


def capture_snapshot(scanner, base_addr, label):
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    my_unit, _team = mul.get_local_team(scanner, base_addr)
    if not my_unit:
        return None
    dna = mul.get_unit_detailed_dna(scanner, my_unit) or {}
    info_ptr = read_u64(scanner, my_unit + mul.OFF_UNIT_INFO)

    fields = []
    fields.extend(scan_region(scanner, my_unit, SCAN_MY_UNIT_SIZE, "my_unit"))
    if mul.is_valid_ptr(info_ptr):
        fields.extend(scan_region(scanner, info_ptr, SCAN_INFO_PTR_SIZE, "info_ptr"))

    return {
        "label": label,
        "meta": {
            "pid": scanner.pid,
            "base_addr": hex(base_addr) if base_addr else "0x0",
            "cgame_ptr": hex(cgame_ptr) if cgame_ptr else "0x0",
            "my_unit_ptr": hex(my_unit) if my_unit else "0x0",
            "info_ptr": hex(info_ptr) if info_ptr else "0x0",
        },
        "dna": dna,
        "fields": fields,
    }


def build_field_map(snapshot):
    out = {}
    for rec in snapshot.get("fields", []):
        out[(rec["region"], rec["offset"])] = rec
    return out


def analyze_snapshots(snapshots):
    grouped = defaultdict(list)
    for snap in snapshots:
        grouped[snap["label"]].append(snap)

    universe = set()
    field_maps = []
    for snap in snapshots:
        fmap = build_field_map(snap)
        field_maps.append((snap, fmap))
        universe.update(fmap.keys())

    exact_unique = defaultdict(list)
    value_sets = []

    for key in sorted(universe, key=lambda x: (x[0], int(x[1], 16))):
        region, offset = key
        per_label_values = {}
        per_label_sets = {}
        for label, label_snaps in grouped.items():
            vals = []
            for snap in label_snaps:
                fmap = build_field_map(snap)
                rec = fmap.get(key)
                if rec is not None:
                    vals.append(rec)
            if not vals:
                continue
            seen = {}
            for rec in vals:
                seen[field_value_tuple(rec)] = rec
            per_label_values[label] = list(seen.values())
            per_label_sets[label] = set(seen.keys())

        if len(per_label_sets) < 2:
            continue

        for label, vals in per_label_values.items():
            if len(vals) != 1:
                continue
            own = next(iter(per_label_sets[label]))
            overlaps = False
            for other_label, other_set in per_label_sets.items():
                if other_label == label:
                    continue
                if own in other_set:
                    overlaps = True
                    break
            if not overlaps:
                exact_unique[label].append(
                    {
                        "region": region,
                        "offset": offset,
                        "value": vals[0],
                    }
                )

        union_size = len(set().union(*per_label_sets.values()))
        pair_overlap = {}
        labels = sorted(per_label_sets.keys())
        for i, a in enumerate(labels):
            for b in labels[i + 1:]:
                pair_overlap[f"{a}|{b}"] = len(per_label_sets[a] & per_label_sets[b])

        value_sets.append(
            {
                "region": region,
                "offset": offset,
                "distinct_total_values": union_size,
                "pair_overlap": pair_overlap,
                "groups": {
                    label: [
                        {
                            "i32": rec["i32"],
                            "u32": rec["u32"],
                            "u64": rec["u64"],
                            "f32": rec["f32"],
                        }
                        for rec in vals
                    ]
                    for label, vals in sorted(per_label_values.items())
                },
            }
        )

    return grouped, exact_unique, value_sets


def write_session_dump(snapshots, grouped, exact_unique, value_sets):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"subclass_loop_scan_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"subclass_loop_scan_{stamp}.txt")

    payload = {
        "snapshots": snapshots,
        "group_counts": {label: len(items) for label, items in grouped.items()},
        "exact_unique": dict(exact_unique),
        "value_sets": value_sets,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==========================================================")
    lines.append(" SUBCLASS LOOP SCANNER")
    lines.append("==========================================================")
    lines.append("[snapshots]")
    for snap in snapshots:
        dna = snap["dna"]
        lines.append(
            f"- label={snap['label']} | short={dna.get('short_name')} | "
            f"name_key={dna.get('name_key')} | family={dna.get('family')} | class_id={dna.get('class_id')}"
        )

    lines.append("")
    lines.append("[exact-unique]")
    for label in sorted(exact_unique.keys()):
        lines.append(f"- {label}")
        for item in exact_unique[label][:40]:
            lines.append(f"    -> {item['region']} + {item['offset']} | {value_text(item['value'])}")

    lines.append("")
    lines.append("[low-overlap-candidates]")
    interesting = []
    for item in value_sets:
        non_zero_pairs = [v for v in item["pair_overlap"].values() if v > 0]
        total_overlap = sum(non_zero_pairs)
        if total_overlap <= 2:
            interesting.append(item)
    for item in interesting[:160]:
        lines.append(f"- {item['region']} + {item['offset']} | distinct_total_values={item['distinct_total_values']}")
        for pair, count in sorted(item["pair_overlap"].items()):
            lines.append(f"    -> overlap {pair}: {count}")
        for label, values in sorted(item["groups"].items()):
            rendered = ", ".join(
                f"(i32={v['i32']},u32={v['u32']},u64={v['u64']},f32={v['f32']})"
                for v in values
            )
            lines.append(f"    -> {label}: {rendered}")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def print_summary(snapshots, grouped, exact_unique, value_sets):
    print("==========================================================")
    print(" SUBCLASS LOOP SCANNER")
    print("==========================================================")
    print(f"Snapshots: {len(snapshots)}")
    for label in sorted(grouped.keys()):
        print(f"- {label}: {len(grouped[label])}")
    print("")
    print("[exact-unique top]")
    for label in sorted(exact_unique.keys()):
        print(f"- {label}")
        for item in exact_unique[label][:8]:
            print(f"  -> {item['region']} + {item['offset']} | {value_text(item['value'])}")
    print("")
    print("[low-overlap top]")
    shown = 0
    for item in value_sets:
        if shown >= 12:
            break
        total_overlap = sum(v for v in item["pair_overlap"].values() if v > 0)
        if total_overlap > 2:
            continue
        print(f"- {item['region']} + {item['offset']} | distinct={item['distinct_total_values']}")
        for pair, count in sorted(item["pair_overlap"].items()):
            print(f"  -> overlap {pair}: {count}")
        shown += 1


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    snapshots = []

    while True:
        print("")
        print("==========================================================")
        print(" SUBCLASS LOOP SCANNER")
        print("==========================================================")
        print("[1] Capture snapshot")
        print("[2] Analyze current session")
        print("[3] Save session dumps")
        print("[4] Clear session")
        print("[0] Exit")
        choice = input("> ").strip()

        if choice == "0":
            break
        if choice == "1":
            label = input("label (LT/MT/HT/SPAA/TD/...): ").strip().upper()
            if not label:
                print("[-] empty label")
                continue
            snap = capture_snapshot(scanner, base_addr, label)
            if not snap:
                print("[-] capture failed: my unit not found")
                continue
            snapshots.append(snap)
            dna = snap["dna"]
            print(
                f"[+] captured {label} | short={dna.get('short_name')} | "
                f"name_key={dna.get('name_key')} | family={dna.get('family')} | class_id={dna.get('class_id')}"
            )
            continue
        if choice == "2":
            if not snapshots:
                print("[-] no snapshots")
                continue
            grouped, exact_unique, value_sets = analyze_snapshots(snapshots)
            print_summary(snapshots, grouped, exact_unique, value_sets)
            continue
        if choice == "3":
            if not snapshots:
                print("[-] no snapshots")
                continue
            grouped, exact_unique, value_sets = analyze_snapshots(snapshots)
            json_path, txt_path = write_session_dump(snapshots, grouped, exact_unique, value_sets)
            print(f"[+] JSON: {json_path}")
            print(f"[+] TEXT: {txt_path}")
            continue
        if choice == "4":
            snapshots.clear()
            print("[+] session cleared")
            continue
        print("[-] unknown choice")


if __name__ == "__main__":
    main()
