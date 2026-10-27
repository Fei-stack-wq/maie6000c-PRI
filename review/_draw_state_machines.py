"""Draw the revised state-machine figures (two 2-panel images) with Pillow."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

S = 2
PW, PH = 460, 560  # panel size
CANVAS_W, CANVAS_H = 940, 580
REG = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

FONTS: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}
img = None
d = None


def F(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype(BOLD if bold else REG, size * S)
    return FONTS[key]


def rect(x, y, w, h, fill, stroke, r=8, width=1.4):
    d.rounded_rectangle(
        [x * S, y * S, (x + w) * S, (y + h) * S],
        radius=r * S,
        fill=fill,
        outline=stroke,
        width=max(1, round(width * S)),
    )


def text(x, y, s, size=10.2, bold=False, color="#4B5563", anchor="la"):
    d.text((x * S, y * S), s, font=F(size, bold), fill=color, anchor=anchor)


def _seg(p1, p2, color, width):
    d.line([p1[0] * S, p1[1] * S, p2[0] * S, p2[1] * S], fill=color, width=max(1, round(width * S)))


def arrow(points, dashed=False, color="#6B7280", width=1.6):
    pts = [(p[0], p[1]) for p in points]
    if dashed:
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            length = math.hypot(x2 - x1, y2 - y1)
            if length == 0:
                continue
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
    size = 8.0
    left = (x2 - size * math.cos(ang - math.pi / 6), y2 - size * math.sin(ang - math.pi / 6))
    right = (x2 - size * math.cos(ang + math.pi / 6), y2 - size * math.sin(ang + math.pi / 6))
    d.polygon(
        [(x2 * S, y2 * S), (left[0] * S, left[1] * S), (right[0] * S, right[1] * S)],
        fill=color,
    )


def new_panel(title: str):
    rect(0, 0, PW, PH, "#FBFCFE", "#D5DCE6", r=10, width=1.2)
    text(16, 30, title, 14, True, "#1F4E79")


def box(x, y, w, h, palette, state, sub, sub2=None):
    rect(x, y, w, h, palette[0], palette[1])
    cx = x + w / 2
    if sub2:
        text(cx, y + 15, state, 12.5, True, "#1F2937", "mm")
        text(cx, y + 31, sub, 10.2, False, "#4B5563", "mm")
        text(cx, y + 44, sub2, 10.2, False, "#4B5563", "mm")
    else:
        text(cx, y + 17, state, 12.5, True, "#1F2937", "mm")
        text(cx, y + 36, sub, 10.2, False, "#4B5563", "mm")


P1 = ("#EAF0FA", "#A9BFDF")
P2 = ("#FFF7E6", "#E0BE72")
P3 = ("#EAF5EE", "#9DCBAF")
P4 = ("#FCEAEE", "#E2A5B4")
LPATH = "#B07A1E"


def note(x, y, lines):
    for i, line in enumerate(lines):
        text(x, y + i * 19, line, 10.2, False, "#4B5563")


def paste_panel(canvas, ox, painter):
    global img, d
    panel = Image.new("RGB", (PW * S, PH * S), "#FFFFFF")
    img, d = panel, ImageDraw.Draw(panel)
    painter()
    canvas.paste(panel, (int(ox * S), int(10 * S)))


# ---------------- Panel 1: Job ----------------
def job_panel():
    new_panel("① 分析任务 Job（修订）")
    box(30, 80, 130, 54, P1, "pending", "待领取")
    box(30, 200, 130, 54, P2, "claimed", "attempts+1 · 租约")
    box(30, 340, 130, 54, P3, "completed", "结果已落库")
    box(280, 200, 150, 66, P4, "failed", "错误已记录", "不伪造结果")

    arrow([(95, 134), (95, 200)])
    text(104, 166, "Worker 原子认领")
    arrow([(95, 254), (95, 340)])
    text(104, 297, "输出有效")
    arrow([(160, 227), (280, 227)])
    text(220, 209, "失败", anchor="mm")
    arrow([(355, 200), (355, 120), (160, 120)], dashed=True)
    text(258, 107, "重试（attempts < max_attempts）", 10.2, False, LPATH, "mm")
    arrow([(30, 227), (16, 227), (16, 107), (30, 107)], dashed=True)

    note(30, 470, [
        "failed 达到 max_attempts 后为终态，不再重试；",
        "租约过期的 claimed 由巡检退回 pending（attempts+1）；",
        "实线 = 正常流转，虚线 = 重试 / 回收。",
    ])


# ---------------- Panel 2: comment analysis ----------------
def comment_panel():
    new_panel("② 评论分析状态（新增字段）")
    box(30, 80, 130, 54, P1, "pending", "待分析")
    box(30, 200, 130, 54, P2, "analyzing", "调用 AI 提取")
    box(30, 340, 220, 74, P3, "analyzed", "with_issue / no_issue", "/ unknown")
    box(290, 200, 140, 54, P4, "failed", "错误已记录")

    arrow([(95, 134), (95, 200)])
    text(104, 166, "取片调度")
    arrow([(95, 254), (95, 340)])
    text(104, 297, "写入关联与证据")
    arrow([(160, 227), (290, 227)])
    text(225, 209, "失败分类", anchor="mm")
    arrow([(360, 200), (360, 120), (160, 120)], dashed=True)
    text(262, 107, "重放：failed → pending", 10.2, False, LPATH, "mm")

    note(30, 470, [
        "统计：接收量 = 全部评论；成功分析量 = analyzed；",
        "失败量 = failed；unknown 计入成功分析但不计问题数；",
        "虚线 = 人工 / 系统重放。",
    ])


# ---------------- Panel 3: Issue ----------------
def issue_panel():
    new_panel("③ 问题组 Issue（修订）")
    box(24, 80, 140, 54, P2, "proposed", "AI 提议待复核")
    box(300, 80, 140, 54, P2, "confirmed", "人工已确认")
    box(24, 220, 140, 54, P4, "dismissed", "人工驳回")
    box(300, 220, 140, 54, P3, "resolved", "已记录处理")

    arrow([(164, 107), (300, 107)])
    text(232, 95, "确认", anchor="mm")
    arrow([(94, 134), (94, 220)])
    text(102, 176, "驳回")
    arrow([(370, 134), (370, 220)])
    text(360, 176, "记录跟进", anchor="ra")
    arrow([(430, 220), (430, 134)])
    text(422, 176, "重开", anchor="ra")
    arrow([(24, 247), (10, 247), (10, 107), (24, 107)], dashed=True)

    note(24, 430, [
        "confirmed 之后必须能走到 resolved（记录跟进），",
        "不能把 confirmed 画成终点；",
        "dismissed 允许人工重开（方案 A，左侧虚线）；",
        "改名 / 合并 / 拆分不改状态，写 issue_actions。",
    ])


# ---------------- Panel 4: ReviewIssue link ----------------
def link_panel():
    new_panel("④ 评论关联 ReviewIssue（修订）")
    box(40, 150, 140, 54, P2, "suggested", "AI 建议关联")
    box(280, 80, 150, 54, P3, "accepted", "人工接受")
    box(280, 220, 150, 54, P4, "rejected", "人工拒绝")

    arrow([(180, 165), (280, 112)])
    text(214, 128, "接受", anchor="mm")
    arrow([(180, 190), (280, 243)])
    text(214, 232, "拒绝", anchor="mm")
    arrow([(330, 134), (330, 220)])
    text(322, 176, "改判", anchor="ra")
    arrow([(390, 220), (390, 134)])
    text(398, 176, "改判", anchor="la")

    note(30, 430, [
        "accepted 是唯一进入「问题提及数」的状态；",
        "AI 建议数与人工确认数分开展示，suggested 不计入确认；",
        "重跑只 supersede origin=ai 且 status=suggested 的行。",
    ])


def build(out_a: str, out_b: str):
    canvas = Image.new("RGB", (CANVAS_W * S, CANVAS_H * S), "#FFFFFF")
    paste_panel(canvas, 10, job_panel)
    paste_panel(canvas, 480, comment_panel)
    canvas.save(out_a)
    print("saved", out_a, canvas.size)

    canvas = Image.new("RGB", (CANVAS_W * S, CANVAS_H * S), "#FFFFFF")
    paste_panel(canvas, 10, issue_panel)
    paste_panel(canvas, 480, link_panel)
    canvas.save(out_b)
    print("saved", out_b, canvas.size)


if __name__ == "__main__":
    build(r"review\fig_states_a.png", r"review\fig_states_b.png")
