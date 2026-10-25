import type { GalleryItem, ImageRole, Job, JobParams, MotionPreset, Session, Style, Upload } from "./types";

export interface Api {
  readonly isMock: boolean;
  session(): Promise<Session>;
  /** Open a judge link: the server keeps it in a cookie from then on. */
  claimLink(token: string): Promise<{ kind: "judge"; name: string }>;
  presets(): Promise<MotionPreset[]>;
  styles(): Promise<Style[]>;
  gallery(): Promise<GalleryItem[]>;
  upload(file: File, kind: "video" | "image"): Promise<Upload>;
  /** Ask for an image's description in a role; poll getUpload until `descriptions[role]` is set. */
  describeUpload(id: string, role: ImageRole): Promise<Upload>;
  getUpload(id: string): Promise<Upload>;
  /** Look for everyone in a clip's start frame; poll getUpload until `people[key].state` is "ready". */
  findPeople(id: string, start: number, retry?: boolean): Promise<Upload & { key: string }>;
  createJob(params: JobParams): Promise<Job>;
  requestPreview(jobId: string, opts?: { newSeed?: boolean }): Promise<Job>;
  approve(jobId: string): Promise<Job>;
  editScene(jobId: string, text: string): Promise<Job>;
  cancel(jobId: string): Promise<Job>;
  job(jobId: string): Promise<Job>;
  jobs(): Promise<Job[]>;
}

/** Error with a sentence a person can act on. The backend never sends stack traces. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: init?.body instanceof FormData ? undefined : { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let message = "Something went wrong on our side. Your credits were not used.";
    try {
      const body = await res.json();
      if (typeof body?.message === "string") message = body.message;
    } catch {
      /* keep the generic sentence */
    }
    throw new ApiError(message, res.status);
  }
  return res.json() as Promise<T>;
}

const live: Api = {
  isMock: false,
  session: () => call("/session"),
  claimLink: (token) => call("/links/claim", { method: "POST", body: JSON.stringify({ token }) }),
  presets: () => call("/presets"),
  styles: () => call("/styles"),
  gallery: () => call("/gallery"),
  upload: (file, kind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return call("/uploads", { method: "POST", body: form });
  },
  describeUpload: (id, role) => call(`/uploads/${id}/describe`, { method: "POST", body: JSON.stringify({ role }) }),
  getUpload: (id) => call(`/uploads/${id}`),
  findPeople: (id, start, retry) =>
    call(`/uploads/${id}/people`, { method: "POST", body: JSON.stringify({ start, retry: !!retry }) }),
  createJob: (params) => call("/jobs", { method: "POST", body: JSON.stringify(params) }),
  requestPreview: (id, opts) =>
    call(`/jobs/${id}/preview`, { method: "POST", body: JSON.stringify({ new_seed: !!opts?.newSeed }) }),
  approve: (id) => call(`/jobs/${id}/approve`, { method: "POST" }),
  editScene: (id, text) => call(`/jobs/${id}/scene`, { method: "POST", body: JSON.stringify({ text }) }),
  cancel: (id) => call(`/jobs/${id}/cancel`, { method: "POST" }),
  job: (id) => call(`/jobs/${id}`),
  jobs: () => call("/jobs"),
};

const useMock = (import.meta.env.VITE_API ?? "mock") !== "live";
export const api: Api = useMock ? (await import("./mock")).mockApi : live;
