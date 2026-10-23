"""Restyle presets: redraw the performer and their world in a look, keep the motion.

Each preset is two strings: the instruction Qwen-Edit applies to the clip's
first frame (which becomes the Animate-2 reference), and the look words fed
to Animate-2's appearance prompt so every later frame stays in that look.

Wording rules (measured with Qwen-Edit): name the look, not what to keep;
one short anti-escape clause ("same pose, same camera") is the only
preservation phrase that helps.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    edit: str  # what Qwen-Edit is told to draw
    look: str  # what Animate-2 is told every frame looks like


STYLES: dict[str, Style] = {s.key: s for s in [
    # Clay was removed 2026-10-20: it invented a prop near fast limb motion in two wordings
    # (bench/RESULTS.md, t5/t6). Revisit later.
    Style("wool", "Knitted Wool",
          "a world knitted from chunky wool yarn: the character and every object made of knitted stitches "
          "and felt, cosy soft light",
          "knitted chunky wool yarn and felt, visible stitches, cosy soft light"),
    Style("anime", "Anime Cel",
          "a hand-drawn anime cel frame: clean ink outlines, flat cel shading, painted background",
          "hand-drawn anime cel animation, clean ink lines, flat cel shading, painted background"),
    Style("toy", "Toy Figure 3D",
          "a glossy 3D toy world: the character as a smooth vinyl collectible figure with rounded "
          "proportions, the room as a bright plastic playset",
          "glossy 3D vinyl toy figure, rounded proportions, bright plastic playset, soft studio light"),
    Style("pixel", "Pixel Art",
          "detailed 16-bit pixel art: crisp square pixels, limited palette, retro game lighting",
          "16-bit pixel art, crisp square pixels, limited retro palette"),
    Style("watercolor", "Watercolor",
          "a loose watercolor painting on textured paper: soft washes, bleeding edges, light pencil lines",
          "loose watercolor painting, soft washes, paper texture, light pencil lines"),
    Style("comic", "Comic Ink",
          "a bold comic-book panel: heavy black ink outlines, halftone dot shading, saturated flat colours",
          "comic-book art, heavy black ink outlines, halftone shading, flat saturated colours"),
    Style("lowpoly", "Low-Poly",
          "a chunky low-poly 3D render: flat-shaded triangular facets, simple bold colours",
          "low-poly 3D, flat-shaded triangular facets, simple bold colours"),
    Style("paper", "Paper Cutout",
          "a layered paper-cutout diorama: the character and scene cut from coloured card with soft "
          "drop shadows between layers",
          "layered coloured paper cutout, card textures, soft shadows between layers"),
    Style("neon", "Neon Night",
          "a neon cyberpunk night: the character in glowing synthwave colours, wet reflective floor, "
          "magenta and cyan rim light",
          "neon cyberpunk night, glowing magenta and cyan rim light, wet reflections"),
]}


def get(key: str) -> Style:
    try:
        return STYLES[key]
    except KeyError:
        raise ValueError(f"unknown style {key!r}; choose from {sorted(STYLES)}") from None
