import { Link } from "@tanstack/react-router";

import { useSetStatus, useWordMoves } from "../api/hooks";
import type { WordMove } from "../api/types";
import { useUi } from "../state/ui";
import { Button, Panel, PanelTitle, cx } from "./ui";

const LABEL: Record<string, string> = { learning: "learning", familiar: "familiar", known: "known" };

/**
 * Today: words that moved by themselves: up because you kept meeting them in what you watched and read without
 * looking them up, or back a step because you kept looking them up. Each can be undone with one click: your own
 * choice always wins (and tells the model it moved too early).
 */
export function WordMovesCard({ lang }: { lang: string }) {
  const moves = useWordMoves(lang).data?.moves ?? [];
  if (moves.length === 0) return null;
  return (
    <Panel aria-labelledby="t-moves" className="anim-in">
      <PanelTitle id="t-moves" aside={<Link to="/words" className="text-xs font-semibold text-accent hover:underline">All words →</Link>}>
        Words you've got
      </PanelTitle>
      <p className="mb-3 text-sm text-ink-2">
        Words move up when you keep meeting them on different days without looking them up, and back a step when you keep
        looking them up. Disagree? Undo it.
      </p>
      <ul className="flex flex-col gap-1.5">
        {moves.slice(0, 12).map((move) => (
          <MoveRow key={move.lexeme_id} lang={lang} move={move} />
        ))}
      </ul>
      {moves.length > 12 && <p className="mt-2 text-xs text-ink-3">…and {moves.length - 12} more on the Words page.</p>}
    </Panel>
  );
}

function MoveRow({ lang, move }: { lang: string; move: WordMove }) {
  const setStatus = useSetStatus();
  const showToast = useUi((s) => s.showToast);
  const movedBack = move.status !== move.to;
  return (
    <li className="well flex flex-wrap items-center gap-2 rounded-xl px-3 py-2">
      <span lang={lang} className="min-w-0 font-semibold">
        {move.lemma}
        {move.reading && move.reading !== move.lemma && <span className="ml-1.5 text-xs font-normal text-ink-3">{move.reading}</span>}
      </span>
      <span className="text-xs text-ink-3">
        {LABEL[move.from]} →{" "}
        <span className={cx(!movedBack && (move.direction === "down" ? "font-semibold text-warn" : "font-semibold text-good"))}>{LABEL[move.to]}</span>
        {" · "}
        {move.direction === "down" ? `looked up ${move.lookups ?? 2} times` : `met on ${move.days} days`}
      </span>
      <span className="flex-1" />
      {movedBack ? (
        <span className="text-xs text-ink-3">now {LABEL[move.status] ?? move.status}</span>
      ) : (
        <Button
          variant="ghost"
          className="min-h-8 px-2.5 text-xs"
          disabled={setStatus.isPending}
          onClick={() =>
            setStatus.mutate(
              { lang, lemma: move.lemma, reading: move.reading, status: move.from },
              { onSuccess: () => showToast(`“${move.lemma}” is ${LABEL[move.from]} again.`) },
            )
          }
        >
          Move back to {LABEL[move.from]}
        </Button>
      )}
    </li>
  );
}
