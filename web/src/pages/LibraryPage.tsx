import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, Pill } from "../components/ui";
import { Empty } from "./JobPage";

export function LibraryPage() {
  const { data: jobs, isLoading } = useQuery({ queryKey: ["jobs"], queryFn: () => api.jobs(), refetchInterval: 4000 });
  if (isLoading) return <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton aspect-[9/16] rounded-[var(--radius-card)]" />)}</div>;
  const list = (jobs ?? []).filter((j) => j.state !== "draft");
  if (!list.length) {
    return <Empty title="No renders yet" line="Your videos appear here, including ones still rendering."
      action={<Link to="/create" className="inline-flex h-11 items-center rounded-[var(--radius-control)] bg-accent px-4 font-medium text-accent-ink">Make your first</Link>} />;
  }
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">My renders</h1>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {list.map((j) => (
          <Link key={j.id} to={`/jobs/${j.id}`}>
            <Card className="overflow-hidden transition hover:border-ink-500">
              <div className="aspect-[9/16] bg-ink-900">
                {j.preview?.reference_url && <img src={j.preview.reference_url} alt="" className="h-full w-full object-cover" />}
              </div>
              <div className="flex items-center justify-between gap-2 p-3">
                <span className="truncate text-sm font-medium">{j.title}</span>
                {j.state === "done" ? <Pill tone="ok">Ready</Pill>
                  : j.state === "failed" ? <Pill tone="bad">Failed</Pill>
                  : j.state === "cancelled" ? <Pill>Cancelled</Pill>
                  : j.state === "awaiting_approval" ? <Pill tone="warn">Needs approval</Pill>
                  : <Pill tone="accent">Rendering</Pill>}
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
