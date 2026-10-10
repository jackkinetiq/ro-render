"""Portrait effects applied to a rendered cutout.

Preview and the saved file both go through this pass, so a stroke, shadow, or
glow in the widget matches the PNG. Pixel sizes are already scaled by the
plugin when the preview is smaller than the output.
"""

import math

import numpy as np

from .image_io import decode_png, encode_png


def _shift(image: np.ndarray, offset_x: float, offset_y: float) -> np.ndarray:
    """Move an image. Positive X goes right and positive Y goes down."""
    out = np.zeros_like(image)
    height, width = image.shape[:2]
    dx = int(round(offset_x))
    dy = int(round(offset_y))
    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    src_x1 = min(width, width - dx)
    src_y1 = min(height, height - dy)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return out
    out[src_y0 + dy : src_y1 + dy, src_x0 + dx : src_x1 + dx] = image[src_y0:src_y1, src_x0:src_x1]
    return out


def _disk_offsets(radius: float) -> list[tuple[int, int]]:
    limit = int(math.ceil(radius))
    offsets = []
    for y in range(-limit, limit + 1):
        for x in range(-limit, limit + 1):
            if x * x + y * y <= radius * radius + 1e-6:
                offsets.append((x, y))
    return offsets or [(0, 0)]


def _dilate(alpha: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0:
        return alpha
    out = np.zeros_like(alpha)
    for x, y in _disk_offsets(radius):
        np.maximum(out, _shift(alpha, x, y), out=out)
    return out


def _erode(alpha: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0:
        return alpha
    out = np.ones_like(alpha)
    for x, y in _disk_offsets(radius):
        np.minimum(out, _shift(alpha, x, y), out=out)
    return out


def _blur_axis(image: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return image
    window = radius * 2 + 1
    padded = np.pad(image, ((0, 0), (radius, radius)), mode="edge")
    cumulative = np.cumsum(padded, axis=1)
    cumulative = np.pad(cumulative, ((0, 0), (1, 0)), mode="constant")
    return (cumulative[:, window:] - cumulative[:, :-window]) / window


def _blur(image: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0.5:
        return image
    each = max(1, int(round(radius / 3)))
    out = image
    for _ in range(3):
        out = _blur_axis(out, each)
        out = _blur_axis(out.T, each).T
    return out.astype(np.float32)


def _over(background: np.ndarray, foreground: np.ndarray) -> np.ndarray:
    src_alpha = foreground[..., 3:4]
    dst_alpha = background[..., 3:4]
    out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
    out_rgb = foreground[..., :3] * src_alpha + background[..., :3] * dst_alpha * (1.0 - src_alpha)
    safe = np.maximum(out_alpha, 1e-6)
    return np.concatenate((out_rgb / safe, out_alpha), axis=-1).astype(np.float32)


def _color_layer(color: list, alpha: np.ndarray) -> np.ndarray:
    height, width = alpha.shape
    layer = np.zeros((height, width, 4), dtype=np.float32)
    layer[..., 0] = color[0]
    layer[..., 1] = color[1]
    layer[..., 2] = color[2]
    layer[..., 3] = np.clip(alpha, 0.0, 1.0)
    return layer


def _mix_inside(subject: np.ndarray, mask: np.ndarray, color: list, opacity: float) -> np.ndarray:
    factor = (np.clip(mask, 0.0, 1.0) * opacity)[..., None]
    mixed = subject.copy()
    mixed[..., :3] = subject[..., :3] * (1.0 - factor) + np.array(color, dtype=np.float32) * factor
    return mixed


def _enabled(effect: dict | None) -> bool:
    return bool(effect) and bool(effect.get("enabled", True))


def composite(rgba: bytes, width: int, height: int, effects: dict) -> bytes:
    subject = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4).astype(np.float32) / 255.0
    alpha = subject[..., 3]

    background_color = effects.get("backgroundColor") or [1, 1, 1]
    background_alpha = 1.0 - float(effects.get("backgroundTransparency") or 0)
    image = _color_layer(background_color, np.full((height, width), background_alpha, dtype=np.float32))

    drop = effects.get("dropShadow") or {}
    if _enabled(drop):
        offset = drop.get("offset") or [0, 0]
        shadow_alpha = _blur(_shift(alpha, float(offset[0]), float(offset[1])), float(drop.get("blur") or 0))
        image = _over(image, _color_layer(drop.get("color") or [0, 0, 0], shadow_alpha * float(drop.get("opacity") or 0)))

    glow = effects.get("outerGlow") or {}
    if _enabled(glow):
        glow_alpha = _blur(alpha, float(glow.get("size") or 0))
        image = _over(image, _color_layer(glow.get("color") or [1, 1, 1], glow_alpha * float(glow.get("opacity") or 0)))

    stroke = effects.get("stroke") or {}
    thickness = float(stroke.get("thickness") or 0)
    if thickness > 0:
        ring = np.clip(_dilate(alpha, thickness) - alpha, 0.0, 1.0)
        image = _over(image, _color_layer(stroke.get("color") or [0, 0, 0], ring))

    inner_glow = effects.get("innerGlow") or {}
    if _enabled(inner_glow):
        size = float(inner_glow.get("size") or 0)
        rim = np.clip(alpha - _erode(alpha, size), 0.0, 1.0)
        rim = _blur(rim, max(1.0, size * 0.35))
        subject = _mix_inside(subject, rim, inner_glow.get("color") or [1, 1, 1], float(inner_glow.get("opacity") or 0))

    inner = effects.get("innerShadow") or {}
    if _enabled(inner):
        offset = inner.get("offset") or [0, 0]
        mask = np.clip(alpha - _shift(alpha, float(offset[0]), float(offset[1])), 0.0, 1.0)
        mask = _blur(mask, float(inner.get("blur") or 0))
        subject = _mix_inside(subject, mask, inner.get("color") or [0, 0, 0], float(inner.get("opacity") or 0))

    image = _over(image, subject)
    return np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8).tobytes()


def composite_png(png_bytes: bytes, effects: dict) -> bytes:
    width, height, rgba = decode_png(png_bytes)
    return encode_png(width, height, composite(rgba, width, height, effects))
