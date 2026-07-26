import os
import json
import glob

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_HISTORY_DIR = os.path.join(PROJECT_DIR, "chat_history")
IMPORTED_DIR = os.path.join(CHAT_HISTORY_DIR, "imported_sessions")

def import_sessions():
    """นำเข้าและแปลงไฟล์ประวัติการแชทเก่าให้เป็น Markdown สรุปอ่านง่าย"""
    os.makedirs(IMPORTED_DIR, exist_ok=True)
    print(f"[*] เริ่มกระบวนการนำเข้าประวัติการแชทเก่ามายัง: {IMPORTED_DIR}")

    # 1. นำเข้า Antigravity Session (1feb635d)
    antigravity_src = os.path.join(CHAT_HISTORY_DIR, "antigravity", "1feb635d-01ce-4014-8f41-d89de7ef00e8")
    if os.path.exists(antigravity_src):
        output_md = os.path.join(IMPORTED_DIR, "antigravity_session_1feb635d.md")
        with open(output_md, "w", encoding="utf-8") as out:
            out.write("# Imported Antigravity Chat Session (1feb635d-01ce-4014-8f41-d89de7ef00e8)\n\n")
            
            # อ่าน Task
            task_file = os.path.join(antigravity_src, "task.md")
            if os.path.exists(task_file):
                out.write("## Task Checklist\n")
                with open(task_file, "r", encoding="utf-8") as tf:
                    out.write(tf.read() + "\n\n")

            # อ่าน Implementation Plan
            plan_file = os.path.join(antigravity_src, "implementation_plan.md")
            if os.path.exists(plan_file):
                out.write("## Implementation Plan\n")
                with open(plan_file, "r", encoding="utf-8") as pf:
                    out.write(pf.read() + "\n\n")

            # อ่าน Walkthrough
            walk_file = os.path.join(antigravity_src, "walkthrough.md")
            if os.path.exists(walk_file):
                out.write("## Walkthrough Summary\n")
                with open(walk_file, "r", encoding="utf-8") as wf:
                    out.write(wf.read() + "\n\n")

        print(f"[+] นำเข้า Antigravity Session สำเร็จ -> {os.path.relpath(output_md, PROJECT_DIR)}")

    # 2. นำเข้า VS Code Sessions
    vscode_files = glob.glob(os.path.join(CHAT_HISTORY_DIR, "vscode", "*.jsonl"))
    for idx, vf in enumerate(vscode_files):
        session_name = os.path.basename(vf).replace(".jsonl", "")
        output_md = os.path.join(IMPORTED_DIR, f"vscode_session_{session_name}.md")
        prompts = []
        with open(vf, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    reqs = data.get("v", {}).get("requests", [])
                    for r in reqs:
                        text = r.get("message", {}).get("text")
                        if text:
                            prompts.append(text)
                except:
                    pass

        with open(output_md, "w", encoding="utf-8") as out:
            out.write(f"# Imported VS Code Chat Session ({session_name})\n\n")
            if prompts:
                out.write("## User Prompts:\n")
                for p_idx, p in enumerate(prompts, 1):
                    out.write(f"### Prompt {p_idx}:\n```\n{p}\n```\n\n")
            else:
                out.write("*(ไม่มีบันทึกข้อความใน session นี้)*\n")

        print(f"[+] นำเข้า VS Code Session สำเร็จ -> {os.path.relpath(output_md, PROJECT_DIR)}")

    print(f"\n✅ นำเข้าประวัติการแชทเก่าเสร็จสมบูรณ์เรียบร้อยแล้ว!")

if __name__ == "__main__":
    import_sessions()
