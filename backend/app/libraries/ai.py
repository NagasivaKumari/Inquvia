"""AI provider calls (mirrors src/lib/investigation/ai.ts)."""
import json
import re

import httpx

from .. import config


async def call_ai_with_parts(
    system_prompt: str,
    parts: list[dict],
    temperature: float = 0.2,
) -> str | None:
    """parts: list of {'text'?: str, 'file'?: {'mimeType', 'base64'}}."""
    text_context = "\n\n".join(p.get("text", "") for p in parts if p.get("text"))

    # 1. Gemini (only provider that consumes multimodal files).
    if config.GEMINI_API_KEY:
        try:
            content_parts = []
            for part in parts:
                if part.get("file"):
                    content_parts.append({
                        "inlineData": {
                            "mimeType": part["file"]["mimeType"],
                            "data": part["file"]["base64"],
                        }
                    })
                elif part.get("text"):
                    content_parts.append({"text": part["text"]})
            payload = {
                "contents": [{"role": "user", "parts": content_parts}],
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
            }
            res = await httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={config.GEMINI_API_KEY}",
                json=payload,
                timeout=60,
            )
            if res.status_code == 200:
                data = res.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
                if text:
                    return text
        except Exception:
            pass

    # Fallback providers (text-only).
    if text_context:
        text = await call_text_provider_chain(system_prompt, text_context, temperature)
        if text:
            return text
    return None


async def call_text_provider_chain(system_prompt: str, text_context: str, temperature: float) -> str | None:
    # 2. Groq
    if config.GROQ_API_KEY:
        try:
            res = await httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.GROQ_API_KEY}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text_context},
                    ],
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if res.status_code == 200:
                data = res.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content")
                if text:
                    return text
        except Exception:
            pass

    # 3. OpenRouter
    if config.OPENROUTER_API_KEY:
        try:
            res = await httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://inquvia.ai",
                    "X-Title": "Inquvia Forensics Engine",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text_context},
                    ],
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if res.status_code == 200:
                data = res.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content")
                if text:
                    return text
        except Exception:
            pass
    return None


def parse_ai_json(raw: str | None):
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        return json.loads(cleaned)
    except Exception:
        return None