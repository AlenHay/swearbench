"""Shareable SVG card. Model names and numbers only; never quotes."""
from __future__ import annotations

from html import escape


MODE_LABEL = {
    "fabrication": "lies", "overreach": "overreach", "giving_up": "gave up on it", "regression": "breaks things",
    "ignored": "ignores me", "repeat": "makes me repeat", "incomplete": "half-done", "insult": "insults",
    "profanity": "swearing", "shouting": "CAPS", "sarcasm": "sarcasm", "slow": "slow",
}


def svg(res, rows=8):
    board = res["board"][:rows]
    w, row_h, top = 640, 44, 92
    h = top + row_h * max(len(board), 1) + 48
    lo = min([s["score"] for s in board] + [0])
    hi = max([s["score"] for s in board] + [1])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           'font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif">',
           f'<rect width="{w}" height="{h}" rx="14" fill="#0d1117"/>',
           '<text x="28" y="44" font-size="24" font-weight="700" fill="#f0f6fc">SwearBench</text>',
           f'<text x="28" y="68" font-size="13" fill="#8b949e">which AI made me swear the least · '
           f'{res["n_reactions"]} reactions</text>']
    for i, s in enumerate(board):
        y = top + i * row_h
        frac = (s["score"] - lo) / ((hi - lo) or 1)
        top_mode = max(s["modes"], key=s["modes"].get) if s["modes"] else None
        color = "#3fb950" if i == 0 else "#f85149" if i == len(board) - 1 and len(board) > 1 else "#58a6ff"
        out += [f'<text x="28" y="{y + 18}" font-size="14" fill="#8b949e">{i + 1}</text>',
                f'<text x="52" y="{y + 18}" font-size="15" font-weight="600" fill="#f0f6fc">{escape(s["model"])}</text>',
                f'<rect x="52" y="{y + 26}" width="300" height="6" rx="3" fill="#21262d"/>',
                f'<rect x="52" y="{y + 26}" width="{max(6, 300 * frac):.0f}" height="6" rx="3" fill="{color}"/>',
                f'<text x="372" y="{y + 20}" font-size="15" font-weight="700" fill="{color}">{s["score"]:.0f}</text>',
                f'<text x="420" y="{y + 14}" font-size="12" fill="#c9d1d9">{s["angry_pct"]:.0f}% angry · {s["swears100"]:.0f} swears/100</text>',
                f'<text x="420" y="{y + 30}" font-size="12" fill="#8b949e">mostly: {MODE_LABEL.get(top_mode, "—")}</text>']
    out.append(f'<text x="28" y="{h - 18}" font-size="11" fill="#6e7681">github.com/AlenHay/swearbench · '
               'higher = fewer reasons to swear</text></svg>')
    return "\n".join(out)
