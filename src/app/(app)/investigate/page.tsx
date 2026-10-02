"use client";

import { useState, useCallback, useRef, Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE, ALGORAND_CONFIG, capabilityTitle, EvidenceServiceContract } from "@/lib/config";
import { apiFetch, invalidateAuthCache } from "@/lib/api";
import { payForCapability, payForEvidence, detectCapabilityEndpoint, normalizeCapabilityEndpoint } from "@/lib/x402/client";
import { connectPera, signChallenge } from "@/lib/wallet/pera";
import { WalletBadge } from "@/components/wallet/WalletBadge";
import { InvestigationResultView } from "@/components/investigation/InvestigationResultView";
import { normalizeToInvestigation } from "@/lib/investigation-normalizer";
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
  inputTypes?: readonly string[];
}

function base64(u8: Uint8Array): string {
  let bin = "";
  u8.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}

interface RawEvidenceField {
  name: string;
  required?: boolean;
  allow_multiple?: boolean;
}

interface RawEvidenceContract {
  endpoint: string;
  accepted_file_extensions?: string[];
  accepted_mimetypes?: string[];
  max_file_size_mb?: number;
  required_inputs?: RawEvidenceField[];
  optional_inputs?: RawEvidenceField[];
}

const EVIDENCE_ENDPOINT_MAP: Record<string, string> = {
  "/api/x402/image-investigation": "/api/evidence/image",
  "/api/x402/image-batch-investigation": "/api/evidence/image",
  "/api/x402/video-investigation": "/api/evidence/video",
  "/api/x402/audio-investigation": "/api/evidence/audio",
  "/api/x402/document-investigation": "/api/evidence/document",
  "/api/x402/data-investigation": "/api/evidence/structured",
  "/api/x402/source-investigation": "/api/evidence/url",
};

const FALLBACK_EXTENSIONS: Record<string, string[]> = {
  "/api/x402/claim-investigation": [
    ".jpg",".jpeg",".png",".webp",".gif",".bmp",".tif",".tiff",".heic",".heif",
    ".mp4",".mov",".m4v",".avi",".mkv",".webm",".mpeg",".mpg",".wmv",
    ".mp3",".wav",".m4a",".aac",".flac",".ogg",".opus",
    ".pdf",".docx",".doc",".txt",".md",".rtf",".odt",".html",".htm",".xhtml",
    ".csv",".tsv",".json",".jsonl",".xlsx",".xls",".parquet",
  ],
  "/api/x402/image-investigation": [".jpg",".jpeg",".png",".webp",".gif",".bmp",".tif",".tiff",".heic",".heif"],
  "/api/x402/image-batch-investigation": [".jpg",".jpeg",".png",".webp",".gif",".bmp",".tif",".tiff",".heic",".heif"],
  "/api/x402/video-investigation": [".mp4",".mov",".m4v",".avi",".mkv",".webm",".mpeg",".mpg",".wmv"],
  "/api/x402/audio-investigation": [".mp3",".wav",".m4a",".aac",".flac",".ogg",".opus",".webm"],
  "/api/x402/document-investigation": [".pdf",".docx",".doc",".txt",".md",".rtf",".odt",".html",".htm",".xhtml"],
  "/api/x402/data-investigation": [".csv",".tsv",".json",".jsonl",".xlsx",".xls",".parquet"],
  "/api/x402/source-investigation": [],
  "/api/evidence/image": [".jpg",".jpeg",".png",".webp",".gif",".bmp",".tif",".tiff",".heic",".heif"],
  "/api/evidence/video": [".mp4",".mov",".m4v",".avi",".mkv",".webm",".mpeg",".mpg",".wmv"],
  "/api/evidence/audio": [".mp3",".wav",".m4a",".aac",".flac",".ogg",".opus",".webm"],
  "/api/evidence/document": [".pdf",".docx",".doc",".txt",".md",".rtf",".odt",".html",".htm",".xhtml"],
  "/api/evidence/structured": [".csv",".tsv",".json",".jsonl",".xlsx",".xls",".parquet"],
  "/api/evidence/url": [],
  "/api/evidence/authenticity": [".jpg",".jpeg",".png",".webp",".gif",".mp4",".mov",".webm",".mp3",".wav"],
};

