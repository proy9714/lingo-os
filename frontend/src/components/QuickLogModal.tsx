import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useActiveLanguage, useLogManual } from "../api/hooks";
import { ACTIVITY_LABELS, formatMinutes, todayIso } from "../lib/format";
import { useUi } from "../state/ui";
import { Icon } from "./Icon";
import { Button, cx } from "./ui";

const ACTIVITIES = ["video", "podcast", "audio", "reading", "manga", "conversation", "class", "writing", "other"];
const PRESETS = [15, 30, 45, 60];
const field =
  "min-h-11 w-full rounded-xl border border-white/14 bg-surface px-3 text-sm text-ink placeholder:text-ink-3 focus:border-accent";

export function QuickLogModal() {
  const open = useUi((s) => s.quickLogOpen);
  const close = useUi((s) => s.closeQuickLog);
  const showToast = useUi((s) => s.showToast);
  const { code, languages } = useActiveLanguage();
  const log = useLogManual();
  const titleId = useId();
  const returnFocus = useRef<Element | null>(null);

  const [language, setLanguage] = useState(code);
  const [activity, setActivity] = useState("podcast");
  const [minutes, setMinutes] = useState(30);
  const [day, setDay] = useState(todayIso());
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    returnFocus.current = document.activeElement;
    setLanguage(code);
    setDay(todayIso());
    log.reset();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      (returnFocus.current as HTMLElement | null)?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    log.mutate(
      { language, activity, minutes, day, title: title || undefined, notes: notes || undefined },
      {
        onSuccess: () => {
          const name = languages.find((l) => l.code === language)?.name ?? language;
          showToast(`Logged ${formatMinutes(minutes)} of ${name}`);
          setTitle("");
          setNotes("");
          close();
        },
      },
    );
  };

  return (
    <div className="anim-fade fixed inset-0 z-40 flex items-end justify-center bg-black/55 p-3 backdrop-blur-sm sm:items-center" onClick={close}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="anim-dialog glass-strong max-h-[92dvh] w-full max-w-md overflow-y-auto rounded-3xl p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 id={titleId} className="text-lg font-bold">
            Log offline time
          </h2>
          <button type="button" onClick={close} aria-label="Close" className="flex size-11 items-center justify-center rounded-xl text-ink-2 hover:bg-white/8">
            <Icon name="close" size={20} />
          </button>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">
              Language
              <select className={field} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {languages.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">
              Activity
              <select className={field} value={activity} onChange={(e) => setActivity(e.target.value)}>
                {ACTIVITIES.map((a) => (
                  <option key={a} value={a}>
                    {ACTIVITY_LABELS[a]}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1.5 text-xs font-medium text-ink-2">Duration</legend>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  aria-pressed={minutes === preset}
                  onClick={() => setMinutes(preset)}
                  className={cx(
                    "min-h-10 rounded-xl px-3.5 text-sm font-semibold transition",
                    minutes === preset ? "bg-accent text-accent-ink" : "border border-white/14 text-ink-2 hover:bg-white/8",
                  )}
                >
                  {preset} min
                </button>
              ))}
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input
                  type="number"
                  min={1}
                  max={720}
                  value={minutes}
                  onChange={(e) => setMinutes(Number(e.target.value))}
                  className={cx(field, "w-24")}
                  aria-label="Minutes"
                  autoFocus
                />
                min
              </label>
            </div>
          </fieldset>

          <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">
            Day
            <input type="date" className={field} value={day} max={todayIso()} onChange={(e) => setDay(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">
            What was it? <span className="font-normal text-ink-3">optional</span>
            <input
              type="text"
              className={field}
              value={title}
              maxLength={200}
              placeholder="e.g. Podcast episode on the bus"
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">
            Notes <span className="font-normal text-ink-3">optional</span>
            <textarea className={cx(field, "min-h-20 py-2")} value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
          </label>

          {log.isError && (
            <p role="alert" className="rounded-xl bg-red-500/15 px-3 py-2 text-sm text-red-200">
              {log.error.message}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" disabled={log.isPending || minutes < 1 || minutes > 720}>
              {log.isPending ? "Saving…" : `Log ${formatMinutes(minutes || 0)}`}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
