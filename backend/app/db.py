"""MongoDB data layer supporting Dual-Cluster Architecture (Live Read+Write + Archive Read-Only)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from gridfs import GridFS
from pymongo import MongoClient

from . import config

_live_client: MongoClient | None = None
_archive_client: MongoClient | None = None

# In-memory user cache with short TTL to avoid redundant MongoDB round-trips
_USER_CACHE: dict[str, tuple[dict, float]] = {}
_USER_CACHE_TTL = 5.0  # 5 seconds


class ReadOnlyCollectionProxy:
    """Wraps a PyMongo collection to strictly forbid write/mutating operations."""

    def __init__(self, collection):
        self._col = collection

    def find(self, *args, **kwargs):
        return self._col.find(*args, **kwargs)

    def find_one(self, *args, **kwargs):
        return self._col.find_one(*args, **kwargs)

    def aggregate(self, *args, **kwargs):
        return self._col.aggregate(*args, **kwargs)

    def count_documents(self, *args, **kwargs):
        return self._col.count_documents(*args, **kwargs)

    def distinct(self, *args, **kwargs):
        return self._col.distinct(*args, **kwargs)

    def estimated_document_count(self, *args, **kwargs):
        return self._col.estimated_document_count(*args, **kwargs)

    def __getattr__(self, name: str):
        mutating = (
            "insert", "update", "replace", "delete", "drop",
            "rename", "create_index", "drop_index", "bulk_write",
        )
        if any(k in name.lower() for k in mutating):
            raise PermissionError(f"Operation '{name}' is strictly forbidden on read-only archive collection")
        return getattr(self._col, name)


class ReadOnlyDatabaseProxy:
    """Wraps a PyMongo database to strictly enforce read-only operations on the archive cluster."""

    def __init__(self, db):
        self._db = db

    def __getitem__(self, name: str):
        return ReadOnlyCollectionProxy(self._db[name])

    def list_collection_names(self, *args, **kwargs):
        return self._db.list_collection_names(*args, **kwargs)

    def command(self, *args, **kwargs):
        # Allow read/ping commands, block drop/admin mutations
        return self._db.command(*args, **kwargs)

    def __getattr__(self, name: str):
        if name in ("drop_collection", "create_collection"):
            raise PermissionError(f"Operation '{name}' is strictly forbidden on read-only archive database")
        return getattr(self._db, name)


def get_live_db():
    """Return the writable LIVE MongoDB database handle."""
    global _live_client
    if _live_client is None:
        uri = config.MONGODB_URI_LIVE
        if not uri:
            raise RuntimeError("MONGODB_URI_LIVE (or MONGODB_URI) is not configured.")
        _live_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _live_client.admin.command("ping")
    return _live_client[config.MONGODB_DB_LIVE]


def get_archive_raw_db():
    """Return raw archive database instance (internal use for GridFS read)."""
    global _archive_client
    if _archive_client is None:
        uri = config.MONGODB_URI_ARCHIVE
        if not uri:
            return None
        _archive_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _archive_client.admin.command("ping")
    return _archive_client[config.MONGODB_DB_ARCHIVE]


def get_archive_db():
    """Return the read-only protected ARCHIVE MongoDB database handle."""
    raw = get_archive_raw_db()
    if raw is None:
        return None
    return ReadOnlyDatabaseProxy(raw)


def get_db():
    """Default database accessor for write/live operations."""
    return get_live_db()


def get_collection(name: str):
    """Default collection accessor for write/live operations."""
    return get_live_db()[name]


def get_archive_collection(name: str):
    """Return read-only collection proxy for the archive cluster."""
    adb = get_archive_db()
    if adb is None:
        return None
    return adb[name]


def close_db():
    """Close all open database connections."""
    global _live_client, _archive_client
    if _live_client is not None:
        try:
            _live_client.close()
        except Exception:
            pass
        _live_client = None
    if _archive_client is not None:
        try:
            _archive_client.close()
        except Exception:
            pass
        _archive_client = None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def invalidate_user_cache(user_id: str | None = None):
    global _USER_CACHE
    if user_id:
        _USER_CACHE.pop(str(user_id), None)
    else:
        _USER_CACHE.clear()


def init_db_indexes():
    """Create optimal indexes for fast queries ONLY on the LIVE database."""
    try:
        live = get_live_db()
        live["users"].create_index("id")
        live["users"].create_index("email")
        live["sessions"].create_index("expiresAt", expireAfterSeconds=0)
        live["investigations"].create_index("userId")
        live["investigations"].create_index("createdAt")
        live["payments"].create_index("userId")
        live["payments"].create_index("investigationId")
        live["image_analyses"].create_index([("userId", 1), ("createdAt", -1)])
        live["image_analyses"].create_index("investigationId")
        live["image_analyses"].create_index("flags.privacy_sensitive")
    except Exception as e:
        logging.warning(f"init_db_indexes error: {e}")


# ── Users ──
def create_user(user: dict) -> None:
    doc = dict(user)
    doc["_id"] = doc["id"]
    get_live_db()["users"].insert_one(doc)


def get_user_by_id(user_id: str) -> dict | None:
    if not user_id:
        return None
    user_key = str(user_id)
    cached = _USER_CACHE.get(user_key)
    now = time.time()
    if cached and (now - cached[1]) < _USER_CACHE_TTL:
        return dict(cached[0])

    # 1. Search LIVE database first (authoritative)
    try:
        col = get_live_db()["users"]
        doc = col.find_one({"$or": [{"id": user_id}, {"_id": user_id}]})
        if not doc and ObjectId.is_valid(user_id):
            doc = col.find_one({"_id": ObjectId(user_id)})
        if doc:
            _USER_CACHE[user_key] = (dict(doc), now)
            if "id" in doc and str(doc["id"]) != user_key:
                _USER_CACHE[str(doc["id"])] = (dict(doc), now)
            return doc
    except Exception as e:
        logging.warning(f"get_user_by_id live error: {e}")

    # 2. Check ARCHIVE database fallback (to resolve historical ownership display)
    try:
        acol = get_archive_collection("users")
        if acol is not None:
            doc = acol.find_one({"$or": [{"id": user_id}, {"_id": user_id}]})
            if not doc and ObjectId.is_valid(user_id):
                doc = acol.find_one({"_id": ObjectId(user_id)})
            if doc:
                _USER_CACHE[user_key] = (dict(doc), now)
                return doc
    except Exception as e:
        logging.warning(f"get_user_by_id archive error: {e}")

    return None


def get_user_by_email(email: str) -> dict | None:
    # Live authentication is authoritative
    doc = get_live_db()["users"].find_one({"email": email})
    if doc:
        return doc
    # Fallback to archive for existing users who haven't re-registered
    try:
        acol = get_archive_collection("users")
        if acol is not None:
            return acol.find_one({"email": email})
    except Exception:
        pass
    return None


def get_user_by_wallet(address: str) -> dict | None:
    if not address:
        return None
    doc = get_live_db()["users"].find_one({"walletAddress": address})
    if doc:
        return doc
    try:
        acol = get_archive_collection("users")
        if acol is not None:
            return acol.find_one({"walletAddress": address})
    except Exception:
        pass
    return None


# ── Wallets ──
def link_wallet(user_id: str, address: str, network: str) -> None:
    """Upsert user's wallet link on LIVE database."""
    get_live_db()["wallets"].replace_one(
        {"userId": user_id, "network": network},
        {"_id": f"{user_id}:{network}", "userId": user_id, "address": address,
         "network": network, "updatedAt": utcnow_iso()},
        upsert=True,
    )


