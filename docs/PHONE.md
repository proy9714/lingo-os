# Lingo OS on your Android phone

The phone runs the same app as the laptop, packaged as an Android app with Capacitor. At home it uses the laptop
over your Wi-Fi; away from home it keeps working with the texts you saved for offline, and everything you do there
(lookups, word statuses, reading time, progress) syncs when it's back in reach.

## 1. On the laptop: let a phone connect

1. Settings → **Phone** → tick **Let a phone sync over this Wi-Fi**.
2. The first time, Windows may ask whether Python may use the network. Allow it on **private networks** only.
3. Only the sync listener (port 8788) is reachable from the Wi-Fi. It answers paired phones only, and every request
   and reply is encrypted with a key that never leaves the QR code. The rest of the app stays bound to the laptop.

## 2. Install the app

**The easy way: Obtainium (recommended).** It installs the app from GitHub releases and updates it whenever a new
release comes out.

1. Install [Obtainium](https://github.com/ImranR98/Obtainium) (from its releases page, or F-Droid).
2. In Obtainium: **Add app** → paste `https://github.com/proy9714/lingo-os` → **Add** → **Install**.
3. Android asks to allow installs from Obtainium the first time: allow it.

New versions then show up in Obtainium (it checks in the background, or pull down to refresh): tap **Update**.

**Or by hand:** open the [latest release](https://github.com/proy9714/lingo-os/releases/latest) on the phone,
download `lingo-os-vX.Y.Z.apk`, open it and allow the install. To update, install the newer APK over the old one;
your paired laptop and offline texts are kept.

Every release is signed with the same key. Android refuses an update signed with a different one, so only install
APKs from this repository's releases. The certificate's SHA-256 is listed in [RELEASING.md](RELEASING.md).

**Or build it yourself** (developers): needs Android Studio, or JDK 21 and the Android SDK.

```powershell
npm run phone
```

This builds the web app, copies it into `frontend/android`, and opens the project in Android Studio. Plug the phone
in with USB debugging on and press **Run**. A self-built app is signed with your own debug key, so uninstall it before
switching to the release APK (and the other way round).

## 3. Pair

1. On the laptop: Settings → Phone → **Pair a phone**. A QR code appears (valid for ten minutes, works once).
2. On the phone: the app opens on **Connect to your laptop**. Tap **Scan the code** (or paste its text) and connect.
   Both devices must be on the same Wi-Fi.

## 4. Use it

- **At home**: the whole app works as on the laptop, through the laptop.
- **Save texts for offline**: on the phone, open the sync screen (tap the status badge, or go to `/connect`) and
  press **Save offline** next to books, articles or texts. A saved text carries its words, your word statuses and
  the dictionary entries it needs.
- **Away from home**: the Read shelf shows what you saved. Reading, lookups, word statuses, the timer and manual
  logs work; changes wait in an outbox and sync automatically when the laptop is back in reach (or press
  **Sync now**). Each change is applied exactly once; if a word was changed on both devices, the later change wins.

## Away from home

Install [Tailscale](https://tailscale.com/) (free) on the laptop and on the phone and sign in to the same account on
both. Lingo OS finds the laptop's Tailscale address by itself, and paired phones learn it on their next sync at home,
so the phone then reaches the laptop over mobile data too (still encrypted end to end). Settings → Phone → **Sync away
from home** shows it, and takes other addresses, such as the laptop's Tailscale name (`laptop.tail1234.ts.net`).

## The phone shows the wrong languages, or none of your progress

The phone shows the Lingo OS it's paired with. If it was paired with another copy (a test install, or another data
folder on the same laptop), it shows that copy's languages, and its saved copy of them when that copy isn't running.
On the phone, open the sync screen (tap the status badge, or go to `/connect`) and press **Disconnect**, then pair
again from **your** Lingo OS: Settings → Phone shows the data folder a phone will sync with, and warns when it's a
temporary test copy. Test servers can refuse phones altogether with `LINGO_PHONE_SYNC=off`.

## Limits for now

- Videos stream from YouTube or the laptop; they can't be saved offline. Manga volumes can: **Save offline** stores
  their page images on the phone too (it takes a moment per page, at home).
- Speech recognition (the tutor's microphone, the speaking check, shadowing) uses Android's own recogniser; the
  first time, Android asks to allow the microphone.
- Gemini isn't called from the phone directly; AI explanations work at home through the laptop.

## Remove a phone

Settings → Phone → **Remove**. It can no longer connect until paired again.
