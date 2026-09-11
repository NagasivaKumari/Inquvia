"use client";

import { useState, useCallback, useRef, Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE, ALGORAND_CONFIG, capabilityTitle } from "@/lib/config";
import { apiFetch, invalidateAuthCache } from "@/lib/api";
import { payForCapability, detectCapabilityEndpoint } from "@/lib/x402/client";
import { connectPera, signChallenge } from "@/lib/wallet/pera";
import { WalletBadge } from "@/components/wallet/WalletBadge";
import styles from "./page.module.css";

interface UploadedFile {
  name: string;
  type: string;
  preview?: string;
  file: File;
}

function base64(u8: Uint8Array): string {
  let bin = "";
  u8.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}

function InvestigateForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  const selectedService = searchParams.get("service") ?? "";
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
  const [paymentStatus, setPaymentStatus] = useState("");
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [walletAddress, setWalletAddress] = useState("");
  const [price, setPrice] = useState<string | null>(null);
  const [detectedCap, setDetectedCap] = useState<string>("");
  const [capabilities, setCapabilities] = useState<
    { path: string; priceUsdc: number }[] | null
  >(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => {
        if (d.user?.walletAddress) {
          setWalletAddress(d.user.walletAddress);
        }
      })
      .catch(() => {});
    // Fetch capabilities once and cache for the session
    apiFetch(`${API_BASE}/api/investigate`)
      .then((r) => r.json())
      .then((d) => setCapabilities(d.capabilities ?? []))
      .catch(() => {});
  }, []);

  // Detect capability from current inputs (for price display).
  useEffect(() => {
    const fileObjects = files.map((f) => f.file);
    const cap = capabilityHint || detectCapabilityEndpoint(fileObjects, url);
    setDetectedCap(cap); // already normalized to /api/x402/... form
    if (capabilities) {
      const capability = capabilities.find((c) => c.path === cap);
      if (capability) {
        setPrice(`$${capability.priceUsdc} USDC`);
      } else {
        setPrice(null);
      }
    }
  }, [files, url, capabilityHint, capabilities]);

  useEffect(() => {
    const onWalletSigning = () => {
      setPaymentStatus("Pera approval requested — approve the $0.50 USDC payment in the Pera window…");
    };
    const onDiagnostic = (e: Event) => {
      const d = (e as CustomEvent<{ step: string; connected?: boolean; message?: string }>)?.detail;
      const step = d?.step ?? "";
      if (step === "error") {
        setPaymentStatus("");
        setError(`Payment flow: ${d?.message ?? "unknown wallet error"}`);
        return;
      }
      const map: Record<string, string> = {
        "preparing-session": "Connecting to Pera wallet (reconnect session)…",
        "session-ready": "Pera session ready.",
        "payment-params-ready": "Preparing network parameters…",
        "opt-in-required": "Your wallet isn't opted into USDC — approve the asset opt-in in Pera now…",
        "opt-in-ready": "USDC opt-in confirmed. Preparing payment…",
        "gate-rejected": "Server requests payment — waiting for Pera approval…",
        "requesting-approval": "Opening Pera — approve the payment in your wallet now…",
        "pera-signing-start": "Waiting for Pera approval: please open the Pera app on your mobile device to sign…",
        "pera-signing-success": "Transaction signed! Submitting payment to network…",
        "request-approved": "Payment approved.",
        "retrying-payment": "Payment attempt stalled — retrying once…",
        "payment-build-error": "Preparing the payment failed — retrying…",
      };
      if (map[step]) setPaymentStatus(map[step]);
      console.info("[inquvia:pay]", e as CustomEvent);
    };
    window.addEventListener("inquvia:wallet-signing", onWalletSigning);
    window.addEventListener("inquvia:pay-diagnostic", onDiagnostic);
    return () => {
      window.removeEventListener("inquvia:wallet-signing", onWalletSigning);
      window.removeEventListener("inquvia:pay-diagnostic", onDiagnostic);
    };
  }, []);

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
    setIsSubmitting(true);
    setError("");

    let address = walletAddress;
    if (!address) {
      // ponytail: connect + authorize inline (same flow as WalletBadge) so the
      // pay click works in one go instead of just showing a "connect your wallet" error.
      try {
        setPaymentStatus("Connecting Pera wallet…");
        const w = await connectPera();
        const message = `Sign to verify control of ${w.address} in ${ALGORAND_CONFIG.network} at ${Date.now()}`;
        const { signature, authenticatorData, message: signedMessage } = await signChallenge(
          w.address,
          message,
          window.location.origin
        );
        const res = await apiFetch(`${API_BASE}/api/wallet/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            providerId: "pera",
            address: w.address,
            message: signedMessage,
            authenticatorData: base64(authenticatorData),
            signatureB64: base64(signature),
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Connection failed");
        invalidateAuthCache();
        setWalletAddress(data.wallet.address);
        address = data.wallet.address;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Wallet connection failed");
        setPaymentStatus("");
        setIsSubmitting(false);
        return;
      }
    }

    const requiredType = capabilityHint.match(/\/api\/x402\/(image|video|document|audio|data)-investigation$/)?.[1];
    if (requiredType) {
      const hasRequiredFile = files.some((file) => {
        if (requiredType === "data") return file.type.includes("json") || file.type.includes("csv");
        if (requiredType === "document") return file.type === "application/pdf" || file.type.startsWith("text/");
        if (requiredType === "video") return file.type.startsWith("video/") || /\.(mp4|mov|avi|wmv)$/i.test(file.name);
        return file.type.startsWith(`${requiredType}/`);
      });
      if (!hasRequiredFile) {
        setError(`Please upload a ${requiredType} file before starting this investigation.`);
        setIsSubmitting(false);
        return;
      }
    }

    setPaymentStatus("Opening Pera Wallet — approve the USDC payment…");

    try {
      const fileObjects = files.map((f) => f.file);
      // capabilityHint is already normalized to /api/x402/... form
      const endpoint = capabilityHint || detectCapabilityEndpoint(fileObjects, url.trim());
      const idempotencyKey = crypto.randomUUID();

      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 300_000);
      let paid;
      try {
        setPaymentStatus("Opening Pera Wallet — approve the USDC payment…");
        paid = await payForCapability({
          address,
          endpoint,
          question: question.trim(),
          serviceName: selectedService || undefined,
          url: url.trim() || undefined,
          files: fileObjects.length > 0 ? fileObjects : undefined,
          idempotencyKey,
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timeout);
      }
      router.push(`/investigation/${paid.id}`);
    } catch (err) {
      const message = err instanceof DOMException && err.name === "AbortError"
        ? "Payment timed out. Open Pera Wallet and approve the request, then try again."
        : err instanceof Error ? err.message : "Payment failed";
      setError(message);
      setPaymentStatus("");
      setIsSubmitting(false);
    }
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
              Images, videos, audio, PDFs, documents, JSON, CSV — up to 10MB each
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,video/*,audio/*,application/pdf,text/*,application/json,text/csv"
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

        {detectedCap && price && (
          <div className={styles.priceDisplay}>
            <span className="text-sm text-muted">
              {selectedService || capabilityTitle(detectedCap)}
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
        {paymentStatus && !error && (
          <div className={styles.paymentStatus} role="status">
            <strong>Wallet approval required</strong>
            <span>{paymentStatus}</span>
            <span className={styles.paymentAmount}>{price ?? "$0.50 USDC"}</span>
          </div>
        )}
      </form>


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