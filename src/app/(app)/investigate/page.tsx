"use client";

import { useState, useCallback, useRef, Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE, ALGORAND_CONFIG, capabilityTitle, EvidenceServiceContract } from "@/lib/config";
import { apiFetch, invalidateAuthCache } from "@/lib/api";
import { payForCapability, detectCapabilityEndpoint } from "@/lib/x402/client";
import { connectPera, signChallenge } from "@/lib/wallet/pera";
import { WalletBadge } from "@/components/wallet/WalletBadge";
import type { Investigation } from "@/lib/types";
import styles from "./page.module.css";

interface UploadedFile {
  name: string;
  type: string;
  preview?: string;
  file: File;
}

interface PaidCapability {
  path: string;
  priceUsdc: number;
  acceptedFileExtensions?: string[];
  acceptedMimeTypes?: string[];
  maxFileSizeMB?: number;
}

/** Raw snake_case contract served by /api/evidence/contracts. */
interface RawEvidenceContract {
  endpoint: string;
  accepted_file_extensions?: string[];
  accepted_mimetypes?: string[];
  max_file_size_mb?: number;
}

function base64(u8: Uint8Array): string {
  let bin = "";
  u8.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}

/** Component to display endpoint requirements dynamically based on service contract. */
function EndpointRequirements({ endpoint, capabilities, services, contracts }: {
  endpoint: string;
  capabilities: PaidCapability[] | null;
  services: EvidenceServiceContract[];
  contracts: RawEvidenceContract[];
}) {
  const map: Record<string, string> = {
    "/api/x402/image-investigation": "/api/evidence/image",
    "/api/x402/video-investigation": "/api/evidence/video",
    "/api/x402/audio-investigation": "/api/evidence/audio",
    "/api/x402/document-investigation": "/api/evidence/document",
    "/api/x402/data-investigation": "/api/evidence/structured",
  };
  const target = map[endpoint] || endpoint;
  const contract = contracts.find((c) => c.endpoint === target);
  
  const cap = capabilities?.find((c) => c.path === endpoint);
  const service = services.find((s) => s.endpoint === endpoint);

  const extensions = contract?.accepted_file_extensions ?? 
                     (cap?.acceptedFileExtensions?.length ? cap.acceptedFileExtensions : service?.acceptedFileExtensions) ?? [];
  const maxSizeMB = contract?.max_file_size_mb ?? cap?.maxFileSizeMB ?? service?.maxFileSizeMB ?? 10;

  if (extensions.length) {
    return (
      <>
        Accepted files: {extensions.map((e) => e.replace(".", "").toUpperCase()).join(", ")}
        {" — "}up to {maxSizeMB}MB each
      </>
    );
  }
  const mimes = contract?.accepted_mimetypes ?? 
                (cap?.acceptedMimeTypes?.length ? cap.acceptedMimeTypes : service?.acceptedMimeTypes) ?? [];
  if (mimes.length) {
    return <>Accepted formats: {mimes.join(", ")} — up to {maxSizeMB}MB</>;
  }
  if (endpoint.endsWith("source-investigation")) return <>Accepts a URL — no file uploads</>;
  return <>Required: submit text or structured data input</>;
}

/** Get the accept attribute for file input based on endpoint contract. */
function getAcceptAttribute(capabilities: PaidCapability[] | null, services: EvidenceServiceContract[] | null, contracts: RawEvidenceContract[], endpoint: string): string {
  if (!endpoint) return "";
  const map: Record<string, string> = {
    "/api/x402/image-investigation": "/api/evidence/image",
    "/api/x402/video-investigation": "/api/evidence/video",
    "/api/x402/audio-investigation": "/api/evidence/audio",
    "/api/x402/document-investigation": "/api/evidence/document",
    "/api/x402/data-investigation": "/api/evidence/structured",
  };
  const target = map[endpoint] || endpoint;
  const contract = contracts.find((c) => c.endpoint === target);
  
  const cap = capabilities?.find((c) => c.path === endpoint);
  const service = services?.find((s) => s.endpoint === endpoint);
  
  const extensions = contract?.accepted_file_extensions ?? cap?.acceptedFileExtensions ?? service?.acceptedFileExtensions ?? [];
  if (extensions.length) return extensions.join(",");
  const mimes = contract?.accepted_mimetypes ?? cap?.acceptedMimeTypes ?? service?.acceptedMimeTypes ?? [];
  if (mimes.length) return mimes.join(",");
  return "";
}

function InvestigateForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  const selectedService = searchParams.get("service") ?? "";
  const rawCap = searchParams.get("cap") ?? "";
  // Normalize: accept either "source-investigation" or "/api/x402/source-investigation"
  const [capabilityHint, setCapabilityHint] = useState(
    rawCap ? (rawCap.startsWith("/api/x402/") ? rawCap : `/api/x402/${rawCap}`) : ""
  );
  const reinvestigateFrom = searchParams.get("reinvestigateFrom") ?? "";

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
  const [capabilities, setCapabilities] = useState<PaidCapability[] | null>(
    null
  );
  const [evidenceServices, setEvidenceServices] = useState<
    EvidenceServiceContract[] | null
  >(null);
  const [contracts, setContracts] = useState<RawEvidenceContract[]>([]);
  const [sourceInv, setSourceInv] = useState<Investigation | null>(null);
  const [reuseError, setReuseError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!reinvestigateFrom) return;
    apiFetch(`${API_BASE}/api/investigations/${reinvestigateFrom}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((inv) => {
        if (!inv) {
          setReuseError("Source investigation not found.");
          return;
        }
        const source = inv as Investigation;
        setSourceInv(source);
        if (source.capability) setCapabilityHint(`/api/x402/${source.capability}`);
        const srcUrl = (source.inputs ?? []).find((i) => i.type === "url")?.content;
        if (srcUrl) setUrl(String(srcUrl));
      })
      .catch(() => setReuseError("Could not load the source investigation."));
  }, [reinvestigateFrom]);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => {
        if (d.user?.walletAddress) {
          setWalletAddress(d.user.walletAddress);
        }
      })
      .catch(() => {});
    // Fetch paid capabilities once and cache for the session
    apiFetch(`${API_BASE}/api/investigate`)
      .then((r) => r.json())
      .then((d) => setCapabilities(d.capabilities ?? []))
      .catch(() => {});
    // Fetch evidence service contracts for dynamic UI
    apiFetch(`${API_BASE}/api/evidence/services`)
      .then((r) => r.json())
      .then((d) => setEvidenceServices(d.services ?? []))
      .catch(() => {});
    // Fetch authoritative evidence contracts
    apiFetch(`${API_BASE}/api/evidence/contracts`)
      .then((r) => r.json())
      .then((d) => setContracts(d ?? []))
      .catch(() => {});
  }, []);

  const getContractForEndpoint = (endpoint: string) => {
    // Map x402 endpoints to /api/evidence endpoints
    const map: Record<string, string> = {
      "/api/x402/image-investigation": "/api/evidence/image",
      "/api/x402/video-investigation": "/api/evidence/video",
      "/api/x402/audio-investigation": "/api/evidence/audio",
      "/api/x402/document-investigation": "/api/evidence/document",
      "/api/x402/data-investigation": "/api/evidence/structured",
    };
    const target = map[endpoint] || endpoint;
    return contracts.find((c) => c.endpoint === target);
  };

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
      const cap = capabilities?.find((c) => c.path === detectedCap);
      const amount = price ?? (cap ? `$${cap.priceUsdc} USDC` : "USDC");
      setPaymentStatus(`Pera approval requested — approve the ${amount} payment in the Pera window…`);
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

    const fileObjects = files.map((f) => f.file);
    const endpoint = capabilityHint || detectCapabilityEndpoint(fileObjects, url.trim());
    setDetectedCap(endpoint);

    // Validate files against the capability contract BEFORE any payment runs,
    // so an unsupported file is rejected with the accepted formats up front.
    const contract = capabilities?.find((c) => c.path === endpoint);
    if (contract) {
      const acceptedExts = (contract.acceptedFileExtensions ?? []).map((e) => e.toLowerCase());
      const acceptedMimes = contract.acceptedMimeTypes ?? [];
      if (acceptedExts.length > 0) {
        const list = acceptedExts.map((e) => e.replace(".", "").toUpperCase()).join(", ");
        if (files.length === 0 && !sourceInv) {
          setError(`Please upload a file before starting this investigation. Accepted formats: ${list}.`);
          setIsSubmitting(false);
          return;
        }
        const bad = files.find(
          (f) =>
            !acceptedExts.some((e) => f.name.toLowerCase().endsWith(e)) &&
            !acceptedMimes.includes(f.type)
        );
        if (bad) {
          setError(
            `"${bad.name}" is not supported by ${capabilityTitle(endpoint)}. Accepted formats: ${list}.`
          );
          setIsSubmitting(false);
          return;
        }
      }
    }

    setPaymentStatus("Opening Pera Wallet — approve the USDC payment…");

    try {
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
          reinvestigateFrom: reinvestigateFrom || undefined,
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

        {sourceInv && (
          <div className={styles.reuseNote} role="note">
            <strong>Reinvestigating Case {sourceInv.id}</strong>
            <p className="text-muted">&ldquo;{sourceInv.question}&rdquo;</p>
            <p className="text-muted" style={{ fontSize: "0.8125rem", marginTop: 4 }}>
              Evidence from the original investigation will be reused — no re-upload needed.
              Upload new files above only if you want to replace or add evidence.
            </p>
            <ul className={styles.reuseList}>
              {(sourceInv.inputs ?? []).map((i, n) => (
                <li key={n} className="text-muted">
                  {i.fileName ? `${i.type}: ${i.fileName}` : `${i.type}: ${i.content}`}
                </li>
              ))}
            </ul>
            {reuseError && <p className={styles.error}>{reuseError}</p>}
          </div>
        )}

        <div className="form-group">
          <label htmlFor="url" className="form-label">
            URL {sourceInv ? "(optional — original is reused)" : "(optional)"}
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
          <label className="form-label">
            {sourceInv ? "Add replacement evidence (optional)" : "Upload evidence (optional)"}
          </label>
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
            {(evidenceServices || capabilities) && detectedCap && (
              <p className="text-xs text-muted">
                <EndpointRequirements
                  endpoint={detectedCap}
                  capabilities={capabilities}
                  services={evidenceServices ?? []}
                  contracts={contracts}
                />
              </p>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={getAcceptAttribute(capabilities, evidenceServices, contracts, detectedCap)}
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
            <span className={styles.paymentAmount}>{price}</span>
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