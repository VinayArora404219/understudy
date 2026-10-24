# Problems we hit, and how each was fixed

Every problem found while building Performance Recast, in the order a video goes through the app: the
clip, the start picture, the engine, who is recast, keeping the clip, the character, the page, and the
plumbing. Each entry is what we saw, why it happened, and what changed. Measurements behind them are in
[bench/RESULTS.md](../bench/RESULTS.md); the test clips are private, so no frames are shown here.

Status: **fixed** unless marked **open**. The open ones are collected at the end.

## 1. The clip

- **Black bars baked into the video** were treated as part of the picture: they reached the start picture,
  and a letterboxed square clip was taken for a portrait one. *Fix:* `media.content_box` finds the real
  picture (ffmpeg cropdetect, a box that only grows across sampled frames) and the clip is cropped to it
  before anything else.
- **Clips with no sound failed** in VideoHelperSuite's loader. *Fix:* every clip gets an audio track,
  digital silence when it has none (`media.normalize`).

## 2. The start picture (Qwen-Image-Edit)

- **The output copied the start picture's framing.** A character photo used as-is made the performer too
  large, drifting toward the camera and cropped by the end, with the photo's room instead of the clip's.
  *Fix:* the start picture is built from the clip's first frame (image 1) and the character (image 2), so
  framing, size and room come from the clip. This automatic matching is the product's core step.
- **The edit copied the character photo's pose,** whatever the instruction said ("same pose", "pose from
  the first picture", more steps, lower denoise: all lost). *Fix:* two things that work, both used. The
  character photo is cropped to head and shoulders (`recast/crop.py`), so there is no body to copy, and the
  first frame's pose is written out in concrete words ("stands upright on its hind legs, front paws at its
  chest"). Concrete words beat abstract instructions every time we measured.
- **A "whole body in frame" clause drew a waist-up clip's character full-body.** *Fix:* the framing words
  follow the clip's own framing.
- **Two characters in another place came back as a split-screen diptych,** one panel per photo, twice in two
  tries. *Fix:* the prompt opens with "One single photograph of one continuous scene…".
- **A character photo's own background sometimes leaked in** (one seed in two). *Fix:* previews are free and
  re-rollable ("Try another version") before a render is spent.
- **A held product re-posed the performer** (the hand on her head moved to the other arm). Asking the vision
  model which hand was free gave mirrored answers: it described the person's own left, not the picture's.
  *Fix:* sides come from MediaPipe Pose keypoints by picture side (`recast/pose.py`), and the product goes in
  the hand that stays in view. The words "beside the thigh" bared a thigh; they now say "hanging down at the
  side".
- **A held product vanished once its hand left the frame.** The start picture had put it in a raised hand
  the performer never raises. *Fix:* the product goes in the performer's real hand, with the whole pose
  spelled out; the bottle then stayed in 5 of 6 sampled frames and came back after leaving shot. The page
  warns that a held product shows only while its hand is in view.
- **Characters posed in another place were worded as the clip's performers.** A dog-and-cat clip recast as
  two men was worded "two animals… one paw low", and the racer came out on all fours. *Fix:* the words name
  the characters' own kind (`reference.cast_word`), and "paw" becomes "hand" for people.

## 3. The engine

- **Wan2.2-Animate's replacement mode only drives humans:** it needs a DWPose skeleton, so a dog or cat
  can't drive it. *Fix:* Recast moved to SCAIL-2 (MIT, Wan2.1 14B, core ComfyUI nodes), which follows a
  tracked mask and works for animals, and puts every identity on one reference, matched left to right.
- **The clay look invented props** near fast limb motion (a bottle, then a pompom) in two wordings, so the
  wording wasn't the cause. *Fix:* clay was removed from the styles.
- **Restyle from one restyled still lost everything that happens later:** sunglasses put on mid-clip never
  appeared, and a car that drives off stayed parked. *Fix:* Restyle became video to video (Wan VACE with a
  depth map of every frame), in chunks anchored on the previous chunk's last frames, so later events
  survive and the joins don't jump.
- **Swap animated one edited still too, and lost the same things:** sunglasses taken out and put on never
  appeared, a car that drives off stayed parked, the jeans changed along with the shirt, and a phone held to
  the camera became a glass shard. *Fix:* Swap runs on SCAIL-2 like Recast. An outfit swap recasts the
  performer as themselves in the new outfit, in the clip's place, so the clip drives every frame; a place
  swap animates their edited still in the new place.
