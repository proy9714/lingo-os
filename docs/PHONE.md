# Lingo OS on your Android phone

The phone runs the same app as the laptop, packaged as an Android app with Capacitor. At home it uses the laptop
over your Wi-Fi; away from home it keeps working with the texts you saved for offline, and everything you do there
(lookups, word statuses, reading time, progress) syncs when it's back in reach.

## 1. On the laptop: let a phone connect

1. Settings → **Phone** → tick **Let a phone sync over this Wi-Fi**.
2. The first time, Windows may ask whether Python may use the network. Allow it on **private networks** only.
3. Only the sync listener (port 8788) is reachable from the Wi-Fi. It answers paired phones only, and every request
   and reply is encrypted with a key that never leaves the QR code. The rest of the app stays bound to the laptop.

## 2. Build and install the app (once)

Building needs **Android Studio** (it brings the Android SDK and a JDK; a large download, a few GB).

```powershell
npm run phone
```

This builds the web app, copies it into `frontend/android`, and opens the project in Android Studio. Then:

1. Plug the phone in with USB debugging on (Settings → About phone → tap *Build number* seven times → Developer
   options → USB debugging), or use Build → Build App Bundle(s) / APK(s) → Build APK(s) and copy the APK over.
2. Press **Run**. The app installs as "Lingo OS".

After changing the app's code, run `npm run phone` again and press Run.

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

## Limits for now

- Videos stream from YouTube or the laptop; they can't be saved offline. Manga reads at home; offline manga is next.
- Android's in-app browser has no speech recognition, so the tutor's microphone, the speaking check and the word
  comparison in shadowing need typing or the laptop for now (recording yourself still works). A native speech plugin
  can be added later.
- Gemini isn't called from the phone directly; AI explanations work at home through the laptop.
- Away from home over mobile data, the phone can't reach the laptop. Tailscale could be added later for that.

## Remove a phone

Settings → Phone → **Remove**. It can no longer connect until paired again.
