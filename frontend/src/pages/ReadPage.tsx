import { useEffect, useState } from "react";

import { useActiveLanguage, useAnnotation } from "../api/hooks";
import { InteractiveText } from "../components/InteractiveText";
import { Button, Chip, Panel, cx } from "../components/ui";

const SAMPLES: Record<string, string> = {
  de: "Am Wochenende rufe ich meine Großeltern an. Sie wohnen auf dem Land und freuen sich immer, wenn sich jemand meldet. Meistens erzählen sie mir, was im Garten gerade wächst und welche Nachbarn umgezogen sind.",
  es: "Cuando por fin llegó el sábado, Lucía decidió aprovechar el buen tiempo. Guardó en la mochila un par de bocadillos y el libro que llevaba semanas sin terminar. El tren salía a las ocho, pero ella apareció en el andén con apenas dos minutos de margen.",
  ja: "週末はいつも近くの公園を散歩します。天気がいい日は、ベンチに座って本を読んだり、子どもたちが遊んでいるのを眺めたりします。帰り道にパン屋さんに寄って、焼きたてのパンを買うのが楽しみです。",
};

const storageKey = (lang: string) => `lingo.read.${lang}`;

function loadText(lang: string): string {
  try {
    return window.localStorage.getItem(storageKey(lang)) ?? "";
  } catch {
    return "";
  }
}

function saveText(lang: string, value: string) {
  try {
    if (value) window.localStorage.setItem(storageKey(lang), value);
    else window.localStorage.removeItem(storageKey(lang));
  } catch {
    // storage unavailable (private window): the text just isn't remembered
  }
}

export function ReadPage() {
  const { code, language } = useActiveLanguage();
  const [text, setText] = useState(() => loadText(code));
  const [draft, setDraft] = useState(text);
  const [editing, setEditing] = useState(!text);

  useEffect(() => {
    const stored = loadText(code);
    setText(stored);
    setDraft(stored);
    setEditing(!stored);
  }, [code]);

  const read = () => {
    const value = draft.trim();
    setText(value);
    saveText(code, value);
    setEditing(!value);
  };

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3 px-1 pt-1">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight">Read</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
            Paste any {language?.name ?? ""} text and click a word to look it up. Books, PDFs and web articles arrive in Phase 3.
          </p>
        </div>
        {!editing && (
          <div className="flex gap-2">
            <Button onClick={() => setEditing(true)}>Edit text</Button>
            <Button
              variant="ghost"
              onClick={() => {
                setDraft("");
                setText("");
                saveText(code, "");
                setEditing(true);
              }}
            >
              Clear
            </Button>
          </div>
        )}
      </header>

      {editing ? (
        <Panel>
          <label className="flex flex-col gap-2 text-sm font-medium text-ink-2">
            Text to read
            <textarea
              lang={code}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={20000}
              placeholder="Paste a paragraph, an article, song lyrics you own, a chat message…"
              className="min-h-56 w-full rounded-xl border border-white/14 bg-surface p-4 text-base leading-relaxed text-ink placeholder:text-ink-3 focus:border-accent"
            />
          </label>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={read} disabled={!draft.trim()}>
              Read it
            </Button>
            <Button variant="ghost" onClick={() => setDraft(SAMPLES[code] ?? "")}>
              Try a sample text
            </Button>
            <span className="ml-auto text-xs text-ink-3">{draft.length.toLocaleString("en")} / 20,000 characters</span>
          </div>
        </Panel>
      ) : (
        <>
          <CoverageBar lang={code} text={text} />
          <article className="rounded-[20px] bg-[#f6f2ea] px-5 py-8 text-[#1f1d1a] shadow-[0_30px_60px_rgb(0_0_0/0.35)] md:px-14 md:py-12">
            <div className={cx("mx-auto max-w-[680px] text-[19px] leading-[1.9]", code === "ja" ? "font-sans" : "font-serif")}>
              <InteractiveText lang={code} text={text} locator="paste" />
            </div>
          </article>
          <Legend />
        </>
      )}
    </div>
  );
}

function CoverageBar({ lang, text }: { lang: string; text: string }) {
  const data = useAnnotation(lang, text).data;
  if (!data || data.summary.known_share === null) return null;
  const share = Math.round(data.summary.known_share * 100);
  return (
    <div className="glass flex flex-wrap items-center gap-2 rounded-2xl px-4 py-3 text-sm">
      <Chip tone="accent">≈ {share}% of words likely known</Chip>
      <Chip>{data.summary.new_words} likely new</Chip>
      <Chip>{data.summary.words} content words</Chip>
      {!data.summary.profile_measured && (
        <span className="text-xs text-ink-3">Estimated from your hours. Take the vocabulary test in Level Lab to sharpen it.</span>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-4 px-1 text-xs text-ink-2">
      <span className="flex items-center gap-1.5">
        <span aria-hidden="true" className="inline-block h-3 w-5 rounded-sm bg-amber-200/80 shadow-[inset_0_-2px_0_#b8700f]" /> likely new
      </span>
      <span className="flex items-center gap-1.5">
        <span aria-hidden="true" className="inline-block h-3 w-5 rounded-sm bg-sky-200/90" /> learning
      </span>
      <span>Plain words: known or probably known. Every word is clickable.</span>
    </div>
  );
}
