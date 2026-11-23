import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { useAiStatus, useAiUsage } from "../api/hooks";
import { Button, Chip, Panel, PanelTitle, Skeleton } from "./ui";

const TASK_LABELS: Record<string, string> = {
  "lookup.context_gloss": "Meaning in context",
  "lookup.grammar": "Grammar breakdowns",
};

/** Settings: is AI on, with which model, what it has cost, and how to turn it on. */
export function AiPanel() {
  const status = useAiStatus();
  const usage = useAiUsage();
  const qc = useQueryClient();
  const test = useMutation({
    mutationFn: api.aiTest,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["ai-usage"] });
      void qc.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });
  const context = status.data?.context;

  return (
    <Panel aria-labelledby="t-ai">
      <PanelTitle
        id="t-ai"
        aside={context && (context.enabled ? <Chip tone="good">on</Chip> : <Chip tone="warn">off · dictionary only</Chip>)}
      >
        AI explanations
      </PanelTitle>
      {!context ? (
        <Skeleton className="h-24" />
      ) : context.enabled ? (
        <>
          <p className="text-sm text-ink-2">
            Clicked words get their meaning in that sentence; any sentence can be broken down. Answers are cached, so a
            sentence you've asked about before costs nothing.
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <div className="well rounded-xl p-3">
              <dt className="text-xs text-ink-3">Provider</dt>
              <dd className="mt-1 font-semibold">{context.provider}</dd>
            </div>
            <div className="well rounded-xl p-3">
              <dt className="text-xs text-ink-3">Model</dt>
              <dd className="mt-1 truncate font-semibold">{context.model}</dd>
            </div>
          </dl>
        </>
      ) : (
        <div className="text-sm leading-relaxed text-ink-2">
          <p>Off: {context.reason}. Word lookups still work from the dictionaries.</p>
          <ol className="mt-2 list-decimal pl-5">
            <li>
              Create an API key at <span className="text-ink">aistudio.google.com</span>.
            </li>
            <li>
              Copy <code className="rounded bg-black/40 px-1">.env.example</code> to <code className="rounded bg-black/40 px-1">.env</code> in
              the project folder and paste it after <code className="rounded bg-black/40 px-1">GEMINI_API_KEY=</code>.
            </li>
            <li>Restart the app, then press Test.</li>
          </ol>
          <p className="mt-2 text-xs text-ink-3">
            Other providers (OpenRouter, Ollama on this laptop) go in <code>config/llm.yaml</code>. Only the sentence you
            ask about is sent, never your word list or history.
          </p>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Testing…" : "Test connection"}
        </Button>
        {test.isSuccess && (
          <span className="text-sm text-good">
            Working: {test.data.provider} / {test.data.model}
          </span>
        )}
        {test.isError && <span className="text-sm text-red-200">{test.error.message}</span>}
      </div>

      {usage.data && usage.data.calls > 0 && (
        <div className="mt-4 border-t border-white/8 pt-3">
          <h3 className="text-xs font-semibold text-ink-3">Last {usage.data.days} days</h3>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {usage.data.tasks.map((t) => (
              <li key={t.task} className="flex justify-between gap-3">
                <span className="text-ink-2">{TASK_LABELS[t.task] ?? t.task}</span>
                <span>
                  {t.calls} calls · {(t.tokens_in + t.tokens_out).toLocaleString("en")} tokens
                  {t.cost !== null && ` · $${t.cost.toFixed(3)}`}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-ink-3">{usage.data.cache_hits} answers came from the cache.</p>
        </div>
      )}
    </Panel>
  );
}
