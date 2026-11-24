import { useState } from "react";

import { useActiveLanguage, useLanguageCatalog, useRemoveLanguage, useSetLanguageVariant } from "../api/hooks";
import { useUi } from "../state/ui";
import { LanguagePicker } from "./LanguagePicker";
import { Button, Chip, Panel, PanelTitle } from "./ui";

/** Settings: the languages you learn (variety, remove) and adding more. */
export function LanguagesPanel() {
  const { languages, code } = useActiveLanguage();
  const catalog = useLanguageCatalog().data ?? [];
  const remove = useRemoveLanguage();
  const setVariant = useSetLanguageVariant();
  const showToast = useUi((s) => s.showToast);
  const [adding, setAdding] = useState(false);
  const variantsOf = (lang: string) => catalog.find((c) => c.code === lang)?.variants ?? [];
  const installing = catalog.filter((c) => c.installing);

  return (
    <Panel id="languages" aria-labelledby="t-languages" className="scroll-mt-4 [grid-column:1/-1]">
      <PanelTitle id="t-languages" aside={<Chip>{languages.length} learning</Chip>}>
        Languages
      </PanelTitle>
      <ul className="flex flex-col gap-2">
        {languages.map((lang) => {
          const variants = variantsOf(lang.code);
          return (
            <li key={lang.code} className="well flex flex-wrap items-center gap-3 rounded-xl px-3 py-2.5">
              <span aria-hidden="true" className="size-3 rounded-full" style={{ background: lang.accent_color }} />
              <span className="min-w-[150px]">
                <span className="font-semibold">{lang.name}</span>{" "}
                <span className="text-ink-3" lang={lang.code} dir={lang.direction}>
                  {lang.native_name}
                </span>
                {lang.code === code && <span className="ml-2 text-xs text-accent">active</span>}
              </span>
              {variants.length > 1 ? (
                <label className="flex items-center gap-2 text-sm text-ink-2">
                  Variety
                  <select
                    value={lang.variant}
                    disabled={setVariant.isPending}
                    onChange={(e) => setVariant.mutate({ code: lang.code, variant: e.target.value })}
                    className="min-h-9 rounded-lg border border-white/14 bg-surface px-2 text-ink"
                  >
                    {variants.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="text-sm text-ink-3">{lang.variant_label}</span>
              )}
              <Button
                variant="ghost"
                className="ml-auto min-h-9 px-3"
                disabled={languages.length === 1 || remove.isPending}
                title={languages.length === 1 ? "Add another language before removing this one" : undefined}
                onClick={() =>
                  remove.mutate(lang.code, {
                    onSuccess: () => showToast(`${lang.name} removed. Your words and history in it are kept: add it again to get them back.`),
                    onError: (error) => showToast(error.message),
                  })
                }
              >
                Remove
              </Button>
            </li>
          );
        })}
      </ul>
      {installing.length > 0 && !adding && (
        <p role="status" className="mt-3 text-sm text-ink-2">
          Setting up {installing.map((c) => c.name).join(", ")} in the background…
        </p>
      )}
      <div className="mt-4">
        {adding ? (
          <>
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold">Add a language (most spoken first)</h3>
              <Button variant="ghost" className="min-h-9 px-3" onClick={() => setAdding(false)}>
                Done
              </Button>
            </div>
            <LanguagePicker onlyNew />
          </>
        ) : (
          <Button onClick={() => setAdding(true)}>+ Add a language</Button>
        )}
      </div>
    </Panel>
  );
}