const FALLBACK_MIMES: Record<string, string[]> = {
  "/api/x402/claim-investigation": [
    "image/jpeg","image/png","image/webp","image/gif","image/bmp","image/tiff","image/heic","image/heif",
    "video/mp4","video/quicktime","video/webm","video/x-matroska","video/x-msvideo","video/mpeg","video/x-m4v","video/x-ms-wmv",
    "audio/mpeg","audio/mp3","audio/wav","audio/ogg","audio/x-m4a","audio/mp4","audio/aac","audio/flac","audio/opus","audio/webm",
    "application/pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/msword","text/plain","text/markdown","text/x-markdown","application/rtf","application/vnd.oasis.opendocument.text",
    "text/csv","text/tab-separated-values","application/json","application/x-jsonlines","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.ms-excel","application/x-parquet","application/parquet","text/html","application/xhtml+xml",
  ],
  "/api/x402/image-investigation": ["image/jpeg","image/png","image/webp","image/gif","image/bmp","image/tiff","image/heic","image/heif"],
  "/api/x402/image-batch-investigation": ["image/jpeg","image/png","image/webp","image/gif","image/bmp","image/tiff","image/heic","image/heif"],
  "/api/x402/video-investigation": ["video/mp4","video/quicktime","video/webm","video/x-matroska","video/x-msvideo","video/mpeg","video/x-m4v","video/x-ms-wmv"],
  "/api/x402/audio-investigation": ["audio/mpeg","audio/mp3","audio/wav","audio/ogg","audio/x-m4a","audio/mp4","audio/aac","audio/flac","audio/opus","audio/webm"],
  "/api/x402/document-investigation": ["application/pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/msword","text/plain","text/markdown","text/x-markdown","application/rtf","application/vnd.oasis.opendocument.text","text/html","application/xhtml+xml"],
  "/api/x402/data-investigation": ["text/csv","text/tab-separated-values","application/json","application/x-jsonlines","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.ms-excel","application/x-parquet","application/parquet"],
  "/api/x402/source-investigation": [],
};

const DIRECT_ANALYSIS_ENDPOINTS = new Set([
  "/api/evidence/assess",
  "/api/evidence/contradictions",
  "/api/evidence/duplicates",
  "/api/evidence/timeline",
  "/api/evidence/gaps",
]);

const SOURCE_EVIDENCE_ENDPOINTS = new Set([
  "/api/evidence/image",
  "/api/evidence/video",
  "/api/evidence/audio",
  "/api/evidence/document",
  "/api/evidence/authenticity",
  "/api/evidence/structured",
  "/api/evidence/url",
]);

const PAID_FILE_ENDPOINTS = new Set([
  "/api/x402/image-investigation",
  "/api/x402/image-batch-investigation",
  "/api/x402/video-investigation",
  "/api/x402/audio-investigation",
  "/api/x402/document-investigation",
  "/api/x402/data-investigation",
]);

const PAID_ENDPOINTS = new Set([
  ...PAID_FILE_ENDPOINTS,
  "/api/x402/claim-investigation",
  "/api/x402/source-investigation",
]);

function evidenceEndpoint(endpoint: string): string {
  return EVIDENCE_ENDPOINT_MAP[endpoint] ?? endpoint;
}

function evidenceContract(
  endpoint: string,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): RawEvidenceContract | undefined {
  const target = evidenceEndpoint(endpoint);
  return contracts.find((contract) => contract.endpoint === target);
}

