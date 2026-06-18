#!/usr/bin/env python3
"""
Pipelit 图片标注检测器 — 检测图片中的红/绿色圈注区域。
需要 Pillow：pip install Pillow

Usage:
  python3 image_annotator.py analyze <image_path>

Output: JSON to stdout
"""
import sys
import json
import pathlib
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def _check_pillow():
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def analyze_annotations(image_path: str) -> dict:
    """检测图片中的彩色圈注区域（红/绿/黄），输出标注列表。"""
    if not _check_pillow():
        return {"error": "pillow_not_installed", "install": "pip install Pillow"}

    from PIL import Image
    import colorsys

    path = pathlib.Path(image_path)
    if not path.exists():
        return {"error": f"文件不存在: {image_path}"}

    img = Image.open(path).convert("RGB")
    width, height = img.size
    pixels = img.load()

    # HSV 阈值：高饱和度 + 目标色相范围
    TARGET_COLORS = {
        "red":   [(0, 10), (350, 360)],   # 色相范围（度），S>0.5, V>0.3
        "green": [(100, 140)],
        "yellow": [(40, 65)],
    }

    def _classify_pixel(r, g, b):
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.45 or v < 0.3:
            return None
        hue = h * 360
        for color, ranges in TARGET_COLORS.items():
            for lo, hi in ranges:
                if lo <= hue <= hi:
                    return color
        return None

    # 降采样扫描（每 4 px 取一次，提升速度）
    STEP = 4
    color_pixels: dict[str, list[tuple[int, int]]] = {}
    for y in range(0, height, STEP):
        for x in range(0, width, STEP):
            c = _classify_pixel(*pixels[x, y])
            if c:
                color_pixels.setdefault(c, []).append((x, y))

    # 找连通区域（简单 bbox 聚合）
    annotations = []
    for color, pts in color_pixels.items():
        if len(pts) < 10:   # 太少的像素不算标注
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        # 扩展 20px margin
        x1 = max(0, x1 - 20)
        y1 = max(0, y1 - 20)
        x2 = min(width, x2 + 20)
        y2 = min(height, y2 + 20)

        # 裁剪并保存
        crop = img.crop((x1, y1, x2, y2))
        with tempfile.NamedTemporaryFile(
            prefix="pipelit_ann_", suffix=".png", delete=False
        ) as tmp:
            tmp_name = tmp.name
        crop.save(tmp_name)

        annotations.append({
            "color": color,
            "bbox": [x1, y1, x2, y2],
            "crop_path": tmp_name,
            "pixel_count": len(pts),
        })

    # 按像素数降序排列（最显眼的标注在前）
    annotations.sort(key=lambda a: a["pixel_count"], reverse=True)

    return {"annotations": annotations, "annotation_count": len(annotations)}


def main():
    args = sys.argv[1:]
    if not args or args[0] == "analyze" and len(args) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    if cmd == "analyze":
        out = analyze_annotations(args[1])
    else:
        out = {"error": f"未知命令: {cmd}"}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
