import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";

/** The judge link. Reusable: opening it again, on any device, resumes the same access (APP_DESIGN §5).
 *  The live backend exchanges the token for a session cookie on GET /j/:token before this page loads;
 *  here we only strip the token from the address bar and welcome them. */
export function JudgeEntryPage() {
  const { token } = useParams();
  const { data: session } = useQuery({ queryKey: ["session"], queryFn: () => api.session() });
  useEffect(() => {
    if (token) window.history.replaceState(null, "", "/welcome");
  }, [token]);
  return (
    <div className="grid min-h-dvh place-items-center px-6">
      <div className="max-w-lg text-center">
        <img src="/favicon.svg" alt="" className="mx-auto h-12 w-12" />
        <h1 className="mt-6 text-3xl font-semibold tracking-tight">Welcome, and thank you for judging</h1>
        <p className="mt-4 text-ink-300">
          This link is yours for the whole judging period and works on any device.
          {session && <> It includes <span className="text-ink-100">{session.renders_total} renders</span>; previews are free.</>}
        </p>
        <ol className="mx-auto mt-8 max-w-sm space-y-3 text-left text-sm text-ink-300">
          <li><span className="text-ink-100">1.</span> Pick a motion: your own clip or one of ours.</li>
          <li><span className="text-ink-100">2.</span> Choose what changes: character, look, place.</li>
          <li><span className="text-ink-100">3.</span> Approve the preview still, then render (a few minutes).</li>
        </ol>
        <Link to="/create" className="mt-10 inline-flex h-14 items-center rounded-[var(--radius-control)] bg-accent px-8 font-medium text-accent-ink hover:brightness-105">
          Start
        </Link>
      </div>
    </div>
  );
}
