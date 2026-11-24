import { Link } from "@tanstack/react-router";

import { useTaste } from "../api/hooks";
import { Chip, Panel, PanelTitle, Skeleton } from "./ui";

/** What the suggestions have learned from you: channels and topics you enjoy, and your calibrated level. */
export function TasteCard({ lang }: { lang: string }) {
  const taste = useTaste(lang).data;
  if (!taste) return <Skeleton className="h-[300px] rounded-[20px]" />;
  const listening = taste.calibration.listening;
  const reading = taste.calibration.reading;
  return (
    <Panel aria-labelledby="t-taste">
      <PanelTitle id="t-taste" aside={<Chip>{taste.signals} signals</Chip>}>
        What your suggestions learned
      </PanelTitle>
      {taste.signals === 0 ? (
        <p className="text-sm text-ink-2">
          Watch and read a few things: what you finish, come back to or skip teaches the suggestions what you like.
        </p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          {taste.channels.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-xs font-semibold text-ink-3">More of</h3>
              <div className="flex flex-wrap gap-1.5">
                {taste.channels.slice(0, 6).map((c) => (
                  <Chip key={c.name} tone="good" className="text-[11px]">
                    {c.name}
                  </Chip>
                ))}
              </div>
            </div>
          )}
          {taste.topics.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-xs font-semibold text-ink-3">Topics you enjoy</h3>
              <p lang={lang} className="text-ink-2">
                {taste.topics.slice(0, 10).join(" · ")}
              </p>
            </div>
          )}
          {(taste.less_of.length > 0 || taste.lengths.length > 0) && (
            <p className="text-xs text-ink-3">
              {taste.lengths.length > 0 && `You usually finish: ${taste.lengths.map((l) => l.bucket).join(", ")}. `}
              {taste.less_of.length > 0 && `Less of: ${taste.less_of.map((c) => c.name).join(", ")}.`}
            </p>
          )}
        </div>
      )}
      <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <div className="well rounded-xl p-3">
          <div className="text-xs text-ink-3">"Just right" for videos</div>
          <div className="mt-1 font-semibold">≈ {Math.round(listening.ideal * 100)}% known</div>
          <div className="text-[11px] text-ink-3">{listening.ratings ? `from ${listening.ratings} ratings` : "default: rate videos to tune"}</div>
        </div>
        <div className="well rounded-xl p-3">
          <div className="text-xs text-ink-3">"Just right" for reading</div>
          <div className="mt-1 font-semibold">≈ {Math.round(reading.ideal * 100)}% known</div>
          <div className="text-[11px] text-ink-3">{reading.ratings ? `from ${reading.ratings} ratings` : "default: rate texts to tune"}</div>
        </div>
      </div>
      <Link to="/watch" className="mt-3 inline-block text-sm font-semibold text-accent hover:underline">
        Rate videos you've watched →
      </Link>
    </Panel>
  );
}
