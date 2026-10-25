# Measured results

Every claim in the README traces to a row here. Timings come from `bench/log.tsv` (one row was hand-corrected and is annotated there), written by
`tools/gpu_bench.sh`. Hardware: RTX 4070 Ti SUPER 16 GB, 32 GB RAM, ComfyUI 0.41.3, executed through
comfy-sdk 0.5.0 → comfy-api-proxy 0.1.6.

Test clips used so far are **private test material**. They are not redistributable, so no frames
or outputs from them are published. Public examples will come only from cleared clips, with
provenance listed in `examples/`.

- **Clip A:** a single animal performer on a static camera, full body, 5 s used.
- **Clip B:** a single human performer, waist-up, with changing coloured stage light.
- **Clip C:** two animal performers side by side at a table (a dog on the left, a cat on the right),
  static camera, with black bars baked into the frame.

## Animate-2 recast (1 segment = 81 frames, 480×832, 16 fps, 10 steps)

| Run | Reference | Wall time | Peak VRAM | Finding |
|---|---|---:|---:|---|
| t1 | matched to the first frame (pose, framing, room) | 552 s | 15,776 MB | Full body kept, pose tracked through arms-up and turn, stable background |
| t4 | same as t1, second seed | 474 s | 15,128 MB | Same framing as t1; motion blur on the fast spin in both seeds |
| t2 | character image used as-is (seated, close framing) | 620 s | 14,584 MB | Inherits the reference's framing: subject too large, grows toward camera, cropped by the end; background from the reference, not the clip |
| t3 | auto-matched (v1 prompt) | 593 s | 14,680 MB | Room carried from the clip ✓, identity from the character ✓, **pose copied from the character image ✗** |

**Conclusion so far:** the reference's agreement with the first frame decides output framing.
Matching it automatically is the product's core job.

## Reference matching (Qwen-Image-Edit-2511, first frame = image 1, character = image 2)

| Variant | Result |
|---|---|
| v1 prompt, "same pose, same camera" | pose taken from the character image |
| v2 prompt, "pose, size and position from the first picture; second picture only for its look", 4-step | still the character image's pose |
| v2 prompt, 20 steps / cfg 3 | still the character image's pose |
| A. v2 + explicit pose words ("stands upright on its hind legs, front paws at its chest"), 4-step | **upright, source size ✓** |
| B. v2, denoise 0.88, 4-step | still the character image's pose ✗ |
| C. v2, character image cropped to head and shoulders, 4-step | **upright, source size, identity kept ✓** |

Finding: **with Qwen-Image-Edit-2511, a full-body character image's pose beats an abstract
instruction ("take the first picture's pose").** It loses to either a *concrete* pose description
(A) or to removing the body from the character image (C). C needs no description of the clip,
so it is the candidate default. A needs the first frame's pose put into words automatically
(e.g. from detected keypoints).

## Restyle (style only, no character; Clip A)

| Run | Style | Render | Finding |
|---|---|---:|---|
| t5_restyle_anime | Anime Cel | 553 s | Clean ink lines and cel shading hold on every sampled frame; pose tracked through arms-up and turn; room restyled consistently. Demo-grade |
| t5_restyle_clay | Clay Stop-Motion (v1 wording) | 785 s | Look reads as smooth clay; **an invented green hand-held object enters bottom-left in frames ~20-40 (absent from the source)** |
| t6_restyle_clay_v2 | Clay, reworded to materials only | 569 s | Bottle gone, but **an invented pompom-like object appears at the same spot and time** (frames ~15-35), where the paw kicks. The source corner is empty |

Finding: restyle works through Animate-2 (anime clean). The clay look **invents a small prop near fast limb motion in both wordings**, so the wording was not the cause (an earlier note here said it was; corrected). **Clay is removed from the style list for now** (decision 2026-10-20); the open question stays here.

## Human performer (Clip B: waist-up, changing coloured stage light)

