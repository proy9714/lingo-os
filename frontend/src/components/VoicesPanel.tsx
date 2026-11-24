import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { useActiveLanguage, useVoices } from "../api/hooks";
import type { Language } from "../api/types";
import { speak } from "../lib/speech";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "./ui";

const SAMPLES: Record<string, string> = {
  de: "Ich rufe dich morgen an, dann können wir alles besprechen.",
  es: "Te llamo mañana y lo hablamos con calma.",
  ja: "明日電話するから、その時にゆっくり話そうね。",
};

/** Settings: which voices read words and sentences aloud. */
export function VoicesPanel() {
  const { languages } = useActiveLanguage();
  const qc = useQueryClient();
  const first = useVoices(languages[0]?.code ?? "");
  const engine = first.data?.engine ?? "neural";
  const save = useMutation({
    mutationFn: api.saveTts,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tts-voices"] }),
  });

  return (
    <Panel aria-labelledby="t-voices">
      <PanelTitle id="t-voices" aside={<Chip tone={engine === "neural" ? "good" : "neutral"}>{engine === "neural" ? "native voices" : "this device only"}</Chip>}>
        Voices
      </PanelTitle>
      <div role="radiogroup" aria-label="Where voices come from" className="flex flex-col gap-2">
        {(
          [
            ["neural", "Native neural voices", "Natural voices for every language, made on this laptop and cached. Needs internet the first time a sentence is spoken: the sentence is sent to Microsoft's speech service (no account)."],
            ["device", "This device's voices only", "Fully offline and private, but only for languages your computer or phone has a voice for. A language without one stays silent instead of being read with an English accent."],
          ] as const
        ).map(([value, title, hint]) => (
          <label
            key={value}
            className={cx(
              "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition",
              engine === value ? "border-accent/50 bg-accent/[0.07]" : "border-white/10 hover:bg-white/[0.04]",
            )}
          >
            <input
              type="radio"
              name="tts-engine"
              checked={engine === value}
              disabled={save.isPending || !first.data}
              onChange={() => save.mutate({ engine: value })}
              className="mt-1 size-4 accent-[var(--accent)]"
            />
            <span>
              <span className="block text-sm font-semibold">{title}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-ink-3">{hint}</span>
            </span>
          </label>
        ))}
      </div>
      <ul className="mt-4 flex flex-col gap-2">
        {languages.map((lang) => (
          <VoiceRow
            key={lang.code}
            lang={lang}
            device={engine === "device"}
            onChoose={(voice) => save.mutate({ lang: lang.code, voice })}
            saving={save.isPending}
          />
        ))}
      </ul>
      {save.isError && <p role="alert" className="mt-2 text-sm text-red-200">{save.error.message}</p>}
    </Panel>
  );
}

function VoiceRow({ lang, device, onChoose, saving }: { lang: Language; device: boolean; onChoose: (voice: string) => void; saving: boolean }) {
  const voices = useVoices(lang.code);
  const data = voices.data;
  if (voices.isPending) return <Skeleton className="h-12 rounded-xl" />;
  return (
    <li className="well flex flex-wrap items-center gap-2 rounded-xl px-3 py-2">
      <span className="w-20 text-sm font-semibold">{lang.name}</span>
      {device ? (
        <span className="flex-1 text-xs text-ink-3">This device's own {lang.name} voice, if it has one</span>
      ) : data && data.voices.length > 0 ? (
        <label className="flex min-w-0 flex-1 items-center">
          <span className="sr-only">{lang.name} voice</span>
          <select
            value={data.voice ?? ""}
            disabled={saving}
            onChange={(e) => onChoose(e.target.value)}
            className="min-h-10 w-full min-w-0 rounded-lg border border-white/14 bg-surface px-2 text-sm text-ink"
          >
            {data.voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} · {v.gender === "Female" ? "female" : v.gender === "Male" ? "male" : v.gender} · {v.locale}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <span className="flex-1 text-xs text-warn">{data?.error ? "Voice list unavailable (offline?)" : "No voices"}</span>
      )}
      <Button
        className="min-h-10 px-3"
        disabled={!device && !data?.voice}
        onClick={() => speak(SAMPLES[lang.code] ?? lang.native_name, lang.code, 1)}
      >
        ▶ Test
      </Button>
    </li>
  );
}
