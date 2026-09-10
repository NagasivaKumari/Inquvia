"""FastAPI application — Inquvia's backend API (replaces Next.js /api routes).

Pure API backend. The Next.js frontend keeps serving pages/SSR; this app owns
all /api/* routes. Same-origin is achieved by proxy/frontend config; no CORS
middleware is added by default.
"""
import json
import os
import base64
from html import escape

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from . import config, db
from .auth import (
    signup,
    login,
    create_jwt,
    verify_jwt,
    to_public_user,
    logout_session,
    request_password_reset,
    is_valid_reset_token,
    reset_password,
    create_user_session,
    get_current_user_from_cookie,
    SESSION_COOKIE,
    SESSION_DURATION_MS,
)
from .libraries import engine, capabilities, atomic_route
from .libraries import discovery as discovery_lib
from .libraries import evidence_client
from .x402.gate import build_x402_middleware, extract_settlement_tx_id_from_response_headers

app = FastAPI(title="Inquvia Backend API")

from fastapi.middleware.cors import CORSMiddleware
_ALLOWED_ORIGINS = [
    o.strip()
    for o in (os.getenv("CORS_ALLOWED_ORIGINS") or "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "payment-required",
        "Payment-Required",
        "payment-response",
        "Payment-Response",
        "x-payment-response",
        "x-x402-payment",
        "x-402-payment",
        "payment-signature",
        "Payment-Signature",
    ],
)

_X402_XFAIL = {"traceback": None}


def _build_x402():
    if _X402_XFAIL.get("traceback") is not None:
        return None
    try:
        return build_x402_middleware()
    except Exception as e:  # noqa
        import traceback
        _X402_XFAIL["traceback"] = "".join(traceback.format_exc())
        return None


_X402_MIDDLEWARE = None


@app.on_event("startup")
async def _init_startup():
    global _X402_MIDDLEWARE
    _X402_MIDDLEWARE = _build_x402()
    try:
        db.init_db_indexes()
    except Exception:
        pass


STATE_X402_HEADER = "payment-response"

WALLET_PROVIDERS = [
    {"id": "pera", "name": "Pera Algo Wallet", "icon": "P", "url": "https://perawallet.app"},
    {"id": "defly", "name": "Defly Wallet", "icon": "D", "url": "https://defly.app"},
]

def _resolve_user(request: Request) -> dict | None:
    # 1. Try Bearer JWT from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        user_id = verify_jwt(token)
        if user_id:
            user = db.get_user_by_id(user_id)
            if user:
                return user
        print(f"DEBUG: verify_jwt failed for token: {token[:10]}... user_id={user_id}")

    # 2. Fallback to session cookie
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        user = get_current_user_from_cookie(cookie)
        if user:
            return user
        print(f"DEBUG: session cookie validation failed for {cookie[:10]}...")

    if not auth_header and not cookie:
        print(f"DEBUG: No Authorization header or session cookie found for {request.url.path}")

    return None


def _unauthorized():
    return JSONResponse({"error": "Unauthorized"}, status_code=401)


@app.middleware("http")
async def x402_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/auth/"):
        return await call_next(request)
    print(f"DEBUG: Path={request.url.path}, Middleware={_X402_MIDDLEWARE is not None}")
    middleware = _X402_MIDDLEWARE
    origin = request.headers.get("origin")
    # Only apply x402 gating to paid capability endpoints
    if middleware is not None and request.url.path.startswith("/api/x402/"):
        try:
            res = await middleware(request, call_next)
        except Exception as e:
            import traceback; traceback.print_exc()
            # Fail closed: a payment-gate error can never mean "run for free".
            res = JSONResponse(
                {"error": "Payment verification failed. No payment was accepted and the capability was not run."},
                status_code=402,
            )
        if res.status_code < 400 and getattr(request.state, "payment_requirements", None):
            from .x402.gate import _record_paid_request
            await _record_paid_request(request, res)
        # Ensure CORS headers are attached even when the x402 middleware short-circuits with 402
        if origin and (origin in _ALLOWED_ORIGINS or "*" in _ALLOWED_ORIGINS):
            res.headers["Access-Control-Allow-Origin"] = origin
            res.headers["Access-Control-Allow-Credentials"] = "true"
            res.headers["Access-Control-Expose-Headers"] = (
                "payment-required, Payment-Required, payment-response, "
                "Payment-Response, x-payment-response, x-x402-payment, x-402-payment, "
                "payment-signature, Payment-Signature"
            )
        return res
    return await call_next(request)