| Run | Change | Render | Finding |
|---|---|---:|---|
| h1b | Anime Cel restyle | 687 s | Clean ink-and-cel look on every sampled frame; hand-to-head, arm raise and back arch all tracked; the shifting stage light became a consistent painted light-ray backdrop |
| h2b | Toy Figure 3D restyle | 538 s | Glossy vinyl figure in an invented toy-room set; pose tracked through the back arch; set stays consistent |
| h3b | Character: white cat (head-only crop, fix C) | 543 s | Cross-species works: the cat raises a paw and arches, following the arm raise and back arch. **The reference was drawn full-body although the clip is waist-up**, because the prompt says "whole body in frame". That clause must follow the clip's framing |

Finding: both restyles and the cross-species recast work on a human clip under hard, changing light.

## Multiple references (Clip B first frame; references generated with Qwen-Image; `bench/experiments/multiref.py`)

Animate-2 takes one reference still, so references are merged into it with Qwen-Edit, which has three
image slots (first frame + two). Character = head-and-shoulders portrait, outfit = red jacket,
product = green bottle. 4-step, seed 1.

| Variant | Jacket | Bottle | Pose kept | Note |
|---|---|---|---|---|
| V1 frame + character + jacket | ✓ details kept | — | ✓ | baseline |
| **V2 frame + character + board(jacket \| bottle)** | ✓ | ✓ held, label kept | ✓ | **best: 3 references, one pass** |
| V3 two passes (V1, then + bottle) | ✓ | ✓ | ✓ | same result, double time, extra edit hop |
| V4 frame + board(character \| jacket \| bottle) | ✓ | ✓ | ✗ head turns to camera | face closer to the portrait, pose lost |

Finding: give the character its own slot and put the extras on one labelled board. Board capacity beyond
two items is still to be measured.

**Through Animate-2** (`mr_v2_render`: V2 reference, Clip B, 460 s, 13,720 MB): the jacket holds on every
sampled frame (zips, colour, fit) and identity stays consistent. **The held bottle is lost once its hand
leaves the frame** (present at frames 0 and 16, gone from 32 on, never returns). It vanishes rather than
morphing. Product rule: worn items (outfit, hat, glasses) are reliable; held props only when the holding
hand stays in shot. The UI says so at upload.

**Cause, found by review:** the V2 reference put the bottle in a raised hand at chest height, a pose the
performer never makes; her real arm hangs down and leaves the frame. Placement must follow the
performer's actual hand:

| Variant | Bottle placement | Rest of pose | Note |
|---|---|---|---|
| V5: "that hand at the hip holds the bottle" + abstract "take her pose" | ✓ low by the thigh | ✗ stands straight, faces camera | the hand instruction pushed out the abstract pose instruction |
| V5b: whole pose spelled out concretely (frame-relative) + low-hand bottle | ✓ | ✓ hand on head, head back, leaning | concrete pose words again beat abstract ones (cf. fix A) |

**Through Animate-2** (`mr_v5b_render`, 413 s, 13,592 MB): the bottle is visible in 5 of 6 sampled
frames (0, 16, 32, 48, 80; 2 of 6 for V2), and it **returns** after its hand dips out of shot around
frame 64. Jacket and identity hold. Minor: a small invented grey ledge at the bottom-left in a few frames.

Product implication: prop placement needs the first frame's pose **in words**. That means a pose
description generated from detected keypoints, which also makes fix A automatic.

## Swap: one thing changes, the performer stays (Clip B; through the app)

