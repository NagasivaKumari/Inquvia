"use client";

import { useState, useCallback, useRef, Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE, EXAMPLE_PROMPTS, capabilityTitle } from "@/lib/config";
import { payForCapability, detectCapabilityEndpoint } from "@/lib/x402/client";
import { WalletBadge } from "@/components/wallet/WalletBadge";
import styles from "./page.module.css";

interface UploadedFile {
  name: string;
  type: string;
  preview?: string;
  file: File;
}

function InvestigateForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  const rawCap = searchParams.get("cap") ?? "";
  // Normalize: accept either "source-investigation" or "/api/x402/source-investigation"
  const capabilityHint = rawCap
    ? rawCap.startsWith("/api/x402/")
      ? rawCap
      : `/api/x402/${rawCap}`
    : "";

  const [question, setQuestion] = useState(initialQuestion);
  const [url, setUrl] = useState("");
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [walletAddress, setWalletAddress] = useState("");
  const [price, setPrice] = useState<string | null>(null);
  const [detectedCap, setDetectedCap] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setWalletAddress(d.user?.walletAddress ?? ""))
      .catch(() => {});
  }, []);

  // Detect capability from current inputs (for price display).
  useEffect(() => {
    const fileObjects = files.map((f) => f.file);
    const cap = capabilityHint || detectCapabilityEndpoint(fileObjects, url);
    setDetectedCap(cap); // already normalized to /api/x402/... form
    fetch(`${API_BASE}/api/investigate`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        const capability = (d.capabilities ?? []).find(
          (c: { path: string }) => c.path === cap
        );
        if (capability) {
          setPrice(`$${capability.priceUsdc} USDC`);
        }
      })
      .catch(() => {});
  }, [files, url, capabilityHint]);

  const handleFiles = useCallback((fileList: FileList | null) => {
    if (!fileList) return;
    const newFiles: UploadedFile[] = [];
    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i];
      const uploaded: UploadedFile = { name: file.name, type: file.type, file };
      if (file.type.startsWith("image/")) {
        uploaded.preview = URL.createObjectURL(file);
      }
      newFiles.push(uploaded);
    }
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const removed = prev[index];
      if (removed.preview) URL.revokeObjectURL(removed.preview);
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) {
      setError("Please enter a question for your investigation.");
      return;
    }
    if (!walletAddress) {
      setError("Connect your Pera wallet to pay the investigation fee.");
      return;
    }

    setIsSubmitting(true);
    setError("");

    try {
      const fileObjects = files.map((f) => f.file);
      // capabilityHint is already normalized to /api/x402/... form
      const endpoint = capabilityHint || detectCapabilityEndpoint(fileObjects, url.trim());
      const idempotencyKey = crypto.randomUUID();

      const paid = await payForCapability({
        address: walletAddress,
        endpoint,
        question: question.trim(),
        url: url.trim() || undefined,
        files: fileObjects.length > 0 ? fileObjects : undefined,
        idempotencyKey,
      });
      router.push(`/investigation/${paid.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
      setIsSubmitting(false);
    }
  };

  const fillExample = (prompt: string) => {
    setQuestion(prompt);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className="heading-lg">Start an Investigation</h1>
        <p className="text-muted">
          Submit a question along with any supporting evidence — text, URLs,
          images, videos, documents, or data.
        </p>
      </header>

      <form onSubmit={handleSubmit} className={styles.form}>
        <div className="form-group">
          <label htmlFor="question" className="form-label">
            What do you want to investigate?
          </label>
          <textarea
            id="question"
            className="form-textarea"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Is this seller legitimate?"
            rows={3}
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="url" className="form-label">
            URL (optional)
          </label>
          <input
            id="url"
            type="url"
            className="form-input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/listing"
          />
        </div>

        <div className="form-group">
          <label className="form-label">Upload evidence (optional)</label>
          <div
            className={`upload-zone ${dragOver ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              handleFiles(e.dataTransfer.files);
            }}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                fileInputRef.current?.click();
              }
            }}
            aria-label="Upload files by clicking or dragging"
          >
            <div className="upload-zone-icon" aria-hidden="true">+</div>
            <p>Drag and drop files here, or click to browse</p>
            <p className="text-xs text-muted">
              Images, videos, PDFs, documents, JSON, CSV — up to 10MB each
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,video/*,application/pdf,text/*,application/json,text/csv"
            onChange={(e) => handleFiles(e.target.files)}
            className="sr-only"
            aria-hidden
          />
        </div>

        {files.length > 0 && (
          <div className={styles.fileList}>
            {files.map((f, i) => (
              <div key={i} className={styles.fileItem}>
                {f.preview ? (
                  <img src={f.preview} alt="" className={styles.filePreview} />
                ) : (
                  <span className={styles.fileIcon} aria-hidden="true">File</span>
                )}
                <span className={styles.fileName}>{f.name}</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => removeFile(i)}
                  aria-label={`Remove ${f.name}`}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        <div className={styles.walletRow}>
          <span className={walletAddress ? styles.walletOk : styles.walletWarn}>
            {walletAddress
              ? "Wallet connected"
              : "No wallet connected — a micro USDC fee is required to run an investigation."}
          </span>
          <WalletBadge
            address={walletAddress || undefined}
            onConnected={(addr) => setWalletAddress(addr)}
            onDisconnected={() => setWalletAddress("")}
            compact
          />
        </div>

        {detectedCap && price && (
          <div className={styles.priceDisplay}>
            <span className="text-sm text-muted">
              {capabilityTitle(detectedCap)}
            </span>
            <span className={styles.priceValue}>{price}</span>
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={isSubmitting}
        >
          {isSubmitting
            ? "Paying & starting investigation…"
            : `Investigate via x402${price ? ` (${price})` : ""}`}
        </button>
      </form>

      <section className={styles.examples} aria-labelledby="prompt-examples">
        <h2 id="prompt-examples" className="heading-sm text-muted">
          Try an example
        </h2>
        <div className={styles.exampleChips}>
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              className={styles.chip}
              onClick={() => fillExample(prompt)}
            >
              {prompt}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function InvestigatePage() {
  return (
    <Suspense fallback={<div className="animate-pulse">Loading…</div>}>
      <InvestigateForm />
    </Suspense>
  );
}