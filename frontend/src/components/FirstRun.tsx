import { isNativeApp } from "../sync/remote";
import { RestoreBackup } from "./DataPanel";
import { LanguagePicker } from "./LanguagePicker";
import { Logo } from "./Logo";

/** A brand-new install: choose the first language to learn. More can be added later in Settings. */
export function FirstRun() {
  return (
    <div className="relative min-h-dvh">
      <div className="ambient" aria-hidden="true" />
      <main className="shell-pad anim-page relative mx-auto flex max-w-5xl flex-col gap-6 !pb-12 md:!pt-16">
        <header className="flex flex-col gap-3">
          <Logo size={64} />
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">Welcome to Lingo OS</h1>
          <p className="max-w-2xl text-ink-2">
            Which language do you want to learn? Lingo OS finds videos and articles at your level in it, makes every word
            clickable, and keeps track of your progress. You can add more languages later in Settings.
          </p>
        </header>
        {!isNativeApp() && (
          <section className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3">
            <p className="text-sm text-ink-2">Coming from another computer? Bring everything back from a Lingo OS backup:</p>
            <RestoreBackup compact />
          </section>
        )}
        <LanguagePicker />
        <p className="text-xs text-ink-3">
          Languages are listed by number of speakers (approximate). Adding one downloads its language model and dictionary
          (about 10 to 70 MB) once; everything then stays on this computer.
        </p>
      </main>
    </div>
  );
}