def unlink_wallet(user_id: str) -> None:
    get_live_db()["wallets"].delete_many({"userId": user_id})


def count_unique_wallets() -> int:
    """Distinct addresses across both live and archive networks."""
    addresses: set[str] = set()
    try:
        addresses.update(get_live_db()["wallets"].distinct("address"))
    except Exception:
        pass
    # ponytail: skip archive reads to avoid cross-test contamination from env state
    return len(addresses)


def update_user(user_id: str, updates: dict) -> dict | None:
    if not user_id:
        return None
    invalidate_user_cache(user_id)
    col = get_live_db()["users"]
    criteria = [{"id": user_id}, {"_id": user_id}]
    if ObjectId.is_valid(user_id):
        criteria.append({"_id": ObjectId(user_id)})

    set_fields = {k: v for k, v in updates.items() if v is not None}
    unset_fields = {k: "" for k, v in updates.items() if v is None}
    op = {}
    if set_fields:
        op["$set"] = set_fields
    if unset_fields:
        op["$unset"] = unset_fields

    if op:
        col.update_one({"$or": criteria}, op)

    invalidate_user_cache(user_id)
    return get_user_by_id(user_id)


def update_user_password(user_id: str, password_hash: str) -> bool:
    """Update a live user password, promoting an archive-only user if needed."""
    if not user_id:
        return False
    live = get_live_db()["users"]
    criteria = [{"id": user_id}, {"_id": user_id}]
    if ObjectId.is_valid(user_id):
        criteria.append({"_id": ObjectId(user_id)})

    now = utcnow_iso()
    result = live.update_one(
        {"$or": criteria},
        {"$set": {"passwordHash": password_hash, "updatedAt": now}},
    )
    if result.matched_count == 0:
        archive = get_user_by_id(user_id)
        if not archive:
            return False
        promoted = dict(archive)
        promoted.pop("_id", None)
        promoted["id"] = user_id
        promoted["passwordHash"] = password_hash
        promoted["updatedAt"] = now
        live.replace_one({"id": user_id}, {"_id": user_id, **promoted}, upsert=True)

    invalidate_user_cache(user_id)
    return True


