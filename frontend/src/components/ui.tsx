import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

export const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(" ");

export function Panel({ className, children, ...rest }: HTMLAttributes<HTMLElement>) {
  return (
    <section className={cx("glass min-w-0 rounded-[20px] p-5", className)} {...rest}>
      {children}
    </section>
  );
}

export function PanelTitle({ id, children, aside }: { id?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
      <h2 id={id} className="text-[13px] font-semibold tracking-[0.08em] text-ink-2 uppercase">
        {children}
      </h2>
      {aside}
    </div>
  );
}

type Tone = "neutral" | "accent" | "good" | "warn";
const TONES: Record<Tone, string> = {
  neutral: "bg-white/8 text-ink-2",
  accent: "bg-accent/15 text-accent",
  good: "bg-emerald-400/15 text-good",
  warn: "bg-orange-400/15 text-warn",
};

export function Chip({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}

type Variant = "primary" | "secondary" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink font-bold hover:brightness-110",
  secondary: "border border-white/16 bg-white/8 text-ink font-semibold hover:bg-white/12",
  ghost: "text-ink-2 font-medium hover:bg-white/8 hover:text-ink",
};

export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm transition disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("animate-pulse rounded-xl bg-white/6", className)} />;
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      className="h-2 overflow-hidden rounded-full bg-white/10"
    >
      <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Segmented tabs for switching a page between views. */
export function Tabs<T extends string>({
  value,
  onChange,
  items,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  items: { value: T; label: string; count?: number | null }[];
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex w-fit max-w-full gap-1 overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.04] p-1">
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          role="tab"
          aria-selected={value === item.value}
          onClick={() => onChange(item.value)}
          className={cx(
            "flex min-h-10 shrink-0 items-center gap-2 rounded-xl px-4 text-sm font-semibold transition",
            value === item.value ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-white/8 hover:text-ink",
          )}
        >
          {item.label}
          {item.count != null && (
            <span
              className={cx(
                "rounded-full px-1.5 py-px text-[11px] tabular-nums",
                value === item.value ? "bg-black/15" : "bg-white/10 text-ink-3",
              )}
            >
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
