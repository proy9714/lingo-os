// Save an item on this device for offline use (texts, books, manga, podcast episodes, transcripts).
// Contract stub: the offline-downloads work replaces the body; the props stay as they are.

export interface DownloadTarget {
  id: number;
  type: string;
  title: string;
}

export function DownloadButton(_props: { item: DownloadTarget; compact?: boolean }) {
  return null;
}
