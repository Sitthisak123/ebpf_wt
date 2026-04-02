# ballistic_layout_dumper.py

Purpose:
- Dump live weapon ballistic layout offsets and persistence candidates.

Run:
```bash
sudo venv/bin/python tools/ballistic_layout_dumper.py
sudo venv/bin/python tools/ballistic_layout_dumper.py --watch
```

Outputs:
- `dumps/origin_dragoff_dump_*.json`
- `dumps/origin_dragoff_dump_*.txt`
- `dumps/origin_dragoff_watch_*.json`
- `dumps/origin_dragoff_watch_*.txt`
- `config/ballistic_layout_persistence.json`

Use when:
- A game update changed ballistic offsets.
- You need fresh memread offsets for speed, mass, caliber, cx, maxDistance.

Notes:
- `velRange` in current build is not trusted as per-ammo live data.
- Persistence stores layout offsets, not ammo values.
