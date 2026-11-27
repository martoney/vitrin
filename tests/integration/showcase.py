"""Sharp-edged wallpapers for the screenshots, drawn at twice the size and downsampled for smooth edges."""
import math
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 2


def hexc(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def finish(image, w, h, path):
    image.resize((w, h), Image.LANCZOS).convert('RGB').save(path)


def stripes(path, w, h):
    W, H = w * SS, h * SS
    image = Image.new('RGB', (W, H), hexc('#1b1b3a'))
    draw = ImageDraw.Draw(image)
    theta = math.radians(32)
    n = (math.cos(theta), math.sin(theta))
    d = (-math.sin(theta), math.cos(theta))
    cx, cy, length = W / 2, H / 2, math.hypot(W, H)
    palette = ['#ff3d81', '#ffd23f', '#f7f7fb', '#1de9b6', '#3a86ff', '#1b1b3a', '#ff7a3d', '#f7f7fb']
    widths = [260, 120, 340, 200, 300, 140, 240, 90]
    offset = -length / 2
    i = 0
    while offset < length / 2:
        width = widths[i % len(widths)] * SS
        colour = hexc(palette[i % len(palette)])
        a, b = offset, offset + width
        poly = []
        for o, sign in ((a, -1), (a, 1), (b, 1), (b, -1)):
            poly.append((cx + n[0] * o + d[0] * length * sign, cy + n[1] * o + d[1] * length * sign))
        draw.polygon(poly, fill=colour)
        pin = 8 * SS
        poly = []
        for o, sign in ((b, -1), (b, 1), (b + pin, 1), (b + pin, -1)):
            poly.append((cx + n[0] * o + d[0] * length * sign, cy + n[1] * o + d[1] * length * sign))
        draw.polygon(poly, fill=hexc('#0b0b1e'))
        offset = b + pin
        i += 1
    finish(image, w, h, path)


def synthwave(path, w, h):
    W, H = w * SS, h * SS
    horizon = int(H * 0.56)
    image = Image.new('RGB', (W, H), hexc('#0b0221'))
    px = image.load()
    top, mid, low = hexc('#12033a'), hexc('#7a1fa2'), hexc('#ff2e97')
    for y in range(horizon):
        t = y / horizon
        a, b, u = (top, mid, t / 0.6) if t < 0.6 else (mid, low, (t - 0.6) / 0.4)
        colour = tuple(int(a[k] + (b[k] - a[k]) * u) for k in range(3))
        for x in range(W):
            px[x, y] = colour
    sun = Image.new('RGB', (W, H), (0, 0, 0))
    sdraw = ImageDraw.Draw(sun)
    r = int(H * 0.27)
    scx, scy = W // 2, horizon - int(r * 0.15)
    for y in range(scy - r, scy + r):
        t = (y - (scy - r)) / (2 * r)
        c1, c2 = hexc('#ffe66d'), hexc('#ff3d81')
        colour = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        half = math.sqrt(max(r * r - (y - scy) ** 2, 0))
        sdraw.line([(scx - half, y), (scx + half, y)], fill=colour)
    mask = Image.new('L', (W, H), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rectangle([0, scy - r, W, horizon], fill=255)
    for k in range(9):
        y = scy + int(r * (0.05 + 0.1 * k))
        mdraw.rectangle([0, y, W, y + int((2 + k * 1.6) * SS)], fill=0)
    sun_mask = ImageChops.multiply(mask, sun.convert('L').point(lambda v: 255 if v else 0))
    image.paste(sun, (0, 0), sun_mask)
    floor = Image.new('RGB', (W, H - horizon), hexc('#0b0221'))
    image.paste(floor, (0, horizon))
    glow = Image.new('RGB', (W, H), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cyan, magenta = hexc('#27f0ff'), hexc('#ff2ee6')
    lines = 14
    for i in range(1, lines + 1):
        t = (i / lines) ** 2.1
        y = horizon + (H - horizon) * t
        gdraw.line([(0, y), (W, y)], fill=cyan, width=max(2, int((2 + 6 * t) * SS)))
    for i in range(-40, 41):
        xb = W / 2 + i * 150 * SS * 1.35
        gdraw.line([(W / 2, horizon), (xb, H)], fill=magenta, width=int(4 * SS))
    haze = glow.filter(ImageFilter.GaussianBlur(10 * SS))
    glow = ImageChops.screen(glow, haze)
    floor_mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(floor_mask).rectangle([0, horizon + 2, W, H], fill=255)
    image.paste(ImageChops.screen(image, glow), (0, 0), floor_mask)
    finish(image, w, h, path)


WALLPAPERS = {'stripes': stripes, 'synthwave': synthwave}
