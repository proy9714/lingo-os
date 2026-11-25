import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useAiModels, useAiProviders, useAiStatus, useAiUsage } from "../api/hooks";
import type { AiProvider, AiProviders } from "../api/types";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "./ui";

const TASK_LABELS: Record<string, string> = {
  "lookup.context_gloss": "Meaning in context",
  "lookup.grammar": "Grammar breakdowns",
  "tutor.chat": "Tutor",
};

const BLURB: Record<string, string> = {
  gemini: "Google. Has a free tier.",
  claude: "Anthropic. Careful, natural explanations.",
  chatgpt: "OpenAI.",
};

/** Settings: choose Gemini, Claude or ChatGPT, paste a key, pick models, test, and see what it has cost. */
export function AiPanel() {
  const status = useAiStatus();
  const providers = useAiProviders();
  const usage = useAiUsage();
  const qc = useQueryClient();
  const refresh = (data?: AiProviders) => {
    if (data) qc.setQueryData(["ai-providers"], data);
    void qc.invalidateQueries({ queryKey: ["ai-status"] });
    void qc.invalidateQueries({ queryKey: ["ai-usage"] });
  };
  const choose = useMutation({ mutationFn: api.aiChoose, onSuccess: refresh });
  const test = useMutation({ mutationFn: api.aiTest, onSettled: () => refresh() });
  const context = status.data?.context;
  const data = providers.data;

  return (
    <Panel aria-labelledby="t-ai">
      <PanelTitle
        id="t-ai"
        aside={context && (context.enabled ? <Chip tone="good">on · {context.provider}</Chip> : <Chip tone="warn">off · dictionary only</Chip>)}
      >
        AI explanations
      </PanelTitle>
      <p className="text-sm text-ink-2">
        Clicked words get their meaning in that sentence, any sentence can be broken down, and the tutor talks with you. Pick
        the AI you have a key for. Only the sentence you ask about is sent, never your word list or history, and answers are
        cached, so asking again costs nothing.
      </p>

      {!data ? (
        <Skeleton className="mt-3 h-40" />
      ) : (
        <>
          <div role="radiogroup" aria-label="AI provider" className="mt-3 grid gap-2 sm:grid-cols-2">
            <ProviderOption
              checked={data.selected === "auto"}
              onSelect={() => choose.mutate({ provider: "auto" })}
              title="Auto"
              detail={`The first one with a key${data.active && data.selected === "auto" ? `: now ${label(data, data.active)}` : ""}`}
            />
            {data.providers.map((p) => (
              <ProviderOption
                key={p.id}
                checked={data.selected === p.id}
                onSelect={() => choose.mutate({ provider: p.id })}
                title={p.label}
                detail={BLURB[p.id] ?? ""}
                badge={<Chip tone={p.has_key ? "good" : "neutral"} className="whitespace-nowrap">{p.has_key ? "key set" : "no key"}</Chip>}
              />
            ))}
          </div>
          {data.providers
            .filter((p) => (data.selected === "auto" ? p.id === (data.active ?? data.providers[0]?.id) : p.id === data.selected))
            .map((p) => (
              <ProviderDetails key={p.id} provider={p} onSaved={refresh} />
            ))}
          {data.local_only && (
            <p className="mt-2 text-xs text-warn">Local-only mode is on in config/llm.yaml: cloud providers are not used.</p>
          )}
        </>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Testing…" : "Test connection"}
        </Button>
        {test.isSuccess && (
          <span className="text-sm text-good">
            Working: {label(data, test.data.provider)} / {test.data.model}
          </span>
        )}
        {test.isError && <span className="text-sm text-red-200">{test.error.message}</span>}
        {choose.isError && <span className="text-sm text-red-200">{choose.error.message}</span>}
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

function label(data: AiProviders | undefined, id: string): string {
  return data?.providers.find((p) => p.id === id)?.label ?? id;
}

function ProviderOption({
  checked,
  onSelect,
  title,
  detail,
  badge,
}: {
  checked: boolean;
  onSelect: () => void;
  title: string;
  detail: string;
  badge?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      onClick={onSelect}
      className={cx(
        "flex items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition",
        checked ? "border-accent/70 bg-accent/10" : "border-white/10 bg-black/20 hover:border-white/25",
      )}
    >
      <span
        aria-hidden="true"
        className={cx("mt-1 size-3.5 shrink-0 rounded-full border-2", checked ? "border-accent bg-accent" : "border-white/40")}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-2">
          <span className="font-semibold">{title}</span>
          {badge}
        </span>
        <span className="mt-0.5 block text-xs text-ink-3">{detail}</span>
      </span>
    </button>
  );
}

/** The chosen provider: paste or remove its key, and pick its models. */
function ProviderDetails({ provider, onSaved }: { provider: AiProvider; onSaved: (data: AiProviders) => void }) {
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: (value: string) => api.aiSaveKey(provider.id, value),
    onSuccess: (data) => {
      setKey("");
      onSaved(data);
    },
  });
  return (
    <div className="well mt-3 rounded-xl p-3 text-sm">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (key.trim()) save.mutate(key.trim());
        }}
      >
        <label className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-xs text-ink-3">
            {provider.label} API key{" "}
            {provider.key_url && (
              <a href={provider.key_url} target="_blank" rel="noreferrer noopener" className="text-accent hover:underline">
                (create one)
              </a>
            )}
          </span>
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={provider.has_key ? `Saved (${provider.key_hint ?? "set"}): paste a new one to replace it` : "Paste your key"}
            className="min-h-10 rounded-lg border border-white/12 bg-black/30 px-3 text-ink outline-none focus:border-accent/60"
          />
        </label>
        <div className="flex gap-2 self-end">
          <Button type="submit" variant="primary" disabled={!key.trim() || save.isPending}>
            {save.isPending ? "Saving…" : "Save key"}
          </Button>
          {provider.has_key && (
            <Button type="button" variant="ghost" disabled={save.isPending} onClick={() => save.mutate("")}>
              Remove
            </Button>
          )}
        </div>
      </form>
      {save.isError && <p className="mt-1.5 text-red-200">{save.error.message}</p>}
      <p className="mt-1.5 text-xs text-ink-3">
        Saved in <code>.env</code> on this computer ({provider.key_env}), never shown again and never sent anywhere but{" "}
        {provider.label}.
      </p>
      {provider.has_key && <ModelPicker provider={provider} onSaved={onSaved} />}
    </div>
  );
}

