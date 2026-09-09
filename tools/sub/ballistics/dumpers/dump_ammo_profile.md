# 🎯 คู่มือการใช้งาน: War Thunder Ammo Classifier & Ballistics Profile Dumper

> **ไฟล์สคริปต์หลัก:** `tools/sub/ballistics/dumpers/dump_ammo_profile.py`  
> **ไฟล์ฐานข้อมูลผลลัพธ์:** `dumps/ammo_classification_records.json`  
> **ภาษาที่รองรับ:** Python 3 (Virtual Environment: `.venv`)

---

## 📌 1. วัตถุประสงค์ (Purpose)
เครื่องมือนี้ถูกสร้างขึ้นเพื่อ:
1. **ดัมพ์ค่าฟิสิกส์ขีปนวิถีสดจากหน่วยความจำเกม (Live Memory)** ของกระสุนที่บรรจุอยู่ในรังเพลิงปัจจุบัน เช่น ความเร็วต้น, มวล, คาลิเบอร์, ความยาวแกน, สัมประสิทธิ์แรงต้าน
2. **เก็บประวัติเมื่อระบบจำแนกกระสุนผิดพลาด (Wrong Classify)** เพื่อนำไปวิเคราะห์และปรับแต่งอัลกอริทึม
3. **เปิดให้ผู้ใช้เลือกประเภทกระสุนจริง (Actual Class Input Option)** พร้อมขนาดลำกล้องจริงและชื่อกระสุน เพื่อนำไปเป็น Ground Truth
4. **สะสมชุดข้อมูล (Dataset)** ในรูปแบบ JSON สำหรับนำไป Fine-tune ตารางจำแนกกระสุน (APFSDS, APDS, APHE, HESH, HEAT-FS, HE, ATGM) ใน [`src/utils/ammo_family.py`](../../../../src/utils/ammo_family.py)

---

## 📂 2. โครงสร้างไฟล์และโฟลเดอร์
```
ebpf_wt/
├── tools/
│   └── sub/
│       └── ballistics/
│           └── dumpers/
│               ├── dump_ammo_profile.py         <-- สคริปต์ Dumper หลัก
│               └── วิธีการใช้งาน.md              <-- เอกสารคู่มือฉบับนี้
├── src/
│   └── utils/
│       └── ammo_family.py                       <-- โมดูล AI จำแนกประเภทกระสุนและลำกล้อง
└── dumps/
    └── ammo_classification_records.json         <-- ฐานข้อมูลบันทึกผลกระสุน
```

---

## 🔬 3. พารามิเตอร์ขีปนวิถีที่อ่านจาก Live Memory

ข้อมูลถูกดึงโดยตรงจาก `weapon_ptr` (`cgame_base + 0x3F0`):

| Offset | ชนิดข้อมูล | พารามิเตอร์ | หน่วย | คำอธิบาย |
|---|---|---|---|---|
| `+0x20E8` | `float` | `speed` | m/s | ความเร็วต้นปากลำกล้อง (Muzzle Velocity) |
| `+0x20F4` | `float` | `mass` | kg | น้ำหนักของหัวกระสุน (Projectile Mass) |
| `+0x20F8` | `float` | `caliber` | m | เส้นผ่านศูนย์กลางกระสุนในเกม (Caliber / Sub-caliber Dart) |
| `+0x20FC` | `float` | `length_cx` | m | ความยาวของหัวกระสุน หรือ Drag Coefficient ($C_x$) |
| `+0x2100` | `float` | `max_dist` | m | ระยะยิงหวังผลสูงสุด (Max Fire Distance) |
| `+0x210C` | `float` | `splinter_x` | kg | มวลสะเก็ดระเบิดส่วนแรก |
| `+0x2110` | `float` | `splinter_y` | kg | มวลสะเก็ดระเบิดส่วนสอง |
| `+0x2114` | `float` | `vel_range_x` | m/s | ย่านความเร็วประสิทธิผลขั้นต่ำ |
| `+0x2118` | `float` | `vel_range_y` | m/s | ย่านความเร็วประสิทธิผลขั้นสูง |

---

## 📐 4. เกณฑ์การจำแนกทางฟิสิกส์ (Physics Principles)

ระบบคำนวณคุณสมบัติทางฟิสิกส์เพิ่มเติมเพื่อจำแนกประเภทกระสุน:

1. **อัตราส่วนความยาวต่อแกน ($L/D$ Aspect Ratio)**:
   $$\text{Aspect Ratio} = \frac{\text{Length}}{\text{Caliber}}$$
   - $\ge 8.0$: **APFSDS** (ลูกดอกทรงตัวด้วยครีบ แกนยาวเรียว ลำกล้องแกน dart มัก $\le 30\text{mm}$)
   - $\le 6.5$: **APDS** (ลูกเจาะเกราะสลัดครอบทรงป้อม แกนสั้น ลำกล้องแกน $\ge 35\text{mm}$)

