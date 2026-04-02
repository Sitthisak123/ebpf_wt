# ballistic_table_dumper.py

Purpose:
- Inspect shared/global ballistic table manager paths found from reverse work.

Run:
```bash
sudo venv/bin/python tools/ballistic_table_dumper.py
sudo venv/bin/python tools/ballistic_table_dumper.py --watch
```

Outputs:
- `dumps/ballistic_table_dump_*.json`
- `dumps/ballistic_table_dump_*.txt`
- `dumps/ballistic_table_watch_*.json`
- `dumps/ballistic_table_watch_*.txt`

Use when:
- Checking whether table slots change across ammo.
- Verifying whether a table path is global/shared or per-ammo.

Current finding:
- Slots from the global manager are shared and do not change across tested ammo.
