"""Draws the example mods' card art (pixel art, PNG) and puts it in their packages.

    python tools/example_art.py          # rewrites balatro/mods/examples/fruit_stand.json's assets

Each image is one card at the game's 2x size (142x190): a frame like the
game's jokers, a coloured panel and a fruit drawn from a small pixel map.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

W, H = 71, 95
EXAMPLES = Path(__file__).resolve().parent.parent / "balatro" / "mods" / "examples"

Colour = tuple[int, int, int, int]


def hexc(s: str, a: int = 255) -> Colour:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), a


def png(pixels: list[list[Colour]]) -> bytes:
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *p) for p in row) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def card(panel: str, fruit: list[str], palette: dict[str, str]) -> bytes:
    clear: Colour = (0, 0, 0, 0)
    px = [[clear] * W for _ in range(H)]
    outline, paper, shade = hexc("#3a3a4a"), hexc("#f1ecdd"), hexc("#d6cfbb")
    r = 5
    for y in range(H):
        for x in range(W):
            dx = max(r - x, 0, x - (W - 1 - r))
            dy = max(r - y, 0, y - (H - 1 - r))
            if dx * dx + dy * dy > r * r:
                continue
            edge = dx * dx + dy * dy > (r - 1) * (r - 1) or x in (0, W - 1) or y in (0, H - 1)
            px[y][x] = outline if edge else (shade if y > H - 4 else paper)
    # the panel
    pc = hexc(panel)
    dark = tuple(max(0, c - 40) for c in pc[:3]) + (255,)
    for y in range(6, H - 6):
        for x in range(5, W - 5):
            px[y][x] = dark if (x in (5, W - 6) or y in (6, H - 7)) else pc
    # stripes, as the game's jokers have a patterned background
    for y in range(7, H - 7):
        for x in range(6, W - 6):
            if (x + y) % 9 == 0:
                px[y][x] = tuple(min(255, c + 14) for c in pc[:3]) + (255,)
    # the fruit, scaled 2x from its map and centred
    fh, fw = len(fruit), max(len(row) for row in fruit)
    s = 3
    ox, oy = (W - fw * s) // 2, (H - fh * s) // 2
    for j, row in enumerate(fruit):
        for i, ch in enumerate(row):
            if ch in palette:
                c = hexc(palette[ch])
                for yy in range(s):
                    for xx in range(s):
                        px[oy + j * s + yy][ox + i * s + xx] = c
    big = [[px[y // 2][x // 2] for x in range(W * 2)] for y in range(H * 2)]
    return png(big)


CHERRY = [
    "..........g.....",
    ".........gg.....",
    "........g.g.....",
    ".......g...g....",
    "......g.....g...",
    ".....g.......g..",
    "..rrr.......rrr.",
    ".rRrrr.....rRrrr",
    ".rRrrr.....rRrrr",
    ".rrrrr.....rrrrr",
    ".rrrrk.....rrrrk",
    "..rkk.......rkk.",
]
BANANA = [
    "............bb..",
    "...........yb...",
    "..........yyy...",
    ".........yyYy...",
    "........yyYy....",
    "......yyyYy.....",
    "...yyyyyYy......",
    ".yyyyyyYy.......",
    "yYYYYYy.........",
    ".yyyy...........",
]
APPLE = [
    ".......b........",
    "......b..ll.....",
    "...rrrbrlllr....",
    "..rRrrrrrrrrr...",
    ".rRRrrrrrrrrrr..",
    ".rRrrrrrrrrrrr..",
    ".rrrrrrrrrrrrr..",
    ".rrrrrrrrrrrrk..",
    "..rrrrrrrrrrk...",
    "...rrrkkrrrk....",
    "....kk..kk......",
]
SALAD = [
    ".....r.....y....",
    "....rrr...yyy...",
    "..g.rrr.o.yyy...",
    ".ggg.r.ooo.y.p..",
    "..g....ooo..ppp.",
    "wwwwwwwwwwwwwwww",
    "wWWWWWWWWWWWWWWw",
    ".wWWWWWWWWWWWWw.",
    "..wWWWWWWWWWWw..",
    "...wwwwwwwwww...",
]
STALL = [
    "rrwwrrwwrrwwrrww",
    "rrwwrrwwrrwwrrww",
    ".bbbbbbbbbbbbbb.",
    ".b............b.",
    ".b.r.y.o.g.p..b.",
    ".b.rr.yy.oo.gg.b",
    ".bbbbbbbbbbbbbb.",
    ".b............b.",
    ".b............b.",
]
SEEDS = [
    "....gg..........",
    "...gGgg.........",
    "....gg.g........",
    "......g.........",
    "...bbbbbbbbb....",
    "...bkkkkkkkb....",
    "...bk.s.s.kb....",
    "...bk..s..kb....",
    "...bk.s.s.kb....",
    "...bkkkkkkkb....",
    "...bbbbbbbbb....",
]

PAL = {"g": "#3f8a3a", "G": "#6cc35f", "l": "#4fae3f", "r": "#d8352f", "R": "#ff8a7a", "k": "#8e1f1c",
       "y": "#f2c230", "Y": "#fff07a", "b": "#7a4a22", "o": "#f08a24", "p": "#8a4fc8", "w": "#c9b48a",
       "W": "#efe2c0", "s": "#5a3a1a"}

ART = {
    "cherry_seven": ("#5b8bd1", CHERRY),
    "banana_bunch": ("#3d9a8b", BANANA),
    "orchard": ("#88a84a", APPLE),
    "fruit_salad": ("#c86a8a", SALAD),
    "market_stall": ("#c99a3a", STALL),
    "seed_packet": ("#7a6ab8", SEEDS),
}


def main() -> None:
    path = EXAMPLES / "fruit_stand.json"
    pkg = json.loads(path.read_text())
    pkg["assets"] = {name: "data:image/png;base64," + base64.b64encode(card(panel, fruit, PAL)).decode()
                     for name, (panel, fruit) in ART.items()}
    path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n")
    print(f"{path}: {len(pkg['assets'])} images")


if __name__ == "__main__":
    main()
