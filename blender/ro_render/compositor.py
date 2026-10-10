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


def grade(rgba: bytes, width: int, height: int, correction: dict | None) -> bytes:
    """Match Studio's ColorCorrectionEffect. Values are already display sRGB."""
    if not correction:
        return rgba
    image = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4).astype(np.float32) / 255.0
    rgb = image[..., :3]
    rgb = rgb + float(correction.get("brightness") or 0)
    contrast = float(correction.get("contrast") or 0)
    rgb = (rgb - 0.5) * (1.0 + contrast) + 0.5
    saturation = float(correction.get("saturation") or 0)
    luma = rgb[..., 0:1] * 0.299 + rgb[..., 1:2] * 0.587 + rgb[..., 2:3] * 0.114
    rgb = luma + (rgb - luma) * (1.0 + saturation)
    tint = correction.get("tint") or [1, 1, 1]
    rgb = rgb * np.array(tint, dtype=np.float32)
    visible = image[..., 3:4] > 0
    image[..., :3] = np.where(visible, np.clip(rgb, 0.0, 1.0), 0.0)
    return np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8).tobytes()


def composite_png(png_bytes: bytes, effects: dict, correction: dict | None = None) -> bytes:
    width, height, rgba = decode_png(png_bytes)
    rgba = grade(rgba, width, height, correction)
    return encode_png(width, height, composite(rgba, width, height, effects))


def _blur_color(image: np.ndarray, radius: float) -> np.ndarray:
    if image.ndim == 2:
        return _blur(image, radius)
    blurred = [_blur(image[..., channel], radius) for channel in range(image.shape[-1])]
    return np.stack(blurred, axis=-1).astype(np.float32)


def bloom_linear(image: np.ndarray, bloom: dict | None) -> np.ndarray:
    """Spread HDR light past the subject. `image` is straight-alpha linear RGBA.

    Studio's threshold is in scene light, so this has to run before the picture
    is clamped to 8-bit. Dim pixels stay put. The halo is allowed to extend
    into the transparent cutout, which is the glow around eyes and flames.
    """
    if not bloom or float(bloom.get("intensity") or 0) <= 0 or float(bloom.get("size") or 0) <= 0:
        return image
    threshold = float(bloom.get("threshold") if bloom.get("threshold") is not None else 2.0)
    intensity = float(bloom.get("intensity") or 0)
    rgb = image[..., :3]
    alpha = image[..., 3:4]
    peak = np.max(rgb, axis=-1, keepdims=True)
    subject = alpha > 0.02
    excess = np.maximum(peak - threshold, 0.0)
    scale = np.where((peak > 1e-6) & subject, excess / np.maximum(peak, 1e-6), 0.0)
    highlight = rgb * scale
    height, width = rgb.shape[:2]
    radius = (float(bloom.get("size") or 0) / 56.0) * float(max(width, height)) * 0.12
    blurred = _blur_color(highlight, radius) * intensity
    glow = np.max(blurred, axis=-1, keepdims=True)
    glow_alpha = np.clip(glow / max(threshold, 0.5), 0.0, 1.0)
    new_alpha = np.maximum(alpha, glow_alpha)
    straight = np.where(new_alpha > 1e-4, (rgb * alpha + blurred) / np.maximum(new_alpha, 1e-4), 0.0)
    out = np.empty_like(image, dtype=np.float32)
    out[..., :3] = straight
    out[..., 3:4] = new_alpha
    return out


def tonemap_display(image: np.ndarray, exposure: float) -> np.ndarray:
    """Straight linear RGBA to straight sRGB RGBA in 0..1. Standard view, no AgX."""
    rgb = np.clip(image[..., :3] * (2.0 ** float(exposure)), 0.0, None)
    encoded = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
    out = np.empty_like(image, dtype=np.float32)
    out[..., :3] = np.clip(encoded, 0.0, 1.0)
    out[..., 3] = np.clip(image[..., 3], 0.0, 1.0)
    return out


def rgba_bytes(image: np.ndarray) -> bytes:
    return np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8).tobytes()