function acceptedExtensions(
  endpoint: string,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): string[] {
  if (endpoint === "/api/x402/claim-investigation") {
    return FALLBACK_EXTENSIONS["/api/x402/claim-investigation"] ?? [];
  }
  const target = evidenceEndpoint(endpoint);
  const contract = contracts.find((item) => item.endpoint === target);
  const capability = capabilities?.find((item) => item.path === endpoint);
  const service = services?.find((item) => item.endpoint === endpoint);
  const extensions = isDirectEvidence(endpoint)
    ? contract?.accepted_file_extensions ?? service?.acceptedFileExtensions ?? []
    : capability?.acceptedFileExtensions ?? contract?.accepted_file_extensions ?? service?.acceptedFileExtensions ?? [];
  const result = extensions.length ? extensions : (FALLBACK_EXTENSIONS[endpoint] ?? []);
  if (!DIRECT_ANALYSIS_ENDPOINTS.has(endpoint)) return result;
  return [...new Set([...result, ".pdf"])];
}

function acceptedMimes(
  endpoint: string,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): string[] {
  if (endpoint === "/api/x402/claim-investigation") {
    return FALLBACK_MIMES["/api/x402/claim-investigation"] ?? [];
  }
  const target = evidenceEndpoint(endpoint);
  const contract = contracts.find((item) => item.endpoint === target);
  const capability = capabilities?.find((item) => item.path === endpoint);
  const service = services?.find((item) => item.endpoint === endpoint);
  const mimes = isDirectEvidence(endpoint)
    ? contract?.accepted_mimetypes ?? service?.acceptedMimeTypes ?? []
    : capability?.acceptedMimeTypes ?? contract?.accepted_mimetypes ?? service?.acceptedMimeTypes ?? [];
  const result = mimes.length ? mimes : (FALLBACK_MIMES[endpoint] ?? []);
  if (!DIRECT_ANALYSIS_ENDPOINTS.has(endpoint)) return result;
  return [...new Set([...result, "application/pdf"])];
}

function maxFileSizeMB(
  endpoint: string,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): number {
  if (!isDirectEvidence(endpoint)) {
    return capabilities?.find((item) => item.path === endpoint)?.maxFileSizeMB ?? 10;
  }
  const contract = evidenceContract(endpoint, capabilities, services, contracts);
  return contract?.max_file_size_mb ?? services?.find((item) => item.endpoint === endpoint)?.maxFileSizeMB ?? 10;
}

function requiredInput(
  endpoint: string,
  name: string,
  _capabilities: PaidCapability[] | null,
  _services: EvidenceServiceContract[] | null,
  _contracts: RawEvidenceContract[],
): boolean {
  // URLs are accepted for every endpoint. Neither file nor url is strictly required in HTML
  // when the user can provide either. Only pure source-investigation with 0 files requires a URL.
  if (endpoint === "/api/x402/source-investigation" || endpoint === "/api/evidence/url") {
    return name === "url";
  }
  return false;
}

function acceptsUrlInput(
  _endpoint: string,
  _capabilities: PaidCapability[] | null,
  _services: EvidenceServiceContract[] | null,
  _contracts: RawEvidenceContract[],
): boolean {
  // Every investigation endpoint accepts a URL
  return true;
}

function allowsMultipleFiles(
  endpoint: string,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): boolean {
  const target = evidenceEndpoint(endpoint);
  if (
    target.includes("document") ||
    target.includes("image") ||
    target.includes("contradictions") ||
    target.includes("assess") ||
    target.includes("duplicates") ||
    target.includes("timeline") ||
    target.includes("gaps") ||
    target.includes("structured") ||
    endpoint.includes("claim-investigation") ||
    endpoint.includes("source-investigation")
  ) {
    return true;
  }
  const contract = contracts.find((item) => item.endpoint === target);
  const field = [...(contract?.required_inputs ?? []), ...(contract?.optional_inputs ?? [])].find(
    (item) => item.name === "file",
  );
  if (field) return field.allow_multiple === true;
  const service = services?.find((item) => item.endpoint === endpoint);
  const serviceField = [...(service?.requiredInputs ?? []), ...(service?.optionalInputs ?? [])].find(
    (item) => item.name === "file",
  );
  if (serviceField) return serviceField.allowMultiple === true;
  return true;
}

function isDirectEvidence(endpoint: string): boolean {
  return endpoint.startsWith("/api/evidence/");
}