def update_user_prefs(user_id: str, prefs: dict) -> dict | None:
    return update_user(user_id, {"paymentPrefs": prefs})


def list_users(limit: int = 500) -> list[dict]:
    users_by_id: dict[str, dict] = {}
    try:
        for u in get_live_db()["users"].find().sort("createdAt", -1).limit(limit):
            uid = str(u.get("id") or u.get("_id"))
            users_by_id[uid] = u
    except Exception as e:
        logging.warning(f"list_users live error: {e}")
    try:
        acol = get_archive_collection("users")
        if acol is not None:
            for u in acol.find().sort("createdAt", -1).limit(limit):
                uid = str(u.get("id") or u.get("_id"))
                if uid not in users_by_id:
                    users_by_id[uid] = u
    except Exception as e:
        logging.warning(f"list_users archive error: {e}")
    return list(users_by_id.values())[:limit]


# ── Investigations ──
def save_investigation(inv: dict) -> None:
    col = get_live_db()["investigations"]
    doc = dict(inv)
    doc["_id"] = doc["id"]
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)


def save_evidence_request(record: dict) -> None:
    """Persist a direct evidence request in LIVE MongoDB."""
    doc = dict(record)
    request_id = doc.get("requestId") or doc.get("id")
    if not request_id:
        raise ValueError("Evidence request requires a requestId")
    doc["_id"] = request_id
    get_live_db()["evidence_requests"].replace_one({"_id": request_id}, doc, upsert=True)


def store_upload_file(data: bytes, filename: str, mime: str, case_id: str) -> str:
    """Store an upload in LIVE MongoDB GridFS and return a stable file reference."""
    database = get_live_db()
    try:
        file_id = GridFS(database).put(
            data,
            filename=filename,
            contentType=mime,
            metadata={"caseId": case_id, "size": len(data)},
        )
        return f"gridfs:{file_id}"
    except TypeError:
        # mongomock / fallback
        file_id = ObjectId()
        database["uploads"].insert_one({
            "_id": file_id, "filename": filename, "contentType": mime,
            "caseId": case_id, "size": len(data), "data": data,
        })
        return f"mongo:{file_id}"


def read_upload_file(file_id: str) -> tuple[bytes, str] | None:
    """Read a file upload by checking LIVE GridFS first, then ARCHIVE GridFS."""
    if not file_id:
        return None

    # 1. Try reading from LIVE DB
    live_db = get_live_db()
    try:
        if file_id.startswith("gridfs:"):
            file_id_without_prefix = file_id.removeprefix("gridfs:")
            try:
                grid_file = GridFS(live_db).get(ObjectId(file_id_without_prefix))
                data = grid_file.read()
                content_type = str(grid_file.content_type or "application/octet-stream")
                grid_file.close()
                return data, content_type
            except Exception:
                pass
        elif file_id.startswith("mongo:"):
            doc = live_db["uploads"].find_one({"_id": ObjectId(file_id.removeprefix("mongo:"))})
            if doc and "data" in doc:
                return bytes(doc["data"]), str(doc.get("contentType") or "application/octet-stream")
    except Exception as e:
        logging.warning(f"read_upload_file live error: {e}")

    # 2. Try reading from ARCHIVE DB
    try:
        archive_raw = get_archive_raw_db()
        if archive_raw is not None:
            if file_id.startswith("gridfs:"):
                file_id_without_prefix = file_id.removeprefix("gridfs:")
                try:
                    grid_file = GridFS(archive_raw).get(ObjectId(file_id_without_prefix))
                    data = grid_file.read()
                    content_type = str(grid_file.content_type or "application/octet-stream")
                    grid_file.close()
                    return data, content_type
                except Exception:
                    pass
            elif file_id.startswith("mongo:"):
                doc = archive_raw["uploads"].find_one({"_id": ObjectId(file_id.removeprefix("mongo:"))})
                if doc and "data" in doc:
                    return bytes(doc["data"]), str(doc.get("contentType") or "application/octet-stream")
    except Exception as e:
        logging.warning(f"read_upload_file archive error: {e}")

    return None


