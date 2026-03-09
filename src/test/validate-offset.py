from bcc import BPF
import ctypes
import os

bpf_source = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct data_t {
    u64 read_value; // เราจะอ่านค่า 8 byte (Pointer)
};

BPF_PERF_OUTPUT(events);
BPF_HASH(config, u32, u32);

int test_read(struct pt_regs *ctx) {
    u32 key = 0;
    u32 *target_pid = config.lookup(&key);
    if (!target_pid) return 0;

    u32 current_pid = bpf_get_current_pid_tgid() >> 32;
    if (current_pid != *target_pid) return 0;

    struct data_t data = {};
    
    // เอา Base Address + Offset ของ LocalPlayer จาก UC
    u64 target_address = 0x40b000 + 0x6cba870; 

    // แอบอ่านค่าจาก Memory ของเกม (อ่านมา 8 bytes)
    bpf_probe_read_user(&data.read_value, sizeof(data.read_value), (void *)target_address);

    events.perf_submit(ctx, &data, sizeof(data));
    return 0;
}
"""

def run_tester(pid):
    print(f"[*] ทดสอบอ่าน Pointer จาก PID: {pid}")
    b = BPF(text=bpf_source)
    b["config"][ctypes.c_uint32(0)] = ctypes.c_uint32(pid)

    # ใช้ poll trigger เหมือนเดิม
    b.attach_kprobe(event="__x64_sys_poll", fn_name="test_read")

    def print_event(cpu, data, size):
        event = b["events"].event(data)
        val = event.read_value
        
        print(f"[!] ข้อมูลที่อ่านได้:")
        print(f"    >>> Hex: 0x{val:016x}")
        
        if val > 0x700000000000:
            print(f"    ✅ นี่คือ Pointer ของ Linux ของแท้! แปลว่า Offset ใกล้เคียงมาก")
        elif val == 0:
            print(f"    ❌ ได้ค่า 0 (ว่างเปล่า) แปลว่า Offset ของ Linux ขยับไปจาก Windows เยอะ")
        else:
            print(f"    ❓ ได้ค่าขยะ แปลว่า Offset ไม่ตรง")
            
        os._exit(0)

    b["events"].open_perf_buffer(print_event)
    print("[*] สลับไปขยับเมาส์ในเกม 1 ที...")
    
    while True:
        try:
            b.perf_buffer_poll()
        except KeyboardInterrupt:
            break

# 🚨 ใส่ PID ใหม่ของ aces ก่อนรัน!
run_tester(13787) # จากรูปคุณคือ 12385