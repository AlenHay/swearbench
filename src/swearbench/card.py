"""Leaderboard card, styled to match chart.svg. Model names and numbers only; never quotes."""
from __future__ import annotations

from html import escape

from .chart import FAMILIES, PAD, STYLE, _text_w, family, pretty

MODE_LABEL = {
    "fabrication": "lies", "overreach": "overreach", "giving_up": "gave up", "regression": "breaks things",
    "ignored": "ignores me", "repeat": "repeats", "incomplete": "half-done", "insult": "insults",
    "profanity": "swearing", "shouting": "CAPS", "sarcasm": "sarcasm", "slow": "slow",
}

W = 760
TOP = 120
ROW_H = 40
RANK_END = PAD + 16
NAME_X = RANK_END + 14
BAR_X = NAME_X + 160
BAR_W = 180
SCORE_END = BAR_X + BAR_W + 40
STATS_X = SCORE_END + 24


def svg(res, rows=8):
    board = res["board"][:rows]
    h = TOP + ROW_H * max(len(board), 1) + PAD + 20
    hi = max([s["score"] for s in board] + [1])
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" class="c" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
         'role="img" aria-label="SwearBench leaderboard">',
         f"<style>{STYLE}</style>",
         f'<rect width="{W}" height="{h}" rx="14" fill="var(--surface)"/>',
         f'<text x="{PAD}" y="{PAD + 18}" font-size="20" font-weight="700" fill="var(--ink)">SwearBench</text>']

    lx, ly = PAD, PAD + 52
    for i, (name, _) in enumerate(FAMILIES):
        o.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="var(--s{i + 1})"/>'
                 f'<text x="{lx + 15}" y="{ly}" font-size="12" fill="var(--ink2)">{name}</text>')
        lx += 15 + _text_w(name) + 24
    o.append(f'<text x="{W - PAD}" y="{ly}" font-size="12" fill="var(--muted)" text-anchor="end">'
             f'{res["n_reactions"]} reactions</text>')

    for i, s in enumerate(board):
        y = TOP + i * ROW_H
        mid = y + ROW_H / 2
        base = mid + 4.5
        col = f"var(--s{family(s['model']) + 1})"
        top_mode = max(s["modes"], key=s["modes"].get) if s["modes"] else None
        o += [f'<line x1="{PAD}" x2="{W - PAD}" y1="{y}" y2="{y}" stroke="var(--grid)" stroke-width="1"/>',
              f'<text x="{RANK_END}" y="{base}" font-size="12" fill="var(--muted)" text-anchor="end">{i + 1}</text>',
              f'<text x="{NAME_X}" y="{base}" font-size="13" font-weight="600" fill="var(--ink)">'
              f'{escape(pretty(s["model"]))}</text>',
              f'<rect x="{BAR_X}" y="{mid - 3}" width="{BAR_W}" height="6" rx="3" fill="var(--grid)"/>',
              f'<rect x="{BAR_X}" y="{mid - 3}" width="{max(6, BAR_W * max(s["score"], 0) / hi):.0f}" height="6" '
              f'rx="3" fill="{col}"/>',
              f'<text x="{SCORE_END}" y="{base}" font-size="13" font-weight="700" fill="var(--ink)" '
              f'text-anchor="end" font-variant-numeric="tabular-nums">{s["score"]:.0f}</text>',
              f'<text x="{STATS_X}" y="{base}" font-size="12" fill="var(--ink2)">'
              f'ships {s["outcome"]:.0f}% · {s["angry_pct"]:.0f}% angry</text>',
              f'<text x="{W - PAD}" y="{base}" font-size="12" fill="var(--muted)" text-anchor="end">'
              f'{MODE_LABEL.get(top_mode, "")}</text>']
    end = TOP + ROW_H * len(board)
    o.append(f'<line x1="{PAD}" x2="{W - PAD}" y1="{end}" y2="{end}" stroke="var(--axis)" stroke-width="1"/>')
    o.append(f'<text x="{PAD}" y="{h - PAD}" font-size="11" fill="var(--muted)">github.com/AlenHay/swearbench</text>')
    o.append("</svg>")
    return "\n".join(o)
