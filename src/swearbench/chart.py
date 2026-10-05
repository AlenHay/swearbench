"""Swearing vs. result: one dot per model. x = rage per 100 turns, y = share of sessions that land."""
from __future__ import annotations

import math
import re
from html import escape

FAMILIES = [("Claude", ("claude",)), ("GPT", ("gpt", "o1", "o3", "o4", "codex")), ("Other", ())]

STYLE = """
.c{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a}
@media (prefers-color-scheme:dark){.c{--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--s1:#3987e5;--s2:#d95926;--s3:#199e70}}
text{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
"""


def pretty(model):
    """claude-opus-5-5 -> Opus 5.5, gpt-5.6-sol -> GPT-5.6 Sol, gemini-3.8-flash-high -> Gemini 3.8 Flash."""
    m = re.sub(r"-\d{8}$", "", model.split("/")[-1])
    if m.startswith("claude-"):
        parts = m[7:].split("-")
        return f"{parts[0].title()} {'.'.join(parts[1:])}"
    if m.startswith("gpt-"):
        ver, *rest = m[4:].split("-")
        return " ".join([f"GPT-{ver}"] + [r.title() for r in rest])
    words = [w for w in m.split("-") if w not in ("high", "low", "medium", "free", "preview")]
    return " ".join(w if any(c.isdigit() for c in w) else w.title() for w in words)


def family(model):
    for i, (_, prefixes) in enumerate(FAMILIES[:-1]):
        if model.startswith(prefixes):
            return i
    return len(FAMILIES) - 1


def _ticks(lo, hi, n=5):
    step = 10 ** math.floor(math.log10((hi - lo) / n or 1))
    for m in (1, 2, 2.5, 5, 10):
        if (hi - lo) / (step * m) <= n:
            step *= m
            break
    start = math.floor(lo / step) * step
    return [start + i * step for i in range(int((hi - start) / step) + 2) if start + i * step <= hi + 1e-9]


PAD = 32


def _text_w(text, size=12):
    return len(text) * size * 0.56


def svg(res):
    pts = res["board"]
    W, H = 760, 540
    L, R, T, B = PAD + 48, PAD, 120, 76
    pw, ph = W - L - R, H - T - B
    xs = [p["rage100"] for p in pts] or [0, 1]
    x_lo, x_hi = math.floor(min(xs) * 0.9 / 10) * 10, math.ceil(max(xs) * 1.05 / 10) * 10
    x_lo, x_hi = (x_lo, x_hi) if x_hi > x_lo else (0, 100)
    X = lambda v: L + (v - x_lo) / (x_hi - x_lo) * pw  # noqa: E731
    Y = lambda v: T + ph - v / 100 * ph  # noqa: E731
    max_n = max([p["sessions"] for p in pts] + [1])

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" class="c" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         'role="img" aria-labelledby="t d">',
         f"<style>{STYLE}</style>",
         '<title id="t">SwearBench: how much swearing gets you what result</title>',
         '<desc id="d">' + escape("; ".join(f'{p["model"]}: rage {p["rage100"]:.0f} per 100 turns, '
                                            f'{p["outcome"]:.0f}% of sessions land' for p in pts)) + "</desc>",
         f'<rect width="{W}" height="{H}" rx="14" fill="var(--surface)"/>',
         f'<text x="{PAD}" y="{PAD + 18}" font-size="20" font-weight="700" fill="var(--ink)">'
         'Swearing vs. result</text>']

    lx, ly = PAD, PAD + 52
    for i, (name, _) in enumerate(FAMILIES):
        o.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="var(--s{i + 1})"/>'
                 f'<text x="{lx + 15}" y="{ly}" font-size="12" fill="var(--ink2)">{name}</text>')
        lx += 15 + _text_w(name) + 24

    for v in _ticks(x_lo, x_hi):
        o.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + ph}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<text x="{X(v):.1f}" y="{T + ph + 22}" font-size="11" fill="var(--muted)" text-anchor="middle">{v:g}</text>')
    for v in range(0, 101, 20):
        o.append(f'<line x1="{L}" x2="{L + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<text x="{L - 12}" y="{Y(v) + 4:.1f}" font-size="11" fill="var(--muted)" text-anchor="end">{v}%</text>')
    o.append(f'<line x1="{L}" x2="{L + pw}" y1="{T + ph}" y2="{T + ph}" stroke="var(--axis)" stroke-width="1"/>')
    o.append(f'<text x="{L + pw / 2}" y="{H - PAD}" font-size="12" fill="var(--ink2)" text-anchor="middle">'
             'Swearing →</text>')
    o.append(f'<text transform="translate({PAD + 4} {T + ph / 2}) rotate(-90)" font-size="12" fill="var(--ink2)" '
             'text-anchor="middle">Shipped →</text>')

    dots = []
    for p in sorted(pts, key=lambda p: -p["sessions"]):
        cx, cy = X(p["rage100"]), Y(p["outcome"])
        r = 5 + 9 * math.sqrt(p["sessions"] / max_n)
        col = f"var(--s{family(p['model']) + 1})"
        lo, hi = p.get("outcome_ci", (p["outcome"], p["outcome"]))
        tip = escape(f'{p["model"]}\nrage {p["rage100"]:.0f}/100 turns · {p["angry_pct"]:.0f}% angry msgs\n'
                     f'{p["outcome"]:.0f}% of {p["sessions"]} sessions land (90% CI {lo:.0f}–{hi:.0f}%)\n'
                     f'SwearBench {p["score"]:.1f}')
        o.append(f'<g><title>{tip}</title>'
                 f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{Y(hi):.1f}" y2="{Y(lo):.1f}" stroke="{col}" stroke-width="2" '
                 'stroke-opacity="0.45" stroke-linecap="round"/>'
                 f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r + 8:.1f}" fill="transparent"/>'
                 f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{col}" stroke="var(--surface)" stroke-width="2"/></g>')
        dots.append((p, cx, cy, r))

    boxes = [(cx - r, cy - r, cx + r, cy + r) for _, cx, cy, r in dots]
    for p, cx, cy, r in dots:
        label = pretty(p["model"])
        w = _text_w(label)
        best = None
        for dy in (0, -18, 18, -32, 32, -46, 46):
            for side in (1, -1):
                x0 = cx + r + 8 if side > 0 else cx - r - 8 - w
                y = cy + 4 + dy
                box = (x0, y - 11, x0 + w, y + 3)
                if not (L + 2 <= box[0] and box[2] <= L + pw - 2 and T + 28 <= box[1] and box[3] <= T + ph - 20):
                    continue
                overlap = sum(max(0, min(box[2], b[2]) - max(box[0], b[0])) * max(0, min(box[3], b[3]) - max(box[1], b[1]))
                              for b in boxes)
                if best is None or overlap < best[0]:
                    best = (overlap, x0, y, box)
            if best and best[0] == 0:
                break
        _, x0, y, box = best or (0, cx + r + 6, cy + 4, (cx + r + 6, cy - 7, cx + r + 6 + w, cy + 7))
        boxes.append(box)
        o.append(f'<text x="{x0:.1f}" y="{y:.1f}" font-size="12" fill="var(--ink)">{escape(label)}</text>')
    o.append("</svg>")
    return "\n".join(o)
