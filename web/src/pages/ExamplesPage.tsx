import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { GalleryItem } from "../api/types";
import { CompareSlider } from "../components/CompareSlider";
import { aspectOf, Card, cx, Pill } from "../components/ui";

const MODES = ["All", "Recast", "Restyle", "Restage"] as const;

/** Examples already made here, each with the clip, pictures and settings behind it: watch one, then start
 *  from it (Recreate copies them into the visitor's own uploads). */
export function ExamplesPage() {
  const { data: items, isLoading } = useQuery({ queryKey: ["gallery"], queryFn: () => api.gallery() });
  const [search, setSearch] = useSearchParams();
  const [mode, setMode] = useState<(typeof MODES)[number]>("All");
  const open = items?.find((x) => x.id === search.get("item"));
  const shown = (items ?? []).filter((x) => mode === "All" || x.mode === mode);
  const show = (id?: string) => setSearch(id ? { item: id } : {}, { replace: true });

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Examples</h1>
      <p className="mt-3 max-w-2xl text-ink-300">
        Every video here was made by this app, on open weights, from the clip and pictures shown with it. Watch one
        before and after, then recreate it: the same clip, people, pictures and settings come with it, ready to change.
      </p>
      <div className="mt-6 inline-flex rounded-[var(--radius-control)] bg-ink-900 p-1 text-sm" role="tablist">
        {MODES.map((m) => (
          <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)} className={cx(
            "rounded-[10px] px-4 py-2 transition-colors", mode === m ? "bg-ink-700 text-ink-100" : "text-ink-300 hover:text-ink-100",
          )}>{m}</button>
        ))}
      </div>

      <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {isLoading && [0, 1, 2].map((i) => <div key={i} className="skeleton aspect-[4/5] rounded-[var(--radius-card)]" />)}
        {shown.map((x) => (
          <Card key={x.id} className="flex flex-col overflow-hidden">
            <button onClick={() => show(x.id)} className="group relative block aspect-[4/5] overflow-hidden bg-ink-900"
              aria-label={`Watch ${x.title}`}>
              {x.aspect && x.aspect[0] > x.aspect[1] ? <>{/* a wide video: the whole frame, its own colours behind it */}
                <img src={x.poster_url} alt="" aria-hidden className="absolute inset-0 h-full w-full scale-110 object-cover opacity-40 blur-2xl" />
                <img src={x.poster_url} alt="" loading="lazy" className="relative h-full w-full object-contain transition group-hover:scale-[1.02]" />
              </> : <img src={x.poster_url} alt="" loading="lazy" className="h-full w-full object-cover transition group-hover:scale-[1.02]" />}
              <span className="absolute left-3 top-3 rounded-full bg-ink-950/80 backdrop-blur"><Pill tone="accent">{x.mode}</Pill></span>
              <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-4 text-left text-sm text-ink-100">
                ▶ Watch before and after{x.seconds ? ` · ${x.seconds} s` : ""}
              </span>
            </button>
            <div className="flex flex-1 flex-col p-4">
              <h2 className="font-semibold">{x.title}</h2>
              {x.line && <p className="mt-1 text-sm text-ink-300">{x.line}</p>}
              <Thumbs item={x} />
              <div className="mt-auto flex gap-2 pt-4">
                <Link to={`/create?example=${x.id}`}
                  className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-accent px-4 text-sm font-medium text-accent-ink hover:brightness-105">
                  Recreate this
                </Link>
                <button onClick={() => show(x.id)}
                  className="inline-flex h-10 items-center rounded-[var(--radius-control)] border border-ink-700 bg-ink-800 px-4 text-sm">Watch</button>
              </div>
            </div>
          </Card>
        ))}
        {items?.length === 0 && <p className="col-span-full text-ink-500">No examples on this server yet.</p>}
      </div>

      {open && <Viewer item={open} onClose={() => show()} />}
    </div>
  );
}

