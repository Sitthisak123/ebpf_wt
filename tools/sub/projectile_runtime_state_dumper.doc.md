# projectile_runtime_state_dumper.py

Purpose:
- Dump live ballistic props and reverse-derived runtime seed for `FUN_07268360`.

Run:
```bash
sudo venv/bin/python tools/projectile_runtime_state_dumper.py
sudo venv/bin/python tools/projectile_runtime_state_dumper.py --watch
```

Outputs:
- `dumps/projectile_runtime_state_dump_*.json`
- `dumps/projectile_runtime_state_dump_*.txt`
- `dumps/projectile_runtime_state_watch_*.json`
- `dumps/projectile_runtime_state_watch_*.txt`

Key fields:
- `model_enum`
- `speed`
- `mass`
- `caliber`
- `cx`
- `drag_k`
- `base_k`
- reverse-derived `runtime_state_candidate`

Notes:
- This is not a raw dump of the local runtime state buffer.
- It reconstructs the expected init-state seed from live memread values.
