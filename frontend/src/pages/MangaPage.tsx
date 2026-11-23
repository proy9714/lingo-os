import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api, mangaImage } from "../api/client";
import { useActiveLanguage, useContentList, useContentMutation, useMangaInbox } from "../api/hooks";
import type { ContentItem, MangaScanResult } from "../api/types";
import { Button, Chip, Panel, PanelTitle, Skeleton } from "../components/ui";

const CATALOG_URL = "https://catalog.mokuro.moe";

export function MangaPage() {
  const { code, language } = useActiveLanguage();
  const list = useContentList(code, "", "manga");
  const inbox = useMangaInbox();
  const scan = useContentMutation(() => api.mangaScan());
  const upload = useContentMutation((file: File) => api.mangaUpload(code, file));
  const fileInput = useRef<HTMLInputElement>(null);
  const [last, setLast] = useState<MangaScanResult | null>(null);

  // Anything dropped into the inbox shows up when you open this page.
  useEffect(() => {
    scan.mutate(undefined, { onSuccess: (result) => result.results.length > 0 && setLast(result) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const report = upload.data ?? last;
  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Manga</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          Read manga with a text layer over the speech bubbles (mokuro format). Hover a bubble to see its text, click a word
          to look it up.
        </p>
      </header>

      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))]">
        <Panel aria-labelledby="t-add-manga">
          <PanelTitle id="t-add-manga">Add volumes</PanelTitle>
          <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm leading-relaxed text-ink-2">
            <li>
              Drop volumes into the inbox folder:
              <code className="mt-1 block overflow-x-auto rounded-lg bg-black/40 px-2 py-1.5 text-xs whitespace-nowrap text-ink">
                {inbox.data?.folder ?? "data\\inbox\\manga"}
              </code>
              A <code>.mokuro</code> file with its image folder, a folder of page images, or a <code>.zip</code>/
              <code>.cbz</code>. Japanese by default; put {language && code !== "ja" ? language.name : "other-language"} volumes
              in a <code>{code !== "ja" ? code : "de"}</code> subfolder.
            </li>
            <li>
              They're imported when you open this page or press Scan. Volumes move into your library folder and zips into{" "}
              <code>_imported</code>; nothing is deleted.
            </li>
          </ol>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" disabled={scan.isPending} onClick={() => scan.mutate(undefined, { onSuccess: setLast })}>
              {scan.isPending ? "Scanning…" : "Scan the inbox"}
            </Button>
            <Button disabled={upload.isPending} onClick={() => fileInput.current?.click()}>
              {upload.isPending ? "Importing…" : "Upload a .zip / .cbz"}
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept=".zip,.cbz,application/zip"
              className="sr-only"
              tabIndex={-1}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
                e.target.value = "";
              }}
            />
          </div>
          {(scan.error ?? upload.error) && (
            <p role="alert" className="mt-3 text-sm text-red-200">
              {(scan.error ?? upload.error)?.message}
            </p>
          )}
          {report && (
            <ul className="mt-3 flex flex-col gap-1 text-sm">
              {report.results.length === 0 ? (
                <li className="text-ink-3">Nothing new in the inbox.</li>
              ) : (
                report.results.map((r, i) => (
                  <li key={`${r.title}-${i}`} className="text-ink-2">
                    <span className="text-ink">{r.title}</span>: {r.status}
                    {r.item_id !== undefined && (
                      <>
                        {" · "}
                        <Link to="/manga/$itemId" params={{ itemId: String(r.item_id) }} className="text-accent underline">
                          open
                        </Link>
                      </>
                    )}
                  </li>
                ))
              )}
            </ul>
          )}
        </Panel>

        <Panel aria-labelledby="t-bunko">
          <PanelTitle id="t-bunko">Mokuro Bunko catalog</PanelTitle>
          <p className="text-sm leading-relaxed text-ink-2">
            Find manga that already has mokuro OCR. Open the catalog in your browser and sign in with your own account. If it
            offers a download, save the volume into the inbox folder and it lands on your shelf with its text, coverage score
            and place in the series.
          </p>
          <a
            href={CATALOG_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/16 bg-white/8 px-4 text-sm font-semibold hover:bg-white/12"
          >
            Open catalog.mokuro.moe ↗
          </a>
          <p className="mt-3 text-xs text-ink-3">
            Lingo OS never crawls or downloads from the site by itself: its robots.txt asks automated tools to stay out.
          </p>
          {inbox.data && !inbox.data.ocr_available && (
            <p className="mt-2 text-xs text-ink-3">
              Volumes without a .mokuro file can be read as images; their text appears once mokuro has processed them.
            </p>
          )}
        </Panel>
      </div>

      <section aria-labelledby="t-manga-shelf" className="flex flex-col gap-3">
        <h2 id="t-manga-shelf" className="px-1 text-lg font-bold">
          Your volumes {list.data && <span className="text-sm font-medium text-ink-3">· {list.data.total}</span>}
        </h2>
        {list.isPending ? (
          <Skeleton className="h-64 rounded-[20px]" />
        ) : list.isError ? (
          <Panel role="alert">Could not load your manga: {list.error.message}</Panel>
        ) : list.data.items.length === 0 ? (
          <Panel>
            <p className="text-sm text-ink-2">No {language?.name ?? ""} volumes yet.</p>
          </Panel>
        ) : (
          <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(46%,170px),1fr))]">
            {list.data.items.map((item) => (
              <VolumeCard key={item.id} item={item} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function VolumeCard({ item }: { item: ContentItem }) {
  const noText = item.analysis_status === "no_text";
  return (
    <li>
      <Link
        to="/manga/$itemId"
        params={{ itemId: String(item.id) }}
        className="glass flex h-full flex-col overflow-hidden rounded-2xl transition hover:bg-white/10"
      >
        <div className="relative aspect-[2/3] bg-black/40">
          <img src={mangaImage(item.id, 1)} alt="" loading="lazy" className="h-full w-full object-cover" />
          {item.progress > 0.02 && item.status !== "finished" && (
            <div className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
              <div className="h-full bg-accent" style={{ width: `${item.progress * 100}%` }} />
            </div>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2 p-3">
          <div className="line-clamp-2 text-sm leading-snug font-semibold">{item.title}</div>
          <div className="text-xs text-ink-3">{item.page_count ? `${item.page_count} pages` : ""}</div>
          <div className="mt-auto flex flex-wrap gap-1.5">
            {noText ? (
              <Chip className="px-2 py-0.5 text-[11px]">images only</Chip>
            ) : item.coverage !== null ? (
              <Chip tone="accent" className="px-2 py-0.5 text-[11px]">
                ≈ {Math.round(item.coverage * 100)}% known
              </Chip>
            ) : (
              <Chip className="px-2 py-0.5 text-[11px]">analysing…</Chip>
            )}
            {item.status === "finished" && (
              <Chip tone="good" className="px-2 py-0.5 text-[11px]">
                finished
              </Chip>
            )}
          </div>
        </div>
      </Link>
    </li>
  );
}
