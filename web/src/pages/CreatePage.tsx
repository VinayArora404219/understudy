import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CharacterRef, ImageRole, Job, JobParams, Mode, MotionPreset, Person, PlaceMode, Upload } from "../api/types";
import { Dropzone } from "../components/Dropzone";
import { PeoplePicker, PersonThumb } from "../components/PeoplePicker";
import { aspectOf, Button, Card, CheckList, cx, Pill, SectionTitle, Spinner } from "../components/ui";

type Step = "motion" | "change" | "preview";
const SHORTEST = 2, LONGEST = 20; // seconds; the server holds the same bounds
/** Three separate jobs, as a visitor thinks of them. Each step 2 asks only its own question. */
const MODES: [Mode, string, string][] = [
  ["recast", "Recast", "Someone else performs your moves: a person, a mascot, an animal."],
  ["restyle", "Restyle", "Your video, redrawn in a look: anime, toy, pixel art and more."],
  ["swap", "Restage", "You stay you. New clothes, a new place, or both."],
];

const MAX_PICKS = 2; // the server's PICK_MAX: with four chosen, one half behind a kept person bled into them
const ELSEWHERE_MAX = 2; // a new place starts from one image edit, with room for two characters

/** Everyone found in the clip's start frame (`people`), and who Recast replaces (`picks`, Person ids).
 *  Words can't pick one person out of a crowd, so the visitor taps them (recast/people.py). */
interface Motion {
  upload?: Upload; preset?: MotionPreset; start: number; length: number;
  people?: { key: string; frame_url: string; list: Person[] }; picks: number[];
}
const chosenOf = (m: Motion): Person[] =>
  (m.people?.list ?? []).filter((p) => m.picks.includes(p.id)).sort((a, b) => a.cx - b.cx); // left to right
/** Recast replaces whoever was chosen; a ready-made motion (no picker) has one performer. */
const performersOf = (mode: Mode, m: Motion): number => (mode === "restyle" ? 1 : Math.max(1, m.picks.length));
/** Chosen before anyone taps: everyone, when there are one or two clear people. Something small next to a
 *  person (a football was found as one) is never chosen for them. */
function autoPicks(list: Person[]): number[] {
  const biggest = Math.max(0, ...list.map((p) => p.area));
  const clear = list.filter((p) => p.area >= biggest * 0.25);
  return clear.length <= 2 ? clear.map((p) => p.id) : []; // more than two: the visitor taps who
}
interface CharSlot { upload: Upload; text: string }
/** Restage: what one chosen person now wears, in words, with a picture of it if there is one. */
interface OutfitSlot { upload?: Upload; text: string }
interface Change {
  characters: (CharSlot | undefined)[]; // [only] or [left, right]
  style?: string;
  place: { mode: PlaceMode; text: string; upload?: Upload };
  outfits: (OutfitSlot | undefined)[]; // Restage: one per chosen person, left to right; empty keeps their clothes
  finish: JobParams["finish"];
  audio: JobParams["audio"];
  draft: boolean; // over 5 s only: a draft (the first 5 s, or the start picture) to approve before the video
}

export function CreatePage() {
  const [search] = useSearchParams();
  const initial = MODES.find(([m]) => m === search.get("mode"))?.[0] ?? "recast";
  const [mode, setMode] = useState<Mode>(initial);
  const [step, setStep] = useState<Step>("motion");
  const [motion, setMotion] = useState<Motion>({ start: 0, length: 5, picks: [] });
  const [change, setChange] = useState<Change>({ draft: false, outfits: [], characters: [], place: { mode: "keep", text: "" }, finish: "720p", audio: "original" });
  const [job, setJob] = useState<Job>();
  const { data: session } = useQuery({ queryKey: ["session"], queryFn: () => api.session() });
  // Recreate: start from a finished render's choices (?from=job id) or an example's (?example=gallery id)
  const from = search.get("from"), example = search.get("example");
  const again = useQuery({
    queryKey: ["recreate", from, example], enabled: !!(from || example), staleTime: Infinity, retry: false,
    queryFn: () => (from ? api.recreateJob(from) : api.recreateExample(example!)),
  });
  useEffect(() => {
    const r = again.data;
    if (!r) return;
    const p = r.params, up = (id?: string) => (id ? r.uploads[id] : undefined);
    setMode(p.mode);
    setMotion({ upload: up(p.motion.upload_id), preset: r.preset ?? undefined, start: p.motion.start, length: p.motion.length,
      people: r.people ?? undefined, picks: p.motion.picks ?? [] });
    setChange({ draft: false, finish: p.finish, audio: p.audio, style: p.style,
      characters: p.characters.map((c) => ({ upload: up(c.upload_id)!, text: c.text })),
      outfits: (p.outfits ?? []).map((o) => (o ? { upload: up(o.upload_id), text: o.text } : undefined)),
      place: { mode: p.place.mode, text: p.place.text ?? "", upload: up(p.place.upload_id) } });
    setStep("change");
  }, [again.data]);

  const steps: [Step, string][] = [["motion", "Motion"], ["change", "What changes"], ["preview", "Preview"]];
  const idx = steps.findIndex(([s]) => s === step);

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
      <div className="min-w-0">
        <ol className="mb-8 flex items-center gap-1.5 text-sm sm:gap-2" aria-label="Progress">
          {steps.map(([s, label], i) => (
            <li key={s} className="flex items-center gap-2">
              <span className={cx(
                "grid h-7 w-7 place-items-center rounded-full text-xs font-semibold",
                i < idx && "bg-accent text-accent-ink", i === idx && "bg-ink-100 text-ink-950", i > idx && "bg-ink-800 text-ink-500",
              )}>{i < idx ? "✓" : i + 1}</span>
              <span className={i === idx ? "text-ink-100" : "text-ink-500"}>{label}</span>
              {i < steps.length - 1 && <span className="mx-0.5 h-px w-3 bg-ink-700 sm:mx-2 sm:w-8" />}
            </li>
          ))}
        </ol>
        {again.isFetching && (
          <Card className="mb-6 flex items-center gap-3 p-5 text-sm text-ink-300"><Spinner /> Getting {from ? "your render's" : "the example's"} choices ready…</Card>
        )}
        {again.isError && <Card className="mb-6 p-5 text-sm text-bad">{(again.error as Error).message}</Card>}
        {again.data && step !== "preview" && (
          <Card className="mb-6 p-4 text-sm text-ink-300">
            Starting from {from ? "your render " : ""}<span className="font-medium text-ink-100">{again.data.title || "an earlier render"}</span>, with every
            choice as it was made. Change anything, then make the video.
          </Card>
        )}
        {step === "motion" && <MotionStep mode={mode} setMode={setMode} motion={motion} setMotion={setMotion} onNext={() => setStep("change")} />}
        {step === "change" && (
          <ChangeStep mode={mode} change={change} setChange={setChange} onBack={() => setStep("motion")}
            onPreview={(j) => { setJob(j); setStep("preview"); }} motion={motion} />
        )}
        {step === "preview" && job && <PreviewStep job={job} onBack={() => setStep("change")} />}
      </div>
      <Summary mode={mode} motion={motion} change={change} creditsLeft={session?.credits_left} />
    </div>
  );
}

