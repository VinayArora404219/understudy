# App design: UI, backend, credits, login

Status: proposal, 2026-10-20. Build window Oct 22–26, after the Animate-2 go/no-go.

## 0. What the organizers expect (submission form, read 2026-10-20)

- **Live link: "optional, but strongly encouraged. Will NOT be shared publicly. Expect 5-10 runs for
  judging purposes ... Feel free to rate-limit or cap spending."** Judges click one private URL;
  ten runs is the whole judging load.
- **Demo video (<2 min): "show us your build (in case we can't get it running) and how you made it."**
  Judges may try to *run the repo themselves*, so setup instructions are judged as part of the build.
- "We're judging the work, not your video editing or quality."
- "Which parts of ComfyUI did you use?" choices: Comfy API · Router · **SDK** · Cloud Agent · Local
  Agent · **MCP**. We use the SDK. An MCP endpoint for the same recast would be a second, honest tick.
- Agreement: "does not include ... real peoples' likenesses without their permission." The app needs
  a consent step on every upload of a person, and our demo clips need signed consent.
- Runpod is named in the publicity agreement as a sponsor; no provider is required ("Rented GPUs still count"). We use Modal (section 8).

Consequences for this design:
1. **Judges get a reusable private link that opens a signed-in session directly. No login wall,
   no expiry during judging, no single-use.** It is capped per link, and only the operator can revoke it.
2. Google sign-in is for the *public* after launch, not for judges. It waits until a domain exists.
3. The repo's quickstart and a `recast doctor` command are part of the judged product.

## 0.1 The standard: professional, from the customer's side

The app is judged by people who have never seen it, in a few minutes, on a private link. Every
screen is designed against that visit:

- **Value before effort.** The first screen shows real results. "Try with a sample clip" works
  without uploading anything, and the first thing a visitor makes is a preview still in about a minute.
- **Never a dead wait.** A render is ~5-9 minutes. Show named stages, the real queue position and an
  ETA from measured rates. The tab can close safely; the result waits in the library (browser notification when done).
