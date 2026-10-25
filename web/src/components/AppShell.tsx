import { useQuery } from "@tanstack/react-query";
import { NavLink, Link, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { cx } from "./ui";

export function AppShell() {
  const { data: session } = useQuery({ queryKey: ["session"], queryFn: () => api.session(), refetchInterval: 15000 });
  const { pathname } = useLocation();
  // without a judge link only the landing page and the privacy page are open (server/links.py)
  const locked = session?.kind === "guest" && !["/", "/privacy"].includes(pathname);
  return (
    <div className="min-h-dvh">
      {api.isMock && (
        <div className="bg-warn/10 text-warn text-center text-xs py-1.5 px-4">
          Preview build: renders are simulated by playing your clip back. Nothing is generated.
        </div>
      )}
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <span>Recast</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {[["/create", "Create"], ["/library", "My renders"]].map(([to, label]) => (
              <NavLink key={to} to={to} className={({ isActive }) => cx(
                "rounded-lg px-3 py-2 transition-colors",
                isActive ? "bg-ink-800 text-ink-100" : "text-ink-300 hover:text-ink-100",
              )}>{label}</NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {session && session.kind !== "guest" && (
              <span className="hidden sm:inline text-ink-300" title="Renders left on this link">
                <span className="text-ink-100 font-medium tabular-nums">{session.renders_left}</span>
                <span className="text-ink-500"> / {session.renders_total} renders left</span>
              </span>
            )}
            {session && <span className="rounded-full bg-ink-800 px-3 py-1.5 text-xs text-ink-300">{session.name}</span>}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
        {locked ? (
          <div className="mx-auto max-w-md py-16 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">Open your judge link</h1>
            <p className="mt-3 text-ink-300">This demo opens with the link you were sent. It works on any device, and
              what you make with it is seen only through it.</p>
          </div>
        ) : <Outlet />}
      </main>
      <footer className="border-t border-ink-800">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-6 text-xs text-ink-500 sm:px-6">
          <span>Open weights only: SCAIL-2, Wan VACE, Wan Animate-2 and Qwen-Image-Edit, run through the Comfy SDK.</span>
          <span>Results are AI-generated and labelled as such.</span>
          <Link to="/privacy" className="hover:text-ink-300">Privacy</Link>
        </div>
      </footer>
    </div>
  );
}
