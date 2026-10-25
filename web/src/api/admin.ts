/** The admin API (server/app.py, /api/admin): make, list and revoke judge links. Only the live server has it. */
import { ApiError } from "./client";

export interface LinkRow {
  id: string;
  name: string;
  created: string;
  expires: string;
  revoked: string | null;
  live: boolean;
  credits: number; // seconds of video it may render
  used: number;
  left: number;
  videos: number; // finished renders
  previews: number;
  uploads: number;
  last_active: string | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/admin${path}`, {
    credentials: "same-origin", headers: { "content-type": "application/json" }, ...init,
  });
  let body: { message?: string } | undefined;
  try {
    body = await res.json();
  } catch {
    /* not JSON: the mock build has no server behind it */
  }
  if (!res.ok || body === undefined) {
    throw new ApiError(body?.message ?? "The admin page needs the live server.", res.status);
  }
  return body as T;
}

export const admin = {
  session: () => call<{ signed_in: boolean }>("/session"),
  login: (password: string) => call<{ signed_in: boolean }>("/login", { method: "POST", body: JSON.stringify({ password }) }),
  logout: () => call<{ signed_in: boolean }>("/logout", { method: "POST" }),
  links: () => call<LinkRow[]>("/links"),
  make: (name: string, credits: number, days: number) =>
    call<{ link: LinkRow; path: string }>("/links", { method: "POST", body: JSON.stringify({ name, credits, days }) }),
  revoke: (id: string) => call<LinkRow>(`/links/${id}/revoke`, { method: "POST" }),
};