function isKnownEndpoint(
  endpoint: string,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): boolean {
  if (isDirectEvidence(endpoint)) {
    return (
      DIRECT_ANALYSIS_ENDPOINTS.has(endpoint) ||
      SOURCE_EVIDENCE_ENDPOINTS.has(endpoint) ||
      services?.some((service) => service.endpoint === endpoint) === true ||
      contracts.some((contract) => contract.endpoint === endpoint)
    );
  }
  return PAID_ENDPOINTS.has(endpoint) || capabilities?.some((item) => item.path === endpoint) === true;
}

function EndpointRequirements({ endpoint, capabilities, services, contracts }: {
  endpoint: string;
  capabilities: PaidCapability[] | null;
  services: EvidenceServiceContract[];
  contracts: RawEvidenceContract[];
}) {
  const extensions = acceptedExtensions(endpoint, capabilities, services, contracts);
  const mimes = acceptedMimes(endpoint, capabilities, services, contracts);
  const maxSizeMB = maxFileSizeMB(endpoint, capabilities, services, contracts);
  const acceptsUrl = acceptsUrlInput(endpoint, capabilities, services, contracts);

  if (extensions.length) {
    return (
      <>
        Accepted files: {extensions.map((item) => item.replace(".", "").toUpperCase()).join(", ")}
        {" — "}up to {maxSizeMB}MB each{acceptsUrl ? " (or provide a URL)" : ""}
      </>
    );
  }
  if (mimes.length) return <>Accepted formats: {mimes.join(", ")} — up to {maxSizeMB}MB{acceptsUrl ? " (or provide a URL)" : ""}</>;
  if (endpoint === "/api/x402/source-investigation" || endpoint === "/api/evidence/url") {
    return <>Accepts a public website or source URL to inspect and analyze</>;
  }
  return <>Accepts a URL or supported evidence files</>;
}

/** All file extensions any endpoint supports — used when no capability is pre-selected
 * so the browser file picker doesn't block valid types. */
const ALL_SUPPORTED_EXTENSIONS = [
  ".jpg",".jpeg",".png",".webp",".gif",".bmp",".tif",".tiff",".heic",".heif",
  ".mp4",".mov",".m4v",".avi",".mkv",".webm",".mpeg",".mpg",".wmv",
  ".mp3",".wav",".m4a",".aac",".flac",".ogg",".opus",
  ".pdf",".docx",".doc",".txt",".md",".rtf",".odt",".html",".htm",".xhtml",
  ".json",".csv",".tsv",".jsonl",".xlsx",".xls",".parquet",
].join(",");

function getAcceptAttribute(
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
  endpoint: string,
  _hasCapabilityHint: boolean,
): string {
  // If claim-investigation or no endpoint, accept all supported file types
  if (!endpoint || endpoint === "/api/x402/claim-investigation") {
    return ALL_SUPPORTED_EXTENSIONS;
  }
  const extensions = acceptedExtensions(endpoint, capabilities, services, contracts);
  if (extensions.length) return extensions.join(",");
  const mimes = acceptedMimes(endpoint, capabilities, services, contracts);
  if (mimes.length) return mimes.join(",");
  return ALL_SUPPORTED_EXTENSIONS;
}

function directEvidenceJson(endpoint: string, question: string, url: string): unknown {
  const claim = question.trim();
  const value: Record<string, unknown> = { claim, question: claim };
  if (url.trim()) value.url = url.trim();
  if (DIRECT_ANALYSIS_ENDPOINTS.has(endpoint)) value.evidence = [];
  return value;
}

function directEvidenceFields(endpoint: string, question: string, url: string): Record<string, string> {
  const claim = question.trim();
  const fields: Record<string, string> = { claim, question: claim };
  if (url.trim()) fields.url = url.trim();
  if (DIRECT_ANALYSIS_ENDPOINTS.has(endpoint)) {
    fields.evidence = "[]";
    fields.payload = JSON.stringify(directEvidenceJson(endpoint, question, url));
  }
  return fields;
}

