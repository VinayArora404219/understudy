import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { admin, type LinkRow } from "../api/admin";
import { Button, Card, cx, Pill, Spinner } from "../components/ui";

/** Judge links: make one (its address is shown once), see what each has used, revoke one. */
export function AdminPage() {
  const qc = useQueryClient();
  const session = useQuery({ queryKey: ["admin"], queryFn: admin.session, retry: false });
  const out = useMutation({ mutationFn: admin.logout, onSuccess: () => qc.setQueryData(["admin"], { signed_in: false }) });
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <header className="border-b border-ink-800">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <span className="font-semibold">Recast</span>
          <span className="text-ink-500">· Links</span>
          {session.data?.signed_in && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => out.mutate()}>Sign out</Button>}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        {session.isLoading ? <p className="flex items-center gap-2 text-ink-300"><Spinner /> Checking…</p>
          : session.isError ? <p className="text-ink-300">{(session.error as Error).message}</p>
          : session.data?.signed_in ? <Links /> : <SignIn />}
      </main>
    </div>
  );
}

function SignIn() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const login = useMutation({ mutationFn: () => admin.login(password), onSuccess: (s) => qc.setQueryData(["admin"], s) });
  return (
    <Card className="mx-auto max-w-sm p-6">
      <h1 className="text-lg font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-ink-500">The password is RECAST_ADMIN_PASSWORD on the server.</p>
      <form className="mt-5 space-y-3" onSubmit={(e) => { e.preventDefault(); login.mutate(); }}>
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
          aria-label="Password" className={field} autoFocus />
        {login.isError && <p className="text-sm text-bad">{(login.error as Error).message}</p>}
        <Button variant="primary" className="w-full" disabled={!password || login.isPending}>Sign in</Button>
      </form>
    </Card>
  );
}

const field = "h-11 w-full rounded-[var(--radius-control)] border border-ink-700 bg-ink-900 px-3.5 text-[15px] focus:border-accent focus:outline-none";

function Links() {
  const qc = useQueryClient();
  const links = useQuery({ queryKey: ["admin", "links"], queryFn: admin.links, refetchInterval: 30_000 });
  const [made, setMade] = useState<{ name: string; url: string }>();
  const revoke = useMutation({ mutationFn: admin.revoke, onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "links"] }) });
  const rows = links.data ?? [];
  const live = rows.filter((l) => l.live);
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Judge links</h1>
          <p className="mt-1 text-sm text-ink-500">
            {live.length} live · {live.reduce((n, l) => n + l.used, 0)} of {live.reduce((n, l) => n + l.credits, 0)} credits used.
            1 credit = 1 second of finished video; previews are free.
          </p>
        </div>
      </div>

      <MakeLink onMade={(name, path) => { setMade({ name, url: `${window.location.origin}${path}` }); qc.invalidateQueries({ queryKey: ["admin", "links"] }); }} />
      {made && <NewLink {...made} onDone={() => setMade(undefined)} />}

      {links.isError && <p className="text-sm text-bad">{(links.error as Error).message}</p>}
      {revoke.isError && <p className="text-sm text-bad">{(revoke.error as Error).message}</p>}
      {links.isLoading ? <p className="flex items-center gap-2 text-ink-300"><Spinner /> Loading…</p>
        : !rows.length ? <p className="text-ink-500">No links yet.</p>
        : (
          <div className="space-y-3">
            {rows.map((l) => <LinkCard key={l.id} link={l} busy={revoke.isPending && revoke.variables === l.id}
              onRevoke={() => { if (window.confirm(`Revoke “${l.name}”? It stops working at once, also where it is already open.`)) revoke.mutate(l.id); }} />)}
          </div>
        )}
    </div>
  );
}

function MakeLink({ onMade }: { onMade: (name: string, path: string) => void }) {
  const [name, setName] = useState("");
  const [credits, setCredits] = useState(300);
  const [days, setDays] = useState(40);
  const make = useMutation({
    mutationFn: () => admin.make(name.trim(), credits, days),
    onSuccess: (r) => { onMade(r.link.name, r.path); setName(""); },
  });
  return (
    <Card className="p-5">
      <form className="grid gap-3 sm:grid-cols-[1fr_140px_120px_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); make.mutate(); }}>
        <label className="block text-sm"><span className="mb-1.5 block text-ink-300">Who it's for</span>
          <input value={name} onChange={(e) => setName(e.target.value.slice(0, 80))} placeholder="e.g. Judge 3" className={field} /></label>
        <label className="block text-sm"><span className="mb-1.5 block text-ink-300">Credits (seconds)</span>
          <input type="number" min={1} max={3600} value={credits} onChange={(e) => setCredits(Number(e.target.value))} className={field} /></label>
        <label className="block text-sm"><span className="mb-1.5 block text-ink-300">Works for (days)</span>
          <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} className={field} /></label>
        <Button variant="primary" disabled={!name.trim() || make.isPending}>Make link</Button>
      </form>
      {make.isError && <p className="mt-3 text-sm text-bad">{(make.error as Error).message}</p>}
    </Card>
  );
}

/** The new link's address: shown here once, since the server keeps only its hash. */
function NewLink({ name, url, onDone }: { name: string; url: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Card className="border-accent/50 p-5">
      <div className="text-sm font-medium">Link for {name}</div>
      <p className="mt-1 text-xs text-warn">Copy it now: it is shown only this once. Lost? Revoke it and make another.</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input readOnly value={url} onFocus={(e) => e.target.select()} className={cx(field, "font-mono text-sm")} aria-label="New link" />
        <Button onClick={() => navigator.clipboard.writeText(url).then(() => setCopied(true))}>{copied ? "Copied" : "Copy"}</Button>
        <Button variant="ghost" onClick={onDone}>Done</Button>
      </div>
    </Card>
  );
}

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "never");
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "not yet");

function LinkCard({ link, busy, onRevoke }: { link: LinkRow; busy: boolean; onRevoke: () => void }) {
  const pct = link.credits ? Math.min(100, Math.round((100 * link.used) / link.credits)) : 0;
  return (
    <Card className={cx("p-4 sm:p-5", !link.live && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium">{link.name}</span>
            {link.revoked ? <Pill tone="bad">Revoked</Pill> : link.live ? <Pill tone="ok">Live</Pill> : <Pill>Expired</Pill>}
          </div>
          <div className="mt-0.5 text-xs text-ink-500">
            {link.id} · made {day(link.created)} · {link.revoked ? `revoked ${day(link.revoked)}` : `until ${day(link.expires)}`} · last active {when(link.last_active)}
          </div>
        </div>
        {link.live && <Button size="sm" variant="ghost" disabled={busy} onClick={onRevoke}>Revoke</Button>}
      </div>
      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-[1fr_auto] sm:items-center">
        <div>
          <div className="flex justify-between text-xs text-ink-500"><span>{link.used} of {link.credits} credits used</span><span>{link.left} left</span></div>
          <div className="mt-1 h-1.5 rounded-full bg-ink-800"><div className="h-1.5 rounded-full bg-accent" style={{ width: `${pct}%` }} /></div>
        </div>
        <div className="flex gap-4 text-xs text-ink-300 tabular-nums">
          <span>{link.videos} video{link.videos === 1 ? "" : "s"}</span>
          <span>{link.previews} preview{link.previews === 1 ? "" : "s"}</span>
          <span>{link.uploads} upload{link.uploads === 1 ? "" : "s"}</span>
        </div>
      </div>
    </Card>
  );
}
