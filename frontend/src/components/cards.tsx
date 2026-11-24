import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api/client";
import { useContentMutation } from "../api/hooks";
import type { UpNextPick } from "../api/types";
import { cx } from "./ui";

/** How an item sits against your level, in plain words, with a colour. */
export const BANDS: Record<string, { label: string; tone: string; hint: string }> = {
  too_easy: { label: "Easy", tone: "bg-white/12 text-ink-2", hint: "You know nearly every word: relaxing, little to learn." },
  comfortable: { label: "Comfortable", tone: "bg-emerald-400/18 text-good", hint: "A few new words: easy to follow." },
  i_plus_1: { label: "Just right", tone: "bg-accent/20 text-accent", hint: "Mostly known, with enough new words to learn from." },
  stretch: { label: "Stretch", tone: "bg-orange-400/18 text-warn", hint: "Harder: you'll miss some of it, and learn a lot." },
  too_hard: { label: "Hard", tone: "bg-red-400/18 text-red-200", hint: "Too many unknown words to enjoy yet." },
};

export function LevelChip({ band, coverage, className }: { band: string | null; coverage: number | null; className?: string }) {
  const info = band ? BANDS[band] : null;
  if (!info && coverage === null) return null;
  return (
    <span
      title={info?.hint}
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap backdrop-blur-md",
        info?.tone ?? "bg-white/12 text-ink-2",
        className,
      )}
    >
      {info?.label}
      {coverage !== null && <span className="font-medium opacity-80">· {Math.round(coverage * 100)}% known</span>}
    </span>
  );
}

const READ_SPEED = 150; // words a minute for a learner, roughly

export function readingMinutes(words: number | null): number | null {
  return words ? Math.max(1, Math.round(words / READ_SPEED)) : null;
}

export function videoThumb(pick: Pick<UpNextPick, "source" | "external_id">, size: "mq" | "hq" | "maxres" = "mq"): string | null {
  return pick.source === "youtube" && pick.external_id ? `https://i.ytimg.com/vi/${pick.external_id}/${size}default.jpg` : null;
}

export function targetOf(pick: Pick<UpNextPick, "kind">): "/read/$itemId" | "/manga/$itemId" | "/watch/$itemId" {
  return pick.kind === "reading" ? "/read/$itemId" : pick.kind === "manga" ? "/manga/$itemId" : "/watch/$itemId";
}

const TYPE_LABELS: Record<string, string> = { epub: "Book", pdf: "PDF", article: "Article", text: "Text", manga_volume: "Manga" };

function hue(seed: string): number {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

/** A cover for things without a picture: the site or author's name on a colour of its own. */
export function GeneratedCover({ pick, className }: { pick: UpNextPick; className?: string }) {
  const name = pick.site || pick.creator || TYPE_LABELS[pick.type] || "Text";
  const h = hue(name);
  return (
    <div
      aria-hidden="true"
      className={cx("flex h-full w-full flex-col justify-between p-3.5", className)}
      style={{ background: `linear-gradient(135deg, hsl(${h} 45% 30%), hsl(${(h + 50) % 360} 55% 16%))` }}
    >
      <span className="text-[10px] font-bold tracking-[0.14em] text-white/70 uppercase">{TYPE_LABELS[pick.type] ?? pick.type}</span>
      <span className="line-clamp-2 font-serif text-xl leading-tight font-semibold text-white/90">{name}</span>
    </div>
  );
}

function Picture({ pick, size = "mq" }: { pick: UpNextPick; size?: "mq" | "hq" | "maxres" }) {
  const [failed, setFailed] = useState(0);
  const sources = [
    pick.kind === "video" ? videoThumb(pick, size) : pick.image,
    pick.kind === "video" && size === "maxres" ? videoThumb(pick, "hq") : null,
  ].filter((s): s is string => Boolean(s));
  const src = sources[failed];
  if (!src) return <GeneratedCover pick={pick} />;
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed((n) => n + 1)}
      className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
    />
  );
}

export function lengthLabel(pick: UpNextPick): string | null {
  if (pick.kind === "video") return pick.duration_sec ? `${Math.round(pick.duration_sec / 60)} min` : null;
  if (pick.kind === "manga") return null;
  const minutes = readingMinutes(pick.word_count);
  return minutes ? `${minutes} min read` : null;
}

function DismissButton({ pick, className, labelled }: { pick: UpNextPick; className?: string; labelled?: boolean }) {
  const dismiss = useContentMutation((id: number) => api.dismiss(id));
  return (
    <button
      type="button"
      onClick={() => dismiss.mutate(pick.id)}
      disabled={dismiss.isPending}
      aria-label={labelled ? undefined : `Not interested in ${pick.title}`}
      title="Not interested: hide it"
      className={cx(
        "z-10 flex items-center justify-center text-white/85 backdrop-blur-md transition hover:text-white",
        labelled
          ? "min-h-11 rounded-xl bg-white/10 px-4 text-sm font-semibold hover:bg-white/16"
          : "size-8 rounded-full bg-black/60 text-base opacity-0 hover:bg-black/80 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100",
        className,
      )}
    >
      {labelled ? "Not interested" : "×"}
    </button>
  );
}

