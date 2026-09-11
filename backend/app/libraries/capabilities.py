"""Capability orchestration + run handlers (mirrors investigation/capabilities/*)."""
from .. import db
from ..libraries import engine
from ..libraries import web_inspector
from ..libraries import evidence_checks
from ..libraries import planner


class InputError(Exception):
    pass


def _req_type(capability_or_reason):
    c = capability_or_reason
    if "image" in c:
        return "image"
    if "video" in c:
        return "video"
    if "document" in c:
        return "document"
    if "url" in c or "domain" in c:
        return "url"
    if "data" in c:
        return "data"
    return "text"


async def run_capability(capability_id, args, requirements, title, before_discover=None):
    inv = engine.start_capability_investigation({
        "id": args["id"], "userId": args.get("userId"), "question": args["question"],
        "inputs": args.get("inputs") or [], "capability": capability_id, "title": title,
        "idempotencyKey": args.get("idempotencyKey"),
    })

    reqs = [
        {"id": f"req_{i + 1}", "type": _req_type(r.get("capability")),
         "capability": r.get("capability"), "reason": r.get("reason")}
        for i, r in enumerate(requirements)
    ]
    engine.plan_capability(inv, reqs)

    if before_discover:
        pending = db.get_investigation(inv["id"])
        before_discover(pending)
        db.save_investigation(pending)

    # Run the planned evidence checks against the submission so the analysis
    # and report are grounded in real acquired observations.
    inv = db.get_investigation(inv["id"])
    await evidence_checks.run_evidence_checks(inv)

    return await engine.analyze_investigation(inv["id"])


async def run_claim_investigation(args):
    question = (args.get("question") or "").strip() or "Investigate this claim"
    reqs = await planner.plan_dynamic_requirements(question, ["text"])
    return await run_capability(
        "claim-investigation", args, reqs,
        "Claim Investigation",
    )


async def run_image_investigation(args):
    question = (args.get("question") or "").strip()
    reqs = await planner.plan_dynamic_requirements(question, ["image"])
    return await run_capability(
        "image-investigation", args, reqs,
        "Image Investigation",
    )


async def run_video_investigation(args):
    question = (args.get("question") or "").strip()
    reqs = await planner.plan_dynamic_requirements(question, ["video"])
    background_tasks = args.get("background_tasks")
    
    # Initialize with 'queued' status
    inv = engine.start_capability_investigation({
        "id": args["id"], "userId": args.get("userId"), "question": args["question"],
        "inputs": args.get("inputs") or [], "capability": "video-investigation", "title": "Video Investigation",
        "idempotencyKey": args.get("idempotencyKey"),
    })
    inv["status"] = "queued"
    db.save_investigation(inv)
    
    if background_tasks:
        background_tasks.add_task(run_video_investigation_async, inv["id"], reqs)
    else:
        # Fallback if no background tasks (e.g. tests)
        await run_video_investigation_async(inv["id"], reqs)
    
    return inv


async def run_video_investigation_async(inv_id: str, reqs: list):
    try:
        inv = db.get_investigation(inv_id)
        if not inv:
            return
        
        inv["status"] = "processing"
        db.save_investigation(inv)
        
        # Original processing logic from run_capability
        engine.plan_capability(inv, reqs)
        
        inv = db.get_investigation(inv_id)
        await evidence_checks.run_evidence_checks(inv)
        await engine.analyze_investigation(inv_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        inv = db.get_investigation(inv_id)
        if inv:
            inv["status"] = "failed"
            inv["limitations"] = [f"Processing failed: {str(e)}"]
            db.save_investigation(inv)


async def run_document_investigation(args):
    question = (args.get("question") or "").strip()
    reqs = await planner.plan_dynamic_requirements(question, ["document"])
    return await run_capability(
        "document-investigation", args, reqs,
        "Document Investigation",
    )


async def run_source_investigation(args):
    url_input = next((i for i in (args.get("inputs") or []) if i.get("type") == "url"), None)
    if not url_input or not url_input.get("content"):
        raise InputError("source-investigation requires a valid URL")
    inputs = [{"type": "url", "content": url_input["content"]}]
    question = (args.get("question") or "").strip() or f"Analyze the source: {url_input['content']}"

    inspection = await web_inspector.inspect_live_url(url_input["content"])

    reqs = await planner.plan_dynamic_requirements(question, ["url"])

    def before(pending):
        if inspection:
            pending["webInspection"] = inspection
            pending.setdefault("sourcesUsed", []).insert(0, url_input["content"])

    return await run_capability(
        "source-investigation", {**args, "inputs": inputs}, reqs,
        "Source Investigation", before,
    )


async def run_data_investigation(args):
    question = (args.get("question") or "").strip()
    reqs = await planner.plan_dynamic_requirements(question, ["data"])
    return await run_capability(
        "data-investigation", args, reqs,
        "Data Investigation",
    )


async def run_audio_investigation(args):
    question = (args.get("question") or "").strip()
    reqs = await planner.plan_dynamic_requirements(question, ["audio"])
    return await run_capability(
        "audio-investigation", args, reqs,
        "Audio Investigation",
    )


CAPABILITY_RUNNERS = {
    "claim-investigation": run_claim_investigation,
    "image-investigation": run_image_investigation,
    "video-investigation": run_video_investigation,
    "document-investigation": run_document_investigation,
    "source-investigation": run_source_investigation,
    "data-investigation": run_data_investigation,
    "audio-investigation": run_audio_investigation,
}