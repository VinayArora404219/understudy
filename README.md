# Understudy

Film something. Choose who in the clip is recast, and as whom. Get the same performance back, played by
your characters, in your own room, with everyone you didn't choose left exactly as filmed, your original
audio, a side-by-side comparison and a `recipe.json` with the exact graph that made it.

Open weights only, end to end, run through the official
[Comfy SDK](https://docs.comfy.org/development/api-development/sdks) against a self-hosted ComfyUI behind
[`comfy-api-proxy`](https://github.com/Comfy-Org/comfy-api-proxy). No closed model or API anywhere in the path.

> Built for Comfy's *Open Source Higgsfield* challenge (Oct 2026), Open Weights category.

## Three modes

| Mode | What changes | How |
|---|---|---|
| **Recast** | Someone else performs your moves: a person, a mascot, an animal. Up to two performers, in the clip's own place or another one. | SCAIL-2 (Wan2.1 14B), tracked by SAM 3.1. Another place starts from a picture made with Qwen-Image-Edit-2511. |
| **Restyle** | The whole video, redrawn in a look: anime, toy, pixel art, comic ink and more. | Wan2.1 VACE 14B, video to video on a depth map of every frame, so things that happen later in the clip still happen. |
| **Restage** | You stay you. New clothes for anyone you choose, a new place, or both. | SCAIL-2 recasts you as yourself, so the clip still drives every frame. Each new outfit is put on with Qwen-Image-Edit-2511 first. |

## What it adds over the stock workflows

- **You choose who is recast.** SAM 3.1 finds everyone in the start frame. You tap up to two people, and
  their masks start the video tracker, with no words involved, so two people dressed alike are still told
  apart. Words can't do this: tracking "man" in a crowd followed a passer-by, and the clip reader named a
  different man on each read.
- **Everyone else stays as filmed.** SCAIL-2 redraws the whole frame, so bystanders came back changed, some
  wearing the new character's glasses. Everyone not chosen is tracked over the whole clip and put back as
  filmed, colour-matched to the render. That includes people who walk in after the first frame.
- **Each character lands on the right person.** SCAIL-2 decides who becomes whom by where the characters
  sit on its reference picture, not by the tracking masks or the prompt; we tested both. So each character
  is cut out of their photo and placed where their performer stands.
- **The preview is the real start of your video.** In the clip's place, the preview renders the video's first
  5 seconds, which is exactly the render's first chunk, with the same graph and seed. A 5 s video is that chunk,
  so keeping it needs no second render. While it renders, the page shows who replaces whom, plus the job's
  progress through each phase.
- **Restyle reads your clip.** Depth can't see sunglasses against a face, so Qwen3-VL looks at four moments of
  the clip and names what the performers put on, take off or pick up; you can edit that line. Background events
  are left out on purpose: naming a far-off cyclist pulled him into the foreground.
- **Every result can be made again.** A finished render's Recreate opens Create with the same clip, the people
  chosen in it, the pictures, their words and every setting, ready to change. The Examples page does the same
  for videos made here: each one's clip and pictures are copied into the visitor's own uploads.
- **It never says what isn't there.** "No glasses" in a prompt only adds the word glasses. Negations are
  removed from the character's words and the render prompt, and the character is cut out of their photo, so a
  helmet on the desk beside them
  can't become their headgear.
- **Reproducible.** `recipe.json` records the input hashes, every setting, the seed, the models, the exact
  ComfyUI API graph it ran (it opens in ComfyUI), and each step done after it.

- **Any length, paid by the second.** Ask for 2 to 20 seconds of your clip. The video renders in 5 s chunks,
  each anchored on the last frames of the one before, and the last chunk is only as long as it needs to be. A
  render costs one credit per second it delivers; previews are free, and a failed render is refunded.

Every problem met while building this, and how each was fixed, is in
[docs/PROBLEMS_AND_FIXES.md](docs/PROBLEMS_AND_FIXES.md). The measurements behind each claim are in
[bench/RESULTS.md](bench/RESULTS.md).

## How it runs

```
web app (React)  ->  server/app.py (FastAPI)  ->  comfy-sdk  ->  comfy-api-proxy  ->  ComfyUI
```

The server builds every graph from bounded parameters (`recast/`), so nothing a visitor sends reaches ComfyUI
as a raw workflow. GPU work runs in two lanes: **quick** (finding people, reading pictures and clips,
image-edit previews) and **heavy** (renders, and the clip's-place preview, which is a render). Each lane runs
one task at a time, so a picker never waits behind a render. The only machine settings are the endpoints:
`COMFY_BASE_URL` (plus `COMFY_API_KEY`) and, optionally, `COMFY_QUICK_BASE_URL` for a second GPU. The
judge build runs both lanes on Modal ([deploy/modal/](deploy/modal/)).

## Judge links and the admin page

With `RECAST_LINKS=1` the server answers only browsers that opened a link: everything made through a link is
seen only through it, and each link has its own credits. Make, list and revoke links with
`tools/make_link.py`, or at `/admin` when `RECAST_ADMIN_PASSWORD` is set, where each link's use is shown too.
Only a hash of each link is stored, so a link is shown once, when it is made.

## Run it yourself

You need a ComfyUI (v0.41.3) with the models in [manifests/models.json](manifests/models.json) (pinned Hugging
Face revisions, sizes and SHA-256 hashes) and the three custom node packs listed there, plus `comfy-api-proxy`
next to it.

```bash
uv venv && uv pip install -e ".[dev]"
(cd web && npm install)
cp .env.example .env          # set COMFY_BASE_URL to your comfy-api-proxy
tools/serve_local.sh          # backend on :8780, web app on http://localhost:5180
python3 tools/add_presets.py   # optional: the example clips as ready-made motions ("Use one of ours")
python3 tools/add_gallery.py spec.json  # optional: finished jobs as Examples to watch and recreate
```

`add_gallery.py` copies finished jobs from this server's data into `gallery/` (each with its videos, recipe and
the uploads behind it) and one start picture per look for the style cards. To show them on another server, copy
`runs/app/gallery/` into that server's data folder.

The `recast` CLI (`recast run`, `recast match`, `recast styles`) is the first version of the pipeline, on Wan
Animate-2, kept for comparison. `--dry-run` writes its graphs without a GPU.

Measured on a 16 GB RTX 4070 Ti SUPER, which offloads part of the 14B models: a 5 s Recast takes about 6 minutes,
and its preview takes about as long, since it is that render.

## Limits (honest list)

- Up to two performers. With four chosen, one standing half behind a person kept as filmed bled into them
  (a beard showing through a cheek); with two, SCAIL-2's other two places go to neighbours who touch the
  chosen ones, which kept the office clip clean. A new place starts from one image edit, which holds two
  people. Anyone hidden behind another person in the start frame isn't found, so they can't be chosen.
  People in clear view work best.
- Native size: 576x1024 for tall clips and 1024x576 for wide ones; 3:4, 4:3 and square at about 480p, and
  Restyle at 480p (not yet measured larger). All at 16 fps, SCAIL-2's own rate. 720p and 1080p output are a
  lanczos upscale, and the result page says so. Fast hands smear.
- One character's likeness drifts younger in some runs. Logos and printed text on clothes turn into invented
  text. Small accessories from a reference photo (glasses) appear in some renders and not others.
- In the clip's place the room is the model's own, graded to the clip's colours as a whole (bench/RESULTS.md).
- Jobs on the same lane queue: two visitors rendering at once wait for each other.
- Four chunks at most: a 20 s ask delivers about 19.3 s in Recast and Restage and 18.6 s in Restyle, and is
  charged for what it delivers.

## Licence

MIT for this repository's code ([LICENSE](LICENSE)). Models, ComfyUI and the custom nodes keep their own
licences, and every model used allows commercial use: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Contributing / publishing rules

Nothing machine-specific, private or unlicensed enters git: no media, no weights, no IPs, paths or usernames, no
third-party clips. `tools/install_hooks.sh` installs a pre-commit check (`tools/check_public.py`) that enforces
this. Machine details live in `.env` (see `.env.example`).
