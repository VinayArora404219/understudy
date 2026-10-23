import { useRef, useState, type ReactNode } from "react";
import { cx, Spinner } from "./ui";

/** Drag-and-drop or tap-to-pick. On phones the picker offers the camera directly. */
export function Dropzone({ accept, onFile, busy, children, compact, label }: {
  accept: string;
  onFile: (f: File) => void;
  busy?: boolean;
  compact?: boolean;
  label: string;
  children?: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onFile(f);
      }}
      className={cx(
        "group relative flex w-full flex-col items-center justify-center rounded-[var(--radius-card)]",
        "border border-dashed text-center transition-colors",
        compact ? "min-h-28 p-4" : "min-h-52 p-8",
        over ? "border-accent bg-accent/5" : "border-ink-700 bg-ink-900 hover:border-ink-500 hover:bg-ink-850",
      )}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      {busy ? (
        <span className="flex items-center gap-2 text-sm text-ink-300"><Spinner /> Checking your file…</span>
      ) : children}
    </button>
  );
}
