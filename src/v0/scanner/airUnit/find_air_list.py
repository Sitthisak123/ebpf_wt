import struct
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, is_valid_ptr

def hunt_air_list():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame = get_cgame_base(scanner, base_addr)
    
    print(f"[*] CGame Base: {hex(cgame)}")
    print("[*] 🛡️ กรุณารอให้มีเครื่องบิน (AI หรือ ผู้เล่น) เกิดในแมพ...")
    input(">>> เมื่อเห็นเครื่องบินแล้ว กด Enter เพื่อเริ่มสแกน...")

    # สแกนหาคู่ Pointer + Count ใน CGame (กวาดตั้งแต่ 0x0 ถึง 0x2000)
    print("[*] กำลังสแกนหาบัญชีรายชื่อเครื่องบิน...")
    
    for off in range(0, 0x2000, 8):
        raw = scanner.read_mem(cgame + off, 8)
        if not raw: continue
        arr_ptr = struct.unpack("<Q", raw)[0]
        
        if is_valid_ptr(arr_ptr):
            # ลองอ่านค่าถัดไป 16-24 bytes (มักจะเป็น Count)
            for c_off in [8, 16]:
                raw_c = scanner.read_mem(cgame + off + c_off, 4)
                if not raw_c: continue
                count = struct.unpack("<I", raw_c)[0]
                
                if 1 <= count <= 128:
                    # ลองสุ่มอ่าน Unit ตัวแรกในลิสต์
                    raw_u = scanner.read_mem(arr_ptr, 8)
                    if raw_u:
                        u_ptr = struct.unpack("<Q", raw_u)[0]
                        if is_valid_ptr(u_ptr):
                            # ตรวจสอบว่าเป็น Unit จริงไหม (เช็ค Matrix หรือ Name)
                            # ลองอ่านชื่อที่ Offset 0xDF8 -> 0x28
                            name = "N/A"
                            info_raw = scanner.read_mem(u_ptr + 0xDF8, 8)
                            if info_raw:
                                info_ptr = struct.unpack("<Q", info_raw)[0]
                                if is_valid_ptr(info_ptr):
                                    n_p_raw = scanner.read_mem(info_ptr + 0x28, 8)
                                    if n_p_raw:
                                        n_p = struct.unpack("<Q", n_p_raw)[0]
                                        if is_valid_ptr(n_p):
                                            name_data = scanner.read_mem(n_p, 16)
                                            if name_data: name = name_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
                            
                            print(f"🎯 [น่าสงสัย] Offset: {hex(off)} | Count: {count} | ตัวอย่างชื่อ: {name}")

if __name__ == "__main__":
    hunt_air_list()