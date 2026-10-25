# API workflows

The graphs the app runs, in ComfyUI's API format, written by `tools/export_workflows.py` from the same code
the server builds them with (`recast/`). The input file names are examples: put your own files in ComfyUI's
`input/` folder under those names, or change the names in the graph. Every job the app runs also saves the
exact graph it ran, with its own file names and seed, in its `recipe.json`.

ComfyUI's editor opens API-format files as graphs: drag one onto the canvas. (Checked by loading
`recast_one_clip_place.json` into ComfyUI v0.41.3: all 30 nodes and their links.)

The models and custom nodes they need are listed, with sources and hashes, in
[`manifests/models.json`](../../manifests/models.json).

| Workflow | What it does |
|---|---|
| [`recast_one_clip_place.json`](recast_one_clip_place.json) | Recast, one chosen performer, in the clip's own place, 5 s (one chunk). Inputs: `drive.mp4` (the clip, 16 fps, 576x1024), `reference.png` (the character cut out of their photo and placed where the performer stands), `pick0.png` (the performer's mask in the first frame, white on black). Putting everyone who was not chosen back as filmed is a step after this graph (recast/composite.py). |
| [`recast_duo_clip_place_10s.json`](recast_duo_clip_place_10s.json) | Recast, two chosen performers, in the clip's own place, 10 s: two chunks (9.8 s), the second anchored on the first's last 5 frames. Inputs as above, with `pick0.png` and `pick1.png`, left to right. |
| [`recast_7s_short_last_chunk.json`](recast_7s_short_last_chunk.json) | Recast, 7 s: a whole chunk and a short last one (81 + 37 frames), so only what is asked is rendered. |
| [`recast_another_place.json`](recast_another_place.json) | Recast into another place: SCAIL-2 animates `reference.png`, a start picture of the character already in the new place (made with `start_picture_another_place.json`). The performer is found by words. |
| [`restyle.json`](restyle.json) | Restyle, 5 s: Wan2.1 VACE redraws every frame from its depth map, in the look of `reference.png` (the first frame restyled, made with `start_picture_restyle.json`). |
| [`start_picture_another_place.json`](start_picture_another_place.json) | Qwen-Image-Edit-2511: the character from `character.png` in the place described, posed like the clip. |
| [`start_picture_restyle.json`](start_picture_restyle.json) | Qwen-Image-Edit-2511: the clip's first frame `frame.png`, redrawn in a look. |
| [`restage_outfit.json`](restage_outfit.json) | Restage, new outfit: the performer's first frame `frame.png` in the garment from `outfit.png`. The video is then a Recast of the performer as themselves, with this picture as the reference. |
| [`find_people.json`](find_people.json) | SAM 3.1 finds everyone in `frame.png`, one mask each: the picker the visitor taps. |
| [`describe_character.json`](describe_character.json) | Qwen3-VL writes a character's words from `character.png`. |
