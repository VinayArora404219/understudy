import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Job, JobProgress } from "../api/types";
import { CompareSlider } from "../components/CompareSlider";
import { PersonThumb } from "../components/PeoplePicker";
import { aspectOf, Button, Card, cx, formatEta, Pill, Spinner } from "../components/ui";
import { PreviewStep } from "./CreatePage";

const ACTIVE = new Set(["queued", "rendering", "finishing", "matching"]);

/** Before approval (or after a failed preview, which costs nothing) the job is still a draft to look at. A job made
 *  straight to the video has no draft: it is in progress from the start. */
const isPreview = (j: Job) => !j.auto &&
  (["draft", "matching", "awaiting_approval"].includes(j.state) || (j.state === "failed" && !j.error?.refunded && !j.result));

export function JobPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { data: job, isLoading, error } = useQuery({
    queryKey: ["job", id], queryFn: () => api.job(id),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.state) ? 1500 : false),
  });
  if (isLoading) return <div className="skeleton mx-auto aspect-[9/16] max-w-sm rounded-[var(--radius-card)]" />;
  if (error || !job) {
    return <Empty title="We can't find this render" line={(error as Error)?.message ?? "It may belong to another link."} />;
  }
  return (
    <div>
      <div className="mb-8 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{job.title}</h1>
        <StatePill job={job} />
      </div>
      {isPreview(job) ? <PreviewStep job={job} onBack={() => nav("/create")} backLabel="Start a new one" />
        : job.state === "done" && job.result ? <Result job={job} />
        : job.state === "failed" || job.state === "cancelled" ? <FailedWithChoices job={job} />
        : <InProgress job={job} />}
    </div>
  );
}

function StatePill({ job }: { job: Job }) {
  if (job.state === "done") return <Pill tone="ok">Ready</Pill>;
  if (job.state === "failed") return <Pill tone="bad">Didn't finish</Pill>;
  if (job.state === "cancelled") return <Pill>Cancelled</Pill>;
  if (job.state === "awaiting_approval") return <Pill tone="warn">Waiting for your approval</Pill>;
  if (job.state === "draft") return <Pill>Not started</Pill>;
  if (job.state === "matching") return <Pill tone="accent"><Spinner className="h-3 w-3" /> {job.auto ? "Getting ready" : "Building preview"}</Pill>;
  return <Pill tone="accent"><Spinner className="h-3 w-3" /> In progress</Pill>;
}

const STAGES: [JobProgress["stage"], string][] = [
  ["dressing", "Putting on the new clothes"],
  ["completing", "Drawing the rest of a character's body"],
  ["waiting_for_gpu", "Waiting for a GPU"],
  ["starting_gpu", "Starting the GPU"],
  ["loading_models", "Loading the models"],
  ["rendering", "Rendering your video"],
  ["finishing", "Adding your audio and finishing"],
];