function Thumbs({ item }: { item: GalleryItem }) {
  return (
    <div className="mt-3 flex flex-wrap items-start gap-3">
      {item.choices.map((c, i) => (
        <div key={i} className="w-16 text-center">
          {c.thumb_url
            ? <img src={c.thumb_url} alt="" className="h-16 w-16 rounded-lg border border-ink-700 object-cover" />
            : <div className="grid h-16 w-16 place-items-center rounded-lg border border-ink-700 bg-ink-900 p-1 text-[10px] leading-tight text-ink-300">{c.text}</div>}
          <div className="mt-1 truncate text-[11px] text-ink-500" title={c.text ?? c.label}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function Viewer({ item, onClose }: { item: GalleryItem; onClose: () => void }) {
  const [view, setView] = useState<"compare" | "result" | "side">("compare");
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const [w, h] = item.aspect ?? [9, 16];
  const fit = { width: `min(100%, calc(70vh * ${w} / ${h}))` };
  const pill = "inline-flex h-10 items-center rounded-[var(--radius-control)] border border-ink-700 bg-ink-800 px-4 text-sm";
  return (
    <div className="fixed inset-0 z-30 overflow-y-auto bg-black/75 p-4 backdrop-blur-sm sm:p-8" onClick={onClose} role="dialog"
      aria-modal aria-label={item.title}>
      <div className="mx-auto grid max-w-6xl gap-6 rounded-[var(--radius-card)] border border-ink-700 bg-ink-950 p-4 sm:p-6 lg:grid-cols-[1fr_320px]"
        onClick={(e) => e.stopPropagation()}>
        <div>
          <div className="mb-4 flex justify-center">
            <div className="inline-flex rounded-[var(--radius-control)] bg-ink-900 p-1 text-sm">
              {([["compare", "Before / after"], ["result", "Result"], ["side", "Side by side"]] as const).map(([k, l]) => (
                <button key={k} onClick={() => setView(k)} className={cx("rounded-[10px] px-3.5 py-2",
                  view === k ? "bg-ink-700 text-ink-100" : "text-ink-300 hover:text-ink-100")}>{l}</button>
              ))}
            </div>
          </div>
          <div className="mx-auto" style={view === "side" ? undefined : fit}>
            {view === "compare"
              ? <CompareSlider before={item.before_url} after={item.after_url} poster={item.poster_url}
                  labels={["Original", item.mode]} aspect={item.aspect ?? undefined} />
              : <video key={view} src={view === "side" ? item.compare_url : item.after_url} poster={item.poster_url}
                  controls autoPlay loop playsInline className="max-h-[70vh] w-full rounded-[var(--radius-card)] bg-ink-900 object-contain"
                  style={view === "side" ? undefined : aspectOf(item.aspect ?? undefined)} />}
          </div>
        </div>
        <aside className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Pill tone="accent">{item.mode}</Pill>
              <h2 className="mt-2 text-xl font-semibold">{item.title}</h2>
            </div>
            <button onClick={onClose} className="rounded-lg px-2 py-1 text-ink-300 hover:text-ink-100" aria-label="Close">✕</button>
          </div>
          {item.line && <p className="text-sm text-ink-300">{item.line}</p>}
          <Card className="p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-500">What went in</h3>
            <Thumbs item={item} />
            {item.summary && <p className="mt-3 text-xs text-ink-500">The video followed: “{item.summary}”</p>}
          </Card>
          <Link to={`/create?example=${item.id}`}
            className="flex h-12 w-full items-center justify-center rounded-[var(--radius-control)] bg-accent font-medium text-accent-ink hover:brightness-105">
            Recreate this
          </Link>
          <p className="text-xs text-ink-500">Opens Create with this clip, the people chosen in it, the pictures and every setting.
            Change anything before you make it; credits are used only when you make the video.</p>
          <div className="flex flex-wrap gap-3">
            <a href={item.compare_url} download className={pill}>Side by side</a>
            <a href={item.recipe_url} download="recipe.json" className={pill}>Recipe</a>
          </div>
        </aside>
      </div>
    </div>
  );
}