- **Guidance, not errors.** Clip checks run on upload and say what to do ("two people detected:
  trim to one", "camera moves a lot: results will drift"). Failures refund automatically and
  explain themselves in one sentence. No stack trace ever reaches the page.
- **Trust.** A consent checkbox for anyone on camera, an "AI-generated" label on outputs, a visible
  privacy note (what we keep, for how long), and a *Delete my data* button.
- **Finish.** One design system (type scale, spacing, colour tokens, dark theme), loading
  skeletons, empty states, keyboard and screen-reader basics, phone-first upload, fast first paint.
  Output files are named sensibly, and there's a share version ready for 9:16.
- **Honesty as a feature.** Show native resolution and when an output is upscaled, the models used,
  render time, and the recipe for reproducing it. That is our edge over the closed product.

## 1. Shape

```
browser ──HTTPS──> nginx (VPS) ──> FastAPI app ──> Postgres (jobs, users, credits)
                      │                 │
                      │ static React    └── private media dir (uploads, outputs)
                      │                        ▲
                      │                        │ HTTPS, worker token (outbound from GPU only)
                      │                 GPU job  (dev: the home GPU; judging: Modal L40S, spawned per job)
                      │                        │ comfy-sdk
                      │                 comfy-api-proxy (loopback) ─> ComfyUI (loopback)
```

- The GPU host has no inbound ports. The worker polls the VPS, leases one job, downloads that
  job's inputs, runs `recast` through the SDK, then uploads the outputs.
- The browser never sees ComfyUI, the proxy, graphs or model names. It sends the bounded
  parameters below, and the server builds the graph.

## 2. Screens

| Screen | What's on it |
|---|---|
| **Landing / gallery** (public) | Before/after pairs playing side by side, filterable by mode (Recast · Restyle · Move). One "Try it" button. Short line: "open weights, reproducible, runs on your own GPU". |
| **Sign in** | Google button, plus a judge-invite link that works without Google. |
| **Create: 1. Motion** | Upload a clip (drag/drop or phone camera), *or* pick a motion from our library. A trim bar picks the window (5 / 10 / 15 / 20 s). The first frame shows with live checks: one performer, whole body visible, steady camera (warnings, not blocks). |
| **Create: 2. Change** | Three stackable cards: **Character** (image + one-line description), **Look** (10 style tiles with animated previews), **Place** (keep mine / describe / upload an image). The credit cost shows before you click. |
| **Create: 3. Preview still** | The matched reference (~1 min) next to the first frame. Buttons: *Approve*, *Try another* (new seed, cheap), *Edit choices*. Nothing expensive runs until you approve. |
| **Create: 4. Render** | Live progress over SSE (queue position, then segment and step). An honest ETA from measured rates. Safe to close the tab; it shows in the library. |
| **Result** | Player with a before/after wipe slider; tabs for Recast, Side-by-side, Vertical share version; downloads (MP4, recipe.json, reference still); *Make a variation* (same choices, new seed); *Share to gallery* (opt-in). |
| **Library** | Your jobs, newest first, with status and credits spent. |
| **Admin** (operator only) | Invites, credit grants, queue view, cancel any job, **global stop switch**, daily GPU-seconds meter. |

## 3. Parameters the user can set

Everything is a bounded choice the server validates (`graph.RecastParams`,
`reference.MatchParams`). Free text is length-capped and only ever reaches a CLIPTextEncode input.

| Group | Parameter | Values | Default |
|---|---|---|---|
| Motion | clip | upload: ≤30 s, ≤200 MB, 256–4096 px, 5–120 fps; or a library id | — |
| | window start | 0 … (len − window) | 0 |
| | window length | 5 / 10 / 15 / 20 s (1–4 segments) | 5 s |
| | subject | person · animal | person |
| Change | character image + description | image ≤15 MB; text ≤400 chars | — |
| | look | one of the 10 styles, or none | none |
| | place | keep mine · describe (≤400 chars) · image | keep mine |
| Quality | preview mode | fast (~1 min) · best (~3 min) | best, if the pose test confirms it |
| | finish | 480p native · 720p · 1080p (labelled as upscaled) | 720p |
| Output | audio | original · mute | original |
| | share layout | side-by-side · stacked · wipe | side-by-side |
| Advanced (collapsed) | seed | integer | random, then recorded |
| | steps | 6–14 | 10 |
| | prompt overrides | appearance, motion (≤600 chars each) | composed for you |

Fixed and never exposed: models, sampler, cfg, shift, fps (16), graph structure.

## 4. Credits

Credits are a quota that protects the GPU budget, not money. No payments in the contest
build: the plan excludes payment processing, and real billing adds tax and compliance work we
can't finish by Oct 30.

| Action | Credits | Why |
|---|---|---|
| Preview still | 1 | ~1–3 GPU-min |
| Render, per 5-second segment | 10 | ~5–9 GPU-min each |
| 720p/1080p finish | 0 | CPU only |
| Variation | same as a render | |

| Grant | Credits |
|---|---|
| New Google account | 25 (≈ 2 renders with previews) |
| Judge invite | 200 |
| Operator | unlimited, still metered |

Mechanics:
- **Append-only ledger.** A hold is placed at submit, settled on success, and refunded on failure,
  cancel or timeout. Balance = sum of the ledger, so nothing can drift.
- **Separate per-user and global limits.** Per user: one active job and N jobs per day. Global:
  queue cap and a daily GPU-seconds budget. When the global budget is spent, new jobs are refused
  with a clear message, whatever anyone's balance.
- The "out of credits" screen points to self-hosting (it's open source), not to a checkout.

Budget check: one 5 s render ≈ 8 GPU-min. At an assumed ~$0.4–0.7/h for a rented 24 GB GPU (check live
prices first), that's roughly $0.05–0.10 a render. The $20 judging envelope then covers a few hundred
renders. The real cost driver is idle time and the model volume, so the pod must stop when idle.

## 5. Login

**Judges: tokenised private link (no login).** Public: Google sign-in later, once a domain exists.

- Google: Authorization Code flow, done server-side in FastAPI (Authlib), scopes `openid email
  profile`. Basic scopes need no Google review, but the consent screen must be *published*;
  in "testing" mode only listed test users can sign in. It needs a domain for the redirect URI, plus
  privacy-policy and terms pages.
- Judge link (built first): `https://<host>/j/<token>`. **Reusable, never single-use.** The same URL
  works every time, on any device or browser, for any number of people. The organizers don't say how
  many judges there are. Each open starts or resumes a session; opening it never uses anything up.
  - Valid until at least Nov 30 (winners are announced Nov 6). Only the operator can turn it off, by hand.
  - The cap is per link and protects money, not access: 25 renders shared (2-3x the "5-10 runs" the
    form expects), previews free. At the cap the judge sees a friendly message. Results, gallery and
    recipes stay viewable, and the operator can raise the cap with one click.
  - Alert the operator on first use and on any failed run, so problems surface while judging is live.
  - A second, independent backup link goes in the form's "Anything else" field.
  - Never a dead end: the link opens to real results even if the GPU is down, and the demo video
    covers "in case we can't get it running".
- Sessions: an opaque id in an HttpOnly, Secure, SameSite=Lax cookie, stored server-side and
  revocable. CSRF token on every state-changing request.
- Ownership checked on every upload, job, output and download. Every id is opaque, and every lookup also filters by owner.

## 6. Backend

Python 3.11, FastAPI, SQLAlchemy 2 + Alembic, Postgres 16, served by uvicorn behind nginx.
Patterns mirror the existing `studio/` (app factory, routers, SSE events), with a real lease added.

Tables: `users`, `sessions`, `invites`, `credit_ledger`, `media` (uploads + outputs: sha256,
probe info, owner, expiry), `jobs`, `job_events`, `gallery_items`, `audit_log`.

Job state machine:

```
draft ─match─> matching ─> awaiting_approval ─approve─> queued ─lease─> rendering ─> finishing ─> done
   │                │                                                         │
   └──────────────── failed / cancelled / expired (credits refunded) <────────┘
```

Worker API (token auth, HTTPS only):
`POST /worker/lease` (`SELECT … FOR UPDATE SKIP LOCKED`, lease 120 s) ·
`POST /worker/jobs/{id}/heartbeat` · `/events` · `/complete` (multipart outputs) · `/fail`.
An expired lease puts the job back in the queue once; a second expiry fails it and refunds the credits.

Public API (session auth): `POST /api/uploads`, `POST /api/jobs` (draft),
`POST /api/jobs/{id}/match`, `/approve`, `/cancel`, `GET /api/jobs/{id}/events` (SSE),
`GET /api/media/{id}` (owner check, then nginx X-Accel-Redirect, short expiry).

Media: private dir on the VPS. Uploads are decoded and re-encoded by `recast.media` (metadata
stripped) under CPU and time limits. Retention: inputs 7 days, outputs 30 days, gallery until
removed.

## 7. Frontend

React 19 + Vite 6 + Tailwind 4 + TanStack Query, the same stack as `studio/web`. Types are generated
from FastAPI's OpenAPI. Dark, cinematic theme; the result video is always the largest thing on
screen. Mobile-first upload, since most clips are shot on phones.

## 8. GPU hosting for judging: Modal (decided 2026-10-20)

Runpod is not required: the form says only "Rented GPUs still count".

- **One Modal class per job type**, with the GPU chosen per class (L40S 48 GB to start, so Animate-2 and
  Qwen-Edit stay loaded together). A Modal volume holds the model files listed in `manifests/models.json`.
- **Inside each container:** ComfyUI on loopback, `comfy-api-proxy` on loopback, and `recast` talking to
  it through `comfy-sdk`, so the execution path matches local exactly.
- **The backend spawns the job** (`Function.spawn(job_id)`, Modal token server-side only). The
  container downloads its inputs from the backend, renders, then uploads outputs and events back to
  the worker API (per-job token). No GPU host has inbound ports.
- **Scale to zero.** Warm one container when a judge link is opened, so the cold start is spent
  while they choose a clip, not after they click Generate.
- **Serial by default.** One container per in-flight job, and judge jobs run one at a time. Measured
  in this workspace: parallel fan-out bills a boot and an idle window per container.
- **Cost guard.** The per-link cap, a global daily GPU-seconds cap, and Modal's own workspace spend
  limit all apply.
- **Local dev:** the same `recast` code runs against the home GPU through an SSH tunnel to its proxy.

## 9. Order of work

1. Backend core: models, auth (invite first, Google second), uploads, jobs, ledger, worker API. CPU tests for ownership, ledger and lease.
2. Worker loop around `recast` (already built); run it against the local box.
3. Frontend: Create flow, then Result, Library, Landing, Admin.
4. Deploy to the VPS (Docker Compose, HTTPS); Modal job image + model volume; security checklist from the brief.
