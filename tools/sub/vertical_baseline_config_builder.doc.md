# vertical_baseline_config_builder.py

Purpose:
- Auto-dedupe hitpoint calibration samples.
- Extract vertical baseline curves.
- Write `config/vertical_baseline_table.json` for `radar_overlay.py`.

Run:
```bash
python3 tools/sub/vertical_baseline_config_builder.py
```

Common options:
```bash
python3 tools/sub/vertical_baseline_config_builder.py \
  --distance-step 200 \
  --min-points 2 \
  --distance-eps 3 \
  --vertical-eps 0.3 \
  --x-eps 0.3 \
  --time-eps 8
```

Input:
- Latest deduped file in `dumps/` if present:
  - `dumps/hitpoint_calibration_samples.deduped_*.jsonl`
- Otherwise:
  - `dumps/hitpoint_calibration_samples.jsonl`

Outputs:
- Config:
  - `config/vertical_baseline_table.json`
- Generated deduped sample snapshot:
  - `dumps/*.autodedup_*.jsonl`
- Build summary:
  - `dumps/*.baseline_builder_*.txt`

What it builds:
- Ammo buckets:
  - `apfsds_like`
  - `he_fullcal_like`
  - `other`
- Profiles grouped by:
  - `my_unit_key`
  - ammo bucket
- Curve points:
  - average distance
  - average effective vertical correction

Config schema:
```json
{
  "updated_at": "...",
  "source": "hitpoint_calibration_autobuild",
  "updated_by_tool": "vertical_baseline_config_builder",
  "table": {
    "apfsds_like": {
      "my_unit_key": {
        "speed": 1463.0,
        "caliber": 0.026,
        "curve": [[300.0, 1.0], [500.0, -3.0]]
      }
    }
  }
}
```

Runtime use:
- `radar_overlay.py` loads `config/vertical_baseline_table.json` at startup.
- If a vehicle key is missing, overlay falls back to the nearest profile by speed/caliber.

Recommended workflow:
1. Collect calibration samples in overlay.
2. Run this builder.
3. Restart overlay and test the new baseline config.

Notes:
- This tool is now the primary path for vertical baseline config generation.
- Older fitting notes/tools under `tools/sub/legacy/` are legacy reference only.
