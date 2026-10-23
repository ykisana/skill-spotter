"""skill-spotter icon: three repeated task lines, a magnifier spotting a "/" (a skill).

Regenerate: .venv/bin/python docs/images/make_icon.py .claude-plugin/icon.png
"""

from PIL import Image, ImageDraw, ImageFilter

S = 2048  # drawn at 2x, saved at 1024
OUT = 1024

BG_TOP = (24, 32, 64)
BG_BOTTOM = (12, 16, 36)
LINE = (88, 104, 150)
LINE_HI = (150, 168, 214)
AMBER = (255, 184, 48)
WHITE = (250, 246, 236)


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def main(path):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # rounded-square background with a vertical gradient
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(BG_TOP, BG_BOTTOM, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # three repeated "task" lines, each a prompt chevron and a bar
    x0, bar_h, gap = int(S * 0.17), int(S * 0.075), int(S * 0.145)
    y_first = int(S * 0.27)
    for i in range(3):
        y = y_first + i * gap
        color = LINE_HI if i == 1 else LINE
        cx = x0
        d.line(
            [(cx, y), (cx + bar_h * 0.45, y + bar_h / 2), (cx, y + bar_h)],
            fill=color,
            width=int(bar_h * 0.28),
            joint="curve",
        )
        bx = cx + int(bar_h * 0.95)
        width = [0.52, 0.6, 0.46][i]
        d.rounded_rectangle(
            [bx, y + bar_h * 0.18, bx + int(S * width), y + bar_h * 0.82],
            radius=int(bar_h * 0.32),
            fill=color,
        )

    # magnifier: soft shadow, then lens fill, ring and handle
    cx, cy, r = int(S * 0.575), int(S * 0.555), int(S * 0.215)
    ring = int(S * 0.045)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse(
        [cx - r - ring, cy - r - ring + 30, cx + r + ring, cy + r + ring + 30], fill=(0, 0, 0, 120)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(40))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img)

    hx, hy = cx + r * 0.72, cy + r * 0.72
    handle_len = S * 0.165
    d.line(
        [(hx, hy), (hx + handle_len * 0.707, hy + handle_len * 0.707)],
        fill=AMBER,
        width=int(S * 0.075),
    )
    end = (hx + handle_len * 0.707, hy + handle_len * 0.707)
    cap = int(S * 0.0375)
    d.ellipse([end[0] - cap, end[1] - cap, end[0] + cap, end[1] + cap], fill=AMBER)

    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 40, 78, 235))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=AMBER, width=ring)

    # the spotted skill: a bold "/" in the lens
    sl = r * 0.5
    d.line(
        [(cx + sl * 0.42, cy - sl), (cx - sl * 0.42, cy + sl)],
        fill=WHITE,
        width=int(S * 0.05),
    )
    for px, py in ((cx + sl * 0.42, cy - sl), (cx - sl * 0.42, cy + sl)):
        c = int(S * 0.025)
        d.ellipse([px - c, py - c, px + c, py + c], fill=WHITE)

    img = img.resize((OUT, OUT), Image.LANCZOS)
    img.save(path, optimize=True)


if __name__ == "__main__":
    import sys

    main(sys.argv[1])
