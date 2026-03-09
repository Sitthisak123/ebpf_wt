from bcc import BPF
import ctypes
import os
import time
import struct
import subprocess
import sys

def get_game_pid():
    try:
        pid = subprocess.check_output(["pgrep", "aces"]).decode().strip().split('\n')[0]
        return int(pid)
    except subprocess.CalledProcessError:
        print("[!] Error: หาโปรเซส 'aces' (War Thunder) ไม่เจอ!")
        sys.exit(1)

def validate_pointer(mem_f, pointer_addr):
    """ แอบส่อง Memory ล่วงหน้าเพื่อกรองพิกัดจริง และตรวจจับการขยับ """
    for offset in [0x10, 0x20, 0x28]:
        base = pointer_addr - offset
        pos_addr = base + 0xB38
        try:
            mem_f.seek(pos_addr)
            data = mem_f.read(12)
            if len(data) == 12:
                x, z, y = struct.unpack('fff', data)
                
                # กรอง 1: ตัดค่า 0.00 และค่าขยะ (พิกัดเกมปกติไม่เกิน +-80000 เมตร)
                if x == 0.0 or y == 0.0 or z == 0.0:
                    continue
                if -80000.0 < x < 80000.0 and -80000.0 < y < 80000.0 and -80000.0 < z < 80000.0:
                    
                    # 🎯 กรอง 2 (Step 6): ตรวจจับการเคลื่อนไหวใน 3 วินาที
                    print(f"\n    [?] พบพิกัดน่าสงสัยที่ Base: {hex(base)}")
                    print(f"        -> กำลังจ้องจับผิด 3 วินาที... (ขยับรถเลย!!)")
                    
                    start_time = time.time()
                    has_moved = False
                    
                    while time.time() - start_time < 3.0:
                        mem_f.seek(pos_addr)
                        new_data = mem_f.read(12)
                        if len(new_data) == 12:
                            nx, nz, ny = struct.unpack('fff', new_data)
                            
                            # ถ้าขยับแม้แต่นิดเดียว (ทศนิยมเปลี่ยนเกิน 0.001) ถือว่าของจริง!
                            if abs(nx - x) > 0.001 or abs(ny - y) > 0.001 or abs(nz - z) > 0.001:
                                has_moved = True
                                break
                        time.sleep(0.1) # เช็คทุกๆ 0.1 วินาที
                        
                    if has_moved:
                        return True, base, offset, x, y, z
                    else:
                        print(f"        ❌ ข้าม: พิกัดนิ่งสนิท (น่าจะเป็น UI, ป้ายชื่อ หรือซากรถ)")
                        continue
        except Exception:
            pass
    return False, 0, 0, 0, 0, 0

# โค้ดภาษา C สำหรับ eBPF
bpf_source = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct data_t {
    u32 x, y, z;
};

BPF_PERF_OUTPUT(events);
BPF_HASH(config, u32, u32);

