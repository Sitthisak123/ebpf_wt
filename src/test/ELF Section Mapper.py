import struct
import sys
import os

def map_elf_sections(file_path):
    if not os.path.exists(file_path):
        print(f"❌ ไม่พบไฟล์: {file_path}")
        return

    with open(file_path, 'rb') as f:
        # 1. อ่าน ELF Header (64 bytes แรก)
        elf_header = f.read(64)
        
        # ดึงข้อมูลสำคัญจาก Header (ใช้ Little Endian <)
        # e_shoff (Offset ของ Section Header Table) อยู่ที่ offset 0x28 (8 bytes)
        e_shoff = struct.unpack("<Q", elf_header[0x28:0x30])[0]
        # e_shentsize (ขนาดต่อ 1 entry) อยู่ที่ offset 0x3A (2 bytes)
        e_shentsize = struct.unpack("<H", elf_header[0x3A:0x3C])[0]
        # e_shnum (จำนวน Section ทั้งหมด) อยู่ที่ offset 0x3C (2 bytes)
        e_shnum = struct.unpack("<H", elf_header[0x3C:0x3E])[0]
        # e_shstrndx (Index ของ Section ที่เก็บชื่อ) อยู่ที่ offset 0x3E (2 bytes)
        e_shstrndx = struct.unpack("<H", elf_header[0x3E:0x40])[0]

        print(f"📦 ข้อมูลไฟล์: {file_path}")
        print(f"   Section Table Offset: {hex(e_shoff)}")
        print(f"   Number of Sections: {e_shnum}")
        print("-" * 50)

        # 2. หา String Table (เพื่อดึงชื่อ Section)
        f.seek(e_shoff + (e_shstrndx * e_shentsize))
        shstr_header = f.read(e_shentsize)
        shstr_offset = struct.unpack("<Q", shstr_header[0x18:0x20])[0]
        shstr_size = struct.unpack("<Q", shstr_header[0x20:0x28])[0]

        f.seek(shstr_offset)
        string_table = f.read(shstr_size)

        # 3. วนลูปหา .data และ .bss
        results = {}
        for i in range(e_shnum):
            f.seek(e_shoff + (i * e_shentsize))
            entry = f.read(e_shentsize)
            
            # ดึงชื่อจาก String Table
            name_idx = struct.unpack("<I", entry[0:4])[0]
            name = string_table[name_idx:].split(b'\x00')[0].decode('utf-8')
            
            # ดึง Virtual Address (sh_addr) และ Size (sh_size)
            v_addr = struct.unpack("<Q", entry[0x10:0x18])[0]
            size = struct.unpack("<Q", entry[0x20:0x28])[0]

            if name in [".data", ".bss"]:
                results[name] = {"addr": v_addr, "size": size}
                print(f"🎯 พบ Section: {name}")
                print(f"   Virtual Address: {hex(v_addr)}")
                print(f"   Size: {hex(size)} bytes")
                print("-" * 30)

        return results

# --- วิธีใช้งาน ---
# เปลี่ยนพาธเป็นที่อยู่ไฟล์ aces ในเครื่องคุณ
game_path = "/home/xda-7/MyGames/WarThunder/linux64/aces" 
map_elf_sections(game_path)