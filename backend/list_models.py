import urllib.request, json, os, sys
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

key = os.getenv("GEMINI_API_KEY", "")
or_key = os.getenv("OPENROUTER_API_KEY", "")
xp_key = os.getenv("EXPLABS_API_KEY", "")
groq_key = os.getenv("GROQ_API_KEY", "")

# --- Gemini available models ---
print("=== GEMINI MODELS (generateContent + flash) ===")
try:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    raw = urllib.request.urlopen(url, timeout=15).read().decode()
    data = json.loads(raw)
    for m in data.get("models", []):
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods and ("flash" in name.lower() or "pro" in name.lower()):
            sys.stdout.write(f"  {name}  |  {m.get('displayName','')}\n")
except Exception as e:
    sys.stdout.write(f"  ERROR: {e}\n")

# --- OpenRouter free vision models ---
print("\n=== OPENROUTER FREE VISION MODELS ===")
try:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {or_key}"}
    )
    raw = urllib.request.urlopen(req, timeout=15).read().decode()
    data = json.loads(raw)
    for m in data.get("data", []):
        mid = m.get("id", "")
        mods = m.get("architecture", {}).get("input_modalities", [])
        pricing = m.get("pricing", {})
        prompt_cost = float(pricing.get("prompt", "1") or "1")
        if "image" in mods and prompt_cost == 0.0:
            sys.stdout.write(f"  {mid}  inputs={mods}\n")
except Exception as e:
    sys.stdout.write(f"  ERROR: {e}\n")

# --- ExperientialLabs available models ---
print("\n=== EXPLABS MODELS ===")
try:
    req = urllib.request.Request(
        "https://api.experientiallabs.ai/v1/models",
        headers={"Authorization": f"Bearer {xp_key}"}
    )
    raw = urllib.request.urlopen(req, timeout=15).read().decode()
    data = json.loads(raw)
    for m in data.get("data", []):
        mid = m.get("id", "")
        sys.stdout.write(f"  {mid}\n")
except Exception as e:
    sys.stdout.write(f"  ERROR: {e}\n")

# --- Groq available models ---
print("\n=== GROQ MODELS ===")
try:
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {groq_key}"}
    )
    raw = urllib.request.urlopen(req, timeout=15).read().decode()
    data = json.loads(raw)
    for m in data.get("data", []):
        mid = m.get("id", "")
        sys.stdout.write(f"  {mid}\n")
except Exception as e:
    sys.stdout.write(f"  ERROR: {e}\n")

sys.stdout.flush()
