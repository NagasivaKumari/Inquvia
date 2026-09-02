import type { AssessmentLabel, RiskLevel, EvidenceSignal } from "../types";

export interface DynamicInvestigationResult {
  title: string;
  plan: {
    capability: string;
    reason: string;
    estimatedCost: number;
    expectedValue: number;
  }[];
  evidence: {
    type: string;
    source: string;
    finding: string;
    confidence: number;
    cost: number;
    signal: EvidenceSignal;
    capability: string;
  }[];
  conclusion: AssessmentLabel;
  conclusionText: string;
  confidence: number;
  risk: RiskLevel;
  findings: string[];
  limitations: string[];
  contradictions: string[];
  relevanceMap: Record<string, number>;
  expectedGainMap: Record<string, number>;
}

export async function callAIWithFallbacks(prompt: string, systemPrompt: string): Promise<string | null> {
  return callAIWithParts(systemPrompt, [{ text: prompt }]);
}

export interface AIPart {
  text?: string;
  /** Multimodal file (mime type + raw base64). Only Gemini can consume these. */
  file?: { mimeType: string; base64: string };
}

/**
 * Call the internal AI with optional multimodal parts (image/video/PDF).
 * Gemini accepts inline_data; the fallback providers receive the textual
 * parts only (no fabricated vision analysis from providers that cannot see).
 */
export async function callAIWithParts(
  systemPrompt: string,
  parts: AIPart[],
  temperature = 0.2
): Promise<string | null> {
  const textContext = parts
    .map((p) => p.text ?? "")
    .filter(Boolean)
    .join("\n\n");

  // 1. Try Gemini API (only provider that consumes real multimodal files).
  const geminiKey = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
  if (geminiKey) {
    try {
      const contentParts: unknown[] = [];
      for (const part of parts) {
        if (part.file) {
          contentParts.push({
            inlineData: {
              mimeType: part.file.mimeType,
              data: part.file.base64,
            },
          });
        } else if (part.text) {
          contentParts.push({ text: part.text });
        }
      }
      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${geminiKey}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            contents: [{ role: "user", parts: contentParts }],
            systemInstruction: { parts: [{ text: systemPrompt }] },
            generationConfig: {
              temperature,
              responseMimeType: "application/json",
            },
          }),
        }
      );
      if (res.ok) {
        const data = await res.json();
        const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
        if (text) return text;
      }
    } catch (err) {
      console.warn("Gemini API call failed, trying next fallback...", err);
    }
  }

  // Fallback providers are text-only.
  if (textContext) {
    const text = await callTextProviderChain(
      systemPrompt,
      textContext,
      temperature
    );
    if (text) return text;
  }

  return null;
}

async function callTextProviderChain(
  systemPrompt: string,
  textContext: string,
  temperature: number
): Promise<string | null> {
  // 2. Try Groq API
  const groqKey = process.env.GROQ_API_KEY;
  if (groqKey) {
    try {
      const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${groqKey}`,
        },
        body: JSON.stringify({
          model: "llama-3.3-70b-versatile",
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: textContext },
          ],
          temperature,
          response_format: { type: "json_object" },
        }),
      });
      if (res.ok) {
        const data = await res.json();
        const text = data.choices?.[0]?.message?.content;
        if (text) return text;
      }
    } catch (err) {
      console.warn("Groq API call failed, trying next fallback...", err);
    }
  }

  // 3. Try OpenRouter API
  const openrouterKey = process.env.OPENROUTER_API_KEY;
  if (openrouterKey) {
    try {
      const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${openrouterKey}`,
          "HTTP-Referer": "https://inquvia.ai",
          "X-Title": "Inquvia Forensics Engine",
        },
        body: JSON.stringify({
          model: "google/gemini-2.0-flash-001",
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: textContext },
          ],
          temperature,
          response_format: { type: "json_object" },
        }),
      });
      if (res.ok) {
        const data = await res.json();
        const text = data.choices?.[0]?.message?.content;
        if (text) return text;
      }
    } catch (err) {
      console.warn("OpenRouter API call failed, trying next fallback...", err);
    }
  }

  return null;
}

/** Best-effort JSON extraction from an AI assistant response. */
export function parseAIJson<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    const cleaned = raw
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/, "")
      .trim();
    const start = cleaned.indexOf("{");
    const end = cleaned.lastIndexOf("}");
    if (start >= 0 && end > start) {
      return JSON.parse(cleaned.slice(start, end + 1)) as T;
    }
    return JSON.parse(cleaned) as T;
  } catch {
    return null;
  }
}
