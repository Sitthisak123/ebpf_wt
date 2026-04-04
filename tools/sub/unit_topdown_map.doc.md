# unit_topdown_map.py

2D top-down map tool that keeps `my position` at the center.

## Purpose
- Debug unit positions without using the broken view-matrix ESP path.
- Show nearby air/ground units in a simple X/Z plane.
- Use your unit as the fixed center of the map.
- Rotate the map to follow the current camera/view direction.

## Run
```bash
sudo venv/bin/python tools/unit_topdown_map.py
```

## Controls
- `+` / `-`: zoom in / out
- `0`: reset zoom
- `R`: toggle `north-up` / `view-up`
- `[` / `]`: previous / next `ViewDir` variant
- `L`: toggle labels
- `Space`: freeze / unfreeze samples
- `Esc`: quit

## Global Keys
- `F2` / `F3`: previous / next `ViewDir` variant
- `F6` / `F7`: zoom in / out
- `F8`: toggle `view-up`
- `F9`: toggle labels
- `Pause`: freeze / unfreeze
- `F10`: reset zoom

Notes:
- Global keys are handled as rising-edge presses in a background thread, so holding a key in-game should not spam repeated actions.
- The tool also listens to raw `/dev/input/event*` keyboard events, which is more reliable when the map window is not focused.

## Notes
- The map uses `get_unit_pos()` and `get_all_units()`.
- It does not use `view matrix` or `world_to_screen()`.
- Unit placement does not use the screen ESP path.
- Camera-follow rotation is derived from local projection around `my_pos`.
- Multiple `ViewDir` variants are drawn with different colors so you can see which axis/sign swap follows the camera correctly.
- `ViewDir` variants now include `Y`-axis mixes such as `xy`, `yx`, `yz`, `zy` in addition to `xz/zx`.
- The current follow variant is shown on the HUD using the same color as its arrow.
- Ground units are drawn as dots.
- Air units are drawn as larger cross markers.
- Friendly/enemy color depends on `OFF_UNIT_TEAM`.
