#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🚀 PoC Probe: Direct ECS Class Table (Query Table) Inspector for War Thunder (Dagor DaECS)
========================================================================================
สคริปต์ทดสอบและพิสูจน์แนวคิด (Proof of Concept):
1. เข้าถึง ECS Manager + OFF_ECS_CLASS_TABLE (0x5E8) และ OFF_ECS_NODE_TABLE (0x178)
2. กวาดหา Query Selectors (0..2048) ที่เอนจินเกมใช้ลงทะเบียนสำหรับ Projectile / Missile / Rocket
3. ดึง Sublist Offsets ตรงไปยัง Node Table เฉพาะก้อนที่เป็นขีปนาวุธ (Bypass 350 archetypes)
4. วัด Benchmark เปรียบเทียบความเร็ว: Brute-Force Sweep vs Direct Class Table Query

วิธีใช้:
  sudo python3 tools/sub/missile/poc_ecs_class_table_probe.py
  sudo python3 tools/sub/missile/poc_ecs_class_table_probe.py --watch
  sudo python3 tools/sub/missile/poc_ecs_class_table_probe.py --compare
========================================================================================
"""

import os
import sys
import time
import struct
import math
import argparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul
from src.utils.missile import MissileScanner, classify_seeker_type, _is_valid_missile_motion

# ====================================================================
# Constants & Offsets
# ====================================================================
ECS_MANAGER_CANDIDATES = [
    getattr(mul, 'OFF_ECS_MANAGER', 0x8cd5940),
    0x8cd5940,
    0x8ccd918,
    0x88b9248,
    0x81a5ef0,
    0x8c48498,
    0x8c2d100,
    0xb0e29b8,
    0xb0e2b98,
    0x8225aa0,
    0x8226ba0,
]

OFF_ECS_NODE_TABLE  = getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178)
OFF_ECS_CLASS_TABLE = getattr(mul, 'OFF_ECS_CLASS_TABLE', 0x5E8)
OFF_PROJ_LIST       = getattr(mul, 'OFF_PROJ_LIST', 0xac02ab8)

OFF_RKT_POS         = getattr(mul, 'OFF_RKT_POS', 0x23c)
OFF_RKT_VEL         = getattr(mul, 'OFF_RKT_VEL', 0x258)
OFF_RKT_OWNER       = getattr(mul, 'OFF_RKT_OWNER', 0x50)
OFF_RKT_STATE       = getattr(mul, 'OFF_RKT_STATE', 0x94)
OFF_RKT_PHASE       = getattr(mul, 'OFF_RKT_PHASE', 0x498)
OFF_RKT_GUIDANCE    = getattr(mul, 'OFF_RKT_GUIDANCE', 0x680)
OFF_RKT_PROPS       = getattr(mul, 'OFF_RKT_PROPS', 0x710)

TOTAL_SELECTORS_TO_SCAN = 2048


# ====================================================================
# Memory Helpers
# ====================================================================
def is_valid_ptr(p: int) -> bool:
    return 0x100000 < p < 0x7FFFFFFFFFFF


def read_ptr(sc: MemoryScanner, addr: int) -> int:
    d = sc.read_mem(addr, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0


def read_u32(sc: MemoryScanner, addr: int) -> int:
    d = sc.read_mem(addr, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0


def read_u16(sc: MemoryScanner, addr: int) -> int:
    d = sc.read_mem(addr, 2)
    return struct.unpack("<H", d)[0] if d and len(d) >= 2 else 0


def read_u8(sc: MemoryScanner, addr: int) -> int:
    d = sc.read_mem(addr, 1)
    return d[0] if d and len(d) >= 1 else 0


def read_vec3(sc: MemoryScanner, addr: int):
    d = sc.read_mem(addr, 12)
    return struct.unpack("<fff", d) if d and len(d) >= 12 else (0.0, 0.0, 0.0)


def read_str(sc: MemoryScanner, addr: int, max_len=64) -> str:
    d = sc.read_mem(addr, max_len)
    if not d:
        return ""
    try:
        end = d.index(0)
        return d[:end].decode("utf-8", errors="replace").strip()
    except ValueError:
        return d.decode("utf-8", errors="replace").strip()


# ====================================================================
# Core Probe Functions
# ====================================================================
class ECSClassTableProbe:
    """
    Direct Inspector สำหรับทดสอบอ่าน ECS Class Table (Query Table)
    เพื่อตรวจสอบ Selector ขีปนาวุธใน War Thunder
    """

    def __init__(self):
        self.pid = 0
        self.base_addr = 0
        self.scanner = None
        self.mgr_ptr = 0
        self.mgr_off = 0
        self.node_table = 0
        self.class_table = 0
        self.missile_scanner = MissileScanner()

    def connect(self) -> bool:
        """เชื่อมต่อ Game Process และค้นหา Pointer ECS Manager"""
        self.pid = get_game_pid()
        if not self.pid:
            print("❌ ไม่พบ Process ของเกม War Thunder (aces)!")
            return False

        self.base_addr = get_game_base_address(self.pid)
        if not self.base_addr:
            print("❌ ไม่สามารถอ่าน Base Address ของเกมได้!")
            return False

        self.scanner = MemoryScanner(self.pid)

        # ค้นหา ECS Manager
        found_mgr = 0
        found_off = 0
        for cand_off in ECS_MANAGER_CANDIDATES:
            m_cand = read_ptr(self.scanner, self.base_addr + cand_off)
            if is_valid_ptr(m_cand):
                n_t = read_ptr(self.scanner, m_cand + OFF_ECS_NODE_TABLE)
                for c_off in (0x4a8, 0x5e8, OFF_ECS_CLASS_TABLE):
                    c_t = read_ptr(self.scanner, m_cand + c_off)
                    if is_valid_ptr(n_t) and is_valid_ptr(c_t) and n_t != c_t:
                        found_mgr = m_cand
                        found_off = cand_off
                        self.node_table = n_t
                        self.class_table = c_t
                        break
                if found_mgr:
                    break

        if not found_mgr:
            print("❌ ไม่พบ ECS Manager ที่ถูกต้อง (ตรวจสอบ Candidates ใน mul.py)!")
            return False

        self.mgr_ptr = found_mgr
        self.mgr_off = found_off

        print(f"✅ เชื่อมต่อเกมสำเร็จ: PID={self.pid} | Base={hex(self.base_addr)}")
        print(f"🎯 ECS Manager:    base+{hex(self.mgr_off)} -> {hex(self.mgr_ptr)}")
        print(f"📁 node_table:     {hex(self.node_table)} (+{hex(OFF_ECS_NODE_TABLE)})")
        print(f"📋 class_table:    {hex(self.class_table)} (+{hex(OFF_ECS_CLASS_TABLE)})")
        return True

    def get_ground_truth_missiles(self) -> list:
        """ดึงรายการขีปนาวุธที่กำลังบินอยู่จริงผ่าน MissileScanner (ใช้เป็นตัวเปรียบเทียบ)"""
        res = self.missile_scanner.scan(self.scanner, self.base_addr)
        return res or []

    def parse_query_descriptor(self, selector: int) -> dict:
        """
        อ่านข้อมูล 64-byte descriptor ของ Query Selector ที่ระบุ
        โครงสร้าง DaECS: class_table + (selector << 6)
        """
        query_addr = self.class_table + (selector << 6)
        meta = self.scanner.read_mem(query_addr, 64)
        if not meta or len(meta) < 32:
            return None

        num_required = meta[0]
        num_optional = meta[1]
        num_sublists = struct.unpack_from("<H", meta, 2)[0]
        total_comps = num_required + num_optional

        # Sublists offset array pointer
        if num_sublists == 0 or num_sublists > 2048:
            return None

        if num_sublists <= 9:
            sublist_base = query_addr + 0x04
        else:
            sublist_base = struct.unpack_from("<Q", meta, 0x08)[0]
            if not is_valid_ptr(sublist_base):
                return None

        # ดึง Sublist Indices ทั้งหมดใน Node Table
        sublist_bytes = self.scanner.read_mem(sublist_base, num_sublists * 4)
        if not sublist_bytes or len(sublist_bytes) < num_sublists * 4:
            return None

        sublist_indices = []
        for i in range(num_sublists):
            idx = struct.unpack_from("<I", sublist_bytes, i * 4)[0]
            if idx < 4096:
                sublist_indices.append(idx)

        return {
            "selector": selector,
            "address": query_addr,
            "num_required": num_required,
            "num_optional": num_optional,
            "num_sublists": num_sublists,
            "total_comps": total_comps,
            "sublists": sublist_indices,
        }

    def inspect_sublist_entities(self, sublist_idx: int) -> list:
        """อ่านข้อมูล Entities จาก Node Table ตาม Archetype Sublist Index ที่กำหนด"""
        entry_addr = self.node_table + sublist_idx * 0x20
        desc = self.scanner.read_mem(entry_addr, 0x20)
        if not desc or len(desc) < 0x20:
            return []

        storage = struct.unpack_from("<Q", desc, 0)[0]
        count = struct.unpack_from("<I", desc, 8)[0]
        capacity = struct.unpack_from("<I", desc, 0x14)[0]

        if count == 0 or not is_valid_ptr(storage) or (storage & 7 != 0):
            return []
        if count > 4096:
            return []

        # อ่าน Pointer ทั้งหมดในก้อน Storage แบบ Bulk เหมือน missile.py
        read_bytes = min(max(capacity * 64, 2048), 65536)
        bulk = self.scanner.read_mem(storage, read_bytes)
        if not bulk:
            return []

        ptrs = []
        for i in range(len(bulk) // 8):
            p = struct.unpack_from("<Q", bulk, i * 8)[0]
            if is_valid_ptr(p) and (p & 7 == 0):
                ptrs.append(p)

        return ptrs

    def scan_all_selectors(self, ground_truth_ptrs=None) -> list:
        """
        กวาดสแกน Selector ทั้งหมด 0..2048 ใน class_table
        เพื่อหาว่า Selector ใดที่มี Entity ขีปนาวุธบรรจุอยู่
        """
        print(f"\n🔍 กำลังกวาดสแกน Query Selectors (0..{TOTAL_SELECTORS_TO_SCAN}) จาก class_table...")
        hits = []
        start_t = time.perf_counter()

        active_queries_count = 0
        total_sublists_checked = 0

        for sel in range(TOTAL_SELECTORS_TO_SCAN):
            q = self.parse_query_descriptor(sel)
            if not q:
                continue

            active_queries_count += 1
            # ตรวจสอบ Archetype ย่อยที่มีข้อมูลจริง (count > 0)
            matched_missiles = []
            active_sublists = []

            for sl in q["sublists"]:
                total_sublists_checked += 1
                ptrs = self.inspect_sublist_entities(sl)
                if not ptrs:
                    continue

                active_sublists.append((sl, len(ptrs)))

                # ตรวจสอบว่าเป็นจรวด/ขีปนาวุธหรือไม่
                for p in ptrs:
                    # ถ้ามี ground truth ให้เช็คตรงพอยน์เตอร์
                    if ground_truth_ptrs and p in ground_truth_ptrs:
                        m_info = self.missile_scanner._check_rocket(self.scanner, p, sl)
                        if m_info:
                            matched_missiles.append(m_info)
                    else:
                        m_info = self.missile_scanner._check_rocket(self.scanner, p, sl)
                        if m_info and m_info.name:
                            matched_missiles.append(m_info)

            if matched_missiles:
                hits.append({
                    "query": q,
                    "active_sublists": active_sublists,
                    "missiles": matched_missiles,
                })

        dur_ms = (time.perf_counter() - start_t) * 1000.0
        print(f"⏱️ กวาดเสร็จสิ้นใน {dur_ms:.2f} ms | พบคิวรีที่มีการลงทะเบียน: {active_queries_count} คิวรี")
        return hits

    def benchmark_comparison(self):
        """วัดประสิทธิภาพเปรียบเทียบระหว่าง Brute-force Sweep 350 ช่อง vs Direct Query"""
        print("\n" + "=" * 70)
        print("⚡ BENCHMARK: Linear Node Table Sweep (เดิม) VS Direct Query (ใหม่)")
        print("=" * 70)

        # 1. Benchmark วิธีเดิม (Linear 350 nodes sweep)
        N_ITER = 50
        start = time.perf_counter()
        count_old = 0
        for _ in range(N_ITER):
            table_bytes = self.scanner.read_mem(self.node_table, 350 * 0x20)
            if table_bytes:
                for idx in range(len(table_bytes) // 0x20):
                    data = table_bytes[idx * 0x20 : (idx + 1) * 0x20]
                    stg = struct.unpack_from("<Q", data, 0)[0]
                    cnt = struct.unpack_from("<I", data, 8)[0]
                    if cnt > 0 and is_valid_ptr(stg):
                        count_old += 1
        dur_old_ms = ((time.perf_counter() - start) / N_ITER) * 1000.0

        print(f"  🐢 [วิธีเดิม: กวาด 350 Archetypes ดิบ]:  {dur_old_ms:.3f} ms / scan (~{350 * 32 / 1024:.1f} KB read)")

        # 2. หา Hit จาก Class table เพื่อทดสอบ Direct Query
        hits = self.scan_all_selectors()
        if hits:
            best_sel = hits[0]["query"]["selector"]
            best_q = hits[0]["query"]
            target_sublists = best_q["sublists"]

            start = time.perf_counter()
            for _ in range(N_ITER):
                # อ่านเฉพาะ Sublists ที่ Query ระบุตรงๆ
                for sl in target_sublists:
                    entry_addr = self.node_table + sl * 0x20
                    desc = self.scanner.read_mem(entry_addr, 0x20)
                    if desc:
                        stg = struct.unpack_from("<Q", desc, 0)[0]
                        cnt = struct.unpack_from("<I", desc, 8)[0]
            dur_new_ms = ((time.perf_counter() - start) / N_ITER) * 1000.0

            speedup = dur_old_ms / max(dur_new_ms, 0.0001)
            print(f"  🚀 [วิธีใหม่: Direct Query Selector {best_sel}]: {dur_new_ms:.3f} ms / scan ({len(target_sublists)} sublists)")
            print(f"  🔥 ความเร็วเพิ่มขึ้น: {speedup:.1f}x เท่า! ประหยัด Memory I/O มหาศาล")
        else:
            print("  ℹ️ ไม่พบจรวดขณะทำการ Benchmark (ลองยิงจรวดในโหมด Test Drive แล้วรันใหม่)")

    def live_watch_mode(self, target_selector: int = None):
        """โหมดเฝ้าติดตามแบบ Real-Time (Live Monitoring HUD)"""
        print("\n" + "=" * 70)
        print("📡 LIVE ECS CLASS TABLE MONITORING (กด Ctrl+C เพื่อออก)")
        print("=" * 70)

        known_selectors = [target_selector] if target_selector else [128, 257, 258, 1079, 1090, 1120]

        try:
            loop_idx = 0
            while True:
                loop_idx += 1
                t0 = time.perf_counter()

                # ดึง Ground Truth ขีปนาวุธจาก OFF_PROJ_LIST
                proj_missiles = self.get_ground_truth_missiles()
                proj_ptrs = {m.ptr for m in proj_missiles}

                # ค้นหา Hits จาก Selectors
                active_hits = []
                for sel in known_selectors:
                    q = self.parse_query_descriptor(sel)
                    if not q:
                        continue
                    for sl in q["sublists"]:
                        ptrs = self.inspect_sublist_entities(sl)
                        for p in ptrs:
                            m = self.missile_scanner._check_rocket(self.scanner, p, sl)
                            if m and m.name:
                                active_hits.append((sel, sl, m))

                dt_us = (time.perf_counter() - t0) * 1_000_000.0

                # แสดงผลสถานะ
                sys.stdout.write(f"\r[Loop #{loop_idx:04d}] Scan: {dt_us:.0f} µs | ProjList: {len(proj_missiles)} | ECS Hits: {len(active_hits)} ")
                sys.stdout.flush()

                if active_hits:
                    print("")
                    for sel, sl, m in active_hits:
                        prof = classify_seeker_type(m.name)
                        print(f"  🎯 [Sel {sel:4d} | Node #{sl:3d}] {m.name} [{prof}] Pos=({m.pos[0]:.0f},{m.pos[1]:.0f},{m.pos[2]:.0f}) Spd={m.speed:.0f}m/s Tgt={m.target_id}")

                time.sleep(0.08)
        except KeyboardInterrupt:
            print("\n👋 ออกจากโหมด Real-Time Monitor")


# ====================================================================
# Main Entry Point
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="PoC ECS Class Table Probe for War Thunder")
    parser.add_argument("--watch", action="store_true", help="รันโหมดเฝ้าติดตาม Real-Time Live Watch")
    parser.add_argument("--compare", action="store_true", help="รัน Benchmark เปรียบเทียบความเร็ว")
    parser.add_argument("--sel", type=int, default=None, help="ระบุ Selector ID ที่ต้องการเจาะจง")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 PoC Probe: Direct ECS Class Table Inspector (Dagor DaECS)")
    print("=" * 70)

    probe = ECSClassTableProbe()
    if not probe.connect():
        return

    # 1. ตรวจสอบสถานะขีปนาวุธปัจจุบันในเกม
    print("\n[+] 1. ตรวจสอบขีปนาวุธที่บินอยู่ขณะนี้ (Ground Truth Baseline)...")
    active_m = probe.get_ground_truth_missiles()
    gt_ptrs = {m.ptr for m in active_m}
    print(f"    พบขีปนาวุธในเกมขณะนี้: {len(active_m)} ลูก")
    for m in active_m:
        print(f"    - {m.name} @ ({m.pos[0]:.0f},{m.pos[1]:.0f},{m.pos[2]:.0f}) spd={m.speed:.0f}m/s ptr={hex(m.ptr)}")

    # 2. กวาดหา Selector
    hits = probe.scan_all_selectors(gt_ptrs)

    print("\n" + "=" * 70)
    print(f"📊 ผลการกวาดสแกน ECS Class Table: พบ {len(hits)} Query Selectors ที่มีขีปนาวุธ")
    print("=" * 70)

    best_selector = None
    for h in hits:
        q = h["query"]
        ms = h["missiles"]
        print(f"\n  🎯 SELECTOR #{q['selector']}:")
        print(f"     Descriptor Addr: {hex(q['address'])}")
        print(f"     Signature:       req={q['num_required']}, opt={q['num_optional']}, sublists={q['num_sublists']}")
        print(f"     Active Nodes:    {h['active_sublists']}")
        print(f"     Missiles Found:  {len(ms)} ลูก")
        for m in ms:
            prof = classify_seeker_type(m.name)
            print(f"       🚀 {m.name} [{prof}] Spd={m.speed:.0f}m/s Pos=({m.pos[0]:.0f},{m.pos[1]:.0f},{m.pos[2]:.0f})")

        if not best_selector:
            best_selector = q['selector']

    # 3. โหมด Benchmark
    if args.compare or not hits:
        probe.benchmark_comparison()

    # 4. โหมด Live Watch
    if args.watch:
        probe.live_watch_mode(args.sel or best_selector)


if __name__ == "__main__":
    main()
