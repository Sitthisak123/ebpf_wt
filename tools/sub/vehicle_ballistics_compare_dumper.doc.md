# vehicle_ballistics_compare_dumper.py

Purpose:
- Compare per-vehicle ballistic and geometry inputs such as barrel origin and zeroing.

Run:
```bash
sudo venv/bin/python tools/vehicle_ballistics_compare_dumper.py
sudo venv/bin/python tools/vehicle_ballistics_compare_dumper.py --watch
```

Outputs:
- `dumps/vehicle_ballistics_compare_dump_*.json`
- `dumps/vehicle_ballistics_compare_dump_*.txt`
- `dumps/vehicle_ballistics_compare_watch_*.json`
- `dumps/vehicle_ballistics_compare_watch_*.txt`

Use when:
- Comparing two vehicles such as `2S38` vs `T-80U-E1`.
- Checking `model`, `drag_k`, `zeroing`, `barrel_base_from_unit`, `barrel_tip_from_unit`.

Watch summary:
- `VEHICLE SUMMARY`
- `COMPARISON SUMMARY`

Notes:
- Lobby/invalid snapshots are filtered out in current version.
