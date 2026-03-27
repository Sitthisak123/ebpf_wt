import os
import sys
import struct
from collections import Counter
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address

def main():
    print("[*] 🧬 ปฏิบัติการ The Hero Scanner (ชำแหละลายนิ้วมือจาก Ghidra)...")
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    # 🎯 ลายนิ้วมือขั้นเทพทั้ง 2 ชุดที่เราสกัดมาได้
    patterns = {
        "Pattern 1 (R12 Test)": "4C 8B 25 ? ? ? ? 4D 85 E4 74 ? 41 0F B7 44 24 08",
        "Pattern 2 (RBX Cmp)":  "48 8B 05 ? ? ? ? 48 39 C3 74 ? 48 8B 05 ? ? ? ? 80 B8"
    }
    
    found_targets = []
    
    for name, pattern in patterns.items():
        print(f"[*] 🔍 กำลังยิงเรดาร์ด้วย {name}...")
        targets = scanner.find_all_patterns(pattern)
        
        for t in targets:
            # คำนวณเป็น Ghidra Offset (เพื่อเอาไปเทียบกับ 0x9809ac8)
            ghidra_offset = (t - base_addr) + 0x400000
            
            # ต้องเป็นโซน Global Variable (ประมาณ 0x8000000 - 0xC000000)
            if 0x8000000 < ghidra_offset < 0xC000000:
                found_targets.append(ghidra_offset)
                print(f"    -> 🟢 BINGO! เจอจาก {name} ที่ Offset: {hex(ghidra_offset)}")

    if not found_targets:
        print("\n[-] ❌ สแกนไม่เจอเลยครับ! (เกมอาจจะเปลี่ยน Register จาก R12/RBX เป็นตัวอื่นไปแล้ว)")
        return
        
    # โหวตหาตัวที่คะแนนสูงสุด (เพื่อกรองความผิดพลาด)
    counter = Counter(found_targets)
    top_target, votes = counter.most_common(1)[0]
    
    print("\n" + "="*50)
    print(f"🏆 สรุปผลการสแกน (The Real DAT_CONTROLLED_UNIT)")
    print("="*50)
    print(f"🎯 Offset ของแท้คือ : {hex(top_target)}")
    print(f"📊 ได้รับการยืนยัน    : {votes} เสียง")
    print("="*50)
    print("\n💡 นำเลขนี้ไปใส่ในไฟล์ mul.py ตรงตัวแปร DAT_CONTROLLED_UNIT ได้เลยครับ!!")

if __name__ == '__main__':
    main()