2. **ความหนาแน่นเชิงปริมาตร (Volumetric Mass Density)**:
   $$\text{Density} = \frac{\text{Mass}}{\text{Caliber}^3} \quad (\text{kg/m}^3)$$
   - $< 11,200\text{ kg/m}^3$: **HESH / HEP** (หัวกระสุนผนังบาง บรรจุสารระเบิดพลาสติกมวลเบา ความเร็ว $\le 800\text{ m/s}$)
   - $\ge 13,200\text{ kg/m}^3$: **APHE / Solid Shot** (กระสุนเจาะเกราะเนื้อเหล็กกล้าตัน/กึ่งตัน มีมวลจำเพาะสูง)

3. **กระสุนเคมี (HEAT-FS)**:
   - ความเร็วสูง ($\ge 850\text{ m/s}$) หัวกระสุนมีก้านและรูปทรง Ogive Aerodynamic ($L/D \ge 3.8$)

---

## 🚀 5. คำสั่งและตัวอย่างการใช้งาน (Usage Examples)

> **หมายเหตุ:** ต้องรันด้วยสิทธิ์ `sudo` เพื่อให้สามารถเข้าถึงหน่วยความจำของ Process `aces` ได้

### 5.1 โหมดถาม-ตอบผ่านเมนู (Interactive Mode)
รันคำสั่งโดยไม่ใส่พารามิเตอร์ ระบบจะอ่านข้อมูลรถถังและกระสุน แสดง Dashboard และขึ้นเมนูตัวเลขให้กดเลือก:

```bash
echo [pwd] | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py
```

**ตัวอย่างหน้าจอ Interactive:**
```text
📌 เลือกประเภทกระสุนที่แท้จริง (Actual Ammo Class):
  [0] INHERIT  : ✅ ข้อมูลถูกต้องทั้งหมด (ใช้ค่าที่ AI ทำนาย: APFSDS | 25mm)
  [1] APFSDS   : Armour-Piercing Fin-Stabilized Discarding Sabot  <-- [PREDICTED]
  [2] APDS     : Armour-Piercing Discarding Sabot
  [3] APHE     : Armour-Piercing High-Explosive / Solid AP
  [4] HESH     : High-Explosive Squash Head / HEP
  [5] HEAT-FS  : High-Explosive Anti-Tank
  [6] HE       : High-Explosive Fragmentation
  [7] ATGM     : Anti-Tank Guided Missile
  [8] AUTO-AP  : Autocannon Kinetic / AP / APDS
  [9] OTHER    : Other / Custom Type

👉 กรุณาเลือกข้อ [0-9], 'i' (Inherit), หรือกด Enter เพื่อยืนยันว่าถูกต้อง [APFSDS]: 
```
- **หากผลทำนายถูกต้องอยู่แล้ว**: ให้กด **`Enter`** หรือพิมพ์ **`0`** หรือ **`i`** ระบบจะสืบทอด (Inherit) ค่ากระสุน (Type) และขนาดลำกล้อง (Bore mm) ที่ทำนายไว้มาใช้ทันที โดยไม่ต้องตอบคำถามซ้ำซ้อน!
- **หากผลทำนายผิด**: ให้พิมพ์เลข `1-9` เพื่อระบุประเภทที่แท้จริง ระบบจะถามขนาดยืนยันลำกล้อง (สามารถกด Enter เพื่อ inherit ขนาดลำกล้องได้เช่นกัน)

---

### 5.2 โหมดสืบทอดค่าผ่านคำสั่ง CLI (`--inherit` หรือ `-i`)
เมื่อต้องการยืนยันผลการทำนายของระบบทันทีโดยไม่ต้องเข้าเมนูถาม-ตอบ:

```bash
# บันทึกโดยยืนยันว่า AI ทำนายถูกต้องทั้งหมด (Inherit Type + Bore)
echo awd25125 | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py --inherit --note "DM33"
```

---

### 5.2 โหมดระบุประเภทกระสุนผ่านคำสั่ง (CLI Flag)
เหมาะสำหรับการบันทึกแบบรวดเร็วไม่ต้องรอกดตอบ:

```bash
# บันทึกกระสุน APFSDS ขนาดลำกล้อง 120mm พร้อมชื่อกระสุน
echo [pwd] | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py \
    --actual APFSDS \
    --bore 120 \
    --note "DM33 on Leopard 2A4"

# บันทึกกระสุน HESH ขนาด 105mm
echo [pwd] | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py \
    --actual HESH \
    --bore 105 \
    --note "L35 HESH on Centurion"

# บันทึกกระสุน HEAT-FS ขนาด 125mm
echo [pwd] | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py \
    --actual HEAT-FS \
    --bore 125 \
    --note "3BK18M on T-72B"
```

---

