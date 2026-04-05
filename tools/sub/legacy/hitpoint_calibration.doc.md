# hitpoint calibration workflow

Purpose:
- Capture manual “actual hit point” samples from the overlay.

Where capture happens:
- In `radar_overlay.py`
- Samples are saved to `dumps/hitpoint_calibration_samples.jsonl`

Capture keys:
- `I/J/K/L` move calibration point
- `Shift` fast move
- `Backspace` reset offset
- `Enter` save sample

Legacy workflow:
1. Enable calibration draw in `radar_overlay.py` only when collecting samples.
2. Capture several samples for each ammo and several distances.
3. Use newer baseline tools in `tools/sub/` to build vertical baseline config.

Notes:
- This file is legacy reference only.
- The old `hitpoint_correction_fit.py` flow has been removed.