/* ---------------------------------------------------------------- 1. motion */

function MotionStep({ mode, setMode, motion, setMotion, onNext }: {
  mode: Mode; setMode: (m: Mode) => void; motion: Motion; setMotion: React.Dispatch<React.SetStateAction<Motion>>; onNext: () => void;
}) {
  const [tab, setTab] = useState<"mine" | "ours">(motion.preset ? "ours" : "mine");
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => api.presets() });
  const fresh = (u: Upload, preset?: MotionPreset): Motion => ({ ...motion, upload: u, preset, start: 0, people: undefined,
    picks: [], length: Math.max(SHORTEST, Math.min(5, Math.floor(u.info.seconds ?? 5))) });
  const up = useMutation({ mutationFn: (f: File) => api.upload(f, "video"), onSuccess: (u) => setMotion(fresh(u)) });
  // a ready-made motion becomes the visitor's own upload, so who is in it is chosen the same way
  const pick = useMutation({ mutationFn: (p: MotionPreset) => api.usePreset(p.id), onSuccess: (u, p) => setMotion(fresh(u, p)) });
  const blocked = motion.upload?.checks.some((c) => c.level === "block");
  const clipSeconds = motion.upload?.info.seconds ?? motion.preset?.seconds ?? 0;
  const ready = (motion.upload && !blocked) || motion.preset;
  // Recast and Restage change chosen people, so someone must be chosen; Restyle redraws everyone
  const lookForPeople = !!motion.upload && !blocked && mode !== "restyle";
  const canGo = ready && (mode === "restyle" || !motion.upload || motion.picks.length > 0);

  return (
    <section>
      <div className="mb-10 grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="What do you want to make?">
        {MODES.map(([m, name, line]) => (
          <button key={m} role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
            className={cx("rounded-[var(--radius-card)] border p-4 text-left transition",
              mode === m ? "border-accent bg-accent/5 ring-2 ring-accent/30" : "border-ink-700 hover:border-ink-500")}>
            <div className="font-semibold">{name}</div>
            <div className="mt-1 text-sm text-ink-300">{line}</div>
          </button>
        ))}
      </div>
      <SectionTitle step="Step 1" title="Pick the motion" hint="The movement, timing and audio all come from this clip." />
      <div className="mb-5 inline-flex rounded-[var(--radius-control)] bg-ink-900 p-1 text-sm">
        {([["mine", "Use my clip"], ["ours", "Use one of ours"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} className={cx(
            "rounded-[10px] px-4 py-2 transition-colors", tab === k ? "bg-ink-700 text-ink-100" : "text-ink-300 hover:text-ink-100",
          )}>{label}</button>
        ))}
      </div>

      {tab === "mine" ? (
        <div className="space-y-5">
          {!motion.upload ? (
            <Dropzone accept="video/*" busy={up.isPending} onFile={(f) => up.mutate(f)} label="Upload a clip">
              <div className="grid h-12 w-12 place-items-center rounded-full bg-ink-800 text-xl">▶</div>
              <div className="mt-4 font-medium">Drop a clip or tap to choose</div>
              <div className="mt-1 text-sm text-ink-500">4–30 seconds · up to 90 MB · phone on a stand works best</div>
            </Dropzone>
          ) : (
            <Card className="flex flex-col gap-5 p-5 sm:flex-row">
              <img src={motion.upload.thumb_url} alt="First frame of your clip" className="h-56 w-auto self-start rounded-xl object-cover" />
              <div className="flex-1 space-y-4">
                <CheckList checks={motion.upload.checks} />
                <Button size="sm" variant="ghost" onClick={() => setMotion({ ...motion, upload: undefined, people: undefined, picks: [] })}>Use a different clip</Button>
              </div>
            </Card>
          )}
          {up.isError && <p className="text-sm text-bad">{(up.error as Error).message}</p>}
          <label className="flex items-start gap-3 text-sm text-ink-300">
            <input type="checkbox" required className="mt-1 accent-[var(--color-accent)]" defaultChecked={false} id="consent" />
            <span>Everyone recognisable in this clip has agreed to it being transformed. Required.</span>
          </label>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {presets.isLoading && [0, 1, 2].map((i) => <div key={i} className="skeleton aspect-[9/16] rounded-[var(--radius-card)]" />)}
          {presets.data?.map((p) => (
            <button key={p.id} onClick={() => pick.mutate(p)} disabled={pick.isPending}
              className={cx("relative overflow-hidden rounded-[var(--radius-card)] border text-left transition",
                motion.preset?.id === p.id ? "border-accent ring-2 ring-accent/40" : "border-ink-700 hover:border-ink-500")}>
              <img src={p.thumb_url} alt="" className="aspect-[9/16] w-full object-cover" />
              {pick.isPending && pick.variables?.id === p.id && <span className="absolute inset-0 grid place-items-center bg-black/40"><Spinner /></span>}
              <div className="p-3">
                <div className="text-sm font-medium">{p.title} <span className="font-normal text-ink-500">· {Math.round(p.seconds)} s</span></div>
                <div className="text-xs text-ink-500">{p.subtitle}</div>
                {p.credit && <div className="mt-1 text-[11px] text-ink-500">Filmed by {p.credit}</div>}
              </div>
            </button>
          ))}
          {presets.data?.length === 0 && <p className="col-span-full text-sm text-ink-500">No ready-made motions on this server yet. Use your own clip.</p>}
          {pick.isError && <p className="col-span-full text-sm text-bad">{(pick.error as Error).message}</p>}
        </div>
      )}

      {lookForPeople && motion.upload && (
        <WhoToReplace upload={motion.upload} start={motion.start} mode={mode} motion={motion} setMotion={setMotion} />
      )}

      {ready && clipSeconds > SHORTEST && (
        <LengthPick value={motion.length} longest={Math.min(LONGEST, Math.floor(clipSeconds))}
          onChange={(l) => setMotion({ ...motion, length: l })} />
      )}

      <div className="mt-8 flex justify-end">
        <Button variant="primary" size="lg" disabled={!canGo}
          onClick={() => {
            const consent = document.getElementById("consent") as HTMLInputElement | null;
            if (motion.upload && consent && !consent.checked) { consent.focus(); consent.reportValidity(); return; }
            onNext();
          }}>Continue</Button>
      </div>
    </section>
  );
}