### 5.3 โหมดเฝ้าดูขณะเล่นในเกม (Watch Mode: `--watch` หรือ `-w`)
โหมดนี้จะตรวจสอบ `weapon_ptr` ตลอดเวลา เมื่อคุณอยู่ในเกม/ห้องซ้อมรบ (Test Drive) แล้วกดปุ่มเปลี่ยนกระสุน (`1`, `2`, `3`, `4`) หน้าจอจะดึงค่ากระสุนชนิดใหม่ขึ้นมาแสดงทันที:

```bash
echo [pwd] | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py --watch
```
- เมื่อกดเปลี่ยนกระสุน ระบบจะพิมพ์ Dashboard ของกระสุนนัดใหม่
- ระบบจะถามว่าต้องการบันทึกนัดนี้ลง JSON หรือไม่
- หากใส่แฟล็ก `--auto` ร่วมด้วย (`--watch --auto`) จะบันทึกตามที่ระบบทายทันทีทุกครั้งที่เปลี่ยนกระสุน

---

### 5.4 โหมดดูรายการกระสุนที่บันทึกไว้ (List Mode: `--list` หรือ `-l`)
ตรวจสอบประวัติและรายการกระสุนทั้งหมดที่เคยบันทึกไว้ใน Dataset:

```bash
echo [pwd] | sudo -S .venv/bin/python3 tools/sub/ballistics/dumpers/dump_ammo_profile.py --list
```

**ตัวอย่างผลลัพธ์:**
```text
================================================================================
📋 รายการ Ballistics Profile ที่บันทึกไว้ (3 รายการ)
================================================================================
#   | Vehicle            | Speed    | Pred     | Actual   | Match | Note
--------------------------------------------------------------------------------
1   | Type 87 RCV        | 1335m/s  | APFSDS   | APFSDS   | ✅     | Type 87 RCV PMB090 APFSDS
2   | Leopard 2A4        | 1650m/s  | APFSDS   | APFSDS   | ✅     | DM33 APFSDS
3   | Centurion Mk 10    | 730m/s   | HESH     | HESH     | ✅     | L35 HESH
================================================================================
```

---

## 💾 6. โครงสร้างไฟล์ข้อมูล JSON (`dumps/ammo_classification_records.json`)

ทุกครั้งที่บันทึก ข้อมูลจะถูกเก็บเป็น JSON Object ดังนี้:

```json
{
  "timestamp": "2026-09-09T13:05:59.418848",
  "vehicle": {
    "short_name": "Type 87 RCV",
    "name_key": "jp_type_87_rcv",
    "family": "exp_tank",
    "nation_id": 0,
    "class_id": 1825761392,
    "my_team": 1,
    "is_air": false
  },
  "raw_ballistics": {
    "speed": 1335.0,
    "mass": 0.134,
    "caliber": 0.0135,
    "length_cx": 0.2,
    "max_distance": 5000.0,
    "splinter_mass_x": 0.002,
    "splinter_mass_y": 0.005,
    "vel_range_x": 500.0,
    "vel_range_y": 700.0
  },
  "derived": {
    "raw_caliber_mm": 13.5,
    "aspect_ratio_ld": 14.81,
    "volumetric_density": 54463.24,
    "sectional_density": 735.25
  },
  "predicted": {
    "ammo_type": "APFSDS",
    "ammo_flag": 288,
    "cal_class": "AUTOCANNON",
    "cal_flag": 1,
    "effective_bore_mm": 25.0,
    "dart_caliber_mm": 13.5,
    "is_subcaliber": true,
    "hud_str": "🔫 Gun : 25mm APFSDS (Dart: 14mm | 1335 m/s) [AUTOCANNON]"
  },
  "actual": {
    "actual_type": "APFSDS",
    "nominal_bore_mm": 25.0,
    "is_correct": true,
    "note": "Type 87 RCV PMB090 APFSDS"
  }
}
```

---

## 🛠️ 7. การนำข้อมูลไปใช้งานเมื่อพบกระสุนจำแนกผิด (Bug Fixing & Tuning)

หากพบว่ากระสุนชนิดใดมีสถานะ `[MISCLASSIFIED]` (ค่าใน `Match` เป็น ❌):
1. เปิดดูค่า `raw_ballistics` และ `derived` (เช่น `aspect_ratio_ld`, `volumetric_density`, `speed`, `caliber`) ในรายการนั้น
2. เข้าไปปรับแต่งเงื่อนไขในฟังก์ชัน `classify_weapon_caliber` ที่ไฟล์ [`src/utils/ammo_family.py`](../../../../src/utils/ammo_family.py)
3. รันคำสั่งตรวจสอบไวยากรณ์:
   ```bash
   .venv/bin/python3 -m py_compile src/utils/ammo_family.py tools/sub/ballistics/dumpers/dump_ammo_profile.py
   ```
4. รันทดสอบใหม่เพื่อยืนยันว่ากระสุนนัดดังกล่าวได้รับการจำแนกอย่างถูกต้อง