function InProgress({ job }: { job: Job }) {
  const qc = useQueryClient();
  const cancel = useMutation({ mutationFn: () => api.cancel(job.id), onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["job", job.id] });
    qc.invalidateQueries({ queryKey: ["session"] });
  } });
  const p = job.progress;
  // the clothes step only for jobs that have one
  const dressing = !!(job.params.outfits?.some(Boolean) || (job.params.mode === "recast" && job.params.outfit));
  const stages = STAGES.filter(([s]) => (s !== "dressing" || dressing) && (s !== "completing" || p?.stage === "completing"));
  const current = p ? Math.max(0, stages.findIndex(([s]) => s === p.stage)) : 0;
  // A sheet of cut-outs ("cast") is what the model works from, not how the video starts: show who was chosen
  const sheet = job.preview?.kind === "cast";
  const start = sheet ? job.preview?.frame_url : job.preview?.reference_url ?? job.preview?.frame_url;
  // before the server has a picture (the first seconds after submitting), the clip itself, never a black box
  const clip = job.inputs?.find((i) => i.kind === "video")?.thumb_url;
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,380px)_1fr]">
      <div className="relative self-start overflow-hidden rounded-[var(--radius-card)] border border-ink-700" style={aspectOf(job.aspect)}>
        {job.preview?.first_url
          ? <video src={job.preview.first_url} poster={job.preview.first_frame_url} autoPlay loop muted playsInline aria-label="The start of your video" className="h-full w-full object-cover opacity-60" />
          : start ? <img src={start} alt={sheet ? "Who you chose, in your first frame" : "Starting frame"} className="h-full w-full object-cover opacity-60" />
          : clip && <img src={clip} alt="Your clip" className="h-full w-full object-cover opacity-60" />}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-5 text-sm">
          {job.preview?.first_url || (start && !sheet && start === job.preview?.reference_url)
            ? "This is where your video starts." : start ? "Who you chose, in your first frame." : "Your clip."}</div>
      </div>
      <div className="space-y-6 self-start">
      <Card className="p-6">
        {!!job.preview?.cast?.length && ( // who becomes whom, while it is made
          <div className="mb-6 flex flex-wrap gap-4 border-b border-ink-700/70 pb-6">
            {job.preview.cast.map((c) => (
              <figure key={c.person} className="flex flex-col items-center gap-1">
                <div className="flex items-center gap-2">
                  <PersonThumb frameUrl={c.frame_url} box={c.box} className="h-16 w-auto max-w-16" />
                  <span aria-hidden className="text-ink-500">→</span>
                  <img src={c.character_url} alt={c.text || "Character"} className="h-16 w-16 rounded-lg object-cover" />
                </div>
                <figcaption className="text-xs text-ink-500">Person {c.person}</figcaption>
              </figure>
            ))}
          </div>
        )}
        <ol className="space-y-4">
          {stages.map(([s, label], i) => (
            <li key={s} className="flex items-center gap-3 text-sm">
              <span className={cx("grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold",
                i < current && "bg-accent text-accent-ink", i === current && "bg-ink-100 text-ink-950", i > current && "bg-ink-800 text-ink-500")}>
                {i < current ? "✓" : i === current ? <Spinner className="h-3 w-3" /> : i + 1}
              </span>
              <span className={i === current ? "text-ink-100" : i < current ? "text-ink-300" : "text-ink-500"}>
                {label}
                {i === current && s === "waiting_for_gpu" && p?.queue_position ? ` · ${p.queue_position} ahead of you` : ""}
                {i === current && s === "rendering" && p?.step
                  ? (p.segments ?? 1) > 1 ? ` · part ${p.segment ?? 1} of ${p.segments}, step ${p.step} of ${p.steps}`
                    : ` · step ${p.step} of ${p.steps}`
                  : ""}
              </span>
            </li>
          ))}
        </ol>
        {p?.stage === "rendering" && p.step && p.steps && (
          <div className="mt-6 h-1.5 overflow-hidden rounded-full bg-ink-800">
            <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${(((p.segment ?? 1) - 1) * p.steps + p.step) / ((p.segments ?? 1) * p.steps) * 100}%` }} />
          </div>
        )}
        <p className="mt-6 text-sm text-ink-300">
          {p?.eta_seconds !== undefined ? `Ready in ${formatEta(p.eta_seconds)}.` : "Starting…"}{" "}
          You can close this tab; it will be waiting in <Link to="/library" className="text-accent hover:underline">My renders</Link>.
        </p>
        <div className="mt-6 flex justify-end">
          <Button variant="danger" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancel and refund</Button>
        </div>
      </Card>
      <Choices job={job} />
      </div>
    </div>
  );
}

const MODE_NAMES: Record<string, string> = { recast: "Recast", restyle: "Restyle", swap: "Restage" };

/** What the visitor chose for this video: the pictures, then every setting in words. */
function Choices({ job, className }: { job: Job; className?: string }) {
  const { data: styles } = useQuery({ queryKey: ["styles"], queryFn: () => api.styles() });
  const p = job.params;
  const rows: [string, string][] = [["Mode", MODE_NAMES[p.mode] ?? p.mode], ["Length", `${p.motion.length} s`]];
  const chars = p.characters ?? [];
  chars.forEach((c, i) => rows.push([chars.length === 1 ? "Character" : chars.length === 2 ? (i ? "Right" : "Left") : `Character ${i + 1}`, c.text]));
  const outfits = p.outfits ?? (p.outfit ? [p.outfit] : []);
  outfits.forEach((o, i) => o && rows.push([outfits.length === 1 ? "Outfit" : `Outfit, person ${i + 1} from the left`, o.text]));
  if (p.style) rows.push(["Look", styles?.find((x) => x.key === p.style)?.name ?? p.style]);
  if (p.mode !== "restyle") {
    rows.push(["Place", p.place.mode === "keep" ? "Your clip's own" : p.place.mode === "describe" ? p.place.text ?? "Described"
      : p.place.mode === "character" ? "The character's photo" : "From your picture"]);
  }
  rows.push(["Quality", p.finish === "480p" ? "Native" : `${p.finish} (upscaled)`]);
  rows.push(["Sound", p.audio === "mute" ? "Muted" : "Your clip's own"]);
  rows.push(["Made", job.auto ? "Straight away" : "From a draft you approved"]);
  return (
    <Card className={cx("self-start p-5", className)}>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-500">Your choices</h2>
      {!!job.inputs?.length && (
        <div className="mt-3 flex flex-wrap gap-3">
          {job.inputs.map((x, i) => (
            <figure key={i} className="w-[72px]">
              <img src={x.thumb_url} alt={x.label} className="h-[72px] w-[72px] rounded-xl border border-ink-700 object-cover" />
              <figcaption className="mt-1 truncate text-center text-[11px] text-ink-500">{x.label}</figcaption>
            </figure>
          ))}
        </div>
      )}
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {rows.map(([k, v], i) => (
          <div key={i} className="contents"><dt className="text-ink-500">{k}</dt><dd className="text-ink-100">{v}</dd></div>
        ))}
      </dl>
    </Card>
  );
}

function Result({ job }: { job: Job }) {
  const r = job.result!;
  const [view, setView] = useState<"compare" | "result" | "side">("compare");
  const [w, h] = job.aspect ?? [9, 16];
  // the player is as large as the screen allows in the video's own shape; nothing is cropped
  const fit = { width: `min(100%, calc(70vh * ${w} / ${h}))` };
  const pill = "inline-flex h-11 items-center rounded-[var(--radius-control)] border border-ink-700 bg-ink-800 px-4";
  const poster = job.preview?.first_frame_url ?? job.preview?.reference_url;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="relative overflow-hidden rounded-[var(--radius-card)] border border-ink-700 bg-ink-950 p-4 sm:p-6">
        {poster && (  // the video's own colours behind it, instead of empty bars
          <img src={poster} alt="" aria-hidden
            className="pointer-events-none absolute inset-0 h-full w-full scale-110 object-cover opacity-40 blur-3xl" />
        )}
        <div className="relative mb-4 flex justify-center">
          <div className="inline-flex rounded-[var(--radius-control)] bg-ink-900/80 p-1 text-sm backdrop-blur">
            {([["compare", "Before / after"], ["result", "Result"], ["side", "Side by side"]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setView(k)} className={cx("rounded-[10px] px-3.5 py-2",
                view === k ? "bg-ink-700 text-ink-100" : "text-ink-300 hover:text-ink-100")}>{l}</button>
            ))}
          </div>
        </div>
        <div className="relative mx-auto" style={view === "side" ? undefined : fit}>
          {view === "compare"
            ? <CompareSlider before={r.source_url} after={r.video_url} poster={poster}
                beforePoster={job.preview?.frame_url} aspect={job.aspect} />
            : <video key={view} src={view === "side" ? r.compare_url : r.video_url} poster={poster}
                controls autoPlay loop playsInline className="max-h-[70vh] w-full rounded-[var(--radius-card)] bg-ink-900 object-contain"
                style={view === "side" ? undefined : aspectOf(job.aspect)} />}
        </div>
        {api.isMock && <p className="relative mt-3 text-center text-xs text-warn">Preview build: this is your own clip played back, not a render.</p>}
      </div>

      <aside className="space-y-4">
        <Choices job={job} />
        <Card className="p-5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-500">Details</h2>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 text-sm">
            <dt className="text-ink-500">Rendered at</dt><dd>{r.native_resolution}</dd>
            <dt className="text-ink-500">Delivered at</dt><dd>{r.delivered_resolution}</dd>
            <dt className="text-ink-500">Render time</dt><dd>{Math.round(r.render_seconds / 60)} min</dd>
            <dt className="text-ink-500">Models</dt><dd>{r.models ?? "Wan Animate-2, Qwen-Image-Edit-2511"}</dd>
            <dt className="text-ink-500">Seed</dt><dd className="font-mono">{job.preview?.seed ?? "—"}</dd>
          </dl>
          <p className="mt-4 text-xs text-ink-500">AI-generated, open weights. The recipe has the exact graph, inputs and settings behind this video.</p>
        </Card>
        <a href={r.video_url} download className="flex h-12 w-full items-center justify-center rounded-[var(--radius-control)] bg-accent font-medium text-accent-ink hover:brightness-105">
          Download video
        </a>
        <div className="flex flex-wrap gap-3">
          <a href={r.compare_url} download className={pill}>Side by side</a>
          <a href={r.recipe_url} download="recipe.json" className={pill}>Recipe</a>
          <Link to="/create" className={pill}>Make another</Link>
        </div>
      </aside>
    </div>
  );
}

function Failed({ job }: { job: Job }) {
  const qc = useQueryClient();
  // a refunded render keeps its approved preview: run it again without redoing the setup
  const again = useMutation({ mutationFn: () => api.approve(job.id), onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["job", job.id] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["session"] });
  } });
  const rerun = !!job.error?.refunded && !!job.preview;
  const button = "mt-6 inline-flex h-11 items-center rounded-[var(--radius-control)] px-4 font-medium";
  return (
    <Card className="max-w-xl p-6">
      <p className="text-ink-100">{job.error?.message ?? "This render didn't finish."}</p>
      {job.error?.refunded && <p className="mt-2 text-sm text-ok">Your render was refunded.</p>}
      {again.isError && <p className="mt-2 text-sm text-bad">{(again.error as Error).message}</p>}
      <div className="flex flex-wrap gap-3">
        {rerun && (
          <button onClick={() => again.mutate()} disabled={again.isPending}
            className={cx(button, "bg-accent text-accent-ink disabled:opacity-60")}>
            {again.isPending ? "Starting…" : "Render again"}
          </button>
        )}
        <Link to="/create" className={cx(button, rerun ? "border border-ink-700 text-ink-100" : "bg-accent text-accent-ink")}>
          {rerun ? "Start over" : "Try again"}
        </Link>
      </div>
    </Card>
  );
}

function FailedWithChoices({ job }: { job: Job }) {
  return <div className="grid gap-6 lg:grid-cols-[minmax(0,36rem)_1fr]"><Failed job={job} /><Choices job={job} /></div>;
}

export function Empty({ title, line, action }: { title: string; line: string; action?: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="mt-2 text-ink-300">{line}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
