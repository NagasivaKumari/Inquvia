"""MongoDB data layer (mirrors src/lib/db/index.ts using pymongo)."""
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from gridfs import GridFS
from pymongo import MongoClient

from . import config

_client: MongoClient | None = None


def get_collection(name: str):
    db = get_db()
    return db[name]


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")
    return _client[config.MONGODB_DB_NAME]


def close_db():
    global _client
    if _client is not None:
        _client.close()
        _client = None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Users ──
def create_user(user: dict) -> None:
    doc = dict(user)
    doc["_id"] = doc["id"]
    get_collection("users").insert_one(doc)


# In-memory user cache with short TTL to avoid redundant MongoDB round-trips
import time
_USER_CACHE: dict[str, tuple[dict, float]] = {}
_USER_CACHE_TTL = 5.0  # 5 seconds


def invalidate_user_cache(user_id: str | None = None):
    global _USER_CACHE
    if user_id:
        _USER_CACHE.pop(str(user_id), None)
    else:
        _USER_CACHE.clear()


def init_db_indexes():
    """Create optimal indexes for fast queries."""
    try:
        get_collection("users").create_index("id")
        get_collection("users").create_index("email")
        get_collection("sessions").create_index("expiresAt", expireAfterSeconds=0)
        get_collection("investigations").create_index("userId")
        get_collection("investigations").create_index("createdAt")
        get_collection("payments").create_index("userId")
        get_collection("payments").create_index("investigationId")
    except Exception:
        pass


def get_user_by_id(user_id: str) -> dict | None:
    if not user_id:
        return None
    user_key = str(user_id)
    cached = _USER_CACHE.get(user_key)
    now = time.time()
    if cached and (now - cached[1]) < _USER_CACHE_TTL:
        return dict(cached[0])

    col = get_collection("users")
    doc = col.find_one({"$or": [{"id": user_id}, {"_id": user_id}]})
    if not doc and ObjectId.is_valid(user_id):
        doc = col.find_one({"_id": ObjectId(user_id)})

    if doc:
        _USER_CACHE[user_key] = (dict(doc), now)
        if "id" in doc and str(doc["id"]) != user_key:
            _USER_CACHE[str(doc["id"])] = (dict(doc), now)
        return doc
    return None


def get_user_by_email(email: str) -> dict | None:
    return get_collection("users").find_one({"email": email})


def update_user(user_id: str, updates: dict) -> dict | None:
    if not user_id:
        return None
    invalidate_user_cache(user_id)
    col = get_collection("users")
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


def update_user_prefs(user_id: str, prefs: dict) -> dict | None:
    return update_user(user_id, {"paymentPrefs": prefs})


# ── Investigations ──
def save_investigation(inv: dict) -> None:
    col = get_collection("investigations")
    doc = dict(inv)
    doc["_id"] = doc["id"]
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)


def save_evidence_request(record: dict) -> None:
    """Persist a direct evidence request and its result in MongoDB."""
    doc = dict(record)
    request_id = doc.get("requestId") or doc.get("id")
    if not request_id:
        raise ValueError("Evidence request requires a requestId")
    doc["_id"] = request_id
    get_collection("evidence_requests").replace_one({"_id": request_id}, doc, upsert=True)


def store_upload_file(data: bytes, filename: str, mime: str, case_id: str) -> str:
    """Store an upload in MongoDB GridFS and return a stable file reference."""
    database = get_db()
    try:
        file_id = GridFS(database).put(
            data,
            filename=filename,
            contentType=mime,
            metadata={"caseId": case_id, "size": len(data)},
        )
        return f"gridfs:{file_id}"
    except TypeError:
        # mongomock does not satisfy GridFS's strict Database type check.
        # Keep tests and lightweight local environments MongoDB-only by using
        # a binary document with the same stable reference behavior.
        file_id = ObjectId()
        database["uploads"].insert_one({
            "_id": file_id, "filename": filename, "contentType": mime,
            "caseId": case_id, "size": len(data), "data": data,
        })
        return f"mongo:{file_id}"


def read_upload_file(file_id: str) -> tuple[bytes, str] | None:
    """Read a GridFS upload by its stable ``gridfs:<id>`` reference."""
    database = get_db()
    try:
        if file_id.startswith("gridfs:"):
            grid_file = GridFS(database).get(ObjectId(file_id.removeprefix("gridfs:")))
            return grid_file.read(), str(grid_file.content_type or "application/octet-stream")
        if file_id.startswith("mongo:"):
            doc = database["uploads"].find_one({"_id": ObjectId(file_id.removeprefix("mongo:"))})
            return (bytes(doc["data"]), str(doc.get("contentType") or "application/octet-stream")) if doc else None
        return None
    except Exception:
        return None


def delete_uploads_for_case(case_id: str) -> None:
    """Delete GridFS uploads belonging to a case."""
    database = get_db()
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


def get_investigation(inv_id: str) -> dict | None:
    doc = get_collection("investigations").find_one({"_id": inv_id})
    return doc


