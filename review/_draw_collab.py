"""Draw the collaboration-model figure: contract-first + four parallel lanes + weekly integration."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

S = 2
W, H = 800, 470
REG = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONTS: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}

img = Image.new("RGB", (W * S, H * S), "#FFFFFF")
d = ImageDraw.Draw(img)


def F(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype(BOLD if bold else REG, size * S)
    return FONTS[key]


def text(x, y, s, size=10, bold=False, color="#4B5563", anchor="la"):
    d.text((x * S, y * S), s, font=F(size, bold), fill=color, anchor=anchor)


def rect(x, y, w, h, fill, stroke, r=8, width=1.3):
    d.rounded_rectangle(
        [x * S, y * S, (x + w) * S, (y + h) * S],
        radius=r * S,
        fill=fill,
        outline=stroke,
        width=max(1, round(width * S)),
    )


def _seg(p1, p2, color, width):
    d.line([p1[0] * S, p1[1] * S, p2[0] * S, p2[1] * S], fill=color, width=max(1, round(width * S)))


def arrow(points, dashed=False, color="#6B7280", width=1.5):
    pts = [(p[0], p[1]) for p in points]
    if dashed:
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            length = math.hypot(x2 - x1, y2 - y1)
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            pos = 0.0
            while pos < length:
                end = min(pos + 5.0, length)
                _seg((x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end), color, width)
                pos += 9.0
    else:
        for i in range(len(pts) - 1):
            _seg(pts[i], pts[i + 1], color, width)
    x1, y1 = pts[-2]
    x2, y2 = pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 7.5
    left = (x2 - size * math.cos(ang - math.pi / 6), y2 - size * math.sin(ang - math.pi / 6))
    right = (x2 - size * math.cos(ang + math.pi / 6), y2 - size * math.sin(ang + math.pi / 6))
    d.polygon([(x2 * S, y2 * S), (left[0] * S, left[1] * S), (right[0] * S, right[1] * S)], fill=color)


# ---- contract block (the only serial part) ----
rect(20, 100, 152, 128, "#EAF0FA", "#A9BFDF")
text(96, 120, "W5 契约周（串行）", 12.5, True, "#1F4E79", "mm")
for i, line in enumerate(["schemas.py + OpenAPI", "0002 迁移（仅 R1）", "mock AI 服务", "seed + 评测样本"]):
    text(96, 142 + i * 20, line, 9.8, False, "#4B5563", "mm")

LANES = [
    (40, "R1 数据与接入（FEI）", "迁移 / 批次接入 / 去重 / 契约", ("#EAF0FA", "#A9BFDF")),
    (110, "R2 流水线（XIANG）", "原子认领 / 租约 / 重试 / 失败隔离", ("#FFF7E6", "#E0BE72")),
    (180, "R3 AI 与评测（XU）", "提取契约 / 证据校验 / 归组 / 评测", ("#EAF5EE", "#9DCBAF")),
    (250, "R4 复核与产品（ZHANG）", "Issue API / 复核页 / e2e / 演示", ("#FCEAEE", "#E2A5B4")),
]

for y, title, sub, (fill, stroke) in LANES:
    rect(236, y, 336, 52, fill, stroke)
    text(248, y + 13, title, 11.2, True, "#1F2937")
    text(248, y + 32, sub, 9.4, False, "#4B5563")

# fan out: contract -> lanes
for y, *_ in LANES:
    arrow([(172, 164), (204, 164), (204, y + 26), (236, y + 26)])

# fan in: lanes -> integration
rect(632, 100, 148, 128, "#EAF5EE", "#9DCBAF")
text(706, 120, "每周五集成日", 12.5, True, "#1F4E79", "mm")
for i, line in enumerate(["M1–M6 里程碑", "e2e + 回归", "迁移统一执行"]):
    text(706, 144 + i * 20, line, 9.8, False, "#4B5563", "mm")
for y, *_ in LANES:
    arrow([(572, y + 26), (604, y + 26), (604, 164), (632, 164)])

# serial gates (below the lanes)
text(20, 318, "串行关口：", 10.2, True, "#1F4E79")
text(92, 318, "① W5 契约冻结   ② 迁移执行（R1 串行）   ③ 联调 / 回归（W7、W12、W13）", 9.8)

# milestone rail + chips
text(20, 350, "里程碑（每 1–2 周收口一次）", 10.2, True, "#1F4E79")
d.line([20 * S, 366 * S, 780 * S, 366 * S], fill="#C9D4E3", width=2 * S)
arrow([(706, 228), (706, 364)], dashed=True)
text(700, 296, "每个里程碑统一收口", 9.2, False, "#B07A1E", "ra")

chips = [
    ("M1", "W5 契约+迁移"),
    ("M2", "W6 主流程"),
    ("M3", "W7 demo"),
    ("M4", "W10 质量"),
    ("M5", "W12 加固"),
    ("M6", "W13 final"),
]
x = 20
for tag, label in chips:
    rect(x, 378, 120, 48, "#FBFCFE", "#C9D4E3")
    text(x + 10, 391, tag, 11.5, True, "#2E74B5")
    text(x + 40, 394, label, 9.2, False, "#4B5563")
    x += 128

img.save(r"review\fig_collab.png")
print("saved review/fig_collab.png", img.size)
