import { useState } from "react";

import { useAddLanguage, useLanguageCatalog } from "../api/hooks";
import type { CatalogLanguage } from "../api/types";
import { Button, ProgressBar, Skeleton, cx } from "./ui";

function speakers(millions: number): string {
  return millions >= 1000 ? `${(millions / 1000).toFixed(1)} billion` : `${millions} million`;
}

/**
 * Every language Lingo OS can teach, most spoken first. Pick one, choose its regional variety, and it downloads what
 * it needs (a language model and a dictionary) in the background, showing progress until it's ready.
 */
export function LanguagePicker({ onlyNew = false, compact = false }: { onlyNew?: boolean; compact?: boolean }) {
  const catalog = useLanguageCatalog();
  const [open, setOpen] = useState<string | null>(null);
  if (catalog.isPending) return <Skeleton className="h-72 rounded-2xl" />;
  if (catalog.isError) return <p role="alert" className="text-sm text-red-200">Could not load the languages: {catalog.error.message}</p>;
  const items = catalog.data.filter((l) => !onlyNew || !l.added || l.installing);
  return (
    <ul className={cx("grid gap-2.5", compact ? "" : "[grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))]")}>
      {items.map((lang, n) => (
        <li key={lang.code} className="anim-in" style={{ "--i": n } as React.CSSProperties}>
          <LanguageCard lang={lang} open={open === lang.code} onOpen={() => setOpen(open === lang.code ? null : lang.code)} />
        </li>
      ))}
    </ul>
  );
}

function LanguageCard({ lang, open, onOpen }: { lang: CatalogLanguage; open: boolean; onOpen: () => void }) {
  const add = useAddLanguage();
  const [variant, setVariant] = useState(lang.variant);
  const failed = lang.install?.status === "failed";
  return (
    <div
      className={cx(
        "flex h-full flex-col gap-3 rounded-2xl border p-4 transition",
        (lang.added && !lang.installing) || !lang.available ? "border-white/8 bg-white/[0.02] opacity-60" : "border-white/10 bg-white/[0.045] hover:border-white/20",
        open && "border-white/25 bg-white/[0.07]",
      )}
      style={{ boxShadow: open || lang.installing ? `inset 3px 0 0 ${lang.accent}` : undefined }}
    >
      <button
        type="button"
        onClick={onOpen}
        disabled={!lang.available || lang.added || lang.installing}
        aria-expanded={open}
        className="flex items-start justify-between gap-3 text-left disabled:cursor-default"
      >
        <span className="min-w-0">
          <span className="block text-lg font-bold" style={{ color: lang.accent }} lang={lang.code} dir={lang.direction}>
            {lang.native_name}
          </span>
          <span className="block text-sm font-semibold text-ink">{lang.name}</span>
          <span className="mt-0.5 block text-xs text-ink-3">≈ {speakers(lang.speakers_millions)} speakers</span>
        </span>
        <span className="shrink-0 text-xs font-semibold text-ink-3">
          {lang.installing ? "" : lang.added ? "Added" : !lang.available ? "Coming soon" : lang.download_mb ? `${lang.download_mb} MB` : "Ready"}
        </span>
      </button>

      {lang.installing && (
        <div role="status">
          <ProgressBar value={lang.install?.progress ?? 0} label={`Setting up ${lang.name}`} />
          <p className="mt-1.5 truncate text-xs text-ink-3">{String(lang.install?.result?.message ?? `Setting up ${lang.name}…`)}</p>
        </div>
      )}
      {failed && !lang.installing && (
        <p role="alert" className="text-xs text-red-200">
          The download didn't finish ({lang.install?.error ?? "network error"}). Try again.
        </p>
      )}

      {open && !lang.added && !lang.installing && (
        <div className="anim-fade flex flex-col gap-3">
          {lang.variants.length > 1 && (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1 text-xs font-medium text-ink-2">Which variety?</legend>
              {lang.variants.map((v) => (
                <label key={v.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name={`variant-${lang.code}`}
                    checked={variant === v.id}
                    onChange={() => setVariant(v.id)}
                    className="size-4 accent-[var(--accent)]"
                  />
                  {v.label}
                </label>
              ))}
              <span className="text-xs text-ink-3">Sets the voices and where videos and articles come from. You can change it later.</span>
            </fieldset>
          )}
          <Button
            variant="primary"
            disabled={add.isPending}
            onClick={() => add.mutate({ code: lang.code, variant })}
            style={{ background: lang.accent, color: lang.accent_ink }}
          >
            {lang.download_mb ? `Add ${lang.name} · download ${lang.download_mb} MB` : `Add ${lang.name}`}
          </Button>
          {add.isError && <p role="alert" className="text-xs text-red-200">{add.error.message}</p>}
        </div>
      )}
    </div>
  );
}
