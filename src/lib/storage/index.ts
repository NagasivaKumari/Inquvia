import fs from "fs";
import path from "path";
import { STORAGE_PATH, MAX_UPLOAD_SIZE, ALLOWED_MIME_TYPES } from "../config";

function resolveStoragePath(): string {
  return path.isAbsolute(STORAGE_PATH)
    ? STORAGE_PATH
    : path.join(process.cwd(), STORAGE_PATH);
}

export interface StoredFile {
  fileName: string;
  filePath: string;
  mimeType: string;
  size: number;
}

function ensureStorageDir() {
  const storagePath = resolveStoragePath();
  if (!fs.existsSync(storagePath)) {
    fs.mkdirSync(storagePath, { recursive: true });
  }
}

export function validateUpload(
  mimeType: string,
  size: number
): { valid: boolean; error?: string } {
  if (size > MAX_UPLOAD_SIZE) {
    return { valid: false, error: "File exceeds maximum size of 10MB" };
  }
  if (
    !ALLOWED_MIME_TYPES.includes(
      mimeType as (typeof ALLOWED_MIME_TYPES)[number]
    )
  ) {
    return { valid: false, error: `File type ${mimeType} is not supported` };
  }
  return { valid: true };
}

export async function storeFile(
  buffer: Buffer,
  fileName: string,
  mimeType: string,
  investigationId: string
): Promise<StoredFile> {
  ensureStorageDir();
  const storagePath = resolveStoragePath();
  const invDir = path.join(storagePath, investigationId);
  if (!fs.existsSync(invDir)) {
    fs.mkdirSync(invDir, { recursive: true });
  }

  const safeName = fileName.replace(/[^a-zA-Z0-9._-]/g, "_");
  const filePath = path.join(invDir, safeName);
  fs.writeFileSync(filePath, buffer);

  return {
    fileName: safeName,
    filePath,
    mimeType,
    size: buffer.length,
  };
}

export function sanitizeText(text: string): string {
  return text
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, "")
    .slice(0, 50000);
}

export function sanitizeUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

export function sanitizeExtractedHtml(html: string): string {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, "")
    .replace(/on\w+\s*=\s*["'][^"']*["']/gi, "")
    .slice(0, 100000);
}
