import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CompareSlider } from "../components/CompareSlider";
import { Card, Pill } from "../components/ui";

const MODES = [
  { key: "recast", name: "Recast", line: "Your performance, played by any character: a person, a mascot, your cat. Up to two performers at once.",
    swatch: "from-[#c8f560]/30 to-[#7dd3fc]/10" },
  { key: "restyle", name: "Restyle", line: "The same video, redrawn: anime, toy figure, pixel art, comic ink.",
    swatch: "from-[#f0abfc]/30 to-[#7dd3fc]/10" },
  { key: "swap", name: "Restage", line: "You stay you. Change one thing: your outfit or the place.",
    swatch: "from-[#fde68a]/30 to-[#f9a8d4]/10" },
];

const STEPS = [
  ["Pick a motion", "Film 4–30 seconds on your phone, or start from one of ours."],
  ["Choose what changes", "Someone else performs, everything gets a new look, or you stay and one thing changes."],
  ["Approve, then render", "See a preview first. Only then does the video render."],
];

export function LandingPage() {
  const { data: gallery } = useQuery({ queryKey: ["gallery"], queryFn: () => api.gallery() });
  return (
    <div className="space-y-24">
      <section className="grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <Pill tone="accent">Open weights, end to end</Pill>
          <h1 className="mt-5 text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
            Film a move.<br />Become anyone.
          </h1>
          <p className="mt-6 max-w-xl text-lg text-ink-300">
            Recast your performance as any character, redraw it in a new look, or move it to a new
            place. Same motion, same timing, your own audio.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/create" className="inline-flex h-14 items-center rounded-[var(--radius-control)] bg-accent px-6 font-medium text-accent-ink hover:brightness-105">
              Start creating
            </Link>
            <a href="#how" className="inline-flex h-14 items-center rounded-[var(--radius-control)] border border-ink-700 bg-ink-800 px-6 font-medium hover:bg-ink-700">
              How it works
            </a>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-500">
            <li>Pay by the second, refunded if it fails</li>
            <li>Every result comes with its recipe</li>
            <li>Runs on your own GPU too</li>
          </ul>
        </div>
        <div className="mx-auto w-full max-w-sm">
          {gallery?.[0] ? (
            <CompareSlider before={gallery[0].before_url} after={gallery[0].after_url} poster={gallery[0].poster_url}
              labels={["Original", gallery[0].mode]} />
          ) : (
            <div className="relative aspect-[9/16] overflow-hidden rounded-[var(--radius-card)] border border-ink-700 bg-gradient-to-br from-ink-800 to-ink-900">
              <div className="absolute inset-0 grid place-items-center p-8 text-center text-sm text-ink-500">
                Before and after examples appear here once our cleared demo clips are rendered.
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        {MODES.map((m) => (
          <Link key={m.key} to={`/create?mode=${m.key}`} className="group">
            <Card className="h-full overflow-hidden transition-colors group-hover:border-ink-500">
              <div className={`h-28 bg-gradient-to-br ${m.swatch}`} />
              <div className="p-6">
                <h3 className="text-lg font-semibold">{m.name} <span className="text-ink-500 transition-transform group-hover:translate-x-0.5">→</span></h3>
                <p className="mt-2 text-sm text-ink-300">{m.line}</p>
              </div>
            </Card>
          </Link>
        ))}
      </section>

      <section id="how" className="scroll-mt-24">
        <h2 className="text-3xl font-semibold tracking-tight">How it works</h2>
        <ol className="mt-8 grid gap-4 md:grid-cols-3">
          {STEPS.map(([title, line], i) => (
            <li key={title} className="rounded-[var(--radius-card)] border border-ink-700/70 bg-ink-900 p-6">
              <div className="grid h-8 w-8 place-items-center rounded-full bg-ink-800 text-sm font-semibold text-accent">{i + 1}</div>
              <h3 className="mt-4 font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm text-ink-300">{line}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-[var(--radius-card)] border border-ink-700/70 bg-ink-900 p-8 sm:p-10">
        <h2 className="text-2xl font-semibold tracking-tight">Nothing hidden</h2>
        <div className="mt-6 grid gap-6 text-sm text-ink-300 md:grid-cols-3">
          <p><span className="block font-medium text-ink-100">Open models only</span>
            SCAIL-2 recasts the performers, Wan VACE restyles the whole clip frame by frame, and Qwen-Image-Edit builds starting frames. All open weights, with no closed API anywhere; every model and license is in the recipe.</p>
          <p><span className="block font-medium text-ink-100">Reproducible</span>
            Each result ships a recipe: input hashes, every setting, the seed, the models and the exact ComfyUI graph it ran, which opens in ComfyUI, plus every step done after it.</p>
          <p><span className="block font-medium text-ink-100">Honest output</span>
            We show the native resolution, when a file is upscaled, and how long it took. Results are labelled as AI-generated.</p>
        </div>
      </section>
    </div>
  );
}
