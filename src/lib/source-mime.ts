/** MIME family classification shared by the source renderers. Pure and
 * dependency-free so it can be imported from tests without a browser. */

export type SourceFamily =
  | "image"
  | "video"
  | "audio"
  | "pdf"
  | "text"
  | "structured"
  | "other";

export function isImage(m: string): boolean {
  return m.startsWith("image/");
}
export function isVideo(m: string): boolean {
  return m.startsWith("video/");
}
export function isAudio(m: string): boolean {
  return m.startsWith("audio/");
}
export function isPdf(m: string): boolean {
  return m === "application/pdf";
}
export function isStructured(m: string): boolean {
  return (
    m.includes("json") ||
    m.includes("csv") ||
    m === "text/tab-separated-values" ||
    m.startsWith("application/x-ndjson")
  );
}
export function isText(m: string): boolean {
  return m.startsWith("text/");
}

/** Single-truth MIME family, ordered so structured ("text/…, application/…")
 * is decided before generic text. Unknown MIME falls through to "other". */
export function sourceFamily(mime: string): SourceFamily {
  const m = (mime ?? "").toLowerCase();
  if (isImage(m)) return "image";
  if (isVideo(m)) return "video";
  if (isAudio(m)) return "audio";
  if (isPdf(m)) return "pdf";
  if (isStructured(m)) return "structured";
  if (isText(m)) return "text";
  return "other";
}