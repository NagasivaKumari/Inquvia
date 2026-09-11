"""FastAPI application — Inquvia's backend API (replaces Next.js /api routes).

Pure API backend. The Next.js frontend keeps serving pages/SSR; this app owns
all /api/* routes. Same-origin is achieved by proxy/frontend config; no CORS
middleware is added by default.
"""
import json
import os
import base64
from html import escape
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.requests import ClientDisconnect

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
from .api import evidence as evidence_api
from .x402.gate import build_x402_middleware, extract_settlement_tx_id_from_response_headers

app = FastAPI(title="Inquvia Backend API")
app.include_router(evidence_api.router)

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
    from starlette.requests import ClientDisconnect
    if request.url.path.startswith("/api/auth/"):
        return await call_next(request)
    print(f"DEBUG: Path={request.url.path}, Middleware={_X402_MIDDLEWARE is not None}")
    middleware = _X402_MIDDLEWARE
    origin = request.headers.get("origin")
    # Only apply x402 gating to paid capability endpoints
    if middleware is not None and (request.url.path.startswith("/api/x402/") or request.url.path.startswith("/api/evidence/")):
        # DIAGNOSTIC: log any PAYMENT-SIGNATURE header (v2) or X-PAYMENT (v1) and whether it decodes.
        _pay_sig = request.headers.get("payment-signature") or request.headers.get("x-payment")
        if _pay_sig:
            try:
                _pay_data = json.loads(base64.b64decode(_pay_sig).decode("utf-8"))
                _accepted = _pay_data.get("accepted") or _pay_data.get("payload") or {}
                print(f"x402 DIAG payment header on {request.method} {request.url.path}: version={_pay_data.get('x402Version')} accepted={_accepted}")
            except Exception as e:
                print(f"x402 DIAG payment header on {request.method} {request.url.path} UNDECODABLE: {type(e).__name__}: {e}")
        try:
            res = await middleware(request, call_next)
        except ClientDisconnect:
            # The client (browser) dropped the socket mid-upload. This is NOT a
            # payment failure and must not 402/fail the gate; the user's upload
            # simply never completed.
            res = JSONResponse({
                "error": "Upload interrupted: the connection closed before the file finished "
                         "uploading. Keep files under 10MB and retry.",
            }, status_code=400)
        except Exception as e:
            import traceback; traceback.print_exc()
            # Fail closed: a payment-gate error can never mean "run for free".
            res = JSONResponse(
                {"error": "Payment verification failed. No payment was accepted and the capability was not run."},
                status_code=402,
            )
        if res.status_code == 402:
            try:
                import json as _json
                detail = _json.loads(res.body if isinstance(res.body, bytes) else b"")
                # DIAGNOSTIC: the PAYMENT-REQUIRED header carries the actual rejection reason.
                _req_hdr = (res.headers.get("payment-required")
                            or res.headers.get("Payment-Required")
                            or res.headers.get("PAYMENT-REQUIRED"))
                _reason = ""
                if _req_hdr:
                    try:
                        _req = _json.loads(base64.b64decode(_req_hdr).decode("utf-8"))
                        _reason = _req.get("error") or ""
                    except Exception:
                        _reason = f"(undecodable PAYMENT-REQUIRED hdr {_req_hdr[:60]}...)"
                print(f"x402 gate rejected {request.method} {request.url.path}: body={detail} reason={_reason!r}")
            except Exception:
                pass
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
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "inquvia-backend"}


@app.get("/api/x402/transaction-params", include_in_schema=False)
async def x402_transaction_params():
    """Algod suggested parameters proxied through the backend.

    The browser payment path used to call testnet-api.algonode.cloud directly;
    free-tier rate limits / CORS / blockers made that hop fail silently, so the
    wallet was never prompted. Serving the params ourselves removes that
    dependency (server-side algod access configured by ALGOD_SERVER/TOKEN/PORT).
    """
    try:
        client = _algod_client()
        sp = client.suggested_params()
    except Exception as e:
        return JSONResponse(
            {"error": f"Algod suggested params unavailable: {e}"},
            status_code=502,
        )

    gh = sp.gh
    return JSONResponse({
        "flatFee": bool(getattr(sp, "flat_fee", False)),
        "fee": int(sp.fee or 0),
        "minFee": int(getattr(sp, "min_fee", 0) or 0),
        "firstRound": int(sp.first or 0),
        "lastRound": int(sp.last or 0),
        "genesisHash": gh.decode() if isinstance(gh, bytes) else str(gh or ""),
        "genesisId": str(sp.gen or ""),
    }, headers={"Cache-Control": "no-store"})