/** The card used in every suggestion grid and row: a big picture, the level, the title, why it was picked. */
export function PickCard({ pick, className }: { pick: UpNextPick; className?: string }) {
  const length = lengthLabel(pick);
  const inProgress = (pick.progress ?? 0) > 0.02 && (pick.progress ?? 0) < 0.9;
  return (
    <article
      className={cx(
        "group relative flex h-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.045] transition hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.08]",
        className,
      )}
    >
      <div className="relative aspect-video overflow-hidden bg-black/40">
        <Picture pick={pick} />
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-14 bg-gradient-to-b from-black/45 to-transparent" />
        <LevelChip band={pick.band} coverage={pick.coverage} className="absolute top-2 left-2 bg-black/55" />
        {length && (
          <span className="absolute right-2 bottom-2 rounded-md bg-black/75 px-1.5 py-0.5 text-[11px] font-semibold">{length}</span>
        )}
        {inProgress && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
            <div className="h-full bg-accent" style={{ width: `${(pick.progress ?? 0) * 100}%` }} />
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <Link
          to={targetOf(pick)}
          params={{ itemId: String(pick.id) }}
          className="line-clamp-2 text-[15px] leading-snug font-semibold outline-none after:absolute after:inset-0 after:content-[''] focus-visible:underline"
        >
          {pick.title}
        </Link>
        <p className="truncate text-xs text-ink-3">{pick.site || pick.creator || TYPE_LABELS[pick.type]}</p>
        <p className="mt-auto pt-1 text-xs leading-snug text-ink-2">{reasonLine(pick)}</p>
      </div>
      <DismissButton pick={pick} className="absolute top-2 right-2" />
    </article>
  );
}

function reasonLine(pick: UpNextPick): string {
  // the % known is already on the picture
  const rest = pick.reasons.filter((r) => !r.endsWith("% known"));
  if (rest.length) return rest.join(" · ");
  if (pick.expected_unknown !== null) return `≈ ${Math.round(pick.expected_unknown)} new words`;
  return "";
}

/** The big card at the top of Today. */
export function FeaturedCard({ pick }: { pick: UpNextPick }) {
  const length = lengthLabel(pick);
  const verb = pick.kind === "video" ? "Watch now" : pick.kind === "manga" ? "Read the volume" : "Read now";
  const inProgress = (pick.progress ?? 0) > 0.02 && (pick.progress ?? 0) < 0.9;
  return (
    <article className="group relative isolate flex min-h-[320px] flex-col justify-end overflow-hidden rounded-[22px] border border-white/12 bg-black/40 md:min-h-[380px]">
      <div className="absolute inset-0 -z-10">
        <Picture pick={pick} size="maxres" />
      </div>
      <div aria-hidden="true" className="absolute inset-0 -z-10 bg-gradient-to-t from-[#05070d] via-[#05070d]/75 to-[#05070d]/10" />
      <div aria-hidden="true" className="absolute inset-0 -z-10 bg-gradient-to-r from-[#05070d]/80 via-[#05070d]/30 to-transparent" />
      <div className="flex flex-col gap-3 p-5 md:p-7">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-white/14 px-2.5 py-1 text-[11px] font-bold tracking-[0.12em] text-white/90 uppercase backdrop-blur-md">
            {inProgress ? "Continue" : "Top pick for you"}
          </span>
          <LevelChip band={pick.band} coverage={pick.coverage} className="bg-black/50 text-xs" />
        </div>
        <h2 className="line-clamp-3 max-w-3xl text-2xl leading-tight font-bold text-white md:text-[32px]">{pick.title}</h2>
        <p className="text-sm text-white/75">
          {[pick.site || pick.creator, length, ...pick.reasons.filter((r) => !r.endsWith("% known"))].filter(Boolean).join(" · ")}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Link
            to={targetOf(pick)}
            params={{ itemId: String(pick.id) }}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-bold text-accent-ink transition hover:brightness-110"
          >
            {pick.kind === "video" && <span aria-hidden="true">▶</span>} {verb}
          </Link>
          <DismissButton pick={pick} labelled />
        </div>
      </div>
    </article>
  );
}

/** A compact row: thumbnail, title, level. Used beside the featured card. */
export function PickRow({ pick }: { pick: UpNextPick }) {
  const length = lengthLabel(pick);
  return (
    <article className="group relative flex gap-3 rounded-2xl border border-white/8 bg-white/[0.04] p-2 transition hover:border-white/16 hover:bg-white/[0.08]">
      <div className="relative aspect-video w-[132px] shrink-0 overflow-hidden rounded-xl bg-black/40">
        <Picture pick={pick} />
        {length && <span className="absolute right-1 bottom-1 rounded bg-black/75 px-1 text-[10px] font-semibold">{length}</span>}
      </div>
      <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 pr-1">
        <Link
          to={targetOf(pick)}
          params={{ itemId: String(pick.id) }}
          className="line-clamp-2 text-sm leading-snug font-semibold outline-none after:absolute after:inset-0 after:content-[''] focus-visible:underline"
        >
          {pick.title}
        </Link>
        <div className="flex min-w-0 items-center gap-2">
          <LevelChip band={pick.band} coverage={null} />
          <span className="truncate text-xs text-ink-3">{pick.site || pick.creator}</span>
        </div>
      </div>
    </article>
  );
}
