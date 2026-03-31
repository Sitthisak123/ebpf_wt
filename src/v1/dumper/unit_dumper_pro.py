import os
import sys
import struct
import json
import time
from datetime import datetime
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import *

def dump_hex(data, start_offset=0):
    """สร้าง hex dump สำหรับการวิเคราะห์"""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_val = " ".join(f"{b:02x}" for b in chunk)
        ascii_val = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"0x{start_offset + i:04x} | {hex_val:<48} | {ascii_val}")
    return "\n".join(lines)

def main():
    print("="*60)
    print("🚀 UNIT DUMPER PRO - DEEP DNA SCANNER")
    print("="*60)

    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
        
        # ค้นหา Offset ล่าสุดก่อนเริ่ม
        init_dynamic_offsets(scanner, base_addr)
        
        cgame_base = get_cgame_base(scanner, base_addr)
        if cgame_base == 0:
            print("[-] ❌ ไม่พบ CGame Base")
            return

        # ดึงยูนิตทั้งหมด (ไม่ Filter)
        all_units_raw = get_all_units(scanner, cgame_base)
        print(f"[*] Found {len(all_units_raw)} total units in memory arrays.")

        dump_results = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for i, (u_ptr, is_air) in enumerate(all_units_raw):
            print(f"[{i+1}/{len(all_units_raw)}] Scanning Unit: {hex(u_ptr)} ...", end="\r")
            
            # ข้อมูลพื้นฐาน
            status = get_unit_status(scanner, u_ptr)
            dna = get_unit_detailed_dna(scanner, u_ptr)
            pos = get_unit_pos(scanner, u_ptr)
            
            unit_data = {
                "index": i,
                "ptr": hex(u_ptr),
                "type": "AIR" if is_air else "GROUND",
                "basic_status": status,
                "dna": dna,
                "position": pos,
                "deep_info_hex": ""
            }

            # Deep Scan: อ่านข้อมูล Info Struct เพิ่มเติม (ถ้ามี)
            if dna and dna.get("info_ptr"):
                info_ptr = dna["info_ptr"]
                # อ่าน 0x300 ไบต์เพื่อหาฟิลด์ข้างเคียง
                raw_info = scanner.read_mem(info_ptr, 0x300)
                if raw_info:
                    unit_data["deep_info_hex"] = dump_hex(raw_info)
            
            dump_results.append(unit_data)

        # บันทึกเป็น JSON
        os.makedirs("dumps", exist_ok=True)
        json_file = f"dumps/deep_unit_dump_{timestamp}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(dump_results, f, indent=4, ensure_ascii=False)

        # บันทึกเป็น Text แบบอ่านง่าย
        txt_file = f"dumps/deep_unit_dump_{timestamp}.txt"
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(f"UNIT DUMP REPORT - {timestamp}\n")
            f.write("="*80 + "\n\n")
            for u in dump_results:
                f.write(f"🔹 UNIT: {u['ptr']} | TYPE: {u['type']}\n")
                if u['basic_status']:
                    f.write(f"   Name: {u['basic_status'][2]} | Team: {u['basic_status'][0]} | State: {u['basic_status'][1]}\n")
                if u['dna']:
                    dna = u['dna']
                    f.write(
                        "   🧬 DNA: "
                        f"Nation:{dna.get('nation_id', -1)} | "
                        f"State:{dna.get('state', -1)} | "
                        f"Class:{dna.get('class_id', -1)} | "
                        f"Key:{dna.get('name_key', 'None')}\n"
                    )
                    f.write(f"   📍 InfoPtr: {hex(dna.get('info_ptr', 0))}\n")
                if u['deep_info_hex']:
                    f.write("   --- [ INFO STRUCT DEEP DUMP ] ---\n")
                    f.write(u['deep_info_hex'] + "\n")
                f.write("-" * 80 + "\n")

        print(f"\n[+] ✅ Dump Complete!")
        print(f"[+] JSON: {json_file}")
        print(f"[+] Text: {txt_file}")

    except Exception as e:
        print(f"\n[-] ❌ Error: {e}")

if __name__ == "__main__":
    main()
