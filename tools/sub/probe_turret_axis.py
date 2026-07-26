import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_cgame_base
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    # Get barrel bone
    get_weapon_barrel(scanner, my_unit, (0,0,0), (1,0,0,0,1,0,0,0,1))
    cache = scanner.bone_cache.get(my_unit)
    if not cache:
        print("No bone cache!")
        return
        
    tree_ptr = cache['tree_ptr']
    wtm_off = cache['wtm_off']
    idx = cache['bone_idx']
    
    wtm_raw = scanner.read_mem(tree_ptr + wtm_off, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    print("=== MONITORING BARREL BONE MATRIX FOR 5 SECONDS ===")
    print("Please rotate your turret/gun in-game now!")
    for i in range(10):
        matrix_data = scanner.read_mem(w_ptr + (idx * 64), 64)
        r0 = struct.unpack_from("<fff", matrix_data, 0x00) # Row 0
        r1 = struct.unpack_from("<fff", matrix_data, 0x10) # Row 1
        r2 = struct.unpack_from("<fff", matrix_data, 0x20) # Row 2
        r3 = struct.unpack_from("<fff", matrix_data, 0x30) # Pos
        
        # Columns
        c0 = (matrix_data[0], matrix_data[16], matrix_data[32])
        c1 = (matrix_data[4], matrix_data[20], matrix_data[36])
        c2 = (matrix_data[8], matrix_data[24], matrix_data[40])
        
        print(f"[{i}] Pos: ({r3[0]:.2f}, {r3[1]:.2f}, {r3[2]:.2f})")
        print(f"    R0 (0x00): ({r0[0]:.3f}, {r0[1]:.3f}, {r0[2]:.3f})")
        print(f"    R1 (0x10): ({r1[0]:.3f}, {r1[1]:.3f}, {r1[2]:.3f})")
        print(f"    R2 (0x20): ({r2[0]:.3f}, {r2[1]:.3f}, {r2[2]:.3f})")
        time.sleep(0.5)

if __name__ == '__main__':
    main()