int live_radar(struct pt_regs *ctx) {
    u32 key = 0;
    u32 *target_pid = config.lookup(&key);
    if (!target_pid) return 0;

    u32 current_pid = bpf_get_current_pid_tgid() >> 32;
    if (current_pid != *target_pid) return 0;

    u64 base_addr = VALID_BASE_PLACEHOLDER; 
    
    struct data_t data = {};
    bpf_probe_read_user(&data.x, sizeof(u32), (void *)(base_addr + 0xB38));
    bpf_probe_read_user(&data.z, sizeof(u32), (void *)(base_addr + 0xB3C)); 
    bpf_probe_read_user(&data.y, sizeof(u32), (void *)(base_addr + 0xB40));

    events.perf_submit(ctx, &data, sizeof(data));
    return 0;
}
"""

def full_auto_radar(target_string):
    pid = get_game_pid()
    target_bytes = target_string.encode('utf-8')

    os.system('clear')
    print("🚀 [Ultimate Auto-Radar: สแกนอัตโนมัติเต็มรูปแบบ]")
    print("-" * 55)
    print(f"[*] 1/4 กำลังค้นหาคำว่า: '{target_string}' ใน RAM ...")
    
    maps_file = f"/proc/{pid}/maps"
    mem_file = f"/proc/{pid}/mem"

    string_addrs = []
    
    # --- Phase 1: ค้นหา String ---
    try:
        with open(maps_file, 'r') as map_f, open(mem_file, 'rb', 0) as mem_f:
            for line in map_f:
                parts = line.split()
                if len(parts) < 2 or 'r' not in parts[1]: continue
                if len(parts) >= 6 and (parts[5].startswith('/dev') or parts[5].startswith('/sys')): continue

                start, end = [int(x, 16) for x in parts[0].split('-')]
                try:
                    mem_f.seek(start)
                    chunk = mem_f.read(end - start)
                    idx = 0
                    while True:
                        idx = chunk.find(target_bytes, idx)
                        if idx == -1: break
                        string_addrs.append(start + idx)
                        idx += len(target_bytes)
                except Exception:
                    pass
    except PermissionError:
        print("[!] สิทธิ์ไม่พอ! กรุณารันด้วย sudo")
        sys.exit(1)

    print(f"    -> เจอข้อความนี้ทั้งหมด {len(string_addrs)} จุด")
    if not string_addrs:
        print("\n❌ ไม่พบข้อความนี้ในเกม ลองเช็คชื่อรถอีกครั้งครับ")
        sys.exit(1)

    print("\n[*] 2/4 สร้างแผนที่ Pointers และคัดกรองพิกัดจริง (ความไวแสง) ...")
    print("🚨🚨 คำเตือน: กรุณาขับรถเดินหน้า/ถอยหลังไว้ตลอดเวลาในเกม 🚨🚨")
    
    pointer_bytes_list = [(s_addr, struct.pack('<Q', s_addr)) for s_addr in string_addrs]
    
    valid_base = 0
    found_offset = 0

    # --- Phase 2 & 3: ค้นหา Pointers & ตรวจจับการเคลื่อนไหว ---
    with open(maps_file, 'r') as map_f, open(mem_file, 'rb', 0) as mem_f:
        for line in map_f:
            if valid_base != 0: break
            parts = line.split()
            if len(parts) < 2 or 'r' not in parts[1]: continue
            if len(parts) >= 6 and (parts[5].startswith('/dev') or parts[5].startswith('/sys')): continue

            start, end = [int(x, 16) for x in parts[0].split('-')]
            try:
                mem_f.seek(start)
                chunk = mem_f.read(end - start)
                
                for s_addr, p_bytes in pointer_bytes_list:
                    idx = 0
                    while True:
                        idx = chunk.find(p_bytes, idx)
                        if idx == -1: break
                        pointer_addr = start + idx

                        # แอบส่อง! ถ้านิ่งเกิน 3 วิ จะโดนเตะทิ้ง ถ้าขยับจะให้ผ่าน!
                        is_valid, base, offset, x, y, z = validate_pointer(mem_f, pointer_addr)
                        if is_valid:
                            print("\n✅ [แจ็คพอตแตก!] ระบบจับการเคลื่อนไหวได้ ยืนยันเป้าหมายจริง!")
                            print(f"    - พบ Pointer ที่: {hex(pointer_addr)}")
                            print(f"    - คำนวณ Unit Base: {hex(base)} (Offset: 0x{offset:X})")
                            valid_base = base
                            found_offset = offset
                            break

                        idx += 8 
                    if valid_base != 0: break
            except Exception:
                pass

    if valid_base == 0:
        print("\n❌ สแกนจบแล้ว ไม่พบพิกัดที่เคลื่อนไหวได้เลยครับ")
        print("[*] คุณลืมขยับรถตอนมันสแกน หรือรถอาจจะตายไปแล้ว ลองใหม่ดูนะ!")
        sys.exit(1)

    print("\n[*] 3/4 เตรียมการแทรกซึมด้วย eBPF ...")
    time.sleep(1)
    
    final_bpf = bpf_source.replace("VALID_BASE_PLACEHOLDER", hex(valid_base))
    
    b = BPF(text=final_bpf)
    b["config"][ctypes.c_uint32(0)] = ctypes.c_uint32(pid)
    b.attach_kprobe(event="__x64_sys_poll", fn_name="live_radar")

    print("[*] 4/4 ระบบพร้อมทำงาน!")
    time.sleep(1)

    def print_event(cpu, data, size):
        event = b["events"].event(data)
        x = struct.unpack('f', struct.pack('I', event.x))[0]
        y = struct.unpack('f', struct.pack('I', event.y))[0]
        z = struct.unpack('f', struct.pack('I', event.z))[0]
        
        if x == 0.0 or y == 0.0 or z == 0.0: return
        
        os.system('clear')
        print("🎯 [Ultimate Auto-Radar - Live Tracking]")
        print("-" * 55)
        print(f"✅ ล็อกเป้าหมาย: '{target_string}' | Base: {hex(valid_base)}")
        print(f"    พิกัด X : {x:10.2f}")
        print(f"    พิกัด Y : {y:10.2f}")
        print(f"    พิกัด Z : {z:10.2f}")
        print("-" * 55)
        print("[*] ระบบ Radar ทำงานสมบูรณ์แบบ! (กด Ctrl+C เพื่อหยุด)")

    b["events"].open_perf_buffer(print_event)
    
    while True:
        try:
            b.perf_buffer_poll()
            time.sleep(0.05)
        except KeyboardInterrupt:
            print("\n[!] ปิดระบบ Radar")
            break

if __name__ == "__main__":
    # 🎯 แก้ชื่อรถของคุณตรงนี้
    TARGET_NAME = "ussr_2s38" 
    
    full_auto_radar(TARGET_NAME)