- **Swap invented trousers** (black in an outfit swap, red in a place swap) because the edit sees only the
  first frame, where the selfie hides them. *Fix:* the vision model reads the clothes below the waist from
  four moments of the clip, and those words go into the edit and the render.
- **A held product showed only while its hand stayed in view,** and it could not survive the move above.
  *Fix:* Product in hand was removed; Swap changes the outfit or the place.
- **Depth can't see small things against the body,** so the sunglasses still vanished. *Fix:* the clip
  reader looks at four moments of the clip and names what a performer puts on, takes off or picks up. The
  visitor can edit that line before rendering.
- **Naming background events backfired:** a far-off cyclist in the reader's line was drawn large in the
  foreground, too early. *Fix:* the reader leaves background motion out.
- **The template's speed LoRA (CausVid 14B) is CC-BY-NC-4.0,** which an open, commercial-friendly entry
  can't ship. *Fix:* lightx2v's Apache-2.0 distill LoRA, with no visible loss. Depth Anything V2 Small is
  used because it is Apache-2.0 (Base and Large are not).

## 4. Who is recast

- **Words can't pick one performer out of a crowd.** Tracking "man" followed a passer-by, then the man in
  front; the chosen man got the shirt and his neighbour got the glasses. The clip reader named a different
  man on each read. *Fix:* the visitor taps who to replace. SAM3 finds everyone in the start frame, one mask
  each, and the chosen masks start SAM3's video tracker with no words, so two people dressed alike are still
  told apart (`recast/people.py`, `web/src/components/PeoplePicker.tsx`).
- **Two people chosen in the middle of a group were not the ones recast.** The characters went to the
  people at the frame's edges, and putting the bystanders back then covered them, so nobody looked recast.
  The tracking and the masks were right, and rewording the prompt changed nothing: SCAIL-2 follows where
  the characters sit on the reference. *Fix:* the reference is the clip's shape, with each character placed
  where their performer stands (`scail.placed_sheet`).
- **SAM3 found only one person per prompt.** *Fix:* its count syntax, `person:8, animal:4`.
- **Swap has no picker step, and its reader described a pedestrian in the background.** *Fix:* Swap
  chooses the performer itself: the biggest person for an outfit; for a place, everyone at least a quarter
  of the biggest one's size, up to two.
- **The clip reader described the person next to the chosen one,** then a walker in the background. *Fix:*
  the reader sees the start frame with only the other detected people greyed out, and is told how many it
  should see. Greying out everything but the chosen ones hid what they touch (a dog's paws on a keyboard
  became "near the ground"), so the room and props stay.
- **A football was detected as a person.** *Fix:* nothing much smaller than the biggest person found is
  chosen automatically; the visitor can still tap it.
- **"Who's in your clip?" asked the visitor something the page could see.** *Fix:* the question is gone.
  Picks set how many performers there are, and whether they are people or animals is read from the clip.

## 5. Keeping the clip around the new characters

SCAIL-2's replacement redraws the whole frame from the clip, not only the masked performers, so the
reference leaked: the chosen man's glasses also appeared on the man beside him, other players' kit changed
colour, and a white studio came back grey.

- **First fix: put the whole clip back outside the performers.** On the way:
  - The pasted clip left grey dog-and-cat shapes, because only the render has background where they stood.
    *Fix:* the new characters are found in the render too, and that area was colour-matched to the clip.
  - One point per new character gave SAM a part (a bib, a strip of wall). *Fix:* three points spread from
    top to bottom, with the frame border counting as an edge.
  - Colour-matching the whole render washed the men out. *Fix:* only the background behind the old
    performers was matched.
  - The encoder dropped most frames (`-shortest` cut 64 of 81). *Fix:* the length is set explicitly, and a
    mask that comes back shorter than the render stops the job instead of shipping a short video.
- **That composite cost more than it fixed.** A ghost of the dog's outline showed on the wall where it had
  stood, a grey ring ran round both men, and they looked pasted on. The render's wall is shaded unlike the
  clip's, which one colour fit per frame can't follow, and the men are lit for the room the model drew. A
  finer, spatially varying colour fit only halved it. *Fix:* the room now stays as rendered, and **only the
  people who aren't recast go back as filmed**, colour-matched to the render, with a new character in front
  of one of them always kept as rendered (`recast/keep.py`, `recast/composite.py`).
- **People who walk in after the start frame weren't protected:** a goalkeeper running into shot kept the
  render's kit colour. *Fix:* everyone in the clip is also tracked by words ("person, animal") on every
  frame, minus the chosen performers' track with a 12 px margin, so nothing of them comes back.

