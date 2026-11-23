const dayFormat = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const longDate = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });
const monthFormat = new Intl.DateTimeFormat("en-GB", { month: "short" });
const weekdayFormat = new Intl.DateTimeFormat("en-GB", { weekday: "short" });

/** 'YYYY-MM-DD' as a local date (no UTC shift). */
export function parseDay(day: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export const formatDay = (day: string) => dayFormat.format(parseDay(day));
export const formatWeekday = (day: string) => weekdayFormat.format(parseDay(day));
export const formatLongToday = () => longDate.format(new Date());
export const formatMonth = (month: string) => monthFormat.format(parseDay(`${month}-01`));

function localIso(moment: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}`;
}

export const todayIso = () => localIso(new Date());

/** Local calendar day ('YYYY-MM-DD') of a stored UTC timestamp. */
export const localDayOf = (utcIso: string) => localIso(new Date(utcIso));

export function formatHours(hours: number): string {
  return hours >= 100 ? `${Math.round(hours)} h` : `${hours.toFixed(1)} h`;
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

const GREETINGS: Record<string, [number, string][]> = {
  de: [
    [11, "Guten Morgen"],
    [18, "Guten Tag"],
    [24, "Guten Abend"],
  ],
  es: [
    [12, "Buenos días"],
    [20, "Buenas tardes"],
    [24, "Buenas noches"],
  ],
  ja: [
    [11, "おはようございます"],
    [18, "こんにちは"],
    [24, "こんばんは"],
  ],
};

export function greeting(lang: string, hour = new Date().getHours()): string {
  const table = GREETINGS[lang] ?? [[24, "Hello"]];
  return (table.find(([until]) => hour < until) ?? table[table.length - 1])[1];
}

export const ACTIVITY_LABELS: Record<string, string> = {
  video: "Video",
  podcast: "Podcast",
  audio: "Audio",
  reading: "Reading",
  article: "Article",
  manga: "Manga",
  tutor: "Tutor",
  shadowing: "Shadowing",
  conversation: "Conversation",
  class: "Class",
  writing: "Writing",
  other: "Other",
};