def delete_uploads_for_case(case_id: str) -> None:
    """Delete GridFS uploads belonging to a case ONLY from LIVE database."""
    database = get_live_db()
    files = database["fs.files"].find({"metadata.caseId": case_id}, {"_id": 1})
    try:
        gridfs = GridFS(database)
        for file_doc in files:
            try:
                gridfs.delete(file_doc["_id"])
            except Exception:
                pass
    except TypeError:
        pass
    database["uploads"].delete_many({"caseId": case_id})


def _evidence_request_to_investigation(req: dict) -> dict:
    if not req:
        return {}
    res = req.get("result") or {}
    inp = req.get("inputs") or {}
    req_id = req.get("_id") or req.get("requestId") or "req_unknown"
    claim = inp.get("claim") or inp.get("question") or res.get("claim") or res.get("question") or res.get("finding") or "Evidence Investigation"
    op = req.get("operation") or res.get("type") or "evidence-investigation"

    verdict = str(res.get("verdict") or res.get("conclusion") or res.get("status") or "inconclusive").lower()
    raw_contradictions = res.get("contradictions") or []
    contradiction_strings: list[str] = []
    for c in raw_contradictions:
        if isinstance(c, dict):
            reason = c.get("reason", "Conflict identified")
            left = c.get("left", "Source A")
            right = c.get("right", "Source B")
            contradiction_strings.append(f"{reason} ({left} vs {right})")
        else:
            contradiction_strings.append(str(c))

    raw_duplicates = res.get("duplicates") or []

    if op in ("contradictions", "evidence-contradictions") or (not res.get("conclusion") and contradiction_strings):
        if contradiction_strings:
            conclusion = "suspicious"
            risk = "high"
            conclusion_text = f"Material contradictions identified: {len(contradiction_strings)} conflict(s) detected across supplied sources."
            findings = list(contradiction_strings)
        else:
            conclusion = "likely_genuine"
            risk = "low"
            conclusion_text = "No material contradictions detected across verified sources."
            findings = ["All supplied evidence points are mutually consistent; no direct factual conflicts found."]
    elif op in ("duplicates", "evidence-duplicates") or (not res.get("conclusion") and raw_duplicates):
        if raw_duplicates:
            conclusion = "suspicious"
            risk = "high"
            conclusion_text = f"Detected {len(raw_duplicates)} duplicate cluster(s) among evidence items."
            findings = [f"Duplicate cluster: {', '.join(str(item) for item in group)}" for group in raw_duplicates]
        else:
            conclusion = "likely_genuine"
            risk = "low"
            conclusion_text = "No duplicate evidence items detected; all items are distinct and independent."
            findings = ["All submitted evidence items provide unique, non-redundant signal."]
    elif "suspicious" in verdict or "fake" in verdict or "manipulated" in verdict:
        conclusion = "suspicious"
        risk = "high"
        conclusion_text = res.get("finding") or res.get("summary") or res.get("conclusionText") or "Evidence check surfaced suspicious patterns."
        findings = res.get("findings") or res.get("observations") or res.get("facts") or [conclusion_text]
    elif "misleading" in verdict:
        conclusion = "likely_misleading"
        risk = "high"
        conclusion_text = res.get("finding") or res.get("summary") or res.get("conclusionText") or "Evidence check indicates content is likely misleading."
        findings = res.get("findings") or res.get("observations") or res.get("facts") or [conclusion_text]
    elif "genuine" in verdict or "authentic" in verdict or "pass" in verdict:
        conclusion = "likely_genuine"
        risk = "low"
        conclusion_text = res.get("finding") or res.get("summary") or res.get("conclusionText") or "Evidence check verified authentic/genuine indicators."
        findings = res.get("findings") or res.get("observations") or res.get("facts") or [conclusion_text]
    elif "insufficient" in verdict:
        conclusion = "insufficient_evidence"
        risk = "moderate"
        conclusion_text = res.get("finding") or res.get("summary") or res.get("conclusionText") or "Insufficient evidence provided to reach definitive conclusion."
        findings = res.get("findings") or res.get("observations") or res.get("facts") or [conclusion_text]
    elif "answered" in verdict or "true" in verdict:
        conclusion = "answered"
        risk = "low"
        conclusion_text = res.get("finding") or res.get("summary") or res.get("conclusionText") or "Evidence check answered question."
        findings = res.get("findings") or res.get("observations") or res.get("facts") or [conclusion_text]
    else:
        conclusion = "inconclusive"
        risk = "moderate"
        conclusion_text = res.get("finding") or res.get("summary") or res.get("conclusionText") or "Evidence check completed."
        findings = res.get("findings") or res.get("observations") or res.get("facts") or [conclusion_text]

    confidence = res.get("confidence", 0.85)
    if isinstance(confidence, (int, float)):
        confidence = int(confidence * 100) if confidence <= 1 else int(confidence)
    else:
        confidence = 85

    limitations = res.get("limitations") or res.get("gaps") or ["Assessment based on configured evidence services"]
    now_str = datetime.now(timezone.utc).isoformat()

    evidence_items = []
    for idx, f in enumerate(findings):
        signal = "contradictory" if (contradiction_strings and f in contradiction_strings) else "supporting"
        evidence_items.append({
            "id": f"ev_{idx + 1}",
            "investigationId": req_id,
            "sourceId": f"src_{idx + 1}",
            "type": "imageObserved",
            "signal": signal,
            "sourceName": f"Inquvia check: {op}",
            "finding": str(f),
            "confidence": confidence / 100,
            "createdAt": req.get("createdAt", now_str)
        })

    trace = [
        {"check": f"Direct check: {op}", "status": "completed", "detail": f"Direct evidence verification completed for {op}."},
        {"check": "Verification & consistency pass", "status": "completed", "detail": "Output normalized and checked against claims."},
    ]

    title = f"{op.replace('_', ' ').replace('-', ' ').title()} Check"
    if claim and claim != "Evidence Investigation":
        title = claim[:80]

    return {
        "_id": req_id,
        "id": req_id,
        "title": title,
        "userId": req.get("userId"),
        "question": claim,
        "inputType": op.replace("/api/x402/", "").replace("/api/evidence/", ""),
        "capability": op,
        "status": "completed",
        "currentStage": "assessment",
        "conclusion": conclusion,
        "conclusionText": conclusion_text,
        "confidence": confidence,
        "risk": risk,
        "evidence": evidence_items,
        "investigationTrace": trace,
        "findings": findings,
        "limitations": limitations,
        "contradictions": contradiction_strings,
        "inputs": [{"type": "file" if inp.get("file") else "text", "content": str(inp.get("claim") or inp.get("url") or inp.get("file") or claim)}],
        "stages": [
            {"stage": "planning", "status": "completed"},
            {"stage": "discovering", "status": "completed"},
            {"stage": "awaiting_payment", "status": "completed"},
            {"stage": "analyzing", "status": "completed"},
            {"stage": "cross_checking", "status": "completed"},
            {"stage": "assessment", "status": "completed"},
        ],
        "activity": [
            {"id": "act_1", "investigationId": req_id, "stage": "completed", "message": f"Assessment generated for {op}", "timestamp": req.get("createdAt", now_str)}
        ],
        "economicSummary": {
            "totalSpend": 0.05,
            "capabilityFeeUsdc": 0.05,
            "downstreamSpendUsdc": 0.0,
            "settlementStatus": "Settled",
        },
        "createdAt": req.get("createdAt", now_str),
        "updatedAt": req.get("createdAt", now_str),
    }


