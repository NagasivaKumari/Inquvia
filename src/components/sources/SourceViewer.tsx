"use client";

import { useEffect, useState, useCallback } from "react";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { isImage, isVideo, isAudio, isPdf, isStructured, isText } from "@/lib/source-mime";
import styles from "./SourceViewer.module.css";

export interface SourceInput {
  type?: string;
  fileName?: string;
  mimeType?: string;
  filePath?: string;
}

function sourceUrl(invId: string, filePath?: string): string {
  if (!filePath) return "";
  return `${API_BASE}/api/sources/${invId}/${encodeURIComponent(filePath)}`;
}

/** Load a source through the authenticated fetch path and hand back a blob URL
 * plus the resolved MIME type.  Used for native <img>/<video>/<audio>/<iframe>
 * elements, which cannot send an Authorization header themselves. */
function useSourceBlob(invId: string, input: SourceInput) {
  const [state, setState] = useState<{
    url: string;
    mime: string;
    fileName: string;
    status: "loading" | "ready" | "error";
  }>({ url: "", mime: "", fileName: "", status: "loading" });

  useEffect(() => {
    if (!input.filePath) {
      setState({ url: "", mime: "", fileName: "", status: "error" });
      return;
    }
    let ok = true;
    setState({ url: "", mime: "", fileName: "", status: "loading" });
    apiFetch(sourceUrl(invId, input.filePath))
      .then(async (r) => {
        if (!r.ok) throw new Error(`Source request failed (${r.status})`);
        const blob = await r.blob();
        if (!ok) return;
        const mime = blob.type || input.mimeType || "application/octet-stream";
        setState({
          url: URL.createObjectURL(blob),
          mime,
          fileName: input.fileName ?? "source",
          status: "ready",
        });
      })
      .catch(() => {
        if (ok) setState({ url: "", mime: "", fileName: "", status: "error" });
      });
    return () => {
      ok = false;
      setState((s) => {
        if (s.url) URL.revokeObjectURL(s.url);
        return { url: "", mime: "", fileName: "", status: "loading" };
      });
    };
  }, [invId, input.filePath, input.mimeType, input.fileName]);

  return state;
}

/** Render the original uploaded source based purely on its MIME type. */
export function SourceViewer({
  invId,
  input,
  className,
}: {
  invId: string;
  input: SourceInput;
  className?: string;
}) {
  const { url, mime, fileName, status } = useSourceBlob(invId, input);
  const m = mime.toLowerCase();

  if (status === "loading") {
    return <p className="text-muted animate-pulse">Loading source…</p>;
  }
  if (status === "error") {
    return (
      <p className={styles.error}>
        Source could not be loaded.{" "}
        {input.filePath && (
          <a
            href={sourceUrl(invId, input.filePath)}
            target="_blank"
            rel="noreferrer"
          >
            Open directly
          </a>
        )}
      </p>
    );
  }

  if (isImage(m)) {
    return (
      <a href={url} target="_blank" rel="noreferrer" title={`Open ${fileName} at full size`}>
        <img src={url} alt={fileName} className={`${styles.media} ${className ?? ""}`} />
      </a>
    );
  }

  if (isVideo(m)) {
    return (
      <video controls preload="metadata" src={url} className={`${styles.media} ${className ?? ""}`} />
    );
  }

  if (isAudio(m)) {
    return <audio controls preload="metadata" src={url} className={styles.media} />;
  }

  if (isPdf(m)) {
    return (
      <iframe
        src={url}
        title={fileName}
        className={`${styles.pdf} ${className ?? ""}`}
      />
    );
  }

  if (isStructured(m)) {
    return <TextSourceViewer invId={invId} input={input} structured />;
  }

  if (isText(m)) {
    return <TextSourceViewer invId={invId} input={input} />;
  }

  // Fallback: unknown MIME — offer a direct link to the original file.
  return (
    <a href={sourceUrl(invId, input.filePath)} target="_blank" rel="noreferrer">
      Open uploaded file {fileName ? `(${fileName})` : ""}
    </a>
  );
}

function TextSourceViewer({
  invId,
  input,
  structured,
}: {
  invId: string;
  input: SourceInput;
  structured?: boolean;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!input.filePath) return;
    let cancelled = false;
    apiFetch(sourceUrl(invId, input.filePath))
      .then(async (r) => {
        if (!r.ok) throw new Error(`Source request failed (${r.status})`);
        const t = await r.text();
        if (!cancelled) setText(t.slice(0, 8000));
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [invId, input.filePath]);

  if (error) return <p className={styles.error}>{error}</p>;
  if (!text) return <p className="text-muted animate-pulse">Loading source…</p>;

  return (
    <>
      <pre className={`${styles.text} ${structured ? styles.structured : ""}`}>{text}</pre>
      <a
        href={sourceUrl(invId, input.filePath)}
        target="_blank"
        rel="noreferrer"
        className={styles.link}
      >
        Open original {input.fileName ? `(${input.fileName})` : "file"}
      </a>
    </>
  );
}