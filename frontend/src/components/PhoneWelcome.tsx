import { Pairing } from "../pages/ConnectPage";
import { Logo } from "./Logo";

const STEPS = [
  <>
    On your computer, install Lingo OS from{" "}
    <a href="https://github.com/proy9714/lingo-os#readme" target="_blank" rel="noreferrer noopener" className="font-semibold text-accent">
      github.com/proy9714/lingo-os
    </a>{" "}
    and open it. Choose your language there: everything you set up on the computer comes to the phone.
  </>,
  <>
    On the computer: <strong className="text-ink">Settings → Phone</strong>, turn on syncing, then press{" "}
    <strong className="text-ink">Pair a phone</strong>.
  </>,
  <>Scan the code below (both on the same Wi-Fi). Away from home, texts you saved for offline still work.</>,
];

/**
 * The Android app's first screen: the phone works together with Lingo OS on a computer, so setting up starts with
 * pairing. Nothing is asked of a laptop before that, so the screen shows at once.
 */
export function PhoneWelcome() {
  return (
    <div className="relative min-h-dvh">
      <div className="ambient" aria-hidden="true" />
      <main className="shell-pad anim-page relative mx-auto flex max-w-lg flex-col gap-5 !pb-12">
        <header className="flex flex-col gap-3 px-1">
          <Logo size={56} />
          <h1 className="text-3xl font-bold tracking-tight">Welcome to Lingo OS</h1>
          <p className="text-ink-2">
            Videos and articles at your level, with every word clickable. The phone app works with Lingo OS on your computer,
            which finds the content and keeps your progress. Set it up in three steps:
          </p>
        </header>
        <ol className="flex flex-col gap-2.5">
          {STEPS.map((step, n) => (
            <li key={n} className="flex gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-3.5 text-sm leading-relaxed text-ink-2">
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent/20 text-sm font-bold text-accent">{n + 1}</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
        {/* once paired, start the app afresh: every page now comes from that computer */}
        <Pairing intro={false} onPaired={() => window.location.replace("/")} />
      </main>
    </div>
  );
}
