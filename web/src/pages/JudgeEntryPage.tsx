import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";

/** The judge link. Reusable: opening it again, on any device, resumes the same access (APP_DESIGN §5).
 *  The token goes to the server once, which keeps it in a cookie; then it leaves the address bar. */
export function JudgeEntryPage() {
  const { token } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const claim = useMutation({
    mutationFn: (t: string) => api.claimLink(t),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session"] });
      nav("/welcome", { replace: true }); // the token leaves the address bar and the history
    },
  });
  useEffect(() => {
    if (token) claim.mutate(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  // /welcome (after the claim, or opened again later) reads who they are from the session
  const { data: session } = useQuery({ queryKey: ["session"], queryFn: () => api.session(), enabled: !token });
  const name = claim.data?.name ?? (session?.kind === "judge" ? session.name : undefined);
  const ready = !!name;
  return (
    <div className="grid min-h-dvh place-items-center px-6">
      <div className="max-w-lg text-center">
        <img src="/favicon.svg" alt="" className="mx-auto h-12 w-12" />
        {claim.isError ? (
          <>
            <h1 className="mt-6 text-3xl font-semibold tracking-tight">This link doesn't work</h1>
            <p className="mt-4 text-ink-300">{(claim.error as Error).message}</p>
          </>
        ) : (
          <>
            <h1 className="mt-6 text-3xl font-semibold tracking-tight">
              {name ? `Welcome, ${name}` : session?.kind === "guest" ? "Open your judge link" : "Opening your link…"}
            </h1>
            <p className="mt-4 text-ink-300">
              This link is yours for the whole judging period and works on any device. What you make with it is
              seen only through it.
              {session?.renders_total ? <> It includes <span className="text-ink-100">{session.renders_total} renders</span>; previews are free.</> : null}
            </p>
            <ol className="mx-auto mt-8 max-w-sm space-y-3 text-left text-sm text-ink-300">
              <li><span className="text-ink-100">1.</span> Pick a motion: your own clip or one of ours.</li>
              <li><span className="text-ink-100">2.</span> Choose who is recast and as whom, or a look, or a new outfit or place.</li>
              <li><span className="text-ink-100">3.</span> Check the preview. In your clip's own place it is the real start of your video.</li>
            </ol>
            <Link to="/create" aria-disabled={!ready}
              className={"mt-10 inline-flex h-14 items-center rounded-[var(--radius-control)] bg-accent px-8 font-medium text-accent-ink hover:brightness-105"
                + (ready ? "" : " pointer-events-none opacity-50")}>
              Start
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