const TIERS = [
  { id: "fast", label: "Quick look-ups", hint: "word meanings, grammar, the tutor" },
  { id: "smart", label: "Deeper work", hint: "speaking feedback, weekly review" },
] as const;

function ModelPicker({ provider, onSaved }: { provider: AiProvider; onSaved: (data: AiProviders) => void }) {
  const [open, setOpen] = useState(false);
  const models = useAiModels(provider.id, open);
  const choose = useMutation({ mutationFn: api.aiChoose, onSuccess: onSaved });
  if (!open) {
    return (
      <p className="mt-2 text-xs text-ink-2">
        Models: {provider.models.fast}
        {provider.models.smart !== provider.models.fast && ` · ${provider.models.smart} for deeper work`}{" "}
        <button type="button" className="font-semibold text-accent hover:underline" onClick={() => setOpen(true)}>
          Change
        </button>
      </p>
    );
  }
  const list = models.data?.models ?? [];
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {TIERS.map((tier) => {
        const current = provider.chosen[tier.id] ?? "";
        const options = Array.from(new Set([...list, ...(current ? [current] : [])])).sort();
        return (
          <label key={tier.id} className="flex flex-col gap-1">
            <span className="text-xs text-ink-3">
              {tier.label} <span className="text-ink-3/80">({tier.hint})</span>
            </span>
            <select
              value={current}
              disabled={models.isLoading || choose.isPending}
              onChange={(e) => choose.mutate({ models: { [provider.id]: { [tier.id]: e.target.value || null } } })}
              className="min-h-10 rounded-lg border border-white/12 bg-black/30 px-2 text-ink outline-none focus:border-accent/60"
            >
              <option value="">Default: {provider.defaults[tier.id]}</option>
              {options.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        );
      })}
      {models.isLoading && <p className="text-xs text-ink-3 sm:col-span-2">Asking {provider.label} which models your key can use…</p>}
      {models.isError && <p className="text-xs text-red-200 sm:col-span-2">{models.error.message}</p>}
    </div>
  );
}