def get_investigation_with_payments(inv_id: str) -> dict | None:
    """Return the investigation with economicSummary computed from settled payments.

    The x402 middleware saves the payment record after the route handler
    returns, so economicSummary cannot be computed during finalization.
    This function is called by the GET endpoint where the payment is already
    persisted.
    """
    inv = get_investigation(inv_id)
    if not inv:
        return None
    payments = get_payments_for_investigation(inv_id)
    settled = [p for p in payments if p.get("status") == "settled"]
    capability_fee = sum(float(p.get("amount") or 0) for p in settled)
    existing = inv.get("economicSummary") or {}
    inv["economicSummary"] = {
        **existing,
        "totalSpend": round(capability_fee, 6),
        "capabilityFeeUsdc": round(capability_fee, 6),
        "settlementStatus": "Settled" if capability_fee > 0 else "Pending",
        "paymentReferences": [p.get("settlementRef") for p in settled if p.get("settlementRef")],
    }
    return inv



def list_investigations(limit: int = 50, user_id: str | None = None) -> list[dict]:
    if not user_id:
        return []
    return (
        list(get_collection("investigations")
             .find({"userId": user_id})
             .sort("createdAt", -1)
             .limit(limit))
    )


def get_investigation_by_idempotency_key(idempotency_key: str, user_id: str) -> dict | None:
    return get_collection("investigations").find_one({"idempotencyKey": idempotency_key, "userId": user_id})


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
    col = get_collection("payments")
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
    # A settled payment is unique per settlement ref: replaying the same tx
    # (idempotent acquire retry) must never double-count spend.
    if ref:
        col.update_many(
            {"settlementRef": ref, "userId": rec.get("userId"), "_id": {"$ne": _id}},
            {"$set": {"_id": _id}},
        )


def get_payment_by_settlement_ref(ref: str, user_id: str) -> dict | None:
    if not ref:
        return None
    doc = get_collection("payments").find_one(
        {"$or": [{"settlementRef": ref}, {"transactionId": ref}], "userId": user_id}
    )
    if not doc:
        return None
    return to_payment_record(doc)


def list_payments(limit: int = 10000) -> list[dict]:
    return [
        to_payment_record(d)
        for d in get_collection("payments").find().sort("createdAt", -1).limit(limit)
    ]


def get_user_payments(user_id: str) -> list[dict]:
    return [
        to_payment_record(d)
        for d in get_collection("payments").find({"userId": user_id}).sort("createdAt", -1)
    ]


def get_payments_for_investigation(investigation_id: str) -> list[dict]:
    return [
        to_payment_record(d)
        for d in get_collection("payments").find({"investigationId": investigation_id}).sort("createdAt", -1)
    ]


# ── Sessions & Resets ──
def create_session(session: dict) -> None:
    doc = dict(session)
    doc["_id"] = doc["id"]
    get_collection("sessions").insert_one(doc)
    # Mirror mongodb TTL on the expiresAt field.
    get_collection("sessions").create_index("expiresAt", expireAfterSeconds=0)


def get_session(session_id: str) -> dict | None:
    return get_collection("sessions").find_one({"_id": session_id})


def delete_session(session_id: str) -> None:
    get_collection("sessions").delete_one({"_id": session_id})


def delete_expired_sessions() -> None:
    get_collection("sessions").delete_many({"expiresAt": {"$lt": utcnow_iso()}})


def create_reset(token: str, user_id: str) -> None:
    get_collection("resets").insert_one({
        "_id": token,
        "token": token,
        "userId": user_id,
        "createdAt": utcnow_iso(),
        "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "used": False,
    })


def get_reset(token: str) -> dict | None:
    return get_collection("resets").find_one({"_id": token})


def mark_reset_used(token: str) -> None:
    get_collection("resets").update_one({"_id": token}, {"$set": {"used": True}})


# ── Stats ──
def get_dashboard_stats(user_id: str) -> dict:
    col = get_collection("investigations")
    total = col.count_documents({"userId": user_id})
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    this_week = col.count_documents({"userId": user_id, "createdAt": {"$gte": week_start}})
    payments = get_user_payments(user_id)
    settled = [p for p in payments if p.get("status") == "settled"]
    total_spend = sum(float(p.get("amount") or 0) for p in settled)
    # Aggregate evidence count + avg confidence from completed investigations.
    evidence_checks = 0
    confidences = []
    cases_by_type: dict[str, int] = {}
    for inv in col.find({"userId": user_id}):
        inv_type = inv.get("inputType") or "unknown"
        cases_by_type[inv_type] = cases_by_type.get(inv_type, 0) + 1
        evidence_checks += len(inv.get("evidence") or [])
        if inv.get("confidence") is not None:
            confidences.append(float(inv["confidence"]))
    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0
    return {
        "totalInvestigations": total,
        "investigationsThisWeek": this_week,
        "evidenceChecksPurchased": evidence_checks,
        "totalSpend": total_spend,
        "averageConfidence": avg_confidence,
        "casesByType": cases_by_type,
    }