import os
import sys
import json
import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OFFSETS_JSON_PATH = os.path.join(PROJECT_ROOT, "config", "offsets.json")
DEFAULT_GAME_BINARY_PATH = "/home/xda-7/MyGames/WarThunder/linux64/aces"


def get_binary_fingerprint(binary_path=DEFAULT_GAME_BINARY_PATH):
    try:
        real_path = os.path.realpath(binary_path)
        st = os.stat(real_path)
        return {
            "path": real_path,
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }
    except Exception:
        return None


class OffsetExporter:
    def __init__(self, output_path=OFFSETS_JSON_PATH):
        self.output_path = output_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

    def load_existing_offsets(self):
        if not os.path.exists(self.output_path):
            return {}
        try:
            with open(self.output_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def export_offsets(self, offsets_dict, dual_export=True):
        """
        บันทึก offsets ทั้งหมดลง config/offsets.json
        และ Dual-Export ลง persistence files เดิมเพื่อความปลอดภัย (Backward Compatibility)
        """
        existing = self.load_existing_offsets()
        existing.update(offsets_dict)
        existing["updated_at"] = datetime.datetime.now().isoformat()
        existing["build_fingerprint"] = get_binary_fingerprint()

        # สร้าง dictionary แสดง offset ทุกตัวเป็น HEX เพื่อให้อ่านง่าย
        def _to_hex_rec(val):
            if isinstance(val, int) and not isinstance(val, bool):
                return hex(val)
            elif isinstance(val, (list, tuple)):
                return [_to_hex_rec(x) for x in val]
            return val

        offsets_hex = {}
        for k, v in existing.items():
            if k in ("updated_at", "build_fingerprint", "offsets_hex"):
                continue
            offsets_hex[k] = _to_hex_rec(v)
        existing["offsets_hex"] = offsets_hex

        # 1. เขียน config/offsets.json
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        # 2. Dual-Export ไปยัง persistence ย่อย
        if dual_export:
            self._dual_export_legacy(existing)

        return True

    def _dual_export_legacy(self, d):
        cfg_dir = os.path.join(PROJECT_ROOT, "config")
        fp = d.get("build_fingerprint")

        # View Matrix
        if "OFF_CAMERA_PTR" in d and "OFF_VIEW_MATRIX" in d:
            path = os.path.join(cfg_dir, "view_matrix_persistence.json")
            doc = {
                "updated_at": datetime.datetime.now().isoformat(),
                "camera_off": int(d["OFF_CAMERA_PTR"]),
                "matrix_off": int(d["OFF_VIEW_MATRIX"]),
                "source": "offset_repair_tool",
                "updated_by_tool": "offset_repair",
                "confidence": 0.99,
                "build_fingerprint": fp
            }
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # BBOX
        if "OFF_UNIT_BBMIN" in d and "OFF_UNIT_BBMAX" in d:
            path = os.path.join(cfg_dir, "unit_bbox_persistence.json")
            doc = {
                "updated_at": datetime.datetime.now().isoformat(),
                "bbmin_off": int(d["OFF_UNIT_BBMIN"]),
                "bbmax_off": int(d["OFF_UNIT_BBMAX"]),
                "source": "offset_repair_tool",
                "updated_by_tool": "offset_repair",
                "confidence": 0.99,
                "build_fingerprint": fp
            }
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Ballistic Layout
        if "BALLISTIC_SPEED_OFF" in d and "BALLISTIC_STRUCT_BASE_OFF" in d:
            path = os.path.join(cfg_dir, "ballistic_layout_persistence.json")
            doc = {
                "updated_at": datetime.datetime.now().isoformat(),
                "updated_by_tool": "offset_repair",
                "confidence": 0.99,
                "layout": {
                    "base_off": int(d.get("BALLISTIC_STRUCT_BASE_OFF", 0x2120)),
                    "speed_off": int(d.get("BALLISTIC_SPEED_OFF", 0x2118)),
                    "mass_off": int(d.get("BALLISTIC_MASS_OFF", 0x2124)),
                    "caliber_off": int(d.get("BALLISTIC_CALIBER_OFF", 0x2128)),
                    "cx_off": int(d.get("BALLISTIC_CX_OFF", 0x212C)),
                    "max_distance_off": int(d.get("BALLISTIC_MAX_DISTANCE_OFF", 0x2130)),
                },
                "build_fingerprint": fp
            }
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Unit Status
        if "OFF_UNIT_STATE" in d and "OFF_UNIT_TEAM" in d:
            path = os.path.join(cfg_dir, "unit_status_persistence.json")
            doc = {
                "updated_at": datetime.datetime.now().isoformat(),
                "updated_by_tool": "offset_repair",
                "confidence": 0.99,
                "unit_state_off": int(d.get("OFF_UNIT_STATE", 0x0F90)),
                "unit_team_off": int(d.get("OFF_UNIT_TEAM", 0x1010)),
                "unit_info_off": int(d.get("OFF_UNIT_INFO", 0x1020)),
                "player_info_off": int(d.get("OFF_PLAYER_INFO", 0x0F98)),
                "invulnerable_off": int(d.get("OFF_UNIT_INVUL", 0x0E90)),
                "build_fingerprint": fp
            }
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
