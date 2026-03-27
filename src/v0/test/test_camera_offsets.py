from bcc import BPF
import ctypes
import os
import time
import struct  # ตัวช่วยถอดรหัส Float

bpf_source = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct data_t {
    u32 x; // เปลี่ยนจาก float เป็น u32 เพื่อหลอก BCC
    u32 y;
    u32 z;
};

BPF_PERF_OUTPUT(events);
BPF_HASH(config, u32, u32);

int test_read(struct pt_regs *ctx) {
    u32 key = 0;
    u32 *target_pid = config.lookup(&key);
    if (!target_pid) return 0;

    u32 current_pid = bpf_get_current_pid_tgid() >> 32;
    if (current_pid != *target_pid) return 0;

    // 🎯 อย่าลืมเปลี่ยนเป็น Address กล้องที่คุณหามาได้นะครับ!
    u64 camera_ptr = 0x7fd812345678; 
    
    if (camera_ptr == 0) return 0;

    struct data_t data = {};
    
    // Offset ของ Position = 0x58 
    u64 pos_addr = camera_ptr + 0x58; 
    
    // ดึงค่า 4-byte (ขนาดเท่ากับ Float)
    bpf_probe_read_user(&data.x, sizeof(u32), (void *)(pos_addr));
    bpf_probe_read_user(&data.z, sizeof(u32), (void *)(pos_addr + 4)); 
    bpf_probe_read_user(&data.y, sizeof(u32), (void *)(pos_addr + 8));

    events.perf_submit(ctx, &data, sizeof(data));
    return 0;
}
"""

def run_offset_tester(pid):
    print(f"[*] เริ่มการทดสอบ Offset สำหรับ PID: {pid}")
    b = BPF(text=bpf_source)
    b["config"][ctypes.c_uint32(0)] = ctypes.c_uint32(pid)

    b.attach_kprobe(event="__x64_sys_poll", fn_name="test_read")

    def print_event(cpu, data, size):
        event = b["events"].event(data)
        
        # ถอดรหัส u32 กลับมาเป็น Float ด้วยโมดูล struct
        val_x = struct.unpack('f', struct.pack('I', event.x))[0]
        val_y = struct.unpack('f', struct.pack('I', event.y))[0]
        val_z = struct.unpack('f', struct.pack('I', event.z))[0]

        os.system('clear')
        print(f"🎯 [ทดสอบ Offset 0x58 (Position)]")
        print(f"    พิกัด X : {val_x:.2f}")
        print(f"    พิกัด Y : {val_y:.2f}")
        print(f"    พิกัด Z : {val_z:.2f}")
        print("\n[*] ขยับกล้องในเกมดูว่าตัวเลขเปลี่ยนตามไหม (กด Ctrl+C เพื่อหยุด)")

    b["events"].open_perf_buffer(print_event)
    
    while True:
        try:
            b.perf_buffer_poll()
            time.sleep(0.05) # หน่วงเวลาให้ดูทัน
        except KeyboardInterrupt:
            print("\n[!] หยุดการทดสอบ")
            break

# 🚨 อย่าลืมเปลี่ยน PID นะครับ
TARGET_PID = 3334 
run_offset_tester(TARGET_PID)