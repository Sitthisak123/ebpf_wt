# Persistence System

ไฟล์นี้สรุประบบ persistence ปัจจุบันสำหรับ offset ที่เปลี่ยนตาม build ของเกม

## เป้าหมาย

- ใช้ `DNA scanner` เป็น baseline
- ใช้ tools เฉพาะทางเพื่อยืนยัน offset/runtime layout ที่ถูกจริง
- บันทึกผลลง persistence พร้อม `build_fingerprint`
- ป้องกันการใช้ offset เก่ากับ binary คนละ build
- ป้องกันไม่ให้ auto tool ที่ `confidence` ต่ำกว่าไปทับไฟล์ที่ได้จาก tool ยืนยันจริง

## Persistence ที่รองรับ

- `config/view_matrix_persistence.json`
- `config/unit_bbox_persistence.json`
- `config/ballistic_layout_persistence.json`

## Schema หลัก

ทุกไฟล์ควรมี field ต่อไปนี้:

- `updated_at`
- `source`
- `updated_by_tool`
- `confidence`
- `build_fingerprint`

`build_fingerprint` ใช้:

- `path`
- `size`
- `mtime_ns`

## Confidence Policy

ระบบจะไม่ให้ auto writer ที่ `confidence` ต่ำกว่าเขียนทับไฟล์เดิม ถ้า:

- fingerprint ของ build ตรงกัน
- และไฟล์เดิมมี `confidence` สูงกว่า

ตัวอย่างค่าปัจจุบัน:

- `find_real_matrix` = `0.95`
- `bbox_dumper` = `0.95`
- `ballistic_layout_dumper` = `0.92`
- `scanner_auto_view_matrix` = `0.78`
- `scanner_auto_bbox` = `0.72`
- `radar_overlay_auto_ballistic` = `0.68`

## Tools ที่ใช้ใน Persistence System

เก็บไว้ที่ `tools/` root:

- `tools/find_real_matrix.py`
- `tools/bbox_dumper.py`
- `tools/ballistic_layout_dumper.py`

หน้าที่:

- `find_real_matrix.py`
  - ยืนยัน `camera_off` และ `matrix_off`
  - เขียน `view_matrix_persistence.json`

- `bbox_dumper.py`
  - ยืนยัน `bbmin_off` และ `bbmax_off`
  - เขียน `unit_bbox_persistence.json`

- `ballistic_layout_dumper.py`
  - ยืนยัน ballistic layout
  - เขียน `ballistic_layout_persistence.json`

## Runtime Writers

มี auto-refresh ที่ runtime ด้วย:

- `scanner_auto_view_matrix`
- `scanner_auto_bbox`
- `radar_overlay_auto_ballistic`

writer เหล่านี้ใช้เมื่อ:

- ไม่มี persistence
- fingerprint ไม่ตรง
- หรือไฟล์ load ไม่ผ่าน

## การทดสอบ

View matrix:

```bash
rm config/view_matrix_persistence.json
sudo venv/bin/python radar_overlay.py
cat config/view_matrix_persistence.json
```

BBox:

```bash
rm config/unit_bbox_persistence.json
sudo venv/bin/python radar_overlay.py
cat config/unit_bbox_persistence.json
```

Ballistic:

```bash
rm config/ballistic_layout_persistence.json
sudo venv/bin/python radar_overlay.py
cat config/ballistic_layout_persistence.json
```

## Recommended Workflow

1. ให้ scanner bootstrap baseline
2. ใช้ tool ยืนยันจริงเมื่อ build เปลี่ยน
3. เขียน persistence จาก tool ที่ confidence สูง
4. ปล่อย runtime ใช้ auto-refresh เฉพาะ fallback

## หมายเหตุ

- `DNA scanner` อย่างเดียวไม่พอสำหรับ final truth
- persistence ที่ผูกกับ `build_fingerprint` คือชั้นป้องกันหลัก
- ถ้า build เปลี่ยน ให้ยืนยันใหม่ด้วย tool ที่เกี่ยวข้องก่อน
