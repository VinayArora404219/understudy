import { Link } from "react-router-dom";
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

export function NotFoundPage() {
  return <Empty title="Page not found" line="The link may be mistyped."
    action={<Link to="/" className="text-accent hover:underline">Go to the start</Link>} />;
}
