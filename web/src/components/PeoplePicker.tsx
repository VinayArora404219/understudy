import { useEffect, useMemo, useRef, useState } from "react";
import type { Person } from "../api/types";
import { cx } from "./ui";

/** One colour per person found, so a number and an outline are easy to match up. Chosen ones turn accent. */
const COLOURS: [number, number, number][] = [
  [125, 211, 252], [240, 171, 252], [253, 186, 116], [134, 239, 172],
  [253, 224, 71], [167, 139, 250], [251, 113, 133], [94, 234, 212],
];
const ACCENT: [number, number, number] = [200, 245, 96];
const rgb = (c: [number, number, number]) => `rgb(${c[0]} ${c[1]} ${c[2]})`;

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((ok, bad) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => bad(new Error(`could not load ${src}`));
    img.src = src;
  });
}

interface Shapes {
  w: number;
  h: number;
  frame: ImageData;
  owner: Int16Array; // index into people of the one in front at each pixel, -1 for nobody
  edge: Int16Array; // the same, on each person's outline only
}

/** Each person's mask, read once: who is under each pixel (the smallest mask wins, as the server's tap
 *  rule does) and where their outlines run. Without a mask (the mock) the box stands in. */
async function readShapes(frameUrl: string, people: Person[]): Promise<Shapes> {
  const frame = await loadImage(frameUrl);
  const w = frame.naturalWidth, h = frame.naturalHeight;
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d", { willReadFrequently: true })!;
  g.drawImage(frame, 0, 0);
  const base = g.getImageData(0, 0, w, h);
  const owner = new Int16Array(w * h).fill(-1);
  const area = new Float64Array(people.length);
  const insides: Uint8Array[] = [];
  for (const [i, p] of people.entries()) {
    const inside = new Uint8Array(w * h);
    if (p.mask_url) {
      g.clearRect(0, 0, w, h);
      g.drawImage(await loadImage(p.mask_url), 0, 0, w, h);
      const px = g.getImageData(0, 0, w, h).data;
      for (let k = 0; k < w * h; k++) inside[k] = px[k * 4] > 127 ? 1 : 0;
    } else {
      const [bx, by, bw, bh] = p.box;
      for (let y = Math.floor(by * h); y < Math.min(h, (by + bh) * h); y++)
        for (let x = Math.floor(bx * w); x < Math.min(w, (bx + bw) * w); x++) inside[y * w + x] = 1;
    }
    insides.push(inside);
    area[i] = p.area;
  }
  const order = people.map((_, i) => i).sort((a, b) => area[b] - area[a]); // biggest first, smallest drawn last
  for (const i of order) {
    const inside = insides[i];
    for (let k = 0; k < w * h; k++) if (inside[k]) owner[k] = i;
  }
  const edge = new Int16Array(w * h).fill(-1);
  const r = Math.max(2, Math.round(Math.min(w, h) / 220)); // about 2 px on a 480 px frame
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = owner[y * w + x];
      if (i < 0) continue;
      const inside = insides[i];
      const out = (xx: number, yy: number) => xx < 0 || yy < 0 || xx >= w || yy >= h || !inside[yy * w + xx];
      if (out(x - r, y) || out(x + r, y) || out(x, y - r) || out(x, y + r)) edge[y * w + x] = i;
    }
  }
  return { w, h, frame: base, owner, edge };
}

/** The start frame with everyone found outlined and numbered; a tap on someone chooses or frees them.
 *  The numbers match Person.id, left to right. */