function validateEvidenceInput(
  endpoint: string,
  files: UploadedFile[],
  url: string,
  sourceInvestigation: Investigation | null,
  capabilities: PaidCapability[] | null,
  services: EvidenceServiceContract[] | null,
  contracts: RawEvidenceContract[],
): string | null {
  const extensions = acceptedExtensions(endpoint, capabilities, services, contracts).map((item) => item.toLowerCase());
  const mimes = acceptedMimes(endpoint, capabilities, services, contracts).map((item) => item.toLowerCase());
  if (!isKnownEndpoint(endpoint, capabilities, services, contracts)) {
    return "This evidence check is not available.";
  }
  const maxSizeMB = maxFileSizeMB(endpoint, capabilities, services, contracts);
  const label = capabilityTitle(endpoint);
  if (url.trim()) {
    const value = url.trim();
    try {
      const parsed = new URL(value);
      if (
        parsed.protocol !== "http:" &&
        parsed.protocol !== "https:"
      ) throw new Error();
      if (!parsed.hostname || parsed.username || parsed.password || /\s/.test(value)) throw new Error();
    } catch {
      return "Please enter a valid HTTP or HTTPS URL.";
    }
    if (value.length > 2048) return "The URL is too long.";
  }

  // URL is accepted for every endpoint.
  // For file/media endpoints, if no file is uploaded and no URL is given:
  if (
    PAID_FILE_ENDPOINTS.has(endpoint) &&
    files.length === 0 &&
    !url.trim() &&
    (!sourceInvestigation || isDirectEvidence(endpoint))
  ) {
    return "Please upload a file or enter a URL before starting this check.";
  }

  if (
    endpoint === "/api/x402/source-investigation" &&
    files.length === 0 &&
    !url.trim() &&
    !sourceInvestigation
  ) {
    return "Please enter a valid URL before starting this check.";
  }

  if (
    DIRECT_ANALYSIS_ENDPOINTS.has(endpoint) &&
    endpoint !== "/api/evidence/gaps" &&
    files.length === 0 &&
    !url.trim()
  ) {
    return "Please provide a PDF or URL for this evidence check.";
  }
  if (endpoint === "/api/evidence/image" && files.length > 1) {
    return "This direct image check accepts one image.";
  }
  if (endpoint === "/api/x402/image-investigation" && files.length > 2) {
    return "Image checks accept at most two images.";
  }
  if (endpoint === "/api/x402/image-batch-investigation" && files.length < 2 && !url.trim()) {
    return "Batch image checks require at least two images.";
  }
  if (files.length > 1 && !allowsMultipleFiles(endpoint, capabilities, services, contracts)) {
    return "This check accepts one file.";
  }

  for (const item of files) {
    const itemName = item.name.toLowerCase();
    const itemType = (item.type || "").toLowerCase();
    const hasExtension = extensions.some((extension) => itemName.endsWith(extension.toLowerCase()));
    const hasMime = mimes.some((m) => m === itemType);
    if ((extensions.length || mimes.length) && !hasExtension && !hasMime) {
      const allowedText = extensions.map((e) => e.replace(".", "").toUpperCase()).join(", ") || mimes.join(", ");
      return `"${item.name}" is not supported by ${label}. Accepted formats: ${allowedText}.`;
    }
    if (item.file.size > maxSizeMB * 1024 * 1024) {
      return `"${item.name}" is larger than the ${maxSizeMB}MB limit.`;
    }
  }

  return null;
}