## 6. The character

- **Two characters with the same description came out as two copies of one person:** identity follows the
  words. *Fix:* the server refuses identical descriptions and asks for each one as they look.
- **The reader's first-frame pose sentence cost an accessory in the clip's place:** with it, sunglasses put
  on mid-clip never appeared; without it they did, on time (same seed). The clip itself drives every frame
  there. *Fix:* the clip's place sends no pose words; another place still does, since they pose its start
  picture.
- **A racer put on a helmet where the clip's man put on sunglasses.** His photo had a helmet on the desk
  beside him, the whole photo was the reference, and the words written for him said "no glasses… with
  matching helmet". A prompt can't say what isn't there; "no glasses" only adds the word. *Fix:* the
  character is cut out of their photo onto the room's colour (`people.cut_out`); anything in front of them,
  like a microphone, leaves a hole that is closed and painted in from around it, and loose pieces of their mask (a strip of trousers at the photo's edge) are dropped. "No X", "without X" and
  "with no X" are removed from the words and from the render prompt, and the vision model is told to
  describe only what is on the body. Re-rendered with the same seed: the sunglasses come and go on time.

## 7. The page

- **The "Who is this?" box could be typed in while the words were still being written,** and nothing said
  so. *Fix:* the box shows progress ("Looking at the picture: face, hair and clothes…") and unlocks once the
  words are in.
- **That progress could spin forever** when the page's first read landed before the request to write the
  words. *Fix:* the page waits for the words themselves, not a "describing" flag, and gives up after three
  minutes with a box to type in.
- **"Who is this?" read like a caption,** inviting a name ("my friend Raj") or an action ("dancing"), though
  these words shape how the character is drawn and the clip decides the moves. *Fix:* the box is labelled
  "How they look in the video", with an example, and its help says the video draws them from the photo and
  these words, without names or actions. Outfits and products get the same wording.
- **"How your video will start" promised something the engines don't do.** The preview picture is a
  reference for the look: SCAIL-2 re-poses its characters to the clip, and VACE takes only its style while
  the clip's depth shapes every frame. *Fix:* it is labelled "The look your video will have", and the page
  says moves, poses and framing come from the clip.
- **The step bar scrolled sideways on a phone.** *Fix:* tighter spacing at phone width, checked at 390 px.
- **"We couldn't look for people in this frame"** appeared when the GPU machine had restarted and the API
  proxy with it. *Fix:* the error reads as a sentence with Try again, and "Try again" now really looks again
  after a miss. A model folder on the GPU machine that briefly stopped answering failed it once more; the
  server now looks twice more by itself, 5 and 20 s later, before showing the error.

## 8. Plumbing

- **comfy-sdk 0.5.0 sends job metadata as a map; comfy-api-proxy 0.1.6 accepts only a string** and rejects
  the job. *Fix:* jobs are submitted without metadata (reported upstream).
- **Uploads collided by name** (every run uploaded `drive.mp4` and ComfyUI renamed duplicates). *Fix:* every
  input is named by its content hash.
- **A re-run with changed words but the same seed reattached to the earlier job** and showed its old image.
  *Fix:* submissions are keyed by the graph's content, never just the seed.
- **Failed jobs were swallowed** ("ended failed"). *Fix:* the server's one-line reason is carried to the page,
  and a re-run after a failure submits again instead of reattaching to the dead job.
- **Cancel right after a server restart didn't reach the GPU,** because the live job handle was gone.
  *Fix:* cancel falls back to the job id stored at submission.
- **Writing the recipe crashed after a finished render:** the parameters still held live SDK asset handles.
  *Fix:* file names are put back before the recipe is written.
- **Models loaded slowly while the GPU sat at 2.5 GB** and looked stuck. The weights were being read from a
  spinning disk with memory swapping; nothing had hung. The judge build runs on Modal's disks. On our own
  machine this is still slow (**open**).

## Open

- One character's likeness drifts younger in some runs, in both places and at both sizes tried.
- Logos and printed text on clothes turn into invented text.
- Small accessories from the reference (glasses) appear in some renders and not others with the same inputs.
- 480p at 16 fps: fast hands smear. Higher resolution should help detail, at about 2.5 to 3 times the time.
- The room keeps the render's colour, so a white studio comes back slightly grey.
- Someone hidden behind another person in the start frame isn't found, so they can't be picked.
