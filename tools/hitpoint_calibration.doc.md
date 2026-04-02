# hitpoint calibration workflow

Purpose:
- Capture manual “actual hit point” samples from the overlay and fit a correction curve.

Where capture happens:
- In `radar_overlay.py`
- Samples are saved to `dumps/hitpoint_calibration_samples.jsonl`

Capture keys:
- `I/J/K/L` move calibration point
- `Shift` fast move
- `Backspace` reset offset
- `Enter` save sample

Recommended workflow:
1. Enable calibration draw in `radar_overlay.py` only when collecting samples.
2. Capture several samples for each ammo and several distances.
3. Run:
   ```bash
   python3 tools/hitpoint_correction_fit.py
   ```
4. Review `dumps/hitpoint_correction_fit.txt`
5. Apply new coefficients into `radar_overlay.py` if needed.

Notes:
- Current overlay defaults have calibration/debug draw disabled.
- This workflow is intended for `model_0 + subcaliber` correction tuning.
