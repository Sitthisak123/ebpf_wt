import os
import json

CHAT_HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chat_history")

def list_chat_histories():
    """ค้นหาไฟล์ประวัติการสนทนาทั้งหมดในโฟลเดอร์ chat_history"""
    print(f"[*] ค้นหาประวัติการสนทนาใน: {CHAT_HISTORY_DIR}")
    if not os.path.exists(CHAT_HISTORY_DIR):
        print("[-] ไม่พบโฟลเดอร์ chat_history")
        return

    antigravity_files = []
    antigravity_dir = os.path.join(CHAT_HISTORY_DIR, "antigravity")
    if os.path.exists(antigravity_dir):
        for root, dirs, files in os.walk(antigravity_dir):
            for file in files:
                antigravity_files.append(os.path.join(root, file))

    vscode_files = []
    vscode_dir = os.path.join(CHAT_HISTORY_DIR, "vscode")
    if os.path.exists(vscode_dir):
        for root, dirs, files in os.walk(vscode_dir):
            for file in files:
                if file.endswith(".jsonl"):
                    vscode_files.append(os.path.join(root, file))

    print(f"\n[+] พบ Antigravity History Files ({len(antigravity_files)} ไฟล์):")
    for f in antigravity_files[:15]:
        rel_path = os.path.relpath(f, CHAT_HISTORY_DIR)
        print(f"  - {rel_path}")
    if len(antigravity_files) > 15:
        print(f"  ... และอีก {len(antigravity_files) - 15} ไฟล์")

    print(f"\n[+] พบ VS Code Chat Sessions ({len(vscode_files)} ไฟล์):")
    for f in vscode_files:
        rel_path = os.path.relpath(f, CHAT_HISTORY_DIR)
        print(f"  - {rel_path}")

if __name__ == "__main__":
    list_chat_histories()