export function PeoplePicker({ frameUrl, people, picks, onToggle }: {
  frameUrl: string; people: Person[]; picks: number[]; onToggle: (id: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [shapes, setShapes] = useState<Shapes>();
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState(-1);
  const key = useMemo(() => frameUrl + people.map((p) => p.mask_url ?? p.box.join()).join("|"), [frameUrl, people]);

  useEffect(() => {
    let live = true;
    setShapes(undefined);
    setFailed(false);
    readShapes(frameUrl, people).then((s) => live && setShapes(s)).catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!shapes || !canvas.current) return;
    const { w, h, frame, owner, edge } = shapes;
    const chosen = people.map((p) => picks.includes(p.id));
    const any = chosen.some(Boolean);
    const out = new ImageData(w, h);
    const src = frame.data, dst = out.data;
    for (let k = 0; k < w * h; k++) {
      const i = owner[k], e = edge[k], o = k * 4;
      let r = src[o], g = src[o + 1], b = src[o + 2];
      if (e >= 0) {
        [r, g, b] = chosen[e] ? ACCENT : COLOURS[e % COLOURS.length];
      } else if (i >= 0) {
        const c = chosen[i] ? ACCENT : COLOURS[i % COLOURS.length];
        const a = chosen[i] ? 0.22 : i === hover ? 0.3 : any ? 0 : 0.14;
        if (any && !chosen[i]) { r *= 0.45; g *= 0.45; b *= 0.45; }
        r += (c[0] - r) * a; g += (c[1] - g) * a; b += (c[2] - b) * a;
      } else if (any) {
        r *= 0.45; g *= 0.45; b *= 0.45;
      }
      dst[o] = r; dst[o + 1] = g; dst[o + 2] = b; dst[o + 3] = 255;
    }
    canvas.current.width = w;
    canvas.current.height = h;
    canvas.current.getContext("2d")!.putImageData(out, 0, 0);
  }, [shapes, picks, hover, people]);

  const at = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!shapes) return -1;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.floor(((e.clientX - rect.left) / rect.width) * shapes.w);
    const y = Math.floor(((e.clientY - rect.top) / rect.height) * shapes.h);
    return x < 0 || y < 0 || x >= shapes.w || y >= shapes.h ? -1 : shapes.owner[y * shapes.w + x];
  };

  if (failed) {
    return <img src={frameUrl} alt="The first frame of your clip" className="max-h-[65vh] max-w-full rounded-xl" />;
  }
  return (
    <div className="relative inline-block max-w-full align-top">
      {!shapes && <div className="skeleton aspect-[9/16] h-[50vh] max-w-full rounded-xl" />}
      <canvas ref={canvas} role="img" aria-label="The first frame of your clip, with everyone we found numbered"
        className={cx("block max-h-[65vh] max-w-full rounded-xl", !shapes && "hidden", hover >= 0 && "cursor-pointer")}
        onClick={(e) => { const i = at(e); if (i >= 0) onToggle(people[i].id); }}
        onMouseMove={(e) => { const i = at(e); if (i !== hover) setHover(i); }}
        onMouseLeave={() => setHover(-1)} />
      {shapes && people.map((p, i) => {
        const on = picks.includes(p.id);
        return (
          <button key={p.id} type="button" aria-pressed={on} aria-label={`Person ${p.id}${on ? ", chosen" : ""}`}
            onClick={() => onToggle(p.id)} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(-1)}
            className="absolute grid h-7 min-w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full px-1.5 text-xs font-bold text-ink-950 shadow-md ring-2 ring-black/40"
            style={{ left: `${(p.box[0] + p.box[2] / 2) * 100}%`, top: `${Math.max(0.03, p.box[1]) * 100}%`,
              background: rgb(on ? ACCENT : COLOURS[i % COLOURS.length]) }}>
            {on ? `✓ ${p.id}` : p.id}
          </button>
        );
      })}
    </div>
  );
}

/** One person cut from the frame, for the character slot that replaces them. */
export function PersonThumb({ frameUrl, box, className }: { frameUrl: string; box: Person["box"]; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let live = true;
    loadImage(frameUrl).then((img) => {
      const c = ref.current;
      if (!live || !c) return;
      const W = img.naturalWidth, H = img.naturalHeight, pad = 0.04;
      const x = Math.max(0, (box[0] - pad) * W), y = Math.max(0, (box[1] - pad) * H);
      const w = Math.min(W - x, (box[2] + 2 * pad) * W), h = Math.min(H - y, (box[3] + 2 * pad) * H);
      const s = 160 / Math.max(w, h);
      c.width = Math.round(w * s);
      c.height = Math.round(h * s);
      c.getContext("2d")!.drawImage(img, x, y, w, h, 0, 0, c.width, c.height);
    }).catch(() => {});
    return () => { live = false; };
  }, [frameUrl, box]);
  return <canvas ref={ref} className={cx("rounded-lg bg-ink-800 object-contain", className)} aria-hidden />;
}
