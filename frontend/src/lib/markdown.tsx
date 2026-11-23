import { Fragment, type ReactNode } from "react";

/** A small Markdown subset for reports: headings, bullet lists, paragraphs and **bold**. Never renders raw HTML. */
export function Markdown({ source }: { source: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={blocks.length} className="my-2 list-disc pl-5 text-sm leading-relaxed text-ink-2">
          {list.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
    if (paragraph.length) {
      blocks.push(
        <p key={blocks.length} className="my-2 text-sm leading-relaxed text-ink-2">
          {inline(paragraph.join(" "))}
        </p>,
      );
      paragraph = [];
    }
  };
  for (const raw of source.split("\n")) {
    const line = raw.trimEnd();
    if (line.startsWith("# ")) {
      flush();
      blocks.push(
        <h2 key={blocks.length} className="mt-2 mb-3 text-xl font-bold">
          {line.slice(2)}
        </h2>,
      );
    } else if (line.startsWith("## ")) {
      flush();
      blocks.push(
        <h3 key={blocks.length} className="mt-5 mb-1 text-base font-bold">
          {line.slice(3)}
        </h3>,
      );
    } else if (/^[-*] /.test(line)) {
      if (paragraph.length) flush();
      list.push(line.slice(2));
    } else if (!line.trim()) {
      flush();
    } else {
      if (list.length) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return <div>{blocks}</div>;
}

function inline(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}
