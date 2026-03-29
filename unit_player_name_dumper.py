import re
import struct
import sys
from collections import defaultdict

from main import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul
from src.utils.scanner import init_dynamic_offsets


SCAN_RANGE_START = 0x00
SCAN_RANGE_END = 0x1400
SCAN_STEP = 0x8
TOP_OFFSETS = 20

MODEL_PREFIXES = (
    "us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_", "air_",
)

NON_NAME_HINTS = (
    "gamedata", "tankmodels", "air_defence", "structures", "flightmodels",
    "exp_", ".blk", "dummy", "fortification", "battleship", "cruiser", "fighter",
    "helicopter", "light tank", "medium tank", "heavy tank",
)


def is_valid_ptr(p):
    return 0x10000 < p < 0xFFFFFFFFFFFFFFFF


def read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_c_string(scanner, ptr, max_len=64):
    if not is_valid_ptr(ptr):
        return None
    data = scanner.read_mem(ptr, max_len)
    if not data:
        return None
    raw = data.split(b"\x00")[0]
    if len(raw) < 3:
        return None
    try:
        text = raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if len(text) < 3 or len(text) > 28:
        return None
    return text


def looks_like_player_name(text):
    if not text:
        return False
    t = text.strip()
    tl = t.lower()

    if "/" in t or "\\" in t:
        return False
    if any(h in tl for h in NON_NAME_HINTS):
        return False
    if tl.startswith(MODEL_PREFIXES):
        return False
    if re.fullmatch(r"[a-z0-9_]+", t):
        # model-like or generic key, very likely not nickname
        return False
    if not re.fullmatch(r"[A-Za-z0-9 _\-\[\]\.]+", t):
        return False
    if not any(ch.isalpha() for ch in t):
        return False
    return True


def collect_playable_units(scanner, base_addr):
    cgame = mul.get_cgame_base(scanner, base_addr)
    if cgame == 0:
        return 0, 0, []

    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    units = []
    for u_ptr, is_air in mul.get_all_units(scanner, cgame):
        status = mul.get_unit_status(scanner, u_ptr)
        if not status:
            continue
        team, state, unit_name, _ = status
        if state >= 1:
            continue

        profile = mul.get_unit_filter_profile(scanner, u_ptr)
        if profile.get("skip"):
            continue

        kind = profile.get("kind")
        if kind == "air":
            is_air = True
        elif kind == "ground":
            is_air = False

        units.append(
            {
                "u_ptr": u_ptr,
                "team": team,
                "is_air": is_air,
                "tag": (profile.get("tag") or "").lower(),
                "path": (profile.get("path") or "").lower(),
                "model": (profile.get("display_name") or "").lower(),
                "label": "MY" if u_ptr == my_unit else ("AIR" if is_air else "GROUND"),
            }
        )
    return cgame, my_unit, units


def scan_candidate_name_offsets(scanner, units):
    offset_hits = defaultdict(list)

    for off in range(SCAN_RANGE_START, SCAN_RANGE_END, SCAN_STEP):
        for u in units:
            ptr = read_ptr(scanner, u["u_ptr"] + off)
            if not is_valid_ptr(ptr):
                continue
            text = read_c_string(scanner, ptr, 64)
            if not looks_like_player_name(text):
                continue
            offset_hits[off].append((u["u_ptr"], text))

    scored = []
    for off, hits in offset_hits.items():
        unique_names = sorted(set(text for _, text in hits))
        coverage = len({u for u, _ in hits})
        if coverage < 2 or len(unique_names) < 2:
            continue
        scored.append((coverage, len(unique_names), off, unique_names[:8]))

    scored.sort(reverse=True)
    return scored, offset_hits


def main():
    print("[*] PLAYER NAME DUMPER")
    pid = get_game_pid()
    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame, my_unit, units = collect_playable_units(scanner, base)
    if cgame == 0 or not units:
        print("[-] no playable units")
        return

    print(f"[*] CGame={hex(cgame)} | MY_UNIT={hex(my_unit) if my_unit else '0x0'} | playable_units={len(units)}")

    scored, raw_hits = scan_candidate_name_offsets(scanner, units)
    if not scored:
        print("[-] no candidate player-name offset found in 0x00..0x13F8")
        return

    print("\n[+] Candidate player-name offsets")
    print("-" * 120)
    print(f"{'Offset':<10} | {'Coverage':<8} | {'Unique':<6} | Examples")
    print("-" * 120)
    for coverage, uniq, off, examples in scored[:TOP_OFFSETS]:
        print(f"{hex(off):<10} | {coverage:<8} | {uniq:<6} | {', '.join(examples)}")

    best_offsets = [entry[2] for entry in scored[:3]]
    print("\n[+] Per-unit names from top offsets")
    print("-" * 120)
    for u in units[:80]:
        parts = []
        for off in best_offsets:
            hit = None
            for uptr, txt in raw_hits.get(off, []):
                if uptr == u["u_ptr"]:
                    hit = txt
                    break
            if hit:
                parts.append(f"{hex(off)}='{hit}'")
        if parts:
            print(f"{u['label']:<6} | unit={hex(u['u_ptr'])} | team={u['team']} | model={u['model']} | " + " ; ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Exit")
    except Exception as e:
        print(f"[-] error: {e}")
        sys.exit(1)