def _algod_client():
    from algosdk.v2client.algod import AlgodClient

    address = config.ALGOD_SERVER
    if not address.startswith(("http://", "https://")):
        address = f"{address}:{config.ALGOD_PORT}"
    return AlgodClient(config.ALGOD_TOKEN or "", address)


@app.get("/api/x402/account-status")
async def x402_account_status(address: str):
    """Whether the account holds the payment asset (opt-in) and its balance."""
    try:
        account = _algod_client().account_info(address)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    asset_id = int(config.ALGORAND_USDC_ASA)
    opted_in = False
    balance = 0
    for holding in account.get("assets", []):
        if int(holding["asset-id"]) == asset_id:
            opted_in = True
            balance = int(holding["amount"])
            break
    return {
        "address": address,
        "assetId": asset_id,
        "optedIn": opted_in,
        "balance": balance,
    }


@app.post("/api/x402/broadcast", include_in_schema=False)
async def x402_broadcast(payload: dict):
    """Broadcast a signed (opt-in) transaction and wait for confirmation."""
    from algosdk import transaction

    stxn = payload.get("signedTxn")
    if not stxn:
        return JSONResponse({"error": "signedTxn (base64) required"}, status_code=400)
    try:
        txid = _algod_client().send_transaction(stxn)
        transaction.wait_for_confirmation(_algod_client(), txid, 4)
        return {"txid": txid}
    except Exception as e:
        return JSONResponse({"error": f"Broadcast failed: {e}"}, status_code=502)


@app.get("/api/health/debug")
async def health_debug():
    return {"allowed_origins": _ALLOWED_ORIGINS}


@app.get("/")
async def api_root(request: Request):
    accepts = request.headers.get("accept", "").lower()
    ua = (request.headers.get("user-agent") or "").lower()
    crawler = any(t in ua for t in (
        "bot/", "spider", "crawler", "googlebot", "facebookexternalhit",
        "twitterbot", "linkedinbot", "slackbot", "discordbot", "whatsapp",
        "telegrambot", "bingbot", "duckduckgo",
    ))
    if crawler or "application/json" not in accepts:
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


