import { API_BASE } from "../config";

// The evidence service URL is retrieved from the environment in the backend,
// but for the frontend, we need to ensure the calls are proxied or made correctly
// based on the user's requirement.
// Note: Core Inquvia must communicate with Evidence Services only through this deployed HTTP URL.

export const EVIDENCE_SERVICE_URL = process.env.NEXT_PUBLIC_EVIDENCE_SERVICE_URL ?? "";

async function evidenceFetch(endpoint: string, data: any) {
  if (!EVIDENCE_SERVICE_URL) {
    throw new Error("EVIDENCE_SERVICE_URL is not configured.");
  }
  
  const response = await fetch(`${EVIDENCE_SERVICE_URL}/api/evidence/${endpoint}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${localStorage.getItem("token") || ""}`
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(`Evidence service error: ${response.statusText}`);
  }

  return response.json();
}

export const EvidenceService = {
  image: (data: any) => evidenceFetch("image", data),
  video: (data: any) => evidenceFetch("video", data),
  url: (data: any) => evidenceFetch("url", data),
  document: (data: any) => evidenceFetch("document", data),
  structured: (data: any) => evidenceFetch("structured", data),
  crossModal: (data: any) => evidenceFetch("cross-modal", data),
  timeline: (data: any) => evidenceFetch("timeline", data),
  provenance: (data: any) => evidenceFetch("provenance", data),
};