/** Looks for everyone in the clip's start frame once a clip is in, to choose who is replaced (Recast) or who
 *  gets new clothes or moves (Restage). */
function WhoToReplace({ upload, start, mode, motion, setMotion }: {
  upload: Upload; start: number; mode: Mode; motion: Motion; setMotion: React.Dispatch<React.SetStateAction<Motion>>;
}) {
  const qc = useQueryClient();
  const [key, setKey] = useState<string>();
  const [slow, setSlow] = useState(false);
  const [full, setFull] = useState(false); // a third tap: say why nothing happened
  const ask = useMutation({
    mutationFn: (retry: boolean) => api.findPeople(upload.id, start, retry),
    onSuccess: (u) => { qc.setQueryData(["upload", u.id], u); setKey(u.key); },
  });
  useEffect(() => { ask.mutate(false); }, [upload.id, start]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuery({
    queryKey: ["upload", upload.id], queryFn: () => api.getUpload(upload.id), enabled: !!key,
    refetchInterval: (r) => (key && r.state.data?.people?.[key]?.state !== "ready" ? 1500 : false),
  });
  const entry = key ? q.data?.people?.[key] : undefined;
  const finding = ask.isPending || (!ask.isError && (!entry || entry.state === "finding"));
  const error = ask.isError ? (ask.error as Error).message : entry?.error;
  useEffect(() => { // the detector shares the GPU with renders, so a wait can be long; say so instead of spinning
    if (!finding) return;
    setSlow(false);
    const t = setTimeout(() => setSlow(true), 30_000);
    return () => clearTimeout(t);
  }, [finding, key]);
  useEffect(() => { // chosen once per frame; coming back to this step keeps the visitor's own choice
    if (!key || entry?.state !== "ready" || !entry.frame_url || entry.error) return;
    const list = entry.people ?? [];
    setMotion((m) => m.people?.key === key ? m : { ...m, people: { key, frame_url: entry.frame_url!, list }, picks: autoPicks(list) });
  }, [key, entry?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const verb = mode === "recast" ? "replace" : "restage";
  const list = (motion.people?.key === key && motion.people?.list) || [];
  const toggle = (id: number) => {
    setFull(false);
    if (!motion.picks.includes(id) && motion.picks.length >= MAX_PICKS) { setFull(true); return; }
    setMotion((m) => ({ ...m, picks: m.picks.includes(id) ? m.picks.filter((x) => x !== id) : [...m.picks, id] }));
  };
  return (
    <div className="mt-8">
      <div className="mb-1 font-medium">{mode === "recast" ? "Who do you want to replace?" : "Who do you want to restage?"}</div>
      {finding ? (
        <>
          <p className="mb-3 flex items-center gap-2 text-sm text-ink-300"><Spinner />
            {slow ? "Still looking. The GPU is busy with another render; this starts as soon as it's free." : "Finding everyone in your first frame…"}</p>
          <div className="relative inline-block max-w-full">
            <img src={upload.thumb_url} alt="" className="max-h-[65vh] max-w-full rounded-xl opacity-50" />
            <div className="skeleton absolute inset-0 rounded-xl opacity-60" />
          </div>
        </>
      ) : error || !list.length ? (
        <div className="rounded-xl border border-ink-700 p-4 text-sm">
          <p className="text-ink-100">{error ?? "We couldn't find anyone in your first frame."}</p>
          <p className="mt-1 text-ink-500">This needs a person or an animal in view at the start of the clip.</p>
          <Button size="sm" className="mt-3" disabled={ask.isPending} onClick={() => { setKey(undefined); setMotion((m) => ({ ...m, people: undefined, picks: [] })); ask.mutate(true); }}>Try again</Button>
        </div>
      ) : (
        <>
          <p className="mb-3 text-sm text-ink-300">
            {list.length === 1 ? "We found one performer. They're chosen; tap to change."
              : motion.picks.length ? `We found ${list.length}. Tap to choose or free someone, up to ${MAX_PICKS}.`
              : `We found ${list.length}. Tap who to ${verb} (up to ${MAX_PICKS}).`}
          </p>
          <PeoplePicker frameUrl={motion.people!.frame_url} people={list} picks={motion.picks} onToggle={toggle} />
          {full && <p className="mt-2 text-sm text-warn">Up to {MAX_PICKS}. Tap someone chosen to free them first.</p>}
          {!motion.picks.length && <p className="mt-2 text-sm text-ink-500">Choose at least one person to continue.</p>}
        </>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- 2. change */

function ChangeStep({ mode, change, setChange, motion, onBack, onPreview }: {
  mode: Mode; change: Change; setChange: (c: Change) => void; motion: Motion; onBack: () => void; onPreview: (j: Job) => void;
}) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const performers = performersOf(mode, motion);
  const two = performers === 2;
  const many = performers > ELSEWHERE_MAX; // only the clip's own place
  const chosen = chosenOf(motion);
  const slots = change.characters.slice(0, performers);
  const filled = slots.filter((c): c is CharSlot => !!c);

  const placeModes: [PlaceMode, string][] = many ? [["keep", "My clip's place"]]
    : mode === "recast"
    ? [["keep", "My clip's place"],
       ...(filled.length ? [["character", two ? "Left character's place" : "My character's place"]] as [PlaceMode, string][] : []),
       ["image", "Use an image"], ["describe", "Describe a place"]]
    : [["keep", "My clip's place"], ["describe", "Describe a place"], ["image", "Use an image"]];
  const wantPlace = mode !== "restyle";
  const place = !wantPlace ? { ...change.place, mode: "keep" as PlaceMode }
    : placeModes.some(([m]) => m === change.place.mode) ? change.place : { ...change.place, mode: "keep" as PlaceMode };
  const style = mode === "swap" ? undefined : change.style;
  const characters = mode === "recast" ? filled : [];
  // Over 5 s, a draft can come first; shorter, the video is made straight away (its draft would be all of it)
  const clip = motion.upload?.info.seconds ?? motion.preset?.seconds;
  const cost = clip ? Math.min(motion.length, Math.floor(clip)) : motion.length;
  const longer = cost > 5;
  const draft = longer && change.draft;
  const clipPlace = mode !== "restyle" && place.mode === "keep"; // its draft is the video's real first 5 s
  // Restage: an outfit or nothing for each chosen person; one with only a picture still needs its words
  const outfits = mode === "swap" ? Array.from({ length: performers }, (_, i) => change.outfits[i]) : [];
  const given = outfits.filter((o): o is OutfitSlot => !!o && (!!o.upload || !!o.text.trim()));
  const outfitsOk = given.every((o) => o.text.trim().length > 2);
  const pictures = given.filter((o) => o.upload).length + (place.mode === "image" ? 1 : 0);
  const fits = place.mode === "keep" || pictures <= 2; // a new place is one edit: the frame and two pictures

  const placeOk = (place.mode !== "describe" || place.text.trim().length > 2) && (place.mode !== "image" || !!place.upload);
  const ready = mode === "recast"
    ? filled.length === performers && filled.every((c) => c.text.trim().length > 2) && placeOk
    : mode === "restyle" ? !!style
    : (given.length > 0 || place.mode !== "keep") && outfitsOk && placeOk && fits;
  const missing = mode === "recast" ? (performers > 1 ? "Add a character for each performer." : "Add a character image.")
    : mode === "restyle" ? "Pick a look."
    : !fits ? "Two outfit pictures and a place picture don't fit together: describe the place, or one outfit, in words."
    : !outfitsOk ? "Say what each new outfit is." : !placeOk ? "Say where to go." : "Give someone new clothes, or pick a new place.";

  const setSlot = (i: number, c: CharSlot | undefined) => {
    const next = [...slots];
    next[i] = c;
    setChange({ ...change, characters: next });
  };

  const start = useMutation({
    mutationFn: async () => {
      const refs: CharacterRef[] = characters.map((c) => ({ upload_id: c.upload.id, text: c.text, keep_outfit: false }));
      const params: JobParams = {
        mode,
        motion: { upload_id: motion.upload?.id, preset_id: motion.upload ? undefined : motion.preset?.id, start: motion.start, length: motion.length,
          picks: mode !== "restyle" && motion.picks.length ? motion.picks : undefined },
        performers,
        subject: "person", // Restage's items need a person; with picks the server reads person or animal from the clip
        characters: refs,
        style,
        place: { mode: place.mode, text: place.text || undefined, upload_id: place.upload?.id },
        outfits: mode === "swap" ? outfits.map((o) => (o && o.text.trim() ? { upload_id: o.upload?.id, text: o.text } : null)) : undefined,
        finish: change.finish,
        audio: change.audio,
        auto: !draft,
      };
      const j = await api.createJob(params);
      return api.requestPreview(j.id);
    },
    onSuccess: (j) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["session"] });
      if (j.auto) nav(`/jobs/${j.id}`); else onPreview(j);
    },
  });

  const placeEditor = (
    <>
      <Segmented label="" value={place.mode} options={placeModes}
        onChange={(v) => setChange({ ...change, place: { ...change.place, mode: v as PlaceMode } })} />
      {place.mode === "describe" && (
        <TextField label="Where?" placeholder="e.g. a neon-lit rooftop at night" value={place.text}
          onChange={(t) => setChange({ ...change, place: { ...change.place, text: t } })} />
      )}
      {place.mode === "image" && (
        <ImagePick label="Place image" image={place.upload} hint="A photo or drawing of the place."
          onPick={(u) => setChange({ ...change, place: { ...change.place, upload: u } })}
          onClear={() => setChange({ ...change, place: { ...change.place, upload: undefined } })} />
      )}
      {place.mode === "keep" && mode === "recast" && <p className="text-sm text-ink-300">Your clip's room, light and camera stay; only the performer changes.</p>}
      {many && mode === "recast" && <p className="text-sm text-ink-500">A new place works with up to {ELSEWHERE_MAX} people; you chose {performers}.</p>}
      {place.mode === "character" && <p className="text-sm text-ink-300">{two ? "Both characters perform in the place in the left character's photo." : "Your character performs in the place in their own photo."}</p>}
    </>
  );

  return (
    <section className="space-y-6">
      {mode === "recast" && <>
        <SectionTitle step="Step 2" title={two ? "Who performs instead?" : "Who performs instead?"}
          hint="Your moves, someone else's look. Add a look or a new place too if you like." />
        <Card className="space-y-6 p-5">
          {(chosen.length ? chosen : two ? [undefined, undefined] : [undefined]).map((person, i) => (
            <div key={person?.id ?? i} className={cx(i > 0 && "border-t border-ink-700/70 pt-6")}>
              <CharacterPick slot={slots[i]} onChange={(c) => setSlot(i, c)}
                who={person && motion.people ? (
                  <span className="flex items-center gap-3">
                    <PersonThumb frameUrl={motion.people.frame_url} box={person.box} className="h-20 w-auto max-w-20" />
                    <span>Replaces person {person.id}</span>
                  </span>
                ) : two ? (i ? "Performer on the right" : "Performer on the left") : ""} />
            </div>
          ))}
          {two && (
            <div className="flex items-center justify-between gap-3 border-t border-ink-700/70 pt-4">
              <p className="text-xs text-ink-500">{chosen.length ? "Characters go onto the chosen people left to right, as in your clip." : "Left and right as you see them in the picture, not their own left and right."}</p>
              <Button size="sm" disabled={!slots[0] && !slots[1]} onClick={() => setChange({ ...change, characters: [slots[1], slots[0]] })}>
                ⇄ Swap who plays whom
              </Button>
            </div>
          )}
        </Card>
        <Option title="Look" line="Optional: draw your character in a style." on={!!change.style}>
          <StyleGrid value={change.style} onChange={(k) => setChange({ ...change, style: k })} />
        </Option>
        <Option title="Place" line="Optional: keep your own room, or go somewhere new." on={place.mode !== "keep"}>
          {placeEditor}
        </Option>
      </>}

      {mode === "restyle" && <>
        <SectionTitle step="Step 2" title="Pick a look" hint="Everyone and everything in your clip is redrawn. Moves, timing and sound stay yours." />
        <Card className="p-5"><StyleGrid value={change.style} onChange={(k) => setChange({ ...change, style: k })} /></Card>
      </>}

      {mode === "swap" && <>
        <SectionTitle step="Step 2" title="What changes?"
          hint="You stay you. Give anyone you chose new clothes, take everyone somewhere new, or both." />
        <Card className="space-y-6 p-5">
          {(chosen.length ? chosen : [undefined]).map((person, i) => (
            <div key={person?.id ?? i} className={cx(i > 0 && "border-t border-ink-700/70 pt-6")}>
              <OutfitPick slot={change.outfits[i]} label={person ? `Outfit for person ${person.id}` : "Outfit"}
                who={person && motion.people ? (
                  <span className="flex items-center gap-3">
                    <PersonThumb frameUrl={motion.people.frame_url} box={person.box} className="h-20 w-auto max-w-20" />
                    <span>Person {person.id}</span>
                  </span>
                ) : ""}
                onChange={(o) => {
                  const next = Array.from({ length: performers }, (_, k) => change.outfits[k]);
                  next[i] = o;
                  setChange({ ...change, outfits: next });
                }} />
            </div>
          ))}
        </Card>
        <Option title="Place" line="Optional: keep your own room, or go somewhere new." on={place.mode !== "keep"}>
          {placeEditor}
        </Option>
      </>}

      <Card className="p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Segmented label="Video quality" value={change.finish}
            options={[["480p", "Native"], ["720p", "720p"], ["1080p", "1080p"]]}
            onChange={(v) => setChange({ ...change, finish: v as Change["finish"] })} />
          <Segmented label="Sound" value={change.audio} options={[["original", "Keep original"], ["mute", "Mute"]]}
            onChange={(v) => setChange({ ...change, audio: v as Change["audio"] })} />
        </div>
        <p className="mt-3 text-xs text-ink-500">The model renders tall and wide clips at 576×1024, other shapes at about 480p, all at 16 fps. 720p and 1080p are upscaled, and labelled so.</p>
      </Card>

      {longer && (
        <label className="flex items-start gap-3 text-sm text-ink-300">
          <input type="checkbox" checked={change.draft} onChange={(e) => setChange({ ...change, draft: e.target.checked })}
            className="mt-1 accent-[var(--color-accent)]" />
          <span>{clipPlace ? "Make a 5 s draft first" : "Check the start picture first"}
            <span className="block text-xs text-ink-500">{clipPlace
              ? "The first 5 seconds, rendered for real, free. You approve it before the whole video is made."
              : "The picture the video starts from, free. You approve it before the video is made."}
              {" "}Off: the whole video is made straight away.</span></span>
        </label>
      )}
      {start.isError && <p className="text-sm text-bad">{(start.error as Error).message}</p>}
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button variant="primary" size="lg" disabled={!ready || start.isPending} onClick={() => start.mutate()}>
          {start.isPending ? <><Spinner /> Starting…</> : draft ? (clipPlace ? "Make the draft" : "Make the start picture")
            : `Make the video · ${cost} credit${cost === 1 ? "" : "s"}`}
        </Button>
      </div>
      {!ready && <p className="text-right text-sm text-ink-500">{missing}</p>}
    </section>
  );
}

function StyleGrid({ value, onChange }: { value?: string; onChange: (k?: string) => void }) {
  const styles = useQuery({ queryKey: ["styles"], queryFn: () => api.styles() });
  return (
    <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
      {styles.data?.map((s) => (
        <button key={s.key} onClick={() => onChange(value === s.key ? undefined : s.key)}
          className={cx("group overflow-hidden rounded-xl border text-left transition",
            value === s.key ? "border-accent ring-2 ring-accent/40" : "border-ink-700 hover:border-ink-500")}>
          {s.image_url
            ? <img src={s.image_url} alt="" loading="lazy" className="aspect-square w-full object-cover transition group-hover:brightness-110" />
            : <div className="aspect-square" style={{ background: `linear-gradient(135deg, ${s.swatch[0]}, ${s.swatch[1]})` }} />}
          <div className="px-2.5 py-2 text-xs font-medium">{s.name}</div>
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- 3. preview */

/** Also shown by the job page, so a preview left waiting in My renders can still be approved. */
export function PreviewStep({ job: first, onBack, backLabel = "Change choices" }: { job: Job; onBack: () => void; backLabel?: string }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: job = first } = useQuery({
    queryKey: ["job", first.id], queryFn: () => api.job(first.id), initialData: first,
    refetchInterval: (q) => (q.state.data?.state === "matching" ? 1000 : false),
  });
  const again = useMutation({ mutationFn: () => api.requestPreview(job.id, { newSeed: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", job.id] }) });
  const approve = useMutation({ mutationFn: () => api.approve(job.id),
    onSuccess: (j) => {
      qc.invalidateQueries({ queryKey: ["session"] });
      qc.invalidateQueries({ queryKey: ["job", j.id] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      nav(`/jobs/${j.id}`);
    } });

  const matching = job.state === "matching";
  const cast = job.preview?.kind === "cast";
  // Recast and Restage in the clip's place preview the video's real first 5 seconds (minutes of GPU); a 5 s video is all of it
  const firstSecond = job.params.mode !== "restyle" && job.params.place.mode === "keep";
  const whole = firstSecond && job.cost_seconds <= 5; // one chunk: the preview is the whole video
  const [editing, setEditing] = useState(false); // an unsaved scene edit must not be skipped by a render
  return (
    <section>
      <SectionTitle step="Step 3" title="Does this look right?"
        hint={firstSecond
          ? whole
            ? "This is your video, rendered for real; its sound is added when you keep it. Your clip stays as filmed: its room, light, objects and everyone you didn't choose. Previews are free; keeping it uses its credits."
            : "These are the first 5 seconds of your video, rendered for real. Your clip stays as filmed: its room, light, objects and everyone you didn't choose, and the rest follows your clip's moves the same way. Check them before credits are spent. Previews are free."
          : "This picture sets the look: who appears, what they wear, the style and the place. Moves, poses and framing come from your clip, so the video won't start exactly like this picture. Check the look before credits are spent. Previews are free."} />
      <div className="grid grid-cols-2 gap-4">
        <Frame label={job.params.motion.picks?.length ? "Who you chose, in your first frame" : "What you filmed (first frame)"} src={job.preview?.frame_url} loading={matching && !job.preview} aspect={job.aspect} />
        {firstSecond
          ? <Frame label={whole ? "Your video (sound is added when you keep it)" : "The first 5 seconds of your video"} video={job.preview?.first_url} poster={job.preview?.first_frame_url}
              src={job.preview?.first_url ? undefined : job.preview?.reference_url}
              loading={matching} wait="Rendering the start of your video… a few minutes" accent
              aspect={job.preview?.first_url || !job.preview?.reference_url ? job.aspect : [1, 1]}
              body={matching && job.preview?.cast?.length ? <CastWhileRendering job={job} whole={whole} /> : undefined} />
          : <Frame label={cast ? "Who replaces them, left to right" : "The look your video will have"} src={job.preview?.reference_url}
              loading={matching} accent aspect={cast ? [1, 1] : job.aspect} />}
      </div>
      {job.preview && !matching && job.state !== "failed" && <p className="mt-4 text-sm text-ink-300">{job.preview.prompt_summary}</p>}
      {!matching && job.preview?.seen && <p className="mt-2 text-xs text-ink-500">{job.preview.seen}</p>}
      {job.params.mode === "restyle" && <SceneLine job={job} onEditing={setEditing} />}
      {!matching && job.preview?.notes?.map((n) => <p key={n} className="mt-2 rounded-xl bg-warn/10 px-4 py-3 text-sm text-warn">{n}</p>)}
      {job.state === "failed" && <p className="mt-4 text-sm text-bad">{job.error?.message ?? "The preview didn't finish."} Previews are free; try again.</p>}
      {again.isError && <p className="mt-4 text-sm text-bad">{(again.error as Error).message}</p>}
      {approve.isError && <p className="mt-4 text-sm text-bad">{(approve.error as Error).message}</p>}
      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack}>{backLabel}</Button>
        <div className="flex gap-3">
          <Button disabled={matching || again.isPending} onClick={() => again.mutate()}>Try another version</Button>
          <Button variant="primary" size="lg" disabled={job.state !== "awaiting_approval" || approve.isPending || editing}
            title={editing ? "Save or cancel your edit first" : undefined} onClick={() => approve.mutate()}>
            {whole && job.preview?.first_url ? "Keep this video" : "Render video"} · {job.cost_seconds} credit{job.cost_seconds === 1 ? "" : "s"}
          </Button>
        </div>
      </div>
    </section>
  );
}

const SCENE_EDITABLE = new Set(["matching", "awaiting_approval", "failed"]);

/** Restyle: the words the render follows. Written automatically from four moments of the clip; shown as
 * progress while that runs, editable once it exists, locked once a render starts. */
function SceneLine({ job, onEditing }: { job: Job; onEditing: (editing: boolean) => void }) {
  const qc = useQueryClient();
  const [draft, setDraftState] = useState<string | null>(null);
  const setDraft = (d: string | null) => { setDraftState(d); onEditing(d !== null); };
  const save = useMutation({ mutationFn: (text: string) => api.editScene(job.id, text),
    onSuccess: (j) => { qc.setQueryData(["job", job.id], j); setDraft(null); } });
  const scene = job.scene;
  if (!scene || scene.state === "reading") {
    if (job.state !== "matching") return null;
    return (
      <div className="mt-4 flex items-center gap-3 rounded-xl border border-ink-800 px-4 py-3 text-sm text-ink-300">
        <Spinner /> Reading your clip: who's in it, where, and anything they put on or pick up…
      </div>
    );
  }
  const locked = !SCENE_EDITABLE.has(job.state) || (job.state === "failed" && !!job.error?.refunded);
  const text = draft ?? scene.text;
  return (
    <div className="mt-4 rounded-xl border border-ink-800 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
          How we read your clip{scene.edited ? " (edited)" : ""}
        </p>
        {draft === null && !locked && (
          <button className="text-sm font-medium text-accent hover:underline" onClick={() => setDraft(scene.text)}>Edit</button>
        )}
      </div>
      {draft === null ? (
        <p className="mt-1 text-sm text-ink-100">{scene.text || "We couldn't read this clip. Add a line so the video knows who and what is in it."}</p>
      ) : (
        <>
          <textarea value={text} maxLength={500} rows={3} autoFocus onChange={(e) => setDraft(e.target.value)}
            className="mt-2 w-full rounded-lg border border-ink-700 bg-transparent p-3 text-sm text-ink-100 focus:border-accent focus:outline-none" />
          {save.isError && <p className="mt-1 text-sm text-bad">{(save.error as Error).message}</p>}
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="primary" disabled={text.trim().length < 3 || save.isPending}
              onClick={() => save.mutate(text)}>{save.isPending ? "Saving…" : "Save"}</Button>
            <Button size="sm" onClick={() => setDraft(null)} disabled={save.isPending}>Cancel</Button>
          </div>
        </>
      )}
      <p className="mt-2 text-xs text-ink-500">
        {locked ? "The video is using these words." : "The video follows these words. Name anything you put on, take off or pick up later in the clip; leave out things passing in the background."}
      </p>
    </div>
  );
}

function Frame({ label, src, video, poster, loading, wait = "Building your preview…", accent, aspect, body }: {
  label: string; src?: string; video?: string; poster?: string; loading?: boolean; wait?: string; accent?: boolean;
  aspect?: [number, number]; body?: React.ReactNode }) {
  return (
    <figure>
      <div className={cx("relative overflow-hidden rounded-[var(--radius-card)] border",
        accent ? "border-accent/40" : "border-ink-700")} style={aspectOf(aspect)}>
        {body ?? (loading ? (
          <div className="skeleton absolute inset-0 grid place-items-center">
            <span className="flex items-center gap-2 rounded-full bg-black/50 px-3 py-1.5 text-sm"><Spinner /> {wait}</span>
          </div>
        ) : video ? <video key={video} src={video} poster={poster} autoPlay loop muted playsInline aria-label={label} className="h-full w-full object-cover" />
          : src ? <img src={src} alt={label} className="h-full w-full object-cover" /> : null)}
      </div>
      <figcaption className="mt-2 text-sm text-ink-500">{label}</figcaption>
    </figure>
  );
}

/** While the preview renders: who replaces whom, at once, and the GPU job's progress over all of its phases. */
function CastWhileRendering({ job, whole }: { job: Job; whole: boolean }) {
  const p = job.progress;
  const pct = !p ? 0 : p.stage === "dressing" || p.stage === "completing" ? 1 : p.stage === "starting_gpu" ? 2 : p.stage === "waiting_for_gpu" ? 4 : p.stage === "loading_models" ? 8
    : p.stage === "rendering" ? Math.round(12 + (70 * (p.step ?? 0)) / (p.steps || 6)) : 88;
  const line = !p ? "Starting…" : p.stage === "dressing" ? "Putting on the new clothes…" : p.stage === "completing" ? "Drawing the rest of a character's body…" : p.stage === "starting_gpu" ? "Reading your clip…" : p.stage === "waiting_for_gpu" ? "Waiting for the GPU…"
    : p.stage === "loading_models" ? "Loading the models…" : p.stage === "rendering" ? `Drawing your video: step ${p.step} of ${p.steps}`
    : "Putting everyone else back as filmed…";
  const left = p?.eta_seconds ? ` · about ${Math.max(1, Math.round(p.eta_seconds / 60))} min left` : "";
  return (
    <div className="absolute inset-0 flex flex-col justify-between gap-3 bg-ink-900 p-4">
      <div className="flex min-h-0 flex-1 items-center justify-center gap-4 sm:gap-6">
        {job.preview?.cast?.map((c) => (
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
      <div>
        <p className="flex items-center gap-2 text-sm text-ink-300"><Spinner /> {whole ? "Rendering your video" : "Rendering the first 5 seconds"}{left}</p>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded-full bg-accent transition-all duration-700" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-1 text-xs text-ink-500">{line}</p>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- pieces */

function Summary({ mode, motion, change, creditsLeft }: { mode: Mode; motion: Motion; change: Change; creditsLeft?: number }) {
  const styles = useQuery({ queryKey: ["styles"], queryFn: () => api.styles() });
  const rows = useMemo(() => {
    const r: [string, string][] = [];
    r.push(["Motion", motion.preset ? `${motion.preset.title} · ${motion.length} s` : motion.upload ? `Your clip · ${motion.length} s` : "Not chosen"]);
    r.push(["Mode", MODES.find(([m]) => m === mode)?.[1] ?? mode]);
    const chosen = chosenOf(motion);
    const of = motion.people ? ` of ${motion.people.list.length}` : "";
    if (mode === "recast" && motion.upload) {
      r.push(["Replacing", chosen.length === 0 ? "Not chosen" : chosen.length === 1 ? `Person ${chosen[0].id}${of}`
        : `People ${chosen[0].id} and ${chosen[1].id}${of}`]);
    }
    const performers = performersOf(mode, motion);
    const two = performers > 1;
    const placeLabel = change.place.mode === "keep" ? "Your own" : change.place.mode === "describe" ? change.place.text || "Described"
      : change.place.mode === "character" ? "Character's photo" : "From image";
    if (mode === "recast") {
      change.characters.slice(0, performers).forEach((c, i) => c && r.push([
        chosen[i] && two ? `For person ${chosen[i].id}` : two ? (i ? "Right" : "Left") : "Character", c.text || "Your image"]));
      if (change.style) r.push(["Look", styles.data?.find((s) => s.key === change.style)?.name ?? change.style]);
      r.push(["Place", placeLabel]);
    } else if (mode === "restyle") {
      r.push(["Look", change.style ? styles.data?.find((s) => s.key === change.style)?.name ?? change.style : "Not chosen"]);
    } else {
      chosenOf(motion).forEach((person, i) => {
        const o = change.outfits[i];
        if (o?.text.trim()) r.push([`Person ${person.id}`, o.text]);
      });
      r.push(["Place", placeLabel]);
    }
    r.push(["Quality", change.finish === "480p" ? "Native" : `${change.finish} (upscaled)`]);
    return r;
  }, [mode, motion, change, styles.data]);
  const clip = motion.upload?.info.seconds ?? motion.preset?.seconds;
  const cost = clip ? Math.min(motion.length, Math.floor(clip)) : motion.length; // the server charges what it delivers
  return (
    <aside className="lg:sticky lg:top-24 lg:self-start">
      <Card className="p-5">
        <h3 className="text-sm font-semibold">Your render</h3>
        <dl className="mt-4 space-y-2.5 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4">
              <dt className="text-ink-500">{k}</dt>
              <dd className="truncate text-right text-ink-100">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-5 border-t border-ink-700 pt-4 text-sm">
          <div className="flex justify-between"><span className="text-ink-500">Cost</span>
            <span>{cost} credit{cost === 1 ? "" : "s"}</span></div>
          {creditsLeft !== undefined && <div className="mt-1 flex justify-between"><span className="text-ink-500">Left after</span>
            <span className={creditsLeft - cost < 0 ? "text-bad" : ""}>{Math.max(0, creditsLeft - cost)}</span></div>}
          <p className="mt-3 text-xs text-ink-500">1 credit = 1 second of finished video. Drafts are free, and a failed
            render is refunded automatically.</p>
        </div>
      </Card>
    </aside>
  );
}

function Option({ title, line, on, tag, children }: { title: string; line: string; on: boolean; tag?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(on);
  useEffect(() => { if (on) setOpen(true); }, [on]);
  return (
    <Card className={cx("transition-colors", on && "border-accent/40")}>
      <button className="flex w-full items-center gap-4 p-5 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={cx("grid h-6 w-6 place-items-center rounded-full border text-xs",
          on ? "border-accent bg-accent text-accent-ink" : "border-ink-500")}>{on ? "✓" : ""}</span>
        <span className="flex-1">
          <span className="flex items-center gap-2 font-medium">{title}{tag && <Pill tone="ok">{tag}</Pill>}</span>
          <span className="block text-sm text-ink-500">{line}</span>
        </span>
        <span className="text-ink-500">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="space-y-4 border-t border-ink-700/70 p-5">{children}</div>}
    </Card>
  );
}

/** The vision model writes the words for an image in its role; they prefill an empty box, editable once written.
 * `slow`: past 3 minutes (on one GPU it waits behind the video in progress); the box opens for typing and the
 * words still fill it if it is empty when they come. `failed`: it wrote nothing, so the visitor types them. */
function useAutoText(upload: Upload | undefined, role: ImageRole, text: string, setText: (t: string) => void) {
  const asked = useRef<string | undefined>(undefined);
  const qc = useQueryClient();
  const [gaveUp, setGaveUp] = useState<string | undefined>(undefined); // upload id whose words never came
  const [slow, setSlow] = useState<string | undefined>(undefined); // upload id whose words are taking long
  // Poll until the words exist, not while the server says "describing": the first read can land before the
  // describe request does and see neither, which used to stop the polling with the box locked.
  const waiting = (u?: Upload) => !!upload && gaveUp !== upload.id && u?.descriptions?.[role] === undefined;
  const q = useQuery({
    queryKey: ["upload", upload?.id], queryFn: () => api.getUpload(upload!.id), enabled: !!upload,
    refetchInterval: (r) => (waiting(r.state.data) ? (slow === upload?.id ? 5000 : 2000) : false),
  });
  useEffect(() => {
    if (!upload || asked.current === upload.id) return;
    asked.current = upload.id;
    const id = upload.id;
    api.describeUpload(id, role).then((u) => qc.setQueryData(["upload", id], u)).catch(() => setGaveUp(id));
  }, [upload?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // a box that never unlocks is worse than an empty one
    if (!upload) return;
    const id = upload.id;
    const t = [setTimeout(() => setSlow(id), 180_000), setTimeout(() => setGaveUp(id), 900_000)];
    return () => t.forEach(clearTimeout);
  }, [upload?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const words = q.data?.descriptions?.[role];
  useEffect(() => {
    if (words && !text.trim()) setText(words);
  }, [words]); // eslint-disable-line react-hooks/exhaustive-deps
  const late = waiting(q.data) && slow === upload?.id;
  return { writing: waiting(q.data) && !late, slow: late,
    failed: words === "" || (!!upload && gaveUp === upload.id && words === undefined) };
}

function CharacterPick({ who, slot, onChange }: { who: React.ReactNode; slot?: CharSlot; onChange: (c: CharSlot | undefined) => void }) {
  const { writing, slow, failed } = useAutoText(slot?.upload, "character", slot?.text ?? "", (t) => slot && onChange({ ...slot, text: t }));
  return (
    <div className="space-y-3">
      {who && <div className="text-sm font-medium text-ink-100">{who}</div>}
      <ImagePick label="Character image" image={slot?.upload}
        hint="A clear photo or drawing, in the clothes they should wear. The pose comes from your clip."
        onPick={(u) => onChange({ upload: u, text: slot?.text ?? "" })}
        onClear={() => onChange(undefined)} />
      {slot && (
        <TextField label="How they look in the video" placeholder="e.g. young woman, long red hair, green hoodie, round glasses"
          value={slot.text} onChange={(t) => onChange({ ...slot, text: t })}
          busy={writing ? "Looking at the picture: face, hair and clothes…" : undefined}
          help={writing ? "You can edit the words once they're written. This takes about half a minute."
            : slow ? "The GPU is busy with another video, so this is taking longer. Type the words now, or wait: they fill in here if the box is still empty."
            : failed ? "We couldn't read the picture. The video draws them from the photo and these words: describe their face, hair and clothes. Their clothes come from the photo."
            : "Written from the picture. The video draws them from the photo and these words, so fix anything wrong. Their clothes come from the photo: to change them, use a photo in those clothes. Their moves come from your clip: leave out names and actions."} />
      )}
    </div>
  );
}

/** Restage: what one chosen person now wears. Words alone work; a picture of the clothes helps. Empty: their own. */
function OutfitPick({ who, label, slot, onChange }: {
  who: React.ReactNode; label: string; slot?: OutfitSlot; onChange: (o: OutfitSlot | undefined) => void;
}) {
  return (
    <div className="space-y-3" role="group" aria-label={label}>
      {who && <div className="text-sm font-medium text-ink-100">{who}</div>}
      <ImagePick label="Outfit image" image={slot?.upload} hint="Optional: a photo of the clothes. Words alone work too."
        onPick={(u) => onChange({ upload: u, text: slot?.text ?? "" })}
        onClear={() => onChange(slot?.text.trim() ? { text: slot.text } : undefined)} />
      {slot?.upload ? (
        <ItemText role="outfit" upload={slot.upload} value={slot.text} onChange={(t) => onChange({ ...slot, text: t })} />
      ) : (
        <TextField label="What they wear now" placeholder="e.g. a red leather biker jacket" value={slot?.text ?? ""}
          onChange={(t) => onChange(t ? { ...slot, text: t } : undefined)}
          help="Leave empty to keep their own clothes." />
      )}
    </div>
  );
}

function ItemText({ role, upload, value, onChange }: { role: ImageRole; upload: Upload; value: string; onChange: (t: string) => void }) {
  const { writing, slow, failed } = useAutoText(upload, role, value, onChange);
  return (
    <TextField label="How it looks in the video" placeholder={role === "outfit" ? "e.g. a red leather biker jacket with silver zips" : "e.g. a green glass bottle with a white label"}
      value={value} onChange={onChange}
      busy={writing ? `Looking at the picture: what the ${role} is, its colour and material…` : undefined}
      help={writing ? "You can edit the words once they're written. This takes about half a minute."
        : slow ? "The GPU is busy with another video, so this is taking longer. Type the words now, or wait: they fill in here if the box is still empty."
        : failed ? "We couldn't read the picture. The video draws it from the photo and these words: say what it is, its colour and material."
        : "Written from the picture. The video draws it from the photo and these words, so fix anything wrong."} />
  );
}

function ImagePick({ label, image, hint, onPick, onClear }: {
  label: string; image?: Upload; hint: string; onPick: (u: Upload) => void; onClear: () => void;
}) {
  const up = useMutation({ mutationFn: (f: File) => api.upload(f, "image"), onSuccess: onPick });
  if (image) {
    return (
      <div className="flex items-center gap-4">
        <img src={image.thumb_url} alt={label} className="h-24 w-24 rounded-xl object-cover" />
        <Button size="sm" variant="ghost" onClick={onClear}>Remove</Button>
      </div>
    );
  }
  return (
    <>
      <Dropzone compact accept="image/*" busy={up.isPending} onFile={(f) => up.mutate(f)} label={label}>
        <div className="text-sm font-medium">Add {label.toLowerCase()}</div>
        <div className="mt-1 text-xs text-ink-500">{hint}</div>
      </Dropzone>
      {up.isError && <p className="text-sm text-bad">{(up.error as Error).message}</p>}
    </>
  );
}

/** `busy`: the words are being written for the visitor, so the box shows progress and takes no typing yet. */
function TextField({ label, value, onChange, placeholder, help, busy }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; help?: string; busy?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm text-ink-300">{label}</span>
      {busy ? (
        <span aria-live="polite" aria-busy="true"
          className="flex h-11 w-full items-center gap-2.5 rounded-[var(--radius-control)] border border-ink-700 bg-ink-900/60 px-3.5 text-[15px] text-ink-300">
          <Spinner /> {busy}
        </span>
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value.slice(0, 400))} placeholder={placeholder}
          className="h-11 w-full rounded-[var(--radius-control)] border border-ink-700 bg-ink-900 px-3.5 text-[15px] placeholder:text-ink-500 focus:border-accent focus:outline-none" />
      )}
      {help && <span className="mt-1.5 block text-xs text-ink-500">{help}</span>}
    </label>
  );
}

/** Seconds of the clip to use, one credit each. Only what is asked is rendered: the last chunk is as short as it
 *  needs to be. */
function LengthPick({ value, longest, onChange }: { value: number; longest: number; onChange: (s: number) => void }) {
  const v = Math.min(value, longest);
  return (
    <div className="mt-6">
      <div className="mb-2 flex items-baseline justify-between text-sm">
        <span className="text-ink-300">How much of the clip to use</span>
        <span className="tabular-nums text-ink-100">{v} s <span className="text-ink-500">· {v} credit{v === 1 ? "" : "s"}</span></span>
      </div>
      <input type="range" min={SHORTEST} max={longest} step={1} value={v} onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--color-accent)]" aria-label="Seconds of the clip to use" />
      <div className="mt-1 flex justify-between text-xs text-ink-500"><span>{SHORTEST} s</span><span>{longest} s</span></div>
    </div>
  );
}

function Segmented({ label, value, options, onChange }: {
  label: string; value: string; options: [string, string][]; onChange: (v: string) => void;
}) {
  return (
    <div>
      {label && <div className="mb-1.5 text-sm text-ink-300">{label}</div>}
      <div className="inline-flex flex-wrap rounded-[var(--radius-control)] bg-ink-900 p-1 text-sm">
        {options.map(([k, l]) => (
          <button key={k} onClick={() => onChange(k)} className={cx(
            "rounded-[10px] px-3.5 py-2 transition-colors", value === k ? "bg-ink-700 text-ink-100" : "text-ink-300 hover:text-ink-100",
          )}>{l}</button>
        ))}
      </div>
    </div>
  );
}