# ── Health / root ──
@app.get("/")
async def api_root(request: Request):
    accepts = request.headers.get("accept", "").lower()
    if "text/html" in accepts and "application/json" not in accepts:
        public_url = config.PUBLIC_APP_URL or str(request.base_url).rstrip("/")
        title = escape(config.APP_NAME)
        description = escape("Evidence-backed investigations paid per request with x402 on Algorand.")
        image_url = escape(f"{public_url}/logo.png", quote=True)
        canonical_url = escape(public_url, quote=True)
        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{title}</title>
    <meta name="description" content="{description}">
    <meta property="og:site_name" content="{title}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="{image_url}">
    <link rel="canonical" href="{canonical_url}">
  </head>
  <body><h1>{title}</h1><p>{description}</p></body>
</html>""",
            headers={"Cache-Control": "public, max-age=300"},
        )
    return {
        "service": "inquvia-backend",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/.well-known/x402", include_in_schema=False)
async def x402_discovery(request: Request):
    base_url = config.PUBLIC_APP_URL or str(request.base_url).rstrip("/")
    network = config.ALGORAND_NETWORK_CAIP2
    resources = []
    for capability in config.PAID_CAPABILITIES:
        resources.append({
            "url": f"{base_url}{capability['endpoint']}",
            "method": "POST",
            "description": capability["description"],
            "network": network,
            "asset": config.ALGORAND_USDC_ASA,
            "amount": str(round(capability["priceUsdc"] * config.ALGORAND_USDC_DECIMALS)),
            "payTo": config.INQUVIA_PAYTO_ADDRESS,
        })
    return {
        "x402Version": 2,
        "name": config.APP_NAME,
        "description": "Evidence-backed investigations paid per request with x402 on Algorand.",
        "resources": resources,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "inquvia-backend"}


@app.get("/api/health/debug")
async def health_debug():
    return {"allowed_origins": _ALLOWED_ORIGINS}


# ── Auth ──
@app.post("/api/auth/signup")
async def api_signup(request: Request):
    body = await _json(request)
    if body is None:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    result = signup(body)
    if not result["ok"]:
        return JSONResponse({"error": result["error"]}, status_code=400)
    user = result["data"]

    login_result = login(body)
    if login_result["ok"]:
        token = create_jwt(login_result["data"]["id"])
        session = create_user_session(login_result["data"]["id"], True)
        resp = JSONResponse({"user": user, "token": token}, status_code=201)
        resp.set_cookie(
            SESSION_COOKIE,
            session["id"],
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=int(SESSION_DURATION_MS / 1000),
            path="/",
        )
        return resp
        
    return JSONResponse({"user": user}, status_code=201)


@app.post("/api/auth/login")
async def api_login(request: Request):
    body = await _json(request)
    if body is None:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    result = login(body)
    if not result["ok"]:
        return JSONResponse({"error": result["error"]}, status_code=401)
    
    remember = bool((body or {}).get("remember", True))
    token = create_jwt(result["data"]["id"])
    pub = to_public_user(result["data"])
    session = create_user_session(result["data"]["id"], remember)
    
    resp = JSONResponse({"user": pub, "token": token})
    max_age = int(SESSION_DURATION_MS / 1000) if remember else None
    resp.set_cookie(
        SESSION_COOKIE,
        session["id"],
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=max_age,
        path="/",
    )
    return resp


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = _resolve_user(request)
    return JSONResponse(
        {"user": to_public_user(user) if user else None},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    user = _resolve_user(request)
    if user:
        db.invalidate_user_cache(user["id"])
    logout_session(sid)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.post("/api/auth/forgot")
async def api_forgot(request: Request):
    body = await _json(request)
    result = request_password_reset((body or {}).get("email") or "")
    if not result["ok"]:
        return JSONResponse({"error": result["error"]}, status_code=400)
    return JSONResponse({"ok": True, "token": result["data"]["token"]})


@app.get("/api/auth/reset")
async def api_reset_check(token: str = ""):
    return JSONResponse({"valid": is_valid_reset_token(token)})


@app.post("/api/auth/reset")
async def api_reset(request: Request):
    body = await _json(request)
    result = reset_password((body or {}).get("token") or "", (body or {}).get("password") or "")
    if not result["ok"]:
        return JSONResponse({"error": result["error"]}, status_code=400)
    return JSONResponse({"ok": True})


# ── User + budget ──
def _clamp_num(v, lo, hi):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    return max(lo, min(hi, v))


@app.get("/api/user")
async def api_user_get(request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    payments = db.get_user_payments(user["id"])
    spent = sum(float(p.get("amount") or 0) for p in payments if p.get("status") == "settled")
    total = float((user.get("paymentPrefs") or {}).get("totalBudget") or 0)
    return JSONResponse({
        "user": to_public_user(user),
        "budget": {"spent": spent, "total": total, "remaining": max(0, total - spent)},
    })


@app.patch("/api/user")
async def api_user_patch(request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    body = await _json(request)
    if body is None:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    cur = user.get("paymentPrefs") or {}
    prefs = {
        "maxPerEvidenceCheck": _clamp_num(body.get("maxPerEvidenceCheck"), 0.001, 10) if body.get("maxPerEvidenceCheck") is not None else cur.get("maxPerEvidenceCheck"),
        "maxPerInvestigation": _clamp_num(body.get("maxPerInvestigation"), 0.001, 1000) if body.get("maxPerInvestigation") is not None else cur.get("maxPerInvestigation"),
        "sessionBudget": _clamp_num(body.get("sessionBudget"), 0.001, 100000) if body.get("sessionBudget") is not None else cur.get("sessionBudget"),
        "totalBudget": _clamp_num(body.get("totalBudget"), 0.001, 1000000) if body.get("totalBudget") is not None else cur.get("totalBudget"),
    }
    updated = db.update_user_prefs(user["id"], prefs)
    if not updated:
        return JSONResponse({"error": "User not found"}, status_code=404)
    return JSONResponse({"user": to_public_user(updated)})


# ── Dashboard ──
@app.get("/api/dashboard")
async def api_dashboard(request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    stats = db.get_dashboard_stats(user["id"])
    recent = db.list_investigations(5, user["id"])
    return JSONResponse({**stats, "recentInvestigations": recent})


# ── Investigations ──
@app.get("/api/investigations")
async def api_investigations(request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    investigations = db.list_investigations(50, user["id"])
    return JSONResponse({"investigations": investigations})


def _owns(user, inv_id: str) -> bool:
    inv = db.get_investigation(inv_id)
    if not inv:
        return False
    return inv.get("userId") == user["id"]


@app.get("/api/investigations/{inv_id}")
async def api_investigation_get(inv_id: str, request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    if not _owns(user, inv_id):
        return JSONResponse({"error": "Investigation not found"}, status_code=404)
    investigation = db.get_investigation(inv_id)
    return JSONResponse(investigation)


@app.get("/api/investigations/{inv_id}/evidence")
async def api_investigation_evidence(inv_id: str, request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    if not _owns(user, inv_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    investigation = db.get_investigation(inv_id)
    return JSONResponse({"evidence": (investigation or {}).get("evidence") or []})


# ── Investigate portfolio ──
@app.get("/api/investigate")
async def api_investigate():
    return JSONResponse({
        "portfolio": "inquvia-composite-x402",
        "payTo": config.INQUVIA_PAYTO_ADDRESS or None,
        "network": config.ALGORAND_NETWORK_CAIP2,
        "capabilities": [
            {
                "id": c["id"], "title": c["title"], "path": c["endpoint"], "method": "POST",
                "priceUsdc": c["priceUsdc"], "priceMicro": round(c["priceUsdc"] * 1e6),
                "description": c["description"], "inputTypes": c["inputTypes"],
            }
            for c in config.PAID_CAPABILITIES
        ],
    })


@app.post("/api/investigate")
async def api_investigate_post():
    return JSONResponse(
        {
            "error": "POST /api/investigate is deprecated. Use an atomic endpoint.",
            "endpoints": [{"id": c["id"], "path": c["endpoint"], "priceUsdc": c["priceUsdc"]} for c in config.PAID_CAPABILITIES],
        },
        status_code=405,
    )


# ── Providers / discovery ──
@app.get("/api/providers")
async def api_providers():
    probe = [{"id": "probe", "type": "text", "capability": "source_verify", "reason": "Configured evidence service probe"}]
    discovery_result = await discovery_lib.discover_services(probe)
    primary_services = await evidence_client.discover_remote_services()
    services = []
    for service in primary_services:
        normalized = dict(service)
        normalized["capability"] = normalized.get("capability") or normalized.get("type")
        services.append(normalized)
    known = {(s.get("providerId"), s.get("type"), s.get("resourceUrl")) for s in services}
    for service in discovery_result["services"]:
        normalized = dict(service)
        normalized["capability"] = normalized.get("capability") or (
            (normalized.get("capabilities") or [None])[0]
        )
        key = (normalized.get("providerId"), normalized.get("type"), normalized.get("resourceUrl"))
        if key not in known:
            services.append(normalized)
            known.add(key)
    source = "primary+configured" if primary_services and discovery_result["services"] else (
        "primary" if primary_services else discovery_result["source"]
    )
    return JSONResponse({"services": services, "source": source})


@app.post("/api/providers/discover")
async def api_providers_discover(request: Request):
    body = await _json(request)
    capabilities = (body or {}).get("capabilities") or []
    if not capabilities:
        return JSONResponse({"requirements": [], "services": [], "source": "none"})
    requirements = [
        {"id": f"req_{i + 1}", "type": "text", "capability": cap, "reason": "Requested capability for discovery"}
        for i, cap in enumerate(capabilities)
    ]
    discovery_result = await discovery_lib.discover_services(requirements)
    return JSONResponse(discovery_result)


# ── Wallet ──
async def _verify_algorand_signature(address: str, data_base64: str, authenticator_data_b64: str, signature_base64: str) -> bool:
    """Verify an ARC-60 AUTH signature (Sign-In With Algorand, ARC-0060).

    Pera signs `EdDSA(SHA256(data) || SHA256(authenticatorData))` with the
    account's ed25519 private key, where `authenticatorData` is FIDO-style
    bytes whose first 32 bytes must equal SHA256(domain). """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        import hashlib
    except ImportError:
        return False

    key = _b32decode_algorand(address)
    if not key or len(key) != 32:
        return False
    try:
        import base64 as _b64
        data = _b64.b64decode(data_base64, validate=True)
        auth_data = _b64.b64decode(authenticator_data_b64, validate=True)
        if len(auth_data) < 32:
            return False
        sig = _b64.b64decode(signature_base64, validate=True)
        message = hashlib.sha256(data).digest() + hashlib.sha256(auth_data).digest()
        pub = Ed25519PublicKey.from_public_bytes(key)
        pub.verify(sig, message)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


def _b32decode_algorand(addr: str) -> bytes | None:
    """Decode a base32 Algorand address (no padding). Returns 36-byte payload
    (last 4 bytes are a checksum) or None."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    b32_table = {c: i for i, c in enumerate(alphabet)}
    if len(addr) % 8 == 1:
        return None
    buffer = 0
    bits = 0
    out = bytearray()
    for ch in addr:
        v = b32_table.get(ch)
        if v is None:
            return None
        buffer = (buffer << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((buffer >> bits) & 0xFF)
    # Return the public key portion (first 32 bytes); drop the 4-byte checksum.
    return bytes(out[:32]) if len(out) >= 36 else (bytes(out) if len(out) == 32 else None)


@app.get("/api/wallet/providers")
async def api_wallet_providers():
    return JSONResponse({"wallets": WALLET_PROVIDERS})


@app.post("/api/wallet/connect")
async def api_wallet_connect(request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    body = await _json(request)
    provider_id = (body or {}).get("providerId") or ""
    address = (body or {}).get("address") or ""
    message = (body or {}).get("message") or ""
    signature = (body or {}).get("signatureB64") or ""
    auth_data = (body or {}).get("authenticatorData") or ""

    if not any(w["id"] == provider_id for w in WALLET_PROVIDERS):
        return JSONResponse({"error": "Unsupported wallet provider"}, status_code=400)
    import re
    if not re.fullmatch(r"[A-Z2-7]{58}", address):
        return JSONResponse({"error": "Invalid Algorand address"}, status_code=400)
    if not message or not signature or not auth_data:
        return JSONResponse({"error": "Missing signed challenge. Real wallet signing required."}, status_code=400)

    import base64 as _b64
    data_b64 = _b64.b64encode(message.encode("utf-8")).decode()

    if not await _verify_algorand_signature(address, data_b64, auth_data, signature):
        return JSONResponse({"error": "Signature verification failed"}, status_code=400)

    db.update_user(user["id"], {"walletAddress": address, "walletNetwork": config.ALGORAND_NETWORK})
    return JSONResponse({"wallet": {"address": address, "network": config.ALGORAND_NETWORK, "providerId": provider_id}})


@app.delete("/api/wallet/connect")
async def api_wallet_disconnect(request: Request):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    db.update_user(user["id"], {"walletAddress": None, "walletNetwork": None})
    return JSONResponse({"ok": True})


# ── x402 activity ──
@app.get("/api/x402/activity")
async def api_x402_activity(request: Request, investigation_id: str = ""):
    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    if investigation_id:
        payments = db.get_payments_for_investigation(investigation_id)
    else:
        payments = db.get_user_payments(user["id"])
    return JSONResponse({"payments": payments})


# ── Atomic paid capabilities ──
async def _handle_atomic_capability(request: Request, capability_id: str):
    x402_available = _X402_MIDDLEWARE is not None

    # FAIL CLOSED: when x402 gating is unavailable the endpoint 402s; it never
    # runs a paid capability free. Only an explicit INQUVIA_X402_OFFLINE=1
    # (local dev) bypasses gating, and even then no payment is recorded.
    if not x402_available and not config.INQUVIA_X402_OFFLINE:
        return JSONResponse({
            "error": "Payment verification unavailable (x402 middleware not active). "
                     "No payment was accepted and the capability was not run.",
        }, status_code=402)

    user = _resolve_user(request)
    if not user:
        return _unauthorized()

    content_type = request.headers.get("content-type") or ""
    files = []
    body = None
    idempotency_key = request.headers.get("Idempotency-Key") or None
    if "multipart/form-data" in content_type:
        form = await request.form()
        body = {
            "question": form.get("question"),
            "url": form.get("url"),
            "text": form.get("text"),
        }
        for f in form.getlist("files"):
            data = await f.read()
            if data and len(data) > 0:
                from .libraries.storage import validate_upload
                ok, err = validate_upload(f.content_type or "", len(data))
                if not ok:
                    return JSONResponse({"error": err}, status_code=400)
                files.append({
                    "data": data,
                    "name": f.filename or "upload.bin",
                    "mime": f.content_type or "application/octet-stream",
                })
    else:
        body = await _json(request)

    try:
        result = await atomic_route.handle_atomic_paid_request(capability_id, user, body, files, idempotency_key)
    except atomic_route.InputValidationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        import traceback; traceback.print_exc()
        return JSONResponse({"error": "Failed to process investigation"}, status_code=500)

    headers = {}
    if not x402_available:
        headers["X-X402-Mode"] = "dev-offline"
    resp_obj = result.get("content") or {}
    return JSONResponse(resp_obj, status_code=result.get("status", 200), headers=headers)
@app.post("/api/x402/claim-investigation")
async def claim_investigation(request: Request):
    return await _handle_atomic_capability(request, "claim-investigation")


@app.post("/api/x402/image-investigation")
async def image_investigation(request: Request):
    return await _handle_atomic_capability(request, "image-investigation")


@app.post("/api/x402/video-investigation")
async def video_investigation(request: Request):
    return await _handle_atomic_capability(request, "video-investigation")


@app.post("/api/x402/document-investigation")
async def document_investigation(request: Request):
    return await _handle_atomic_capability(request, "document-investigation")


@app.post("/api/x402/source-investigation")
async def source_investigation(request: Request):
    return await _handle_atomic_capability(request, "source-investigation")


@app.post("/api/x402/data-investigation")
async def data_investigation(request: Request):
    return await _handle_atomic_capability(request, "data-investigation")


# ── Helpers ──
async def _json(request: Request):
    try:
        if not request.headers.get("content-type") or not await request.body():
            return None
        return await request.json()
    except Exception:
        return None
