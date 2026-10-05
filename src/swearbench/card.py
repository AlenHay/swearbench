"""Shareable SVG card. Model names and numbers only; never quotes."""
from __future__ import annotations

from html import escape

from .chart import pretty


MODE_LABEL = {
    "fabrication": "lies", "overreach": "overreach", "giving_up": "gave up", "regression": "breaks things",
    "ignored": "ignores me", "repeat": "repeats", "incomplete": "half-done", "insult": "insults",
    "profanity": "swearing", "shouting": "CAPS", "sarcasm": "sarcasm", "slow": "slow",
}


PAD = 28
RANK_END = PAD + 12
NAME_X = RANK_END + 14
BAR_W = 280
SCORE_END = NAME_X + BAR_W + 48
STATS_X = SCORE_END + 24
STATS_W = 164
W = STATS_X + STATS_W + PAD
ROW_H = 48
TOP = 96


def svg(res, rows=8):
    board = res["board"][:rows]
    h = TOP + ROW_H * max(len(board), 1) + 36
    lo = min([s["score"] for s in board] + [0])
    hi = max([s["score"] for s in board] + [1])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
           'font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif">',
           f'<rect width="{W}" height="{h}" rx="14" fill="#0d1117"/>',
           f'<text x="{PAD}" y="46" font-size="24" font-weight="700" fill="#f0f6fc">SwearBench</text>',
           f'<text x="{PAD}" y="70" font-size="13" fill="#8b949e">{res["n_reactions"]} reactions</text>']
    for i, s in enumerate(board):
        y = TOP + i * ROW_H
        text_y, bar_y, sub_y = y + 14, y + 24, y + 32
        frac = (s["score"] - lo) / ((hi - lo) or 1)
        top_mode = max(s["modes"], key=s["modes"].get) if s["modes"] else None
        color = "#3fb950" if i == 0 else "#f85149" if i == len(board) - 1 and len(board) > 1 else "#58a6ff"
        out += [f'<text x="{RANK_END}" y="{text_y}" font-size="14" fill="#8b949e" text-anchor="end">{i + 1}</text>',
                f'<text x="{NAME_X}" y="{text_y}" font-size="15" font-weight="600" fill="#f0f6fc">{escape(pretty(s["model"]))}</text>',
                f'<rect x="{NAME_X}" y="{bar_y}" width="{BAR_W}" height="6" rx="3" fill="#21262d"/>',
                f'<rect x="{NAME_X}" y="{bar_y}" width="{max(6, BAR_W * frac):.0f}" height="6" rx="3" fill="{color}"/>',
                f'<text x="{SCORE_END}" y="{text_y}" font-size="16" font-weight="700" fill="{color}" '
                f'text-anchor="end" font-variant-numeric="tabular-nums">{s["score"]:.0f}</text>',
                f'<text x="{STATS_X}" y="{text_y}" font-size="12" fill="#c9d1d9">ships {s["outcome"]:.0f}% · {s["angry_pct"]:.0f}% angry</text>',
                f'<text x="{STATS_X}" y="{sub_y}" font-size="12" fill="#8b949e">{MODE_LABEL.get(top_mode, "")}</text>']
    out.append(f'<text x="{PAD}" y="{h - 20}" font-size="11" fill="#6e7681">github.com/AlenHay/swearbench</text></svg>')
    return "\n".join(out)
