// In-browser stand-in for the backend, so the UI can be built and reviewed before the API exists.
// It never pretends to render: previews and results are the visitor's own media played back,
// and the UI marks every mock result as such.

import type { Api } from "./client";
import type { Check, GalleryItem, Job, JobParams, MotionPreset, Session, Style, Upload } from "./types";

const STYLES: Style[] = [
  { key: "anime", name: "Anime Cel", swatch: ["#7dd3fc", "#f0abfc"] },
  { key: "toy", name: "Toy Figure 3D", swatch: ["#f9a8d4", "#fde68a"] },
  { key: "pixel", name: "Pixel Art", swatch: ["#86efac", "#3b82f6"] },
  { key: "watercolor", name: "Watercolor", swatch: ["#fde2e4", "#bde0fe"] },
  { key: "comic", name: "Comic Ink", swatch: ["#fde047", "#ef4444"] },
  { key: "neon", name: "Neon Night", swatch: ["#d946ef", "#06b6d4"] },
  { key: "wool", name: "Knitted Wool", swatch: ["#fdba74", "#a78bfa"] },
  { key: "paper", name: "Paper Cutout", swatch: ["#fcd34d", "#fb7185"] },
  { key: "lowpoly", name: "Low-Poly", swatch: ["#5eead4", "#6366f1"] },
];

