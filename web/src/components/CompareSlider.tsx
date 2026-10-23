import { useEffect, useRef, useState } from "react";
import { aspectOf } from "./ui";

/** Before/after wipe over two synchronised videos (or stills). Drag, tap or use arrow keys. */
export function CompareSlider({ before, after, poster, beforePoster, kind = "video", labels = ["Original", "Recast"], aspect }: {
  aspect?: [number, number]; // the result's shape; both layers are centre-cropped to it, as the result was
  beforePoster?: string; // the original's still, shown until its video plays (never the result's)
  before: string;
  after: string;
  poster?: string;
  kind?: "video" | "image";
  labels?: [string, string];
}) {
  const [pos, setPos] = useState(50);
  const box = useRef<HTMLDivElement>(null);
  const a = useRef<HTMLVideoElement>(null);
  const b = useRef<HTMLVideoElement>(null);

  // keep the two clips on the same frame
  useEffect(() => {
    if (kind !== "video") return;
    const lead = b.current, follow = a.current;
    if (!lead || !follow) return;
    const sync = () => {
      if (Math.abs(follow.currentTime - lead.currentTime) > 0.06) follow.currentTime = lead.currentTime;
    };
    lead.addEventListener("timeupdate", sync);
    lead.addEventListener("seeked", sync);
    return () => {
      lead.removeEventListener("timeupdate", sync);
      lead.removeEventListener("seeked", sync);
    };
  }, [kind, before, after]);

  const move = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    setPos(Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100)));
  };

  const media = (src: string, ref?: React.RefObject<HTMLVideoElement | null>, still = poster) =>
    kind === "video" ? (
      <video ref={ref} src={src} poster={still} autoPlay muted loop playsInline className="h-full w-full object-cover" />
    ) : (
      <img src={src} alt="" className="h-full w-full object-cover" />
    );

  return (
    <div
      ref={box}
      className="relative w-full select-none overflow-hidden rounded-[var(--radius-card)] bg-ink-900 touch-none"
      style={aspectOf(aspect)}
      onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture?.(e.pointerId); move(e.clientX); }}
      onPointerMove={(e) => { if (e.buttons) move(e.clientX); }}
      role="slider"
      aria-label="Compare original and result"
      aria-valuenow={Math.round(pos)}
      aria-valuemin={0}
      aria-valuemax={100}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") setPos((p) => Math.max(0, p - 5));
        if (e.key === "ArrowRight") setPos((p) => Math.min(100, p + 5));
      }}
    >
      <div className="absolute inset-0">{media(after, b)}</div>
      <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}>{media(before, a, beforePoster ?? poster)}</div>
      <div className="pointer-events-none absolute inset-y-0" style={{ left: `${pos}%` }}>
        <div className="absolute inset-y-0 -left-px w-0.5 bg-white/90 shadow-[0_0_12px_rgba(0,0,0,0.6)]" />
        <div className="absolute top-1/2 -left-4 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-white text-ink-950 text-xs font-bold shadow-lg">⇆</div>
      </div>
      <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-xs font-medium backdrop-blur">{labels[0]}</span>
      <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-xs font-medium backdrop-blur">{labels[1]}</span>
    </div>
  );
}
