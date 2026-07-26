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
    
    # Check tree+0x00 and tree+0x10 and u_ptr directly!
    wtm_raw_00 = scanner.read_mem(tree_ptr + 0x00, 8)
    w_ptr_00 = struct.unpack("<Q", wtm_raw_00)[0]
    
    wtm_raw_10 = scanner.read_mem(tree_ptr + 0x10, 8)
    w_ptr_10 = struct.unpack("<Q", wtm_raw_10)[0]
    
    idx = 348 # bone_gun
    print(f"Monitoring bone {idx} (bone_gun) for 10 seconds...")
    print("Please move turret left/right AND elevate/depress gun up/down!\n")
    
    for t in range(20):
        time.sleep(0.5)
        m00 = scanner.read_mem(w_ptr_00 + idx * 64, 64)
        m10 = scanner.read_mem(w_ptr_10 + idx * 64, 64)
        
        r0_00 = struct.unpack_from("<fff", m00, 0x00)
        r1_00 = struct.unpack_from("<fff", m00, 0x10)
        r2_00 = struct.unpack_from("<fff", m00, 0x20)
        r3_00 = struct.unpack_from("<fff", m00, 0x30)
        
        r0_10 = struct.unpack_from("<fff", m10, 0x00)
        r1_10 = struct.unpack_from("<fff", m10, 0x10)
        r2_10 = struct.unpack_from("<fff", m10, 0x20)
        r3_10 = struct.unpack_from("<fff", m10, 0x30)
        
        print(f"--- T={t*0.5:.1f}s ---")
        print(f"[tree+0x00] Row0: ({r0_00[0]:.3f}, {r0_00[1]:.3f}, {r0_00[2]:.3f})")
        print(f"            Row1: ({r1_00[0]:.3f}, {r1_00[1]:.3f}, {r1_00[2]:.3f})")
        print(f"            Row2: ({r2_00[0]:.3f}, {r2_00[1]:.3f}, {r2_00[2]:.3f})")
        print(f"            Pos:  ({r3_00[0]:.3f}, {r3_00[1]:.3f}, {r3_00[2]:.3f})")
        
        print(f"[tree+0x10] Row0: ({r0_10[0]:.3f}, {r0_10[1]:.3f}, {r0_10[2]:.3f})")
        print(f"            Row1: ({r1_10[0]:.3f}, {r1_10[1]:.3f}, {r1_10[2]:.3f})")
        print(f"            Row2: ({r2_10[0]:.3f}, {r2_10[1]:.3f}, {r2_10[2]:.3f})")
        print(f"            Pos:  ({r3_10[0]:.3f}, {r3_10[1]:.3f}, {r3_10[2]:.3f})\n")

if __name__ == '__main__':
    main()