def _linear_channel(value: float) -> float:
    value = min(max(float(value), 0.0), 1.0)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _luma(color) -> float:
    red, green, blue = (_linear_channel(color[0]), _linear_channel(color[1]), _linear_channel(color[2]))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def studio_environment(lighting: dict) -> tuple[list, float, float]:
    """Sky tint, world strength, and sun energy from Studio's lighting settings.

    Skybox images are usually not owned by the place, so they cannot be read.
    The fill is the daytime sky, pulled toward Atmosphere and OutdoorAmbient.
    Strength is set so that fill's luminance stays under the albedo. A grey
    world at full strength is what was lifting dark armor up to clay.
    """
    outdoor = list(lighting.get("outdoorAmbient") or [0.5, 0.5, 0.5])
    atmosphere = lighting.get("atmosphere") or {}
    air = list(atmosphere.get("color") or [0.55, 0.70, 0.95])
    decay = list(atmosphere.get("decay") or air)
    density = min(max(float(atmosphere.get("density") or 0), 0.0), 1.0)
    haze = min(max(float(atmosphere.get("haze") or 0), 0.0), 1.0)
    sun = lighting.get("sunDirection") or [0, 1, 0]
    sun_y = min(max(float(sun[1] if len(sun) > 1 else 1.0), 0.0), 1.0)
    zenith = [0.20 + 0.40 * sun_y, 0.35 + 0.40 * sun_y, 0.55 + 0.40 * sun_y]
    zenith = [zenith[i] * (1.0 - density) + float(air[i]) * density for i in range(3)]
    horizon_mix = 0.45 + 0.35 * haze
    horizon = [zenith[i] * (1.0 - horizon_mix) + float(decay[i]) * horizon_mix for i in range(3)]
    sky = [zenith[i] * 0.72 + horizon[i] * 0.28 for i in range(3)]
    # Outdoor ambient tints the fill. Keep most of the sky hue so a blue
    # daytime sky is not repainted as the grey outdoor color.
    sky = [sky[i] * 0.82 + float(outdoor[i]) * 0.18 for i in range(3)]
    for key, weight in (("colorShiftTop", 0.2), ("colorShiftBottom", 0.1)):
        shift = lighting.get(key) or [0, 0, 0]
        if sum(float(channel) for channel in shift) > 0.01:
            sky = [sky[i] * (1.0 - weight) + float(shift[i]) * weight for i in range(3)]
    sky_luma = max(_luma(sky), 1e-3)
    env = lighting.get("environmentDiffuse")
    env_scale = 1.0 if env is None else max(float(env), 0.0)
    strength = min(4.0, (0.55 / sky_luma) * env_scale)
    brightness = lighting.get("brightness")
    glare = min(max(float(atmosphere.get("glare") or 0), 0.0), 1.0)
    sun_energy = max(0.0 if brightness is None else float(brightness), 0.0) * 0.35 * (1.0 + glare)
    return sky, strength, sun_energy


def sun_rays_linear(image: np.ndarray, rays: dict | None, origin) -> np.ndarray:
    """Screen-space sun rays. Origin is camera view x, y with y up, in 0..1."""
    if not rays or origin is None:
        return image
    intensity = float(rays.get("intensity") or 0)
    if intensity <= 0.0001:
        return image
    height, width = image.shape[:2]
    spread = min(max(float(rays.get("spread") or 0.1), 0.0), 1.0)
    ox = float(origin[0]) * width
    oy = (1.0 - float(origin[1])) * height
    yy, xx = np.mgrid[0:height, 0:width]
    direction_x = ox - xx
    direction_y = oy - yy
    distance = np.sqrt(direction_x * direction_x + direction_y * direction_y) + 1e-3
    length = (0.04 + spread * 0.35) * float(max(width, height))
    steps = 12
    total = np.zeros(image.shape[:2] + (3,), dtype=np.float32)
    rgb = image[..., :3]
    for step in range(1, steps + 1):
        travel = (step / steps) * length
        sample_x = np.clip(np.rint(xx + direction_x / distance * travel).astype(np.int32), 0, width - 1)
        sample_y = np.clip(np.rint(yy + direction_y / distance * travel).astype(np.int32), 0, height - 1)
        total += rgb[sample_y, sample_x] * image[sample_y, sample_x, 3:4]
    glow = total / steps * intensity
    out = image.copy()
    out[..., :3] = rgb + glow
    glow_alpha = np.clip(np.max(glow, axis=-1, keepdims=True), 0.0, 1.0)
    out[..., 3:4] = np.maximum(image[..., 3:4], glow_alpha * (1.0 - image[..., 3:4]))
    return out


def focus_blur_radius(distance: float, dof: dict | None, long_side: int) -> float:
    """Pixels of blur for a subject at `distance` studs from the camera."""
    if not dof:
        return 0.0
    focus = float(dof.get("focusDistance") or 0)
    band = max(float(dof.get("inFocusRadius") or 0), 0.0)
    delta = float(distance) - focus
    if abs(delta) <= band:
        return 0.0
    amount = float(dof.get("farIntensity") or 0) if delta > 0 else float(dof.get("nearIntensity") or 0)
    if amount <= 0:
        return 0.0
    outside = min((abs(delta) - band) / 25.0, 1.0)
    return amount * outside * float(long_side) * 0.05


def blur_radius_px(blur: dict | None, long_side: int) -> float:
    if not blur:
        return 0.0
    size = float(blur.get("size") or 0)
    if size <= 0:
        return 0.0
    return size * float(long_side) / 360.0


def blur_straight(image: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0.5:
        return image
    alpha = image[..., 3:4]
    blurred_rgb = _blur_color(image[..., :3] * alpha, radius)
    blurred_alpha = _blur_color(alpha[..., 0], radius)[..., None]
    out = np.empty_like(image, dtype=np.float32)
    out[..., 3:4] = blurred_alpha
    out[..., :3] = np.where(blurred_alpha > 1e-4, blurred_rgb / np.maximum(blurred_alpha, 1e-4), 0.0)
    return out


def apply_fog(image: np.ndarray, fog: dict | None, distance: float) -> np.ndarray:
    if not fog:
        return image
    start = float(fog.get("start") or 0)
    end = float(fog.get("end") if fog.get("end") is not None else 100000)
    if end <= start + 1.0 or end >= 100000 or distance <= start:
        return image
    amount = min(max((float(distance) - start) / (end - start), 0.0), 1.0)
    if amount <= 0.001:
        return image
    color = np.array([_linear_channel(channel) for channel in (fog.get("color") or [1, 1, 1])], dtype=np.float32)
    out = image.copy()
    visible = image[..., 3:4]
    out[..., :3] = image[..., :3] * (1.0 - amount) + color * amount
    out[..., :3] = np.where(visible > 0, out[..., :3], 0.0)
    return out
