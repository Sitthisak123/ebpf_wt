import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    raw_ptr = scanner.read_mem(my_unit + 0x238, 8)
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    
    wtm_raw = scanner.read_mem(tree_ptr + 0x00, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
    name_ptr = struct.unpack("<Q", raw_name)[0]
    names_block = scanner.read_mem(name_ptr, 0x4000)
    
    bone_names = {}
    for i in range(400):
        try:
            str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
            if str_offset == 0 or str_offset >= len(names_block): continue
            end_idx = names_block.find(b'\x00', str_offset)
            if end_idx != -1:
                bname = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').strip()
                if "gun" in bname.lower() or "turret" in bname.lower() or "camera" in bname.lower():
                    bone_names[i] = bname
        except: pass

    print(f"Found {len(bone_names)} relevant gun/turret bones:")
    for idx, bname in bone_names.items():
        print(f"  [{idx:3d}] {bname}")
        
    print("\n=== SNAPSHOTTING AND MONITORING GUN/TURRET BONES ===")
    print("Please move turret left/right AND raise/lower gun up/down!\n")
    
    snapshots = {}
    for idx in bone_names:
        snapshots[idx] = scanner.read_mem(w_ptr + idx * 64, 64)
        
    for step in range(12):
        time.sleep(0.5)
        print(f"--- Step {step+1} ---")
        for idx, bname in bone_names.items():
            curr = scanner.read_mem(w_ptr + idx * 64, 64)
            if curr != snapshots[idx]:
                snapshots[idx] = curr
                r0 = struct.unpack_from("<fff", curr, 0x00)
                r1 = struct.unpack_from("<fff", curr, 0x10)
                r2 = struct.unpack_from("<fff", curr, 0x20)
                r3 = struct.unpack_from("<fff", curr, 0x30)
                print(f"  🔥 Bone [{idx:3d}] '{bname}' CHANGED!")
                print(f"      Row0: ({r0[0]:.4f}, {r0[1]:.4f}, {r0[2]:.4f})")
                print(f"      Row1: ({r1[0]:.4f}, {r1[1]:.4f}, {r1[2]:.4f})")
                print(f"      Row2: ({r2[0]:.4f}, {r2[1]:.4f}, {r2[2]:.4f})")
                print(f"      Pos : ({r3[0]:.4f}, {r3[1]:.4f}, {r3[2]:.4f})")

if __name__ == '__main__':
    main()
