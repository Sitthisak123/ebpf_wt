import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_unit_3d_box_data, get_cgame_base, get_all_units
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    print(f"My Unit: {hex(my_unit)}")
    cache = mul.bone_cache.get(my_unit)
    if not cache:
        get_weapon_barrel(scanner, my_unit, (0,0,0), (1,0,0,0,1,0,0,0,1))
        cache = mul.bone_cache.get(my_unit)
        
    if not cache:
        print("Failed to get bone cache!")
        return
        
    tree_ptr = cache['tree_ptr']
    wtm_off = cache['wtm_off']
    idx = cache['bone_idx']
    
    wtm_raw = scanner.read_mem(tree_ptr + wtm_off, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    print(f"Tree: {hex(tree_ptr)} WTM_PTR: {hex(w_ptr)} Bone Index: {idx}")
    
    # Read name of bone idx
    raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
    name_ptr = struct.unpack("<Q", raw_name)[0]
    names_block = scanner.read_mem(name_ptr, 0x4000)
    str_offset = struct.unpack_from("<H", names_block, idx * 2)[0]
    end_idx = names_block.find(b'\x00', str_offset)
    b_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore')
    print(f"Bone Name: '{b_name}'")
    
    # Print matrix 3 times
    for s in range(3):
        matrix_data = scanner.read_mem(w_ptr + (idx * 64), 64)
        r0 = struct.unpack_from("<ffff", matrix_data, 0x00)
        r1 = struct.unpack_from("<ffff", matrix_data, 0x10)
        r2 = struct.unpack_from("<ffff", matrix_data, 0x20)
        r3 = struct.unpack_from("<ffff", matrix_data, 0x30)
        print(f"\n--- Sample {s+1} ---")
        print(f"Row0 (X-axis/Forward?): ({r0[0]:.4f}, {r0[1]:.4f}, {r0[2]:.4f})")
        print(f"Row1 (Y-axis/Up?):      ({r1[0]:.4f}, {r1[1]:.4f}, {r1[2]:.4f})")
        print(f"Row2 (Z-axis/Right?):   ({r2[0]:.4f}, {r2[1]:.4f}, {r2[2]:.4f})")
        print(f"Row3 (Position):        ({r3[0]:.4f}, {r3[1]:.4f}, {r3[2]:.4f})")
        time.sleep(0.5)

if __name__ == '__main__':
    main()
