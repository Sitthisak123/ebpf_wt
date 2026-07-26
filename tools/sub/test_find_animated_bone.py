import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr, get_local_team, get_cgame_base, get_all_units

def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    cgame_base = get_cgame_base(scanner, base_addr)
    
    my_unit, _ = get_local_team(scanner, base_addr)
    if my_unit != 0:
        u_ptr = my_unit
        print(f"[*] 🎯 Local Player Unit: {hex(u_ptr)}")
    else:
        units = get_all_units(scanner, cgame_base)
        if not units:
            print("[-] No units found!")
            sys.exit()
        u_ptr = units[0][0]
        print(f"[*] Unit: {hex(u_ptr)}")
        
    target_idx = -1
    target_name = ""
    u_ptr_tree = 0
    
    for offset in [0x238, 0x1F0, 0x1FD8, 0x2E20, 0x2F38, 0x1E8, 0x1E0, 0x1D8]:
        raw_ptr = scanner.read_mem(u_ptr + offset, 8)
        if not raw_ptr: continue
        tree_ptr = struct.unpack("<Q", raw_ptr)[0]
        if not is_valid_ptr(tree_ptr): continue
        
        name_raw = scanner.read_mem(tree_ptr + 0x40, 8)
        if not name_raw: continue
        name_ptr = struct.unpack("<Q", name_raw)[0]
        
        if is_valid_ptr(name_ptr):
            names_block = scanner.read_mem(name_ptr, 0x4000)
            if names_block:
                for i in range(400):
                    try:
                        str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                        if str_offset == 0 or str_offset >= len(names_block): continue
                        end_idx = names_block.find(b'\x00', str_offset)
                        if end_idx != -1:
                            bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').strip().lower()
                            bad_words = ["fuel", "water", "smoke", "mg", "machine", "camera", "optic", "antenna", "gunner", "track", "wheel", "suspension"]
                            if ("gun_barrel" in bone_name or bone_name == "bone_gun") and not any(bad in bone_name for bad in bad_words):
                                target_idx = i
                                target_name = bone_name
                                u_ptr_tree = tree_ptr
                                print(f"[+] BINGO! Bone Index: {i} ('{bone_name}' at tree offset {hex(offset)})")
                                break
                    except: pass
        if target_idx != -1: break

    if target_idx == -1:
        print("[-] Target bone index not found!")
        sys.exit()
        
    print("\n[!] Snapshotting matrices...")
    candidates = {}
    for sub_off in range(0x0, 0x100, 8):
        p2_raw = scanner.read_mem(u_ptr_tree + sub_off, 8)
        if p2_raw:
            ptr2 = struct.unpack("<Q", p2_raw)[0]
            if is_valid_ptr(ptr2):
                mat_raw = scanner.read_mem(ptr2 + (target_idx * 64), 64)
                if mat_raw and len(mat_raw) == 64:
                    candidates[f"sub_off {hex(sub_off)}"] = {'ptr': ptr2, 'mat': mat_raw}
                    
    print(f"Monitoring {len(candidates)} matrix pointers over 10 seconds. Move mouse left/right and up/down!")
    for step in range(10):
        time.sleep(1.0)
        print(f"\n--- Check {step+1} ---")
        for name, data in candidates.items():
            new_mat = scanner.read_mem(data['ptr'] + (target_idx * 64), 64)
            if new_mat and len(new_mat) == 64:
                old_m = data['mat']
                if new_mat != old_m:
                    data['mat'] = new_mat
                    r0_old = struct.unpack_from("<fff", old_m, 0x00)
                    r0_new = struct.unpack_from("<fff", new_mat, 0x00)
                    r1_new = struct.unpack_from("<fff", new_mat, 0x10)
                    r2_new = struct.unpack_from("<fff", new_mat, 0x20)
                    r3_new = struct.unpack_from("<fff", new_mat, 0x30)
                    print(f"  🔥 CHANGED! {name}:")
                    print(f"      Row0: ({r0_new[0]:.4f}, {r0_new[1]:.4f}, {r0_new[2]:.4f})")
                    print(f"      Row1: ({r1_new[0]:.4f}, {r1_new[1]:.4f}, {r1_new[2]:.4f})")
                    print(f"      Row2: ({r2_new[0]:.4f}, {r2_new[1]:.4f}, {r2_new[2]:.4f})")
                    print(f"      Row3: ({r3_new[0]:.4f}, {r3_new[1]:.4f}, {r3_new[2]:.4f})")

if __name__ == '__main__':
    main()
