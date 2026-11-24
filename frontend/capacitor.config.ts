import type { CapacitorConfig } from "@capacitor/cli";

// The Android app is this same web app, packaged with Capacitor (docs/PHONE.md).
// CapacitorHttp sends requests natively, so the app (served from https://localhost) can reach the laptop's
// plain-HTTP sync listener on the home Wi-Fi; the bodies are encrypted end to end (src/sync/crypto.ts).
const config: CapacitorConfig = {
  appId: "app.lingoos.phone",
  appName: "Lingo OS",
  webDir: "dist",
  android: {
    // Lets the WebView start the camera (QR pairing) and microphone (shadowing, tutor) after Android's own prompt.
    allowMixedContent: false,
  },
  plugins: {
    CapacitorHttp: { enabled: true },
  },
};

export default config;
