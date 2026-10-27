import { Link, useRouteError } from "react-router-dom";
import { Empty } from "./JobPage";

export function PrivacyPage() {
  return (
    <article className="mx-auto max-w-2xl space-y-4 text-ink-300">
      <h1 className="text-2xl font-semibold text-ink-100">Privacy</h1>
      <p>Your uploads and renders are private to your link or account. Nobody else can open them.</p>
      <p>Uploaded clips and images are kept for 7 days and renders for 30 days, then deleted. Nothing is
        shown in the public gallery unless you choose to share it.</p>
      <p>We strip metadata (location, device) from every upload. Media is processed only by the open models
        listed on the result page, on GPUs we rent; it is never sent to a third-party AI service.</p>
      <p>Only upload people who have agreed to be transformed. Results are labelled as AI-generated.</p>
    </article>
  );
}

/** What a page that failed to draw shows instead of the router's bare error screen: a way back, never a dead end.
 *  The error itself goes to the console, where a bug report can quote it. */
export function RouteError() {
  const error = useRouteError();
  console.error(error);
  return <Empty title="Something went wrong on this page" line="Nothing you made is lost. Reload, or go back to your renders."
    action={<div className="flex justify-center gap-3">
      <button onClick={() => window.location.reload()}
        className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-accent px-4 text-sm font-medium text-accent-ink">Reload</button>
      <a href="/library" className="inline-flex h-10 items-center rounded-[var(--radius-control)] border border-ink-700 bg-ink-800 px-4 text-sm">My renders</a>
    </div>} />;
}

export function NotFoundPage() {
  return <Empty title="Page not found" line="The link may be mistyped."
    action={<Link to="/" className="text-accent hover:underline">Go to the start</Link>} />;
}
