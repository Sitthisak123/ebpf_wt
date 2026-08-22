import os
import sys
import re
import cv2
import pytesseract

def extract_folder(img_dir, header_title, output_file="dumps/flightpath.txt"):
    if not os.path.exists(img_dir):
        print(f"Directory {img_dir} does not exist!")
        return False

    png_files = [f for f in os.listdir(img_dir) if f.endswith(".png")]
    if not png_files:
        print(f"No PNG images found in {img_dir}!")
        return False

    # Sort files numerically if possible (1.png, 2.png...)
    def get_num(fname):
        match = re.search(r'(\d+)', fname)
        return int(match.group(1)) if match else 999999

    sorted_files = sorted(png_files, key=get_num)
    print(f"Found {len(sorted_files)} images in {img_dir}: {sorted_files}")

    output_lines = [f"\n=== {header_title} ===\n"]
    output_lines.append(f'{"Image":<10} | {"Flight time (s)":<15} | {"Speed (m/s)":<12} | {"Distance (m)":<12} | {"Position X (m)":<15} | {"Position Y (m)":<15}')
    output_lines.append('-' * 95)

    for fname in sorted_files:
        img_path = os.path.join(img_dir, fname)
        img = cv2.imread(img_path)
        if img is None:
            print(f"Failed to read image {img_path}")
            continue

        h, w, _ = img.shape
        crop = img[int(h * 0.15):int(h * 0.75), int(w * 0.15):int(w * 0.95)]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray)

        ft = re.search(r'Flight time:\s*([0-9.]+)', text)
        sp = re.search(r'Speed:\s*([0-9.]+)', text)
        dist = re.search(r'Distance:\s*([0-9.]+)', text)
        pos = re.search(r'Position X:\s*([0-9.]+)\s*m,\s*Y:\s*([0-9.]+)', text)

        ft_v = ft.group(1) if ft else 'N/A'
        sp_v = sp.group(1) if sp else 'N/A'
        dist_v = dist.group(1) if dist else 'N/A'
        px_v = pos.group(1) if pos else 'N/A'
        py_v = pos.group(2) if pos else 'N/A'

        line = f'{fname:<10} | {ft_v:<15} | {sp_v:<12} | {dist_v:<12} | {px_v:<15} | {py_v:<15}'
        output_lines.append(line)
        print(f"Extracted {fname}: time={ft_v}, spd={sp_v}, dist={dist_v}, pos=({px_v}, {py_v})")

    extracted_text = "\n".join(output_lines) + "\n"

    with open(output_file, "a", encoding="utf-8") as f:
        f.write(extracted_text)

    print(f"\n✅ Successfully appended telemetry section to {output_file}")
    return True

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "dumps/2"
    header = sys.argv[2] if len(sys.argv) > 2 else "War Thunder Flight Path Telemetry Data (1-26.png) [0.1 km to 0.1 km]"
    extract_folder(target_dir, header)