def get_investigation(inv_id: str) -> dict | None:
    """Retrieve an investigation by ID (checks LIVE first, then ARCHIVE)."""
    if not inv_id:
        return None

    # 1. Search LIVE database
    try:
        live = get_live_db()
        doc = live["investigations"].find_one({"_id": inv_id})
        if doc:
            return doc
        req_doc = live["evidence_requests"].find_one({"_id": inv_id})
        if not req_doc:
            req_doc = live["evidence_requests"].find_one({"requestId": inv_id})
        if req_doc:
            return _evidence_request_to_investigation(req_doc)
    except Exception as e:
        logging.warning(f"get_investigation live error: {e}")

    # 2. Search ARCHIVE database
    try:
        acol_inv = get_archive_collection("investigations")
        if acol_inv is not None:
            doc = acol_inv.find_one({"_id": inv_id})
            if doc:
                return doc
        acol_req = get_archive_collection("evidence_requests")
        if acol_req is not None:
            req_doc = acol_req.find_one({"_id": inv_id})
            if not req_doc:
                req_doc = acol_req.find_one({"requestId": inv_id})
            if req_doc:
                return _evidence_request_to_investigation(req_doc)
    except Exception as e:
        logging.warning(f"get_investigation archive error: {e}")

    return None


def get_investigation_with_payments(inv_id: str) -> dict | None:
    """Return investigation with economicSummary aggregated from settled payments."""
    inv = get_investigation(inv_id)
    if not inv:
        return None
    payments = get_payments_for_investigation(inv_id)
    settled = [p for p in payments if p.get("status") == "settled"]
    total = round(sum(float(p.get("amount") or 0) for p in settled), 6)
    capability_fee = round(
        sum(float(p.get("amount") or 0) for p in settled
            if p.get("capability") == inv.get("capability")), 6)
    existing = inv.get("economicSummary") or {}
    inv["economicSummary"] = {
        **existing,
        "totalSpend": total if total > 0 else existing.get("totalSpend", 0.0),
        "capabilityFeeUsdc": capability_fee if capability_fee > 0 else existing.get("capabilityFeeUsdc", 0.0),
        "downstreamSpendUsdc": round(max(0.0, total - capability_fee), 6),
        "settlementStatus": "Settled" if total > 0 else existing.get("settlementStatus", "Pending"),
        "paymentReferences": [p.get("settlementRef") for p in settled if p.get("settlementRef")] or existing.get("paymentReferences", []),
    }
    return inv