| Swap | Result |
|---|---|
| Outfit: red leather jacket, pose words read automatically | **jacket fitted and detailed, pose and stage light exactly kept** |
| Product: green bottle, "in one hand" (no side known) | bottle clear, but the edit **re-posed her**: the hand on her head moved to the other arm |
| Product: side asked of the vision model | the model answered body-relative (mirrored: it called the raised arm the one on the picture's right). Sides now come from MediaPipe Pose keypoints (`recast/pose.py`) |
| Product: both arms named by picture side, from keypoints | **pose exactly kept, bottle in the free hand at the hip**. The words "beside the thigh" bared a thigh, so they now read "hanging down at the side" |

Also found: a re-run with changed words but the same seed reattached to the earlier job and showed
its old image. Submissions are now keyed by the graph's content, in the app and the CLI.

## Two performers (Clip C; `bench/experiments/duo.py`)

Each animal is replaced by its own character: the man (character 1) for the performer on the
picture's left, the woman (character 2) for the one on its right. Both character images were
cropped to head and shoulders (fix C), and each performer's pose was written out by picture side
(fix A). Directions in the prompt refer to the picture, never to a performer's own left or right.

| Step | Result |
|---|---|
| Reference, seed 1 (4-step) | **both identities correct, each in its animal's place and pose; the clip's studio, keyboard and laptop kept** |
| Reference, seed 2 (4-step) | both people correct, but character 1's own background (a TV studio) leaked in |
| Render of seed 1, 5 s (389 s, 13,944 MB) | the two stay distinct on every sampled frame, with no identity swap or merge. Head turns, the lean in and the hand on the keyboard all follow; character 2's hand raise is smaller than the cat's paw raise |
| Through the app: automatic head crops (`recast/crop.py`), **no pose words**, seed 1 | both identities and the clip's studio kept, but the poses weaken: both stand facing the camera, and only the left character's hand stays on the keyboard. **Pose words carry the duo's pose** |
| Through the app with **pose words read automatically** from the first frame (`recast/describe.py`, Qwen3-VL-8B via core TextGenerate, about 1 min) | read as "dog on the left: leans forward, head down, both hands on the keyboard; cat on the right: sits upright, one hand raised near the laptop". The reference matches the hand-written-pose version: the left character leans over the keyboard with both hands on it, and the right one raises a hand with the other on the laptop. **Fix A is now automatic** |

Finding: **two performers work with the open stack**: three Qwen-Edit image slots (frame, plus one per
character) and one Animate-2 reference that holds both. A seed can still leak a character
image's background, so the free re-roll before rendering is part of the method. Three or more
performers would need a shared reference board and are untested.

## Robustness fixes found by the runs

- **Silent clips failed** (first Clip B runs): VideoHelperSuite's loader errors when a clip has no
  audio stream. `media.normalize` now gives every clip an audio track (digital silence if needed).
- **Uploads collided by name**: every run uploaded `drive.mp4`, and ComfyUI renamed the duplicates.
  Inputs are now named by content hash.
- **Failed jobs were swallowed**: the CLI showed only "ended failed". `RenderFailed` now carries the
  server's one-line reason, and a re-run after a failure resubmits instead of reattaching to the
  dead job.
- **Baked-in black bars** (Clip C): a letterboxed clip passed its bars into the reference, and the
  "portrait" shape was the frame's, not the picture's. `media.content_box` now finds the picture
  (cropdetect, with a box that only grows across sampled frames), and the clip is cropped to it
  before anything else.

## Integration notes

- comfy-sdk 0.5.0 sends job `metadata` as a map, while comfy-api-proxy 0.1.6 accepts only a string and
  rejects the job. We submit without metadata (reported upstream: pending).
- Proxy asset uploads land in ComfyUI's input directory under plain filenames, so
  VideoHelperSuite's loader reads them unchanged.
- `recast/graph.py` reproduces, node for node, a 3-segment graph that rendered successfully before
  this project (`tests/test_graph.py::test_port_matches_a_graph_that_rendered`).

## SCAIL-2: one engine for both places (2026-10-20/21)

Clip C (two animals at a keyboard and a laptop, white studio, a cut at ~3.5 s), two character photos
taken in busy studios, 5 s, 16 fps. Script: `bench/experiments/scail.py`; app: `recast/scail.py`.

| Run | Mode | Size / weights | Time | Peak VRAM | Result |
|---|---|---|---|---|---|
| replace_v1 (Wan2.2-Animate, human clip) | replacement | 480x832 Q3 | 565 s | 13.8 GB | room kept; DWPose needs a human body, so animals can't drive it |
| scail_v1 | replacement | 640 Q4_K_M | 851 s | 11.9 GB | both characters in the clip's room, props kept, nothing from their photos; left→right matching right; motion follows by meaning, across the cut |
| scail_v2 | replacement | 704 Q6_K | 681 s | 11.5 GB | near-identical to v1 (same seed); slightly sharper logos. Size and quant are not the identity lever |
| scail_anim_b | animation | 640 Q4_K_M | 497 s | 10.8 GB | both characters in the left character's studio (start still), same performance |

- **Start still for another place (duo):** without a one-scene opening sentence, Qwen-Image-Edit returned a
  split-screen diptych (one panel per character picture) twice in two tries. Opening with "One single
  photograph of one continuous scene…" fixed it on the next two tries.
- **Props:** carrying the clip's objects into another place works when named as words, but was rejected as a
  product rule: another place keeps its own things. The clip reader now also writes `body`, the pose
  without objects, for that case.
- **Open:** one character's likeness drifts younger in every run, both modes and both sizes; logos turn into
  invented text; the white backdrop renders greyish.

## Restyle by video-to-video (2026-10-21)

A street clip (selfie start, step back, sunglasses taken out at ~3 s and put on, a car driving off at ~1 s),
anime look, 480x832, 16 fps. Animate-2's Restyle animates one restyled first frame. Scripts:
`bench/experiments/vace_restyle.py` (controls), `bench/experiments/vace_chunks.py` (app engine, `recast/vace.py`).

| Run | Control | Speed LoRA | Prompt | Time | Glasses | Car leaves |
|---|---|---|---|---|---|---|
| Animate-2 (app before) | one still | — | look only | ~5 min / 10 s | never | stays parked |
| vace_canny (5 s) | Canny | CausVid 0.3, 4 steps (template) | events named | 307 s | black smear | yes |
| vace_canny_v2 (5 s) | Canny | CausVid 1.0, 6 steps | events named | 239 s | on time, one smudgy frame | yes |
| vace_depth_v2 (5 s) | depth | CausVid 1.0, 6 steps | events named | 205 s | on time, clean | yes |
| vace_10s (2 chunks) | depth | CausVid 1.0, 6 steps | who and where only | 443 s | **never** | yes |
| vace_10s_reader (2 chunks) | depth | lightx2v T2V distill 1.0, 6 steps | clip reader, 4 moments | 583 s | on and off on time | yes |

- **Chunk joins:** anchoring each chunk on the previous chunk's last 9 frames (control mask 0) left no
  visible jump or colour shift at the join.
- **Depth can't see small things against the body.** With a prompt that didn't name them, sunglasses put on
  mid-clip never appeared. The clip reader now reads a 2x2 sheet of four moments and names what a performer
  puts on, takes off or picks up.
- **Background events must not be named.** The reader's first line mentioned a cyclist passing at the very
  end, far away; VACE drew one large in the foreground at 4 s. The reader now leaves background motion out.
- **Licenses:** the template's CausVid 14B LoRA is CC-BY-NC-4.0; replaced by lightx2v's Apache-2.0 T2V
  distill LoRA with no visible loss. Depth Anything V2 Small is Apache-2.0 (Base and Large are not).

## Choosing who is recast, and keeping the clip around them (2026-10-23)

Private regression set, six cases through the app: a dog-and-cat duo recast as two men (clip's place and
the left character's place), a man on a street recast as a woman (clip's place and her own place), a man
running on a football pitch with other players (15 s), and one man chosen out of a crowd of six.

**Words can't pick a performer.** In the crowd, tracking "man" with one object followed a passer-by, then the
man in front; the chosen man got the shirt, his neighbour got the glasses. "man in a grey suit" held the right
man for 10 s, "man in a suit" did not, and the clip reader named a different man on each read. So the visitor
chooses: `recast/people.py` finds everyone in the start frame (SAM3_Detect, prompt `person:8, animal:4`; a
plain prompt returns one detection), and the chosen masks start SAM3's video tracker with no words, tracked
once over the whole clip. All six cases rendered as before or better; the crowd case put the reference on the
chosen man.

**SCAIL-2 redraws the whole frame**, not only the masked performers: the reference's glasses also landed on a
bystander, other players' kit changed colour, a white studio came back grey. `recast/keep.py` +
`recast/composite.py` put the clip back outside the performers:

| Step | Measured |
|---|---|
| Paste the clip back outside the old performers' mask, grown and blurred | bystander's glasses mostly gone; a white studio showed grey dog-and-cat shapes, where only the render's background exists |
| + new characters found in the render (a man is bigger than the cat he replaces) | one point per character gave a part (a bib, a wall strip); three points spread over the body gave the whole person |
| + per-frame colour fit (gain and offset, background pixels only) applied to the whole render | studio white again, but the men washed out |
| + colour fit applied only where old performers stood and new ones don't | studio white, men as rendered |
| + everyone else found in the start frame tracked and kept as filmed (grown 6 px) | the bystander's leaked glasses reduced to a small fragment where his face touches the chosen man |

- **The reader's pose sentence hurts the clip's place.** Same seed, same everything: with "stands facing
  forward, both hands at sides" (wrong: the first frame is a selfie), sunglasses put on mid-clip never
  appeared; without it, they did, on time. The clip's place no longer sends pose words; another place still
  does (they pose its start picture).
- **Another place is worded by the characters, not the performers.** A dog-and-cat clip recast as two men was
  worded "two animals... one paw low in front", and the racer came out on all fours.
- **Open:** small accessories from the reference (glasses) appear in some renders and not others with the
  same inputs; "Try another version" is the remedy for now.

## Put back only the other people, not the room (2026-10-24)

The composite above put the whole clip back outside the performers. On the duo it cost more than it fixed:
a ghost of the dog's outline on the wall where the dog had stood, and a grey ring round both men. The render's
wall is shaded unlike the clip's (darker towards one corner), and one colour fit per frame can't follow it.
A tighter character mask plus a colour offset that varies across the frame (measured on the wall, spread by a
40 px blur) halved both, and the men still looked pasted on: they are lit for the room the model drew.

So the room now stays as rendered, and only the people who aren't recast go back as filmed, colour-matched
to the render. Same four renders in the clip's place, no new render:

| Case | Whole room put back | Only other people put back |
|---|---|---|
| Duo, two men for a dog and a cat | dog's outline on the wall, ring round the men | as rendered: neither (studio a little grey) |
| Street, one person | ring round her | as rendered |
| Football pitch, two players nearby | goalkeeper's kit as filmed | first try: goalkeeper in the render's blue, see below |
| Crowd, one man chosen of six | leaked glasses gone | leaked glasses gone, faces as filmed |

- **People who walk in later are never in the start frame.** The goalkeeper runs into shot mid-clip, so the
  start-frame detector didn't find him and nothing put him back. Everyone is now also tracked through the
  clip by words ("person, animal", looked for on every frame), minus the chosen performers' track grown
  12 px, so no edge of them comes back. With that the goalkeeper's kit is as filmed, and on the duo the
  bystander mask covers 0.03% of the frame (specks): nothing of the dog returns.

## Only the character goes to the model, and words never say what is absent (2026-10-24)

A man on a street puts on sunglasses mid-clip; recast in the clip's place as a racing driver, the driver put
on a helmet at that moment instead. Two inputs said he owns a helmet and no glasses: his photo (a helmet sat
on the desk beside him, and the whole photo was the reference) and his words, written by the vision model:
"... no facial hair, no glasses, wears red, blue, white racing suit with matching helmet". A prompt can't
say what isn't there; "no glasses" only adds the word.

- The character is now cut out of their photo for the clip's place (`people.cut_out`: the biggest person or
  animal SAM3 finds, on the room's own colour, cropped round them). Desk, helmet and the logo wall go.
  Something in front of them (a microphone) left a hole in the mask: gaps under 18% of their width are
  closed and painted in from around them (a soft smudge, invisible in the render).
- `describe.drop_negations` removes "no X", "without X" and "with no X" from the written words and from the
  render prompt; the character instruction now also says never an object beside them.
- Same clip, pick and seed, new words "middle-aged Black man with short dark hair, wearing a red, blue, and
  white racing suit with a V-shaped emblem on the chest": the sunglasses come and go on time, no helmet.

## Swap moved onto SCAIL-2 (2026-10-24)

Swap used to animate one edited still, like the old Restyle, and lost the same things on the street clip:
the sunglasses never appeared, the car stayed parked, the jeans changed with the shirt, and a phone held to
the camera became a glass shard. Swap now runs on SCAIL-2 like Recast.

- **Outfit:** replacement mode in the clip's place; the reference is the performer's own first frame
  with the outfit edited in, and the words are "the same person as in the video, now wearing X, with
  {their lower clothes}". The clip drives every frame.
- **Place:** animation mode with the edited still in the new place.
- What went wrong on the way, and the fix for each:
  - The outfit edit reframed him and invented black trousers. Pose words are no longer sent for an outfit
    swap, and the vision model reads what he wears below the waist from four moments of the clip ("blue
    jeans"); that goes into the edit and the render words.
  - The place swap gave him red trousers: fixed by the same lower-clothes words.
  - The clip reader described a pedestrian in the background. Swap has no picker step, so the performer is
    now chosen automatically: the biggest person for an outfit; for a place, everyone at least a quarter of
    the biggest one's size, up to two.

| Swap (street clip, through the app) | Result |
|---|---|
| Outfit | his jeans kept, sunglasses taken out and put on on time, the car drives off |
| Place: "a snowy mountain road" | same man and shirt, jeans kept, sunglasses taken out and put on on time; render 525 s |

Product in hand was removed: it showed only while its hand stayed in view, and the move above can't keep
an object the clip doesn't have.

## Who becomes whom follows the reference's layout (2026-10-24)

A group of seven in a room; the two in the middle chosen, recast in the clip's place as a man in a hard hat
and a racing driver. SCAIL-2 drew the hard hat on the person at the far left and the racer on the two at
the right, and left the chosen two almost as filmed; putting the bystanders back as filmed then covered the
characters, so the video showed nobody recast. One 5 s chunk per test, same seed:

| Test | Who got the characters |
|---|---|
| Tracking alone (SAM3 track and the coloured masks, saved) | the right two, all 10 s, coloured to match the reference |
| As shipped: the characters side by side on a square sheet, "On the left… On the right…" | the people at the frame's edges |
| Same sheet; "In the middle of the group, on the left/right…", "everyone else stays as in the video" | the people at the frame's edges |
| **Each cut-out placed where its performer stands, on a sheet the clip's shape** | **the chosen two; everyone else as filmed** |

The masks and the words don't decide it; where the characters sit on the reference does. The square sheet
worked on every two-performer clip before because those performers stood left and right. The sheet is now
`scail.placed_sheet` whenever performers are chosen: each cut-out fitted to its performer's box,
top-aligned. Through the app, the same clip and picks: right people, 384 s for 5 s. Re-run on the new
sheet: the dog-and-cat duo is unchanged (378 s), and the one man chosen in a crowd gets the character's
face and glasses, which no longer show up on the man in front of him (398 s).

Also: a character's SAM3 mask carried a loose strip of trousers from the bottom of their photo, which
floated under them on the reference. Pieces under 15% of the biggest part are now dropped.

## The preview is the video's real start (2026-10-24)

In the clip's place the preview used to be the reference itself: the characters cut out of their photos on
a plain colour. It is what SCAIL-2 is given, and it says nothing about how the video will look. The preview
now renders the video's first chunk (5 s) and plays all of it, muted, bystanders kept as filmed like the
render; who replaces whom is shown at once, with the job's progress, while it renders.

- **A short render is not the start of the long one.** Two 17-frame renders (same reference, masks, prompt
  and seed) put the characters right, but leaked a costume's colours onto bystanders, and one drew a white
  object on the table; the full render's first second had neither. A shorter latent draws different noise.
- **The full first chunk is.** The render's first chunk is the same graph, seed and length, so the preview
  matches the video frame for frame (checked on the group clip). A 5 s video is one chunk: its render graph
  is byte-identical to the preview's, so approving delivers the preview's output without the GPU (17 s from
  approve to download, against 306 to 385 s for a render).
- **Cost on the 16 GB card:** a preview takes about 6.5 min instead of about 1 min; a 5 s video then costs
  nothing more, a longer one renders as before. "Try another version" re-rolls the seed the video uses.

## Recast with a new outfit dresses the character first (2026-10-25)

SCAIL-2 draws the character from one reference picture and the words, so an outfit has to be in that
picture. Before the video, Qwen-Image-Edit-2511 dresses each character's own photo ("The person in the first
picture now wears ..."), and Qwen3-VL reads the dressed photo for the render's words. Both are kept per
character and outfit, so another version and the render reuse them.

| Test (16 GB card, words only: "a yellow raincoat and rubber boots") | Result |
|---|---|
| Waist-up photo of an older man in a red jumper | the coat and boots are on him, and the face, hair and beard stay his |
| Framing | asking for boots zoomed the edit out to the whole body, so the face is smaller. The cut-out is fitted to the performer's box anyway |
| Words read back | "An elderly man with white hair and beard, wearing a yellow hooded raincoat, dark pants, and yellow boots" |
| Time | 166 s from cold, both models loading |

In a real Recast (street clip, same character photo: a woman in a white off-shoulder top, seed 1):

| Clothes asked for | Preview |
|---|---|
| Photo dressed first ("a yellow raincoat"), words read from it | she wears the yellow hooded raincoat from the first frame on |
| Words only: her own words with "wears a bright yellow hooded raincoat", photo as uploaded | she keeps the white top from the photo, and the yellow went onto her trousers, as joggers with drawstrings |

The reference picture decides the clothes; words that disagree with it only move a colour somewhere else.

## Any length: a short last chunk (2026-10-25)

A video is rendered in 81-frame chunks, each later one anchored on the previous chunk's last 5 frames; the
last chunk is now only as long as needed (1 + 4n frames). 7 s of the street clip rendered as 81 + 37 frames:
113 frames, 7.06 s, with sound. At the join (frames 79 and 81) and through the short chunk (96, 112) the
jacket, jeans, street and light stay the same. Whole chunks build byte-identical graphs to before.


## Four people, and Restage with an outfit each (2026-10-25)

Each preview is the real first 5 s (in the clip's own place) or the start picture (a new place), on the
16 GB card, from the example clips in `examples/`.

| Test | Result |
|---|---|
| Recast of 4 of the 6 office coworkers (astronaut, raincoat, chef, grandpa), clip's place | each character on their own person, left to right, for the whole 5 s; the two not chosen stay as filmed |
| ... where a chosen person stands half behind one kept as filmed | the two bleed into each other: the grandpa's white beard shows through the kept woman's cheek, a dark red wedge appears by her ponytail, and in one frame her ponytail doubles |
| Restage, two dancers, an outfit each in words ("a shiny silver sequin jacket", "a bright red tracksuit") | each is cut out of the first frame and dressed in their own edit; faces and hair stay; the left dancer keeps her jeans, the right one is in the tracksuit head to toe, through the whole dance |
| Restage, one person, outfit and new place together ("a red leather biker jacket", "a rooftop terrace at sunset over a city") | one edit gives both: the jacket over her own top on the rooftop, with her pose, sunglasses and necklace kept |
| The lower-clothes reader, on a clip that shows only the upper body | it answered "The image shows only the upper body of the person. Nothing below", which went into the prompt as clothes; such replies are now dropped |

## Running on Modal (2026-10-24)

The judge build renders on Modal (`deploy/modal/`): ComfyUI 0.41.3 + comfy-api-proxy 0.1.6 per container, same
model files (pinned and sha256-checked, `manifests/models.json`), same torch 2.13.0+cu130 and custom-node
versions as the 16 GB development card. The app reaches it exactly as it reaches the development card,
through comfy-sdk; only `COMFY_BASE_URL` (+ `COMFY_QUICK_BASE_URL`, `COMFY_API_KEY`) change. Two lanes, so a
render never holds up a picker:

| Lane | GPU | Runs | Idle → zero after |
|---|---|---|---|
| heavy | L40S 48 GB | renders; Recast-in-the-clip's-place preview (a real 5 s render) | 12 min |
| quick | L4 24 GB | finding people (SAM 3.1), reading photos and clips (Qwen3-VL 8B), image-edit previews (Qwen-Image-Edit), cut-outs | 5 min |

**Same seed, same graph, different GPU.** Jobs from the development card were replayed through the app with
identical parameters. The graphs the server submitted were identical apart from output file names, so any
difference comes from the GPU stack alone.

| Output (replayed job) | Modal GPU | SSIM vs development card | PSNR |
|---|---|---:|---:|
| Recast 5 s render, two performers, in the clip's place (Clip C) | L40S | 0.991 | 42.5 dB |
| the same, delivered 720p | L40S | 0.987 | 41.6 dB |
| its kept-performer masks and layers | L40S | ≥ 0.999 | 46–63 dB |
| Swap preview (image edit, human performer) | L40S / L4 | 0.946 / 0.964 | 25.3 / 27.7 dB |
| Restyle preview (image edit, Clip C) | L40S / L4 | 0.953 / 0.969 | 27.7 / 29.6 dB |
| Pose words and scene description (Qwen3-VL) | L40S, L4 | word-for-word identical | |

The video renders match frame for frame by eye. Image-edit previews keep the same composition, subject and
pose with differences in fine texture (individual trees, road grain): the same seed on a different GPU
architecture runs different kernels, and a 4-step image edit lets that show. Both Ada-generation cards stay
within the same picture; the L4 lands closer to the development card than the L40S does.

**Time and cost per task** (GPU seconds from ComfyUI's own execution timestamps; dollars at Modal list
prices for the GPU plus the container's requested CPU and RAM; development card times from the runs above):

| Task | Lane / GPU | GPU time | Wall time in the app | Cost | Development card |
|---|---|---:|---:|---:|---:|
| Recast 5 s render | heavy / L40S | 160–296 s (mean 207) | 196 s | $0.10–0.18 | 699 s for the same job |
| Restyle 5 s render | heavy / L40S | 109 s | 133 s | $0.07 | no 5 s run (10 s Restyle: 667–941 s) |
| Image-edit preview | quick / L4 | 43–59 s | 85–131 s | $0.014 | about 1 min |
| (same on L40S) | heavy / L40S | 21–29 s | 55–60 s | $0.015 | |
| Reading a photo or clip | quick / L4 | 3–25 s (mean 13) | 12–22 s warm | $0.004 | 45–60 s |
| Finding people | quick / L4 | 6–9 s | 24–36 s warm (after a reading) | $0.002 | |

No task loaded a model partially on either lane: the L4's 22 GB holds the image-edit model with its text
encoder, and Qwen3-VL 8B, one after the other. The L4 takes about twice as long as the L40S per task for
the same dollars, and costs 2.4× less per idle minute, which is where most of a judging session's money goes.

**Start-up.** Cold start to a ready endpoint: 14.7 s on the heavy lane, 30.3 s on the quick lane (ComfyUI
itself boots in 11–15 s and 21–25 s). The first task after a cold start also loads its models (a photo
reading took 62 s cold against 12–22 s warm). A warm request is about 1.1 s round trip from the test client.
An idle tail costs about $0.43 (heavy, 12 min) and $0.09 (quick, 5 min).

**Two lanes at once.** With a Recast-in-the-clip's-place preview rendering on the heavy lane (steps 1→3 of
6), a second create's photo reading finished in 22 s and its people search in 36 s on the quick lane,
instead of queueing behind the render. `tools/e2e_browser.py` ran its two-performer Recast case through the
web app against the Modal lanes: people found, both photos read, the preview rendered, no failures.
