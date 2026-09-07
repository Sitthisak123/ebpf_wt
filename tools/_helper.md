# 🛠️ Tools Directory Index

## 🔒 Persistence Tools (Root: `tools/`)
- View Matrix: `tools/find_real_matrix.py` -> `config/view_matrix_persistence.json`
- Bounding Box: `tools/bbox_dumper.py` -> `config/unit_bbox_persistence.json`
- Ballistic Layout: `tools/ballistic_layout_dumper.py` -> `config/ballistic_layout_persistence.json`
- Weapon Barrel: `tools/barrel_offset_dumper.py` -> `config/barrel_offset_persistence.json`
- Ground Subclass: `tools/subclass_offset_dumper.py` -> `config/ground_subclass_persistence.json`
- Unit Status & Meta: `tools/unit_status_dumper.py` -> `config/unit_status_persistence.json`
- Documentation: `tools/persistence_system.doc.md`

## 📁 Subcategory Tools (`tools/sub/`)
- **Velocity & Telemetry (`tools/sub/vel/`)**:
  - Ground Vel Debugger: `tools/sub/vel/ground_vel_debugger.py`
  - Vel Log Analyzer: `tools/sub/vel/analyze_vel_log.py`
  - Vel Logic Comparator: `tools/sub/vel/compare_vel_logic.py`
  - Ground Vel Dumper 296: `tools/sub/vel/ground_vel_dumper_296.py`
  - Ground Vel Offset Finder: `tools/sub/vel/find_ground_velocity_offset.py`
  - Telemetry Extractor: `tools/sub/vel/extract_telemetry.py`
  - Air Velocity Scanner: `tools/sub/vel/scan/01_my_unit_velocity_scanner.py`
  - Tick Rate Scanner: `tools/sub/vel/scan/03_json_tick_rate_scanner.py`

- **Missiles & Rockets (`tools/sub/missile/`)**:
  - Missile ESP Debugger: `tools/sub/missile/missile_esp_debugger.py`
  - Missile Global Scanner: `tools/sub/missile/missile_global_scanner.py`
  - Missile Query Probe: `tools/sub/missile/missile_query_probe.py`
  - Missile Starned Dumper: `tools/sub/missile/missile_starned_dumper.py`

- **ESP & Performance (`tools/sub/esp/`)**:
  - ESP Debugger & Profiler: `tools/sub/esp/esp_debugger.py`
  - ESP Snapshot Dumper: `tools/sub/esp_runtime_snapshot_dumper.py`

- **Ballistics & CCIP (`tools/sub/ballistics/` & `tools/sub/`)**:
  - CCIP Offset Dumper: `tools/sub/ballistics/ccip_offset_dumper.py`
  - Ballistic Table Dumper: `tools/sub/ballistic_table_dumper.py`
  - Vertical Baseline Builder: `tools/sub/vertical_baseline_config_builder.py`

- **Subclasses & Entities**:
  - Unit Subclass Hunter: `tools/sub/subclass_offset_hunter.py`