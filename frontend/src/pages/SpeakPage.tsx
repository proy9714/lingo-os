import { useEffect, useState } from "react";

import { useActiveLanguage } from "../api/hooks";
import { ShadowStudio } from "../components/speak/ShadowStudio";
import { TutorPanel } from "../components/speak/TutorPanel";
import { cx } from "../components/ui";
import { useShadowTarget } from "../state/shadow";

type Tab = "tutor" | "shadowing";

export function SpeakPage() {
  const { code, language } = useActiveLanguage();
  const target = useShadowTarget((s) => s.clipId);
  const clear = useShadowTarget((s) => s.clear);
  const [tab, setTab] = useState<Tab>(target !== null ? "shadowing" : "tutor");
  const [clip, setClip] = useState<number | null>(target);

  // "Shadow this line" in the player lands here with that clip open.
  useEffect(() => {
    if (target !== null) {
      setTab("shadowing");
      setClip(target);
      clear();
    }
  }, [target, clear]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3 px-1 pt-1">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight">Speak</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
            Talk with a tutor that stays at your level, or shadow lines from what you watch. Both count as speaking time.
          </p>
        </div>
        <div role="tablist" aria-label="Speaking practice" className="glass flex gap-1 rounded-2xl p-1">
          {(["tutor", "shadowing"] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cx(
                "min-h-10 rounded-xl px-4 text-sm font-semibold transition",
                tab === key ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-white/8",
              )}
            >
              {key === "tutor" ? "Tutor" : "Shadowing"}
            </button>
          ))}
        </div>
      </header>
      {tab === "tutor" ? <TutorPanel lang={code} /> : <ShadowStudio key={code} lang={code} initialClip={clip} />}
      <span className="sr-only">{language?.name}</span>
    </div>
  );
}