/** A neutral poster (gradient + figure silhouette) so presets look intentional without stock media. */
function poster(a: string, b: string, label: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 270 480">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs>
  <rect width="270" height="480" fill="url(#g)"/>
  <g fill="rgba(11,11,15,0.55)"><circle cx="135" cy="150" r="34"/><path d="M95 200h80l18 120-28 4-10-70-6 160h-24l-6-110-6 110h-24l-6-160-10 70-28-4z"/></g>
  <text x="18" y="456" font-family="system-ui" font-size="18" font-weight="600" fill="rgba(11,11,15,0.75)">${label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const PRESETS: MotionPreset[] = [
  { id: "p-groove", title: "Easy groove", subtitle: "Full body · steady camera", seconds: 5,
    thumb_url: poster("#334155", "#c8f560", "Easy groove"), preview_url: "" },
  { id: "p-wave", title: "Big wave hello", subtitle: "Waist up · one arm", seconds: 5,
    thumb_url: poster("#312e81", "#f0abfc", "Big wave hello"), preview_url: "" },
  { id: "p-spin", title: "Slow spin", subtitle: "Full body · turn around", seconds: 5,
    thumb_url: poster("#1e3a8a", "#7dd3fc", "Slow spin"), preview_url: "" },
];

const session: Session = { kind: "judge", name: "Judge preview", credits_left: 300, credits_total: 300 };
const uploads = new Map<string, Upload>();
const jobs = new Map<string, Job>();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const id = (p: string) => `${p}_${Math.random().toString(36).slice(2, 10)}`;

async function readVideo(url: string): Promise<{ w: number; h: number; s: number; thumb: string }> {
  const v = document.createElement("video");
  v.src = url;
  v.muted = true;
  v.playsInline = true;
  await new Promise<void>((ok, bad) => {
    v.onloadeddata = () => ok();
    v.onerror = () => bad(new Error("This file could not be read as a video."));
  });
  v.currentTime = Math.min(0.1, v.duration / 2);
  await new Promise((r) => (v.onseeked = r));
  const c = document.createElement("canvas");
  c.width = v.videoWidth;
  c.height = v.videoHeight;
  c.getContext("2d")!.drawImage(v, 0, 0);
  return { w: v.videoWidth, h: v.videoHeight, s: v.duration, thumb: c.toDataURL("image/jpeg", 0.85) };
}

async function readImage(url: string): Promise<{ w: number; h: number }> {
  const img = new Image();
  img.src = url;
  await img.decode();
  return { w: img.naturalWidth, h: img.naturalHeight };
}

function clipChecks(w: number, h: number, s: number): Check[] {
  const checks: Check[] = [];
  checks.push(s < 1
    ? { id: "length", level: "block", message: "Clip is shorter than 1 second", hint: "Use a clip of 4–30 seconds." }
    : s > 30
      ? { id: "length", level: "warn", message: `Clip is ${s.toFixed(0)} s long`, hint: "Pick the part to use with the window below (up to 20 s)." }
      : { id: "length", level: "ok", message: `${s.toFixed(1)} s, long enough` });
  checks.push(Math.min(w, h) < 256
    ? { id: "size", level: "block", message: "Resolution is too low", hint: "Use a clip at least 256 px on its short side." }
    : { id: "size", level: "ok", message: `${w}×${h}, ${h >= w ? "portrait" : "landscape"}` });
  // The server checks performer count, framing and camera motion. The mock says so instead of pretending.
  checks.push({ id: "performer", level: "ok", message: "Performer and camera checks run on the server",
    hint: "Best results: one person, whole body or waist-up, camera on a stand." });
  return checks;
}

function title(p: JobParams): string {
  const what = p.mode === "swap" ? (p.outfits?.some(Boolean) ? "New outfit" : "New place") : p.characters.length === 2 ? "Duo recast" : p.characters.length ? "Recast" : p.style ? STYLES.find((s) => s.key === p.style)?.name ?? "Restyle" : "Move";
  return `${what} · ${p.motion.length} s`;
}

function summary(p: JobParams): string {
  const parts: string[] = [];
  const [a, b] = p.characters;
  parts.push(b ? `The performer on the left becomes ${a.text.trim()} and the one on the right becomes ${b.text.trim()}`
    : a ? `The performer becomes ${a.text.trim() || "your character"}` : "The performer stays themselves");
  if (p.outfit) parts.push(`wearing ${p.outfit.text.trim() || "your outfit"}`);
  if (p.style) parts.push(`drawn as ${STYLES.find((s) => s.key === p.style)?.name}`);
  parts.push(p.place.mode === "keep" ? "in the original place" : p.place.mode === "describe"
    ? `in ${p.place.text?.trim() || "the place you described"}` : "in the place from your image");
  return parts.join(", ") + ".";
}

function sourceOf(p: JobParams): { url: string; thumb: string } {
  if (p.motion.upload_id) {
    const u = uploads.get(p.motion.upload_id)!;
    return { url: u.url, thumb: u.thumb_url };
  }
  const preset = PRESETS.find((x) => x.id === p.motion.preset_id)!;
  return { url: preset.preview_url, thumb: preset.thumb_url };
}

async function runRender(jobId: string) {
  const j = jobs.get(jobId)!;
  // re-read on every tick: cancel() can land while this loop sleeps
  const cancelled = () => (jobs.get(jobId)!.state as Job["state"]) === "cancelled";
  const steps = 10;
  const stages: [Job["progress"], number][] = [
    [{ stage: "waiting_for_gpu", queue_position: 1, eta_seconds: 480 }, 1500],
    [{ stage: "starting_gpu", eta_seconds: 460 }, 1500],
    [{ stage: "loading_models", eta_seconds: 420 }, 1500],
  ];
  for (const [progress, ms] of stages) {
    if (cancelled()) return;
    j.state = "queued";
    j.progress = progress;
    await sleep(ms);
  }
  j.state = "rendering";
  for (let s = 1; s <= steps; s++) {
    if (cancelled()) return;
    j.progress = { stage: "rendering", segment: 1, segments: 1, step: s, steps, eta_seconds: (steps - s) * 38 + 20 };
    await sleep(900);
  }
  j.state = "finishing";
  j.progress = { stage: "finishing", eta_seconds: 10 };
  await sleep(1200);
  const src = sourceOf(j.params);
  j.state = "done";
  j.progress = undefined;
  j.result = {
    video_url: src.url, compare_url: src.url, share_url: src.url, source_url: src.url,
    recipe_url: "data:application/json," + encodeURIComponent(JSON.stringify({ mock: true, params: j.params }, null, 2)),
    render_seconds: 512, native_resolution: "480×832 @ 16 fps",
    delivered_resolution: j.params.finish === "480p" ? "480×832" : `${j.params.finish} (upscaled)`,
  };
}

export const mockApi: Api = {
  isMock: true,
  async session() { return { ...session }; },
  async claimLink() { return { kind: "judge" as const, name: session.name }; },
  async presets() { return PRESETS; },
  async styles() { return STYLES; },
  async gallery(): Promise<GalleryItem[]> { return []; },

  async upload(file, kind) {
    await sleep(400);
    const url = URL.createObjectURL(file);
    let u: Upload;
    if (kind === "video") {
      const v = await readVideo(url);
      u = { id: id("up"), kind, url, thumb_url: v.thumb, info: { width: v.w, height: v.h, seconds: v.s },
        checks: clipChecks(v.w, v.h, v.s) };
    } else {
      const i = await readImage(url);
      u = { id: id("up"), kind, url, thumb_url: url, info: { width: i.w, height: i.h },
        checks: [{ id: "img", level: "ok", message: `${i.w}×${i.h}` }] };
    }
    uploads.set(u.id, u);
    return u;
  },

  // the mock has no vision model: it says so with an empty description, and the visitor types one
  async describeUpload(id, role) {
    const u = uploads.get(id)!;
    u.descriptions = { ...u.descriptions, [role]: "" };
    return { ...u };
  },
  async getUpload(id) { return { ...uploads.get(id)! }; },

  // the mock has no detector: two made-up people on the clip's first frame, outlined by their boxes
  async findPeople(id, start) {
    const u = uploads.get(id)!;
    const key = `${start.toFixed(2)}_auto`;
    if (!u.people?.[key]) {
      u.people = { ...u.people, [key]: { state: "finding" } };
      void sleep(1500).then(() => {
        u.people = { ...u.people, [key]: { state: "ready", frame_url: u.thumb_url, people: [
          { id: 1, box: [0.1, 0.2, 0.32, 0.72], area: 0.15, cx: 0.26 },
          { id: 2, box: [0.56, 0.24, 0.3, 0.68], area: 0.13, cx: 0.71 },
        ] } };
      });
    }
    return { key, ...u };
  },

  async createJob(params) {
    const j: Job = { id: id("job"), created_at: new Date().toISOString(), state: "draft", title: title(params),
      params, cost_seconds: params.motion.length };
    jobs.set(j.id, j);
    return { ...j };
  },

  async requestPreview(jobId, opts) {
    const j = jobs.get(jobId)!;
    j.state = "matching";
    const seed = opts?.newSeed ? Math.floor(Math.random() * 1e6) : j.preview?.seed ?? 1;
    void (async () => {
      await sleep(2600);
      const src = sourceOf(j.params);
      const ref = j.params.characters[0] ? uploads.get(j.params.characters[0].upload_id)!.thumb_url : src.thumb;
      j.preview = { frame_url: src.thumb, reference_url: ref, seed, prompt_summary: summary(j.params) };
      j.state = "awaiting_approval";
    })();
    return { ...j };
  },

  async approve(jobId) {
    const j = jobs.get(jobId)!;
    if (session.credits_left < j.cost_seconds) throw new Error(`This video needs ${j.cost_seconds} credits and ${session.credits_left} are left. Pick a shorter length.`);
    session.credits_left -= j.cost_seconds;
    j.state = "queued";
    void runRender(jobId);
    return { ...j };
  },

  async editScene(jobId, text) {
    const j = jobs.get(jobId)!;
    j.scene = { state: "ready", text: text.trim(), edited: true };
    return { ...j };
  },

  async cancel(jobId) {
    const j = jobs.get(jobId)!;
    if (j.state !== "done") {
      if (["queued", "rendering", "finishing"].includes(j.state)) session.credits_left += j.cost_seconds;
      j.state = "cancelled";
      j.error = { message: "Cancelled.", refunded: true };
    }
    return { ...j };
  },

  async job(jobId) {
    const j = jobs.get(jobId);
    if (!j) throw new Error("This render does not exist or belongs to someone else.");
    return { ...j, progress: j.progress ? { ...j.progress } : undefined };
  },

  async jobs() {
    return [...jobs.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((j) => ({ ...j }));
  },
};