@app.get("/logo.png", include_in_schema=False)
async def logo():
    # Explicitly look in the project's public directory from the defined ROOT
    candidate = config.ROOT / "public" / "logo.png"
    if candidate.is_file():
        return Response(
            content=candidate.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Logo file not found at {candidate}")


@app.get("/.well-known/x402", include_in_schema=False)
async def x402_discovery(request: Request):
    base_url = config.PUBLIC_APP_URL or str(request.base_url).rstrip("/")
    if "localhost" in base_url or "127.0.0.1" in base_url:
        base_url = str(request.base_url).rstrip("/")
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


@app.get("/api/investigations/{inv_id}/files/{file_name}")
async def api_investigation_file(inv_id: str, file_name: str, request: Request):
    """Serve a file the user uploaded to this investigation (owner-only)."""
    from urllib.parse import quote
    from .libraries import storage as _storage

    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    if not _owns(user, inv_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    investigation = db.get_investigation(inv_id)
    hit = next(
        (i for i in (investigation or {}).get("inputs") or [] if i.get("fileName") == file_name and i.get("filePath")),
        None,
    )
    if not hit:
        return JSONResponse({"error": "File not found"}, status_code=404)
    stored = db.read_upload_file(hit["filePath"])
    buf = stored[0] if stored else None
    mime = (stored[1] if stored else None) or hit.get("mimeType") or "application/octet-stream"
    if buf is None:
        p = _storage.resolve_stored_path(hit["filePath"])
        if p:
            try:
                buf = p.read_bytes()
            except OSError:
                buf = None
    if buf is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return Response(
        content=buf,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{quote(file_name)}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@app.get("/api/sources/{inv_id}/{source_ref:path}")
async def api_source_file(inv_id: str, source_ref: str, request: Request):
    """Serve an uploaded source by its storage reference (owner-only).

    ``source_ref`` is the ``filePath`` stored on the investigation input
    (e.g. ``gridfs:<ObjectId>``).  This endpoint is the generic,
    auth-aware path for rendering original uploaded media in the UI.
    """
    from .libraries import storage as _storage
    from urllib.parse import quote, unquote

    user = _resolve_user(request)
    if not user:
        return _unauthorized()
    if not _owns(user, inv_id):
        return JSONResponse({"error": "Not found"}, status_code=404)

    investigation = db.get_investigation(inv_id)
    if not investigation:
        return JSONResponse({"error": "Not found"}, status_code=404)

    # source_ref may be URL-encoded by the frontend
    decoded_ref = unquote(source_ref)

    hit = next(
        (i for i in (investigation.get("inputs") or [])
         if i.get("filePath") and (i["filePath"] == decoded_ref or i["filePath"] == source_ref)),
        None,
    )
    if not hit:
        return JSONResponse({"error": "Source not found"}, status_code=404)

    stored = db.read_upload_file(hit["filePath"])
    buf = stored[0] if stored else None
    mime = (stored[1] if stored else None) or hit.get("mimeType") or "application/octet-stream"
    if buf is None:
        p = _storage.resolve_stored_path(hit["filePath"])
        if p:
            try:
                buf = p.read_bytes()
            except OSError:
                buf = None
    if buf is None:
        return JSONResponse({"error": "Source not found"}, status_code=404)

    file_name = hit.get("fileName") or "source"
    return Response(
        content=buf,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{quote(file_name)}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


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
    }, headers={"Cache-Control": "public, max-age=300"})


@app.post("/api/investigate")
async def api_investigate_post():
    return JSONResponse(
        {
            "error": "POST /api/investigate is deprecated. Use an atomic endpoint.",
            "endpoints": [{"id": c["id"], "path": c["endpoint"], "priceUsdc": c["priceUsdc"]} for c in config.PAID_CAPABILITIES],
        },
        status_code=405,
    )


# ── Inquvia capabilities ──
@app.get("/api/providers")
async def api_providers():
    services = [
        {
            "id": capability["id"],
            "name": capability["title"],
            "capability": capability["id"],
            "capabilities": capability.get("inputTypes") or [capability["id"].removeprefix("evidence-")],
            "description": capability["description"],
            "endpoint": capability["endpoint"],
            "priceUsdc": capability.get("priceUsdc", config.INVESTIGATION_PRICE_USDC),
            "priceMicro": round(capability.get("priceUsdc", config.INVESTIGATION_PRICE_USDC) * 1e6),
            "providerId": "inquvia",
            "providerName": "Inquvia",
            "paid": True,
        }
        for capability in config.EVIDENCE_CAPABILITIES
    ]
    return JSONResponse({"services": services, "source": "inquvia"},
                        headers={"Cache-Control": "public, max-age=300"})


@app.post("/api/providers/discover")
async def api_providers_discover(request: Request):
    body = await _json(request)
    capabilities = (body or {}).get("capabilities") or []
    if not capabilities:
        return JSONResponse({"requirements": [], "services": [], "source": "none"})
    matches = [
        capability for capability in config.PAID_CAPABILITIES
        if capability["id"] in capabilities or any(
            requested in capability["inputTypes"] for requested in capabilities
        )
    ]
    return JSONResponse({
        "requirements": capabilities,
        "services": [
            {"id": capability["id"], "name": capability["title"], "providerId": "inquvia",
             "providerName": "Inquvia", "capabilities": capability["inputTypes"],
             "description": capability["description"], "paid": True}
            for capability in matches
        ],
        "source": "inquvia",
    })


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
        try:
            form = await request.form()
        except ClientDisconnect:
            return JSONResponse({
                "error": "Upload interrupted: the connection closed before the file finished "
                         "uploading. Keep files under 10MB and retry.",
            }, status_code=400)
        except Exception:
            return JSONResponse({"error": "Could not read the uploaded file."}, status_code=400)
        body = {
            "question": form.get("question"),
            "url": form.get("url"),
            "text": form.get("text"),
            "serviceName": form.get("serviceName"),
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


@app.post("/api/x402/audio-investigation")
async def audio_investigation(request: Request):
    return await _handle_atomic_capability(request, "audio-investigation")


# ── Helpers ──
async def _json(request: Request):
    try:
        if not request.headers.get("content-type") or not await request.body():
            return None
        return await request.json()
    except Exception:
        return None
