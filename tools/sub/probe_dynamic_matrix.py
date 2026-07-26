import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr, get_weapon_barrel, get_cgame_base
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    # Trigger get_weapon_barrel to fill bone_cache
    get_weapon_barrel(scanner, my_unit, (0,0,0), (1,0,0,0,1,0,0,0,1))
    cache = scanner.bone_cache.get(my_unit)
    if not cache:
        print("No cache!")
        return
        
    tree_ptr = cache['tree_ptr']
    idx = cache['bone_idx']
    print(f"Tree: {hex(tree_ptr)} Bone Idx: {idx}")
    
    # Collect all candidate array pointers from tree_ptr (from +0x00 up to +0x80)
    pointers = {}
    for off in range(0, 0x80, 8):
        raw = scanner.read_mem(tree_ptr + off, 8)
        if not raw: continue
        ptr = struct.unpack("<Q", raw)[0]
        if is_valid_ptr(ptr):
            pointers[off] = ptr
            
    print(f"Found {len(pointers)} array pointers in tree_ptr:")
    for off, ptr in pointers.items():
        print(f"  Offset +{hex(off)} -> Pointer {hex(ptr)}")
        
    print("\n=== MONITORING FOR DYNAMIC CHANGES (rotate turret/aim gun!) ===")
    print("Snapshotting initial 64 bytes at each pointer for bone_idx...")
    initial_data = {}
    for off, ptr in pointers.items():
        initial_data[off] = scanner.read_mem(ptr + idx * 64, 64)
        
    for s in range(10):
        time.sleep(0.5)
        print(f"\n--- Check {s+1} ---")
        for off, ptr in pointers.items():
            curr = scanner.read_mem(ptr + idx * 64, 64)
            if curr != initial_data[off]:
                print(f"  🔥 CHANGED! Pointer at tree+{hex(off)} ({hex(ptr)}) matrix changed!")
                if curr and len(curr) == 64:
                    r0 = struct.unpack_from("<fff", curr, 0x00)
                    r1 = struct.unpack_from("<fff", curr, 0x10)
                    r2 = struct.unpack_from("<fff", curr, 0x20)
                    r3 = struct.unpack_from("<fff", curr, 0x30)
                    print(f"      Row0: ({r0[0]:.4f}, {r0[1]:.4f}, {r0[2]:.4f})")
                    print(f"      Row1: ({r1[0]:.4f}, {r1[1]:.4f}, {r1[2]:.4f})")
                    print(f"      Row2: ({r2[0]:.4f}, {r2[1]:.4f}, {r2[2]:.4f})")
                    print(f"      Row3: ({r3[0]:.4f}, {r3[1]:.4f}, {r3[2]:.4f})")
            else:
                print(f"  (unchanged) tree+{hex(off)}")

if __name__ == '__main__':
    main()