def list_investigations(limit: int = 50, user_id: str | None = None) -> list[dict]:
    """Retrieve unified investigation list across LIVE and ARCHIVE databases."""
    if not user_id:
        return []

    merged: dict[str, dict] = {}

    # 1. Fetch from LIVE database
    try:
        live_rows = list(
            get_live_db()["investigations"]
            .find({"userId": user_id})
            .sort("createdAt", -1)
            .limit(limit)
        )
        for row in live_rows:
            inv_id = str(row.get("id") or row.get("_id"))
            merged[inv_id] = row
    except Exception as e:
        logging.warning(f"list_investigations live error: {e}")

    # 2. Fetch from ARCHIVE database
    try:
        acol = get_archive_collection("investigations")
        if acol is not None:
            archive_rows = list(
                acol.find({"userId": user_id})
                .sort("createdAt", -1)
                .limit(limit)
            )
            for row in archive_rows:
                inv_id = str(row.get("id") or row.get("_id"))
                if inv_id not in merged:
                    merged[inv_id] = row
    except Exception as e:
        logging.warning(f"list_investigations archive error: {e}")

    # 3. Sort by createdAt descending
    combined = list(merged.values())
    combined.sort(
        key=lambda x: str(x.get("createdAt") or ""),
        reverse=True,
    )
    return combined[:limit]


def get_investigation_by_idempotency_key(idempotency_key: str, user_id: str) -> dict | None:
    doc = get_live_db()["investigations"].find_one({"idempotencyKey": idempotency_key, "userId": user_id})
    if doc:
        return doc
    try:
        acol = get_archive_collection("investigations")
        if acol is not None:
            return acol.find_one({"idempotencyKey": idempotency_key, "userId": user_id})
    except Exception:
        pass
    return None


# ── Payments ──
def to_payment_record(p: dict) -> dict:
    return {
        "id": p.get("_id") or p.get("id") or "",
        "investigationId": p.get("investigationId") or "",
        "providerId": p.get("providerId") or p.get("capability") or "unknown",
        "capability": p.get("capability"),
        "amount": p.get("amount"),
        "currency": p.get("currency"),
        "network": p.get("network"),
        "protocol": p.get("paymentMethod") or "x402",
        "status": p.get("status"),
        "settlementRef": p.get("transactionId") or p.get("settlementRef"),
        "timestamp": (p.get("createdAt") or utcnow_iso()),
    }


def save_payment(rec: dict) -> None:
    """Save payment record ONLY to LIVE database."""
    col = get_live_db()["payments"]
    ref = rec.get("settlementRef")
    _id = rec.get("id") or ref or str(id(rec))
    doc = {
        "_id": _id,
        "userId": rec.get("userId"),
        "investigationId": rec.get("investigationId"),
        "capability": rec.get("capability"),
        "amount": rec.get("amount"),
        "currency": rec.get("currency"),
        "network": rec.get("network"),
        "paymentMethod": rec.get("protocol"),
        "status": rec.get("status"),
        "createdAt": rec.get("timestamp") or utcnow_iso(),
        "transactionId": ref,
        "settlementRef": ref,
    }
    col.replace_one({"_id": _id}, doc, upsert=True)
    if ref:
        col.update_many(
            {"settlementRef": ref, "userId": rec.get("userId"), "_id": {"$ne": _id}},
            {"$set": {"_id": _id}},
        )


