"""Draw Figure 1 (end-to-end flow) for docs/architecture.md.

Output: assets/fig1_end_to_end_flow.png
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

S = 2
W, H = 1000, 1120
REG = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONTS: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}

img = Image.new("RGB", (W * S, H * S), "#FFFFFF")
d = ImageDraw.Draw(img)

P1 = ("#EAF0FA", "#A9BFDF")
P2 = ("#FFF7E6", "#E0BE72")
P3 = ("#EAF5EE", "#9DCBAF")
P4 = ("#FCEAEE", "#E2A5B4")
EDGE = "#7A8494"
LOOP = "#C08A2A"
TITLE = "#1F4E79"
INK = "#1F2937"
SUB = "#4B5563"
MUTED = "#8A94A3"


def F(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype(BOLD if bold else REG, size * S)
    return FONTS[key]


def text(x, y, s, size=11, bold=False, color=SUB, anchor="la"):
    d.text((x * S, y * S), s, font=F(size, bold), fill=color, anchor=anchor)


def rect(x, y, w, h, fill, stroke, r=9, width=1.4):
    d.rounded_rectangle(
        [x * S, y * S, (x + w) * S, (y + h) * S],
        radius=r * S,
        fill=fill,
        outline=stroke,
        width=max(1, round(width * S)),
    )


def _seg(p1, p2, color, width, dash=False):
    x1, y1 = p1
    x2, y2 = p2
    if not dash:
        d.line([x1 * S, y1 * S, x2 * S, y2 * S], fill=color, width=max(1, round(width * S)))
        return
    length = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos = 0.0
    while pos < length:
        end = min(pos + 6.0, length)
        d.line(
            [(x1 + ux * pos) * S, (y1 + uy * pos) * S, (x1 + ux * end) * S, (y1 + uy * end) * S],
            fill=color,
            width=max(1, round(width * S)),
        )
        pos += 10.0


def arrow(points, color=EDGE, width=1.7, dash=False):
    pts = [(p[0], p[1]) for p in points]
    for i in range(len(pts) - 1):
        _seg(pts[i], pts[i + 1], color, width, dash)
    x1, y1 = pts[-2]
    x2, y2 = pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 8.5
    left = (x2 - size * math.cos(ang - math.pi / 6), y2 - size * math.sin(ang - math.pi / 6))
    right = (x2 - size * math.cos(ang + math.pi / 6), y2 - size * math.sin(ang + math.pi / 6))
    d.polygon(
        [(x2 * S, y2 * S), (left[0] * S, left[1] * S), (right[0] * S, right[1] * S)],
        fill=color,
    )


def node(idx, y, title, detail, palette):
    rect(215, y, 585, 64, palette[0], palette[1])
    text(232, y + 14, f"{idx}  {title}", 12.6, True, INK)
    text(232, y + 40, detail, 11.0)


def rotated_label(x, y, s, color=LOOP, size=10.5):
    tmp = Image.new("RGBA", (240 * S, 26 * S), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    td.text((120 * S, 13 * S), s, font=F(size), fill=color, anchor="mm")
    tmp = tmp.rotate(90, expand=True)
    img.paste(tmp, (int(x * S), int(y * S - tmp.height / 2)), tmp)


PHASES = [
    ("接入与校验", 22, 190),
    ("解析入库", 202, 352),
    ("AI 分析", 374, 610),
    ("归组", 632, 696),
    ("人工复核", 718, 868),
    ("收口", 890, 1040),
]
for name, top, bottom in PHASES:
    text(26, top + 2, name, 11.5, True, MUTED)
    _seg((20, bottom + 8), (800, bottom + 8), "#E4E9F0", 1.2, dash=True)

NODES = [
    (30, "数据来源：单平台评论", "商家导出 CSV 或授权接口拉取（首版二选一，不自行采集）", P1),
    (116, "POST /review-batches（Idempotency-Key）", "建 IngestionBatch(validating)，返回 202 {batch_id, status}；job_count 校验后取", P1),
    (202, "逐行校验与规范化", "编码 / 必填字段 / 行数 ≤5,000；错误行写 batch_rows（可下载）", P1),
    (288, "有效行入库（同一事务）", "comments(analysis_status=queued) + jobs(pending, extract_issues)；批次 imported", P1),
    (374, "Worker 原子认领 Job", "FOR UPDATE SKIP LOCKED + 租约；attempts+1；写入 fencing", P2),
    (460, "调 AI /extract-issues", "单条或 20–50 条/批；校验 JSON Schema + evidence 必须是原文子串", P2),
    (546, "落库（同一事务）", "analysis_runs + comment_issues(suggested) + issues(proposed)；comments→analyzed", P2),
    (632, "归组后处理（可重跑）", "按 product+category 召回 proposed/confirmed；关联唯一约束兜底，未命中建组", P2),
    (718, "人工复核看板", "AI 建议数 vs 人工确认数；原文证据高亮；分页 / 筛选", P4),
    (804, "复核动作 → issue_actions（append-only）", "确认 / 驳回 / 改名 / 合并 / 拆分 / 记录跟进 / 重开；expected_version 乐观锁", P4),
    (890, "终态与关组", "resolved（已记录处理）/ dismissed（可重开）；新评论只生成 suggested 提示", P3),
    (976, "统计（接口返回 as_of）", "接收量 / 成功 / 失败、问题提及数（accepted 去重）、分析覆盖率", P3),
]

for i, (y, title, detail, palette) in enumerate(NODES, start=1):
    node(i, y, title, detail, palette)
    if i < len(NODES):
        arrow([(507, y + 64), (507, NODES[i][0])])

# loop 1: validation error -> resubmit (new batch)
arrow([(800, 234), (838, 234), (838, 148), (800, 148)], color=LOOP, dash=True)
rotated_label(846, 190, "重传")

# loop 2: retryable failure -> pending
arrow([(800, 492), (872, 492), (872, 406), (800, 406)], color=LOOP, dash=True)
rotated_label(880, 449, "重试")

# loop 3: new comment on closed issue -> suggested hint only
arrow([(800, 922), (918, 922), (918, 750), (800, 750)], color=LOOP, dash=True)
rotated_label(926, 836, "提示")

# legend
_seg((20, 1058), (980, 1058), "#D5DCE6", 1.2)
text(26, 1066, "实线 = 主流程；虚线回流：① 校验失败 → 修正后重传（新批次） ② 可重试错误 → 回 pending，超限 failed → 人工重放 ③ 关组后新评论只提示、不进确认数。", 10.2, True, "#1F4E79")
text(26, 1090, "失败不伪造结果：AI 不可用时 Job=failed、comments.analysis_status=failed，页面可见并可重放。", 10.2)

os.makedirs("assets", exist_ok=True)
out = r"assets\fig1_end_to_end_flow.png"
img.save(out)
print("saved", out, img.size)