function formatDirectResult(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function InvestigateForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  const selectedService = searchParams.get("service") ?? "";
  const rawCap = searchParams.get("cap") ?? "";
  const [capabilityHint, setCapabilityHint] = useState(normalizeCapabilityEndpoint(rawCap));
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
  const [directResult, setDirectResult] = useState<unknown>();
  const [directResultTxId, setDirectResultTxId] = useState("");
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
        if (source.capability) setCapabilityHint(normalizeCapabilityEndpoint(source.capability));
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

  // Detect capability from current inputs (for price display).
  useEffect(() => {
    const fileObjects = files.map((f) => f.file);
    const cap = normalizeCapabilityEndpoint(capabilityHint || detectCapabilityEndpoint(fileObjects, url));
    setDetectedCap(cap);
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

    const fileObjects = files.map((item) => item.file);
    const endpoint = normalizeCapabilityEndpoint(
      capabilityHint || detectCapabilityEndpoint(fileObjects, url.trim()),
    );
    setDetectedCap(endpoint);
    const validationError = validateEvidenceInput(
      endpoint,
      files,
      url.trim(),
      sourceInv,
      capabilities,
      evidenceServices,
      contracts,
    );
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSubmitting(true);
    setError("");
    setDirectResult(undefined);
    setDirectResultTxId("");

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

    setPaymentStatus("Opening Pera Wallet — approve the USDC payment…");

    try {
      const idempotencyKey = crypto.randomUUID();
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 300_000);
      try {
        setPaymentStatus("Opening Pera Wallet — approve the USDC payment…");
        if (isDirectEvidence(endpoint)) {
          const paid = await payForEvidence({
            address,
            endpoint,
            fields: directEvidenceFields(endpoint, question, url.trim()),
            json: directEvidenceJson(endpoint, question, url.trim()),
            files: fileObjects.length > 0 ? fileObjects : undefined,
            fileField: "file",
            idempotencyKey,
            signal: controller.signal,
          });
          const invId =
            (paid.data as Record<string, unknown> | null)?.id ??
            (paid.data as Record<string, unknown> | null)?.investigationId ??
            (paid.data as Record<string, unknown> | null)?.requestId;
          if (invId) {
            router.push(`/investigation/${invId}`);
            return;
          }
          setDirectResult(paid.data ?? null);
          setDirectResultTxId(paid.txId);
          setPaymentStatus(paid.txId ? "Payment settled." : "Evidence returned.");
          setIsSubmitting(false);
          return;
        }
        const paid = await payForCapability({
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
        router.push(`/investigation/${paid.id}`);
      } finally {
        window.clearTimeout(timeout);
      }
    } catch (err) {
      const message = err instanceof DOMException && err.name === "AbortError"
        ? "Payment timed out. Open Pera Wallet and approve the request, then try again."
        : err instanceof Error ? err.message : "Payment failed";
      setError(message);
      setPaymentStatus("");
      setIsSubmitting(false);
    }
  };

  const requiresUrl = requiredInput(detectedCap, "url", capabilities, evidenceServices, contracts);
  const requiresFile = requiredInput(detectedCap, "file", capabilities, evidenceServices, contracts);
  const multipleFiles = allowsMultipleFiles(detectedCap, capabilities, evidenceServices, contracts);
  const directEvidence = isDirectEvidence(detectedCap);

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
            URLs {requiresUrl ? "(required)" : sourceInv ? "(optional — original is reused)" : "(optional — multiple URLs separated by newlines or commas)"}
          </label>
          <textarea
            id="url"
            className="form-textarea"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/listing"
            required={requiresUrl && !sourceInv}
          />
        </div>

        <div className="form-group">
          <label className="form-label">
            {sourceInv
              ? "Add replacement evidence (optional)"
              : "Upload evidence (optional — or provide a URL above)"}
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
            multiple={multipleFiles}
            accept={getAcceptAttribute(capabilities, evidenceServices, contracts, detectedCap, Boolean(capabilityHint))}
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
            ? directEvidence ? "Running evidence check…" : "Paying & starting investigation…"
            : directEvidence
              ? `Run evidence check via x402${price ? ` (${price})` : ""}`
              : `Investigate via x402${price ? ` (${price})` : ""}`}
        </button>
        {paymentStatus && !error && (
          <div className={styles.paymentStatus} role="status">
            <strong>{directEvidence ? "Evidence payment status" : "Wallet approval required"}</strong>
            <span>{paymentStatus}</span>
            <span className={styles.paymentAmount}>{price ?? "USDC"}</span>
          </div>
        )}
      </form>

      {directResult !== undefined && (
        <section className={styles.result} aria-live="polite">
          <h2 className="heading-md">Evidence result</h2>
          <InvestigationResultView
            investigation={normalizeToInvestigation(directResult, detectedCap, directResultTxId)}
          />
          {directResultTxId && (
            <p className="text-muted">Settlement transaction: {directResultTxId}</p>
          )}
        </section>
      )}

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