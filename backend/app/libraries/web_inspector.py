"""Live web inspection: DNS + TLS cert + HTTP fetch (mirrors webInspector.ts)."""
import re
import ssl
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx


def _get_certificate(hostname: str, port: int = 443) -> dict | None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((hostname, port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname=hostname) as ssock:
                der = ssock.getpeercert(binary_form=True)
                if not der:
                    return None
                from cryptography import x509
                cert = x509.load_der_x509_certificate(der)
                subject = cert.subject
                issuer = cert.issuer
                org = None
                for attr in subject:
                    if attr.oid._name == "organizationName":
                        org = attr.value
                        break
                issuer_names = {a.oid._name: a.value for a in issuer}
                issuer_org = issuer_names.get("organizationName") or issuer_names.get("commonName")
                valid_to = cert.not_valid_after_utc
                return {
                    "issuer": issuer_org or "Trusted Authority",
                    "valid_to": valid_to.isoformat(),
                    "days_remaining": max(0, round((valid_to - datetime.now(timezone.utc)).total_seconds() / 86400)),
                }
    except Exception:
        return None


async def inspect_live_url(target_url: str) -> dict | None:
    try:
        normalized = target_url.strip()
        if not normalized.startswith("http://") and not normalized.startswith("https://"):
            normalized = "https://" + normalized
        parsed = urlparse(normalized)
        hostname = parsed.hostname or ""

        # 1. DNS resolution (A records).
        dns_records: list[str] = []
        try:
            import socket as _socket
            records = _socket.getaddrinfo(hostname, None, _socket.AF_INET)
            dns_records = [item[4][0] for item in records if item[4] and item[4][0]]
            dns_records = list(dict.fromkeys(dns_records))
        except Exception:
            dns_records = []

        # 2. SSL inspection.
        ssl_valid = False
        ssl_issuer = None
        ssl_days_remaining = None
        if parsed.scheme == "https":
            cert = _get_certificate(hostname, parsed.port or 443)
            if cert:
                ssl_valid = True
                ssl_issuer = cert["issuer"]
                ssl_days_remaining = cert["days_remaining"]

        # 3. Live HTTP page fetch.
        status_code = None
        title = None
        meta_description = None
        body_snippet = None
        is_online = False
        try:
            with httpx.Client(timeout=6.0, follow_redirects=True) as client:
                res = client.get(
                    normalized,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InquviaForensics/2.0"},
                )
            status_code = res.status_code
            is_online = res.is_success or res.status_code < 500
            html = res.text
            t = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
            if t:
                title = t.group(1).strip()
            d = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
            if d:
                meta_description = d.group(1).strip()
            clean = re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", " ", html, flags=re.I)
            clean = re.sub(r"<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>", " ", clean, flags=re.I)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            body_snippet = clean[:1000]
        except Exception:
            is_online = len(dns_records) > 0

        return {
            "url": normalized,
            "hostname": hostname,
            "dnsRecords": dns_records,
            "sslValid": ssl_valid,
            "sslIssuer": ssl_issuer,
            "sslDaysRemaining": ssl_days_remaining,
            "statusCode": status_code,
            "title": title,
            "metaDescription": meta_description,
            "bodySnippet": body_snippet,
            "isOnline": is_online,
        }
    except Exception:
        return None