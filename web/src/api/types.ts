// The API contract between the web app and the backend (docs/APP_DESIGN.md §6).
// The mock (mock.ts) and the real backend both implement exactly this.

export type CheckLevel = "ok" | "warn" | "block";

/** A pre-flight check on an uploaded clip or image, phrased as guidance, never as an error code. */
export interface Check {
  id: string;
  level: CheckLevel;
  message: string; // "One performer in view"
  hint?: string; // what to do about it
}

export interface MediaInfo {
  width: number;
  height: number;
  seconds?: number;
  fps?: number;
  has_audio?: boolean;
}

export interface Upload {
  id: string;
  kind: "video" | "image";
  url: string; // private, short-lived
  thumb_url: string;
  info: MediaInfo;
  checks: Check[];
  descriptions?: Partial<Record<ImageRole, string>>; // written by the vision model, "" when it couldn't
  describing?: ImageRole[]; // still being written
  people?: Record<string, PeopleEntry>; // a clip's start frame, by people key ("0.00_portrait")
}

/** Someone found in a clip's start frame; Recast replaces the ones the visitor chooses. */
export interface Person {
  id: number; // 1, 2, 3... left to right
  box: [number, number, number, number]; // x, y, width, height as fractions of the frame
  area: number; // fraction of the frame
  cx: number; // centre, fraction of the width: what "left to right" means everywhere
  mask_url?: string; // white on black, the frame's size
}

export interface PeopleEntry {
  state: "finding" | "ready";
  frame_url?: string;
  people?: Person[];
  error?: string; // ready but nobody could be looked for
}

export type ImageRole = "character" | "outfit";

/** A ready-made motion a visitor can use without filming anything. */
export interface MotionPreset {
  id: string;
  title: string;
  subtitle: string;
  seconds: number;
  thumb_url: string;
  preview_url: string;
  credit?: string; // who filmed it
}

export interface Style {
  key: string;
  name: string;
  swatch: [string, string]; // gradient used on the tile until a preview clip exists
}

export type PlaceMode = "keep" | "describe" | "image" | "character";

/** A character image. Cropped to head and shoulders unless keep_outfit: a full-body picture's pose
 *  otherwise leaks into the result (bench/RESULTS.md, fix C). */
export interface CharacterRef {
  upload_id: string;
  text: string;
  keep_outfit: boolean;
}

/** recast: someone else performs · restyle: everything redrawn in a look · swap: one thing changes, the performer stays */
export type Mode = "recast" | "restyle" | "swap";

export interface JobParams {
  mode: Mode;
  /** picks: Recast's chosen people (Person.id) in the start frame; they set `performers`. */
  motion: { upload_id?: string; preset_id?: string; start: number; length: number; picks?: number[] }; // seconds, 2..20
  performers: number; // who is replaced (Recast) or in the clip: 1 to 4, or up to 2 in a new place
  subject: "person" | "animal"; // with picks, the server reads it from the clip
  /** One per performer, or none. With two performers: [the one on the picture's left, the one on its right]. */
  characters: CharacterRef[];
  outfit?: { upload_id?: string; text: string }; // jobs made before Restage took one outfit per person
  /** Restage: what each chosen person now wears, left to right; null keeps their own clothes. */
  outfits?: ({ upload_id?: string; text: string } | null)[];
  /** true: straight to the video, credits held from the start. false: a draft to approve first. */
  auto?: boolean;
  style?: string;
  place: { mode: PlaceMode; text?: string; upload_id?: string };
  finish: "480p" | "720p" | "1080p";
  audio: "original" | "mute";
  seed?: number;
}

export type JobState =
  | "draft"
  | "matching"
  | "awaiting_approval"
  | "queued"
  | "rendering"
  | "finishing"
  | "done"
  | "failed"
  | "cancelled";

export interface CastPair {
  person: number; // as numbered on the picker
  box: [number, number, number, number]; // in frame_url, fractions
  frame_url: string; // the clip's start frame, unmarked
  character_url: string; // the character's photo
  text: string; // how they look
}

export interface JobPreview {
  frame_url: string; // the clip's first frame
  reference_url: string; // what the render will start from
  seed: number;
  prompt_summary: string; // plain-language description of what will change
  notes?: string[]; // anything the visitor should know about how their images were used
  seen?: string; // how we read the clip: "a dog on the left (leans forward …)"
  kind?: "still" | "cast"; // still: the picture the video starts from; cast: who replaces whom, left to right
  first_url?: string; // cast: the video's first second, rendered for real (muted, loops)
  first_frame_url?: string; // its first frame, for posters
  pending?: boolean; // cast: shown at once while the first second renders
  cast?: CastPair[]; // cast: each chosen person, left to right, with who replaces them
}

export interface JobProgress {
  stage: "dressing" | "completing" | "waiting_for_gpu" | "starting_gpu" | "loading_models" | "rendering" | "finishing";
  queue_position?: number;
  segment?: number;
  segments?: number;
  step?: number;
  steps?: number;
  eta_seconds?: number;
}

export interface JobResult {
  video_url: string;
  compare_url: string;
  share_url: string; // vertical 9:16 share version
  recipe_url: string;
  source_url: string;
  render_seconds: number;
  native_resolution: string; // "480×832 @ 16 fps"
  delivered_resolution: string; // "720×1248 (upscaled)"
  models?: string; // the models that made this video, e.g. "SCAIL-2 (Wan2.1 14B), SAM 3.1"
}

export interface Job {
  id: string;
  created_at: string;
  state: JobState;
  title: string; // "Anime Cel · 5 s"
  params: JobParams;
  cost_seconds: number; // credits: 1 credit = 1 second of finished video
  auto?: boolean; // made straight to the video, without a draft to approve
  aspect?: [number, number]; // delivered width, height: known once the clip is prepared
  inputs?: { label: string; kind: "video" | "image"; thumb_url: string }[]; // what went in, for the result page
  preview?: JobPreview;
  progress?: JobProgress;
  result?: JobResult;
  error?: { message: string; refunded: boolean };
  scene?: SceneLine; // Restyle: how we read the clip, in the words the render uses
}

export interface SceneLine {
  state: "reading" | "ready"; // reading: being written, not editable yet
  text: string;
  edited?: boolean; // the visitor's own words
}

export interface Session {
  kind: "judge" | "user" | "guest";
  name: string;
  credits_left: number;
  credits_total: number;
}

export interface GalleryItem {
  id: string;
  mode: "Recast" | "Restyle" | "Move";
  title: string;
  before_url: string;
  after_url: string;
  poster_url: string;
}
