from PIL import Image
import numpy as np


def uncomposite_black_white(black_path: str, white_path: str, out_path: str):
    # 读入并转 RGB（不要带 alpha）
    img_b = Image.open(black_path).convert("RGB")
    img_w = Image.open(white_path).convert("RGB")

    if img_b.size != img_w.size:
        raise ValueError(f"Size mismatch: {img_b.size} vs {img_w.size}")

    # 转 float 0..1
    b = np.asarray(img_b, dtype=np.float32) / 255.0
    w = np.asarray(img_w, dtype=np.float32) / 255.0

    # 由 a = 1 - (Ow - Ob)；对每通道算一份
    a_rgb = 1.0 - (w - b)

    # 抗噪：把 a 从 RGB 合成一个值（中位数通常更稳）
    a = np.median(a_rgb, axis=2)

    # clamp
    a = np.clip(a, 0.0, 1.0)

    # 由 Ob = C*a => C = Ob/a
    # 避免除零
    eps = 1e-6
    a_safe = np.maximum(a, eps)

    c = b / a_safe[..., None]
    c = np.clip(c, 0.0, 1.0)

    # a==0 的地方颜色设为 0（可选）
    c[a <= eps] = 0.0

    # 组装 RGBA
    rgba = np.zeros((b.shape[0], b.shape[1], 4), dtype=np.uint8)
    rgba[..., :3] = (c * 255.0 + 0.5).astype(np.uint8)
    rgba[..., 3] = (a * 255.0 + 0.5).astype(np.uint8)

    Image.fromarray(rgba, mode="RGBA").save(out_path)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    # 示例：python script.py
    uncomposite_black_white("black.png", "white.png", "out.png")
