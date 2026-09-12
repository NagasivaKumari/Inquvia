"""AI provider calls (mirrors src/lib/investigation/ai.ts)."""
import json
import re

import httpx

from .. import config


async def call_ai_with_parts(
    system_prompt: str,
    parts: list[dict],
    temperature: float = 0.2,
    text_fallback: bool = True,
) -> str | None:
    """parts: list of {'text'?: str, 'file'?: {'mimeType', 'base64'}}.

    text_fallback=False restricts the call to providers that actually receive
    the attached files (Gemini multimodal). Chat-only text providers only see
    the text parts and would hallucinate about unseen files, so calls that
    must read a file (audio transcription) pass False."""
    text_context = "\n\n".join(p.get("text", "") for p in parts if p.get("text"))

    # 1. Gemini (multimodal).
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
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}",
                    json=payload,
                )
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
                    if text:
                        return text
        except Exception:
            pass

    # 2. Experiential (OpenAI-compatible, supports audio/video/images via parts).
    if config.EXPLABS_API_KEY:
        try:
            messages = [{"role": "system", "content": system_prompt}]
            user_content = []
            for part in parts:
                if part.get("text"):
                    user_content.append({"type": "text", "text": part["text"]})
                elif part.get("file"):
                    mime = part["file"]["mimeType"]
                    b64 = part["file"]["base64"]
                    if mime.startswith("audio/"):
                        user_content.append({"type": "input_audio", "input_audio": {"data": b64, "format": mime.split("/")[1]}})
                    elif mime.startswith("image/"):
                        user_content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                    else:
                        user_content.append({"type": "text", "text": f"[file: {mime}]"})
            messages.append({"role": "user", "content": user_content})
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(
                    "https://api.experientiallabs.ai/v1/chat/completions",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.EXPLABS_API_KEY}"},
                    json={
                        "model": config.EXPLABS_MODEL,
                        "messages": messages,
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content")
                    if text:
                        return text
        except Exception:
            pass

    # 3. OpenRouter (OpenAI-compatible, supports vision via image_url).
    if config.OPENROUTER_API_KEY:
        try:
            messages = [{"role": "system", "content": system_prompt}]
            user_content = []
            for part in parts:
                if part.get("text"):
                    user_content.append({"type": "text", "text": part["text"]})
                elif part.get("file"):
                    mime = part["file"]["mimeType"]
                    b64 = part["file"]["base64"]
                    if mime.startswith("image/"):
                        user_content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                    elif mime.startswith("audio/"):
                        user_content.append({"type": "text", "text": f"[audio: {mime}]"})
                    else:
                        user_content.append({"type": "text", "text": f"[file: {mime}]"})
            messages.append({"role": "user", "content": user_content})
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://inquvia.ai",
                        "X-Title": "Inquvia Forensics Engine",
                    },
                    json={
                        "model": config.OPENROUTER_MODEL,
                        "messages": messages,
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content")
                    if text:
                        return text
        except Exception:
            pass

    # Fallback providers (text-only). Only reached when a call is allowed to
    # degrade to the text context — never for file-dependent transcription.
    if text_fallback and text_context:
        text = await call_text_provider_chain(system_prompt, text_context, temperature)
        if text:
            return text
    return None


async def call_text_provider_chain(system_prompt: str, text_context: str, temperature: float) -> str | None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Groq
        if config.GROQ_API_KEY:
            try:
                res = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.GROQ_API_KEY}"},
                    json={
                        "model": config.GROQ_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text_context},
                        ],
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content")
                    if text:
                        return text
            except Exception:
                pass

        # 2. Experiential (OpenAI-compatible API)
        if config.EXPLABS_API_KEY:
            try:
                res = await client.post(
                    "https://api.experientiallabs.ai/v1/chat/completions",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.EXPLABS_API_KEY}"},
                    json={
                        "model": config.EXPLABS_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text_context},
                        ],
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
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
                res = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://inquvia.ai",
                        "X-Title": "Inquvia Forensics Engine",
                    },
                    json={
                        "model": config.OPENROUTER_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text_context},
                        ],
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content")
                    if text:
                        return text
            except Exception:
                pass

        # 4. OpenAI
        if config.OPENAI_API_KEY:
            try:
                res = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                    json={
                        "model": config.OPENAI_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text_context},
                        ],
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
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