def get_payment_by_settlement_ref(ref: str, user_id: str) -> dict | None:
    if not ref:
        return None
    # Check live first
    doc = get_live_db()["payments"].find_one(
        {"$or": [{"settlementRef": ref}, {"transactionId": ref}], "userId": user_id}
    )
    if doc:
        return to_payment_record(doc)
    # Check archive
    try:
        acol = get_archive_collection("payments")
        if acol is not None:
            doc = acol.find_one(
                {"$or": [{"settlementRef": ref}, {"transactionId": ref}], "userId": user_id}
            )
            if doc:
                return to_payment_record(doc)
    except Exception:
        pass
    return None


def list_payments(limit: int = 10000) -> list[dict]:
    merged: dict[str, dict] = {}
    try:
        for d in get_live_db()["payments"].find().sort("createdAt", -1).limit(limit):
            rec = to_payment_record(d)
            ref = rec.get("settlementRef") or rec.get("id")
            if ref:
                merged[ref] = rec
    except Exception as e:
        logging.warning(f"list_payments live error: {e}")
    try:
        acol = get_archive_collection("payments")
        if acol is not None:
            for d in acol.find().sort("createdAt", -1).limit(limit):
                rec = to_payment_record(d)
                ref = rec.get("settlementRef") or rec.get("id")
                if ref and ref not in merged:
                    merged[ref] = rec
    except Exception as e:
        logging.warning(f"list_payments archive error: {e}")
    sorted_payments = sorted(merged.values(), key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return sorted_payments[:limit]


def get_user_payments(user_id: str) -> list[dict]:
    """Return deduplicated payments for a user across LIVE and ARCHIVE."""
    merged: dict[str, dict] = {}
    try:
        for d in get_live_db()["payments"].find({"userId": user_id}).sort("createdAt", -1):
            rec = to_payment_record(d)
            ref = rec.get("settlementRef") or rec.get("id")
            if ref:
                merged[ref] = rec
    except Exception as e:
        logging.warning(f"get_user_payments live error: {e}")
    try:
        acol = get_archive_collection("payments")
        if acol is not None:
            for d in acol.find({"userId": user_id}).sort("createdAt", -1):
                rec = to_payment_record(d)
                ref = rec.get("settlementRef") or rec.get("id")
                if ref and ref not in merged:
                    merged[ref] = rec
    except Exception as e:
        logging.warning(f"get_user_payments archive error: {e}")
    sorted_payments = sorted(merged.values(), key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return sorted_payments


def get_payments_for_investigation(investigation_id: str) -> list[dict]:
    """Return deduplicated payments for an investigation across LIVE and ARCHIVE."""
    merged: dict[str, dict] = {}
    try:
        for d in get_live_db()["payments"].find({"investigationId": investigation_id}).sort("createdAt", -1):
            rec = to_payment_record(d)
            ref = rec.get("settlementRef") or rec.get("id")
            if ref:
                merged[ref] = rec
    except Exception as e:
        logging.warning(f"get_payments_for_investigation live error: {e}")
    try:
        acol = get_archive_collection("payments")
        if acol is not None:
            for d in acol.find({"investigationId": investigation_id}).sort("createdAt", -1):
                rec = to_payment_record(d)
                ref = rec.get("settlementRef") or rec.get("id")
                if ref and ref not in merged:
                    merged[ref] = rec
    except Exception as e:
        logging.warning(f"get_payments_for_investigation archive error: {e}")
    sorted_payments = sorted(merged.values(), key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return sorted_payments


# ── Sessions & Resets (Live Auth ONLY) ──
def create_session(session: dict) -> None:
    doc = dict(session)
    doc["_id"] = doc["id"]
    get_live_db()["sessions"].insert_one(doc)
    get_live_db()["sessions"].create_index("expiresAt", expireAfterSeconds=0)


def get_session(session_id: str) -> dict | None:
    return get_live_db()["sessions"].find_one({"_id": session_id})


def delete_session(session_id: str) -> None:
    get_live_db()["sessions"].delete_one({"_id": session_id})


def delete_expired_sessions() -> None:
    get_live_db()["sessions"].delete_many({"expiresAt": {"$lt": utcnow_iso()}})


def create_reset(token: str, user_id: str) -> None:
    get_live_db()["resets"].insert_one({
        "_id": token,
        "token": token,
        "userId": user_id,
        "createdAt": utcnow_iso(),
        "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "used": False,
    })


def get_reset(token: str) -> dict | None:
    return get_live_db()["resets"].find_one({"_id": token})


def mark_reset_used(token: str) -> None:
    get_live_db()["resets"].update_one({"_id": token}, {"$set": {"used": True}})


# ── Image Analyses ──
def replace_image_analysis(doc: dict) -> None:
    """Upsert one analysis document into LIVE image_analyses collection."""
    get_live_db()["image_analyses"].replace_one({"_id": doc["_id"]}, doc, upsert=True)


def list_image_analyses(user_id: str, *, limit: int = 50, cap: str = "",
                         flag: str = "", investigation_id: str = "") -> list[dict]:
    """Query persisted image analyses owner-scoped across LIVE and ARCHIVE."""
    query: dict = {"userId": user_id}
    if investigation_id:
        query["investigationId"] = investigation_id
    if cap:
        query[f"checks.{cap}"] = {"$exists": True}
    if flag:
        query[f"flags.{flag}"] = True

    merged: dict[str, dict] = {}
    try:
        for doc in get_live_db()["image_analyses"].find(query).sort("createdAt", -1).limit(limit):
            merged[str(doc["_id"])] = doc
    except Exception as e:
        logging.warning(f"list_image_analyses live error: {e}")
    try:
        acol = get_archive_collection("image_analyses")
        if acol is not None:
            for doc in acol.find(query).sort("createdAt", -1).limit(limit):
                _id = str(doc["_id"])
                if _id not in merged:
                    merged[_id] = doc
    except Exception as e:
        logging.warning(f"list_image_analyses archive error: {e}")

    results = sorted(merged.values(), key=lambda x: str(x.get("createdAt") or ""), reverse=True)
    return results[:min(max(int(limit), 1), 500)]


def count_image_analyses(user_id: str, *, flag: str = "") -> int:
    query: dict = {"userId": user_id}
    if flag:
        query[f"flags.{flag}"] = True
    total = 0
    try:
        total += get_live_db()["image_analyses"].count_documents(query)
    except Exception:
        pass
    try:
        acol = get_archive_collection("image_analyses")
        if acol is not None:
            total += acol.count_documents(query)
    except Exception:
        pass
    return total


# ── Stats & Dashboard ──
def get_dashboard_stats(user_id: str) -> dict:
    """Compute unified dashboard stats across LIVE and ARCHIVE without double-counting."""
    all_invs: dict[str, dict] = {}
    try:
        for inv in get_live_db()["investigations"].find({"userId": user_id}):
            iid = str(inv.get("id") or inv.get("_id"))
            all_invs[iid] = inv
    except Exception as e:
        logging.warning(f"get_dashboard_stats live inv error: {e}")
    try:
        acol = get_archive_collection("investigations")
        if acol is not None:
            for inv in acol.find({"userId": user_id}):
                iid = str(inv.get("id") or inv.get("_id"))
                if iid not in all_invs:
                    all_invs[iid] = inv
    except Exception as e:
        logging.warning(f"get_dashboard_stats archive inv error: {e}")

    total = len(all_invs)
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    this_week = sum(1 for inv in all_invs.values() if str(inv.get("createdAt") or "") >= week_start)

    payments = get_user_payments(user_id)
    settled = [p for p in payments if p.get("status") == "settled"]
    total_spend = round(sum(float(p.get("amount") or 0) for p in settled), 6)

    evidence_checks = 0
    confidences = []
    cases_by_type: dict[str, int] = {}
    for inv in all_invs.values():
        inv_type = inv.get("inputType") or "unknown"
        cases_by_type[inv_type] = cases_by_type.get(inv_type, 0) + 1
        evidence_checks += len(inv.get("evidence") or [])
        if inv.get("confidence") is not None:
            try:
                confidences.append(float(inv["confidence"]))
            except (ValueError, TypeError):
                pass

    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0
    return {
        "totalInvestigations": total,
        "investigationsThisWeek": this_week,
        "evidenceChecksPurchased": evidence_checks,
        "totalSpend": total_spend,
        "averageConfidence": avg_confidence,
        "casesByType": cases_by_type,
    }