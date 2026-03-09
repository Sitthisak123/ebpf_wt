from bcc import BPF
import ctypes
import os
import time
import struct
flag = 0
bpf_source = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct data_t {
    u32 x1, y1, z1; // สำหรับ Offset 0x10 (ModelName)
    u32 x2, y2, z2; // สำหรับ Offset 0x20 (FullName)
    u32 x3, y3, z3; // สำหรับ Offset 0x28 (ShortName)
};

BPF_PERF_OUTPUT(events);
BPF_HASH(config, u32, u32);

int test_read(struct pt_regs *ctx) {
    u32 key = 0;
    u32 *target_pid = config.lookup(&key);
    if (!target_pid) return 0;

    u32 current_pid = bpf_get_current_pid_tgid() >> 32;
    if (current_pid != *target_pid) return 0;

    // 🎯 1. ใส่ Pointer ของชื่อรถถังที่คุณหาได้ตรงนี้
    u64 found_addr = 0x23fdf528; // <--- เปลี่ยนเลขตรงนี้!
    
    struct data_t data = {};
    
    // ทดสอบที่ 1: ถอย 0x10 (ModelName)
    u64 base1 = found_addr - 0x10;
    bpf_probe_read_user(&data.x1, sizeof(u32), (void *)(base1 + 0xB38));
    bpf_probe_read_user(&data.z1, sizeof(u32), (void *)(base1 + 0xB3C)); 
    bpf_probe_read_user(&data.y1, sizeof(u32), (void *)(base1 + 0xB40));

    // ทดสอบที่ 2: ถอย 0x20 (FullName)
    u64 base2 = found_addr - 0x20;
    bpf_probe_read_user(&data.x2, sizeof(u32), (void *)(base2 + 0xB38));
    bpf_probe_read_user(&data.z2, sizeof(u32), (void *)(base2 + 0xB3C)); 
    bpf_probe_read_user(&data.y2, sizeof(u32), (void *)(base2 + 0xB40));

    // ทดสอบที่ 3: ถอย 0x28 (ShortName)
    u64 base3 = found_addr - 0x28;
    bpf_probe_read_user(&data.x3, sizeof(u32), (void *)(base3 + 0xB38));
    bpf_probe_read_user(&data.z3, sizeof(u32), (void *)(base3 + 0xB3C)); 
    bpf_probe_read_user(&data.y3, sizeof(u32), (void *)(base3 + 0xB40));

    events.perf_submit(ctx, &data, sizeof(data));
    return 0;
}
"""

def to_float(u32_val):
    return struct.unpack('f', struct.pack('I', u32_val))[0]

def run_position_reader(pid):
    print(f"[*] เจาะระบบหารถถังจาก PID: {pid}")
    b = BPF(text=bpf_source)
    b["config"][ctypes.c_uint32(0)] = ctypes.c_uint32(pid)
    b.attach_kprobe(event="__x64_sys_poll", fn_name="test_read")

    def print_event(cpu, data, size):
        event = b["events"].event(data)
        os.system('clear')
        
        print("🎯 [ทดสอบดึงพิกัดจาก 3 Offsets หลัก]")
        print("-" * 40)
        
        for i, (name, x, y, z) in enumerate([
            ("0x10 (ModelName)", to_float(event.x1), to_float(event.y1), to_float(event.z1)),
            ("0x20 (FullName) ", to_float(event.x2), to_float(event.y2), to_float(event.z2)),
            ("0x28 (ShortName)", to_float(event.x3), to_float(event.y3), to_float(event.z3))
        ]):
            # ตรวจสอบว่าพิกัดสมจริงไหม
            if -50000.0 < x < 50000.0 and x != 0.0 and abs(x) != 2147440000.0:
                print(f"✅ สมมติฐานที่ {i+1} : {name}")
                print(f"    X: {x:.2f} | Y: {y:.2f} | Z: {z:.2f}  <-- ของจริง!! ขับรถดูเลย!!")
            else:
                print(f"❌ สมมติฐานที่ {i+1} : {name}")
                print(f"    (ได้ค่าขยะ: X={x:.2f})")
        print("-" * 40)
        print("[*] ขยับรถในเกมดูว่าเลขไหนเปลี่ยนตาม (กด Ctrl+C เพื่อหยุด)")
        global flag
        flag = 1

    b["events"].open_perf_buffer(print_event)
    
    while True:
        try:
            b.perf_buffer_poll()
            time.sleep(1) 
            if flag:
                return
        except KeyboardInterrupt:
            break

# 🚨 อย่าลืมเปลี่ยน PID นะครับ
TARGET_PID = 329024 
run_position_reader(TARGET_PID)