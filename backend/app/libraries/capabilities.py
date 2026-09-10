"""Capability orchestration + run handlers (mirrors investigation/capabilities/*)."""
from .. import db
from ..libraries import engine
from ..libraries import web_inspector


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

    return await engine.discover_and_acquire(inv["id"], args.get("userId") or "")


async def run_claim_investigation(args):
    question = (args.get("question") or "").strip() or "Investigate this claim"
    from ..libraries.planner import plan_claim_requirements
    return await run_capability(
        "claim-investigation", args, plan_claim_requirements(question, ["text"]),
        "Claim Investigation",
    )


async def run_image_investigation(args):
    question = (args.get("question") or "").strip()
    from ..libraries.planner import plan_image_requirements
    return await run_capability(
        "image-investigation", args, plan_image_requirements(question, ["image"]),
        "Image Investigation",
    )


async def run_video_investigation(args):
    question = (args.get("question") or "").strip()
    from ..libraries.planner import plan_video_requirements
    return await run_capability(
        "video-investigation", args, plan_video_requirements(question, ["video"]),
        "Video Investigation",
    )


async def run_document_investigation(args):
    question = (args.get("question") or "").strip()
    from ..libraries.planner import plan_document_requirements
    return await run_capability(
        "document-investigation", args, plan_document_requirements(question, ["document"]),
        "Document Investigation",
    )


async def run_source_investigation(args):
    url_input = next((i for i in (args.get("inputs") or []) if i.get("type") == "url"), None)
    if not url_input or not url_input.get("content"):
        raise InputError("source-investigation requires a valid URL")
    inputs = [{"type": "url", "content": url_input["content"]}]
    question = (args.get("question") or "").strip() or f"Analyze the source: {url_input['content']}"

    inspection = await web_inspector.inspect_live_url(url_input["content"])

    from ..libraries.planner import plan_source_requirements

    def before(pending):
        if inspection:
            pending["webInspection"] = inspection
            pending.setdefault("sourcesUsed", []).insert(0, url_input["content"])

    return await run_capability(
        "source-investigation", {**args, "inputs": inputs}, plan_source_requirements(question, ["url"]),
        "Source Investigation", before,
    )


async def run_data_investigation(args):
    question = (args.get("question") or "").strip()
    from ..libraries.planner import plan_data_requirements
    return await run_capability(
        "data-investigation", args, plan_data_requirements(question, ["data"]),
        "Data Investigation",
    )


async def run_audio_investigation(args):
    question = (args.get("question") or "").strip()
    from ..libraries.planner import plan_audio_requirements
    return await run_capability(
        "audio-investigation", args, plan_audio_requirements(question, ["audio"]),
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