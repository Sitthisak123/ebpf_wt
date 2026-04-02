# hitpoint_correction_fit.py

Purpose:
- Fit a dynamic Y-correction curve from saved manual calibration samples.

Run:
```bash
python3 tools/hitpoint_correction_fit.py
```

Input:
- `dumps/hitpoint_calibration_samples.jsonl`

Outputs:
- `dumps/hitpoint_correction_fit.json`
- `dumps/hitpoint_correction_fit.txt`

Model:
- Fits `y_up` from sample offsets using:
  - distance
  - speed delta vs 1500 m/s
  - distance x speed interaction
  - caliber delta vs 0.016

Use when:
- You captured enough manual calibration samples and want updated coefficients for overlay correction.
