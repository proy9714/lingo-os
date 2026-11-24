import { useMarkWatched } from "../api/hooks";
import { useUi } from "../state/ui";
import { Icon } from "./Icon";
import { cx } from "./ui";

const WORDS = {
  video: { mark: "Mark as completed", done: "Completed", toast: "Completed: it's in your Watched list.", undone: "Marked as not completed." },
  text: { mark: "Mark as read", done: "Read", toast: "Marked as read: it won't be suggested again.", undone: "Marked as not read." },
} as const;

/** Finished it (here or elsewhere): it leaves the suggestions and counts toward what you like. Click again to undo. */
export function CompletedButton({
  id,
  finished,
  kind,
  onDone,
}: {
  id: number;
  finished: boolean;
  kind: "video" | "text";
  onDone?: () => void;
}) {
  const mark = useMarkWatched();
  const showToast = useUi((s) => s.showToast);
  const words = WORDS[kind];
  const toggle = () =>
    mark.mutate(
      { id, watched: !finished },
      {
        onSuccess: () => {
          if (finished) showToast(words.undone);
          else {
            onDone?.();
            showToast(words.toast, { label: "Undo", run: () => mark.mutate({ id, watched: false }) }, { itemId: id, kind });
          }
        },
        onError: (error) => showToast(`Couldn't save that: ${error.message}`),
      },
    );
  return (
    <button
      type="button"
      aria-pressed={finished}
      onClick={toggle}
      disabled={mark.isPending}
      title={finished ? `${words.done}. Click to undo` : words.mark}
      className={cx(
        "inline-flex min-h-10 items-center gap-2 rounded-xl px-3.5 text-sm font-semibold transition disabled:opacity-60",
        finished
          ? "anim-pop border border-emerald-400/40 bg-emerald-400/15 text-good hover:bg-emerald-400/22"
          : "border border-white/16 bg-white/8 text-ink hover:bg-white/12",
      )}
    >
      <Icon name="check" size={16} />
      {finished ? words.done : words.mark}
    </button>
  );
}
