import { useEffect, useState } from "react";

import { useRateDifficulty } from "../api/hooks";
import { useUi } from "../state/ui";
import { cx } from "./ui";

const LEVELS: { value: number; label: string; short: string; on: string }[] = [
  { value: 1, label: "Very easy", short: "V. easy", on: "bg-sky-400/25 text-sky-100 border-sky-300/50" },
  { value: 2, label: "Easy", short: "Easy", on: "bg-emerald-400/25 text-emerald-100 border-emerald-300/50" },
  { value: 3, label: "Comfortable", short: "OK", on: "bg-accent/25 text-accent border-accent/60" },
  { value: 4, label: "Hard", short: "Hard", on: "bg-orange-400/25 text-orange-100 border-orange-300/50" },
  { value: 5, label: "Very hard", short: "V. hard", on: "bg-red-400/25 text-red-100 border-red-300/50" },
];

/**
 * "How hard was this?": very easy … very hard. Each rating moves your "just right" level for videos or reading,
 * so every suggestion is re-ranked. Click the chosen one again to clear it.
 */
export function DifficultyRating({
  itemId,
  value,
  compact = false,
  kind = "video",
}: {
  itemId: number;
  value: number | null | undefined;
  compact?: boolean;
  kind?: "video" | "text";
}) {
  const rate = useRateDifficulty();
  const showToast = useUi((s) => s.showToast);
  const [current, setCurrent] = useState<number | null>(value ?? null);
  useEffect(() => setCurrent(value ?? null), [value]);

  const choose = (n: number) => {
    const next = current === n ? null : n;
    setCurrent(next);
    rate.mutate(
      { id: itemId, value: next },
      {
        onSuccess: (result) => showToast(next ? result.message : "Rating removed."),
        onError: (error) => {
          setCurrent(value ?? null);
          showToast(`Couldn't save the rating: ${error.message}`);
        },
      },
    );
  };

  return (
    <div className={cx("flex flex-wrap items-center", compact ? "gap-1" : "gap-2")}>
      {!compact && <span className="mr-1 text-sm font-semibold text-ink-2">How hard was this {kind}?</span>}
      <div role="radiogroup" aria-label={`How hard was this ${kind}?`} className="flex flex-wrap gap-1">
        {LEVELS.map((level) => {
          const on = current === level.value;
          return (
            <button
              key={level.value}
              type="button"
              role="radio"
              aria-checked={on}
              title={level.label}
              disabled={rate.isPending}
              onClick={() => choose(level.value)}
              className={cx(
                "rounded-lg border font-semibold transition disabled:opacity-60",
                compact ? "min-h-8 px-2 text-[11px]" : "min-h-9 px-3 text-xs",
                on ? level.on : "border-white/12 text-ink-3 hover:bg-white/8 hover:text-ink",
              )}
            >
              {compact ? level.short : level.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
