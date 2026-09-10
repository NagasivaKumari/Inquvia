"""Evidence requirement planning (mirrors investigation/planner.ts)."""

CAPABILITY_BANK = {
    "image_provenance": {"capability": "image_provenance", "reason": "Determine where and when the image originates", "type": "image"},
    "source_verify": {"capability": "source_verify", "reason": "Verify the credibility and identity of the source", "type": "url"},
    "reverse_image": {"capability": "reverse_image", "reason": "Search for prior occurrences of the image across indices", "type": "image"},
    "image_metadata": {"capability": "image_metadata", "reason": "Inspect EXIF and metadata for consistency", "type": "image"},
    "video_analysis": {"capability": "video_analysis", "reason": "Analyze video content for manipulation or context", "type": "video"},
    "frame_evidence": {"capability": "frame_evidence", "reason": "Extract and verify key frames from the video", "type": "video"},
    "domain_lookup": {"capability": "domain_lookup", "reason": "Check domain registration, WHOIS and DNS telemetry", "type": "url"},
    "ssl_scan": {"capability": "ssl_scan", "reason": "Validate SSL certificate and security posture", "type": "url"},
    "content_extract": {"capability": "content_extract", "reason": "Extract and verify page content", "type": "url"},
    "claim_support": {"capability": "claim_support", "reason": "Find supporting evidence for the claim", "type": "text"},
    "contradictory_evidence": {"capability": "contradictory_evidence", "reason": "Find evidence that contradicts the claim", "type": "text"},
    "original_source": {"capability": "original_source", "reason": "Locate the original source of the claim", "type": "text"},
    "independent_source": {"capability": "independent_source", "reason": "Locate independent corroborating sources", "type": "text"},
    "data_consistency": {"capability": "data_consistency", "reason": "Validate structured data for consistency", "type": "data"},
    "document_verify": {"capability": "document_verify", "reason": "Verify document authenticity and issuer", "type": "document"},
    "audio_transcription": {"capability": "audio_transcription", "reason": "Transcribe and inspect the audio recording", "type": "audio"},
}


def plan_evidence_requirements(question: str, inputs: list[str]) -> list[dict]:
    seen = set()
    result = []

    def add(key):
        if key in seen:
            return
        seen.add(key)
        cap = CAPABILITY_BANK.get(key)
        if not cap:
            return
        result.append({
            "id": f"req_{len(seen)}_{key}",
            "type": cap["type"],
            "capability": cap["capability"],
            "reason": cap["reason"],
        })

    q = question.lower()
    types = set(inputs)

    if "image" in types or any(w in q for w in ("image", "photo", "picture")):
        add("image_provenance")
        add("source_verify")
        add("reverse_image")
        if not any(w in q for w in ("image", "photo")) or "image" in types:
            add("image_metadata")
    elif "video" in types or any(w in q for w in ("video", "footage", "clip")):
        add("video_analysis")
        add("frame_evidence")
        add("source_verify")
        add("image_metadata")
    elif "document" in types or any(w in q for w in ("document", "pdf", "file")):
        add("document_verify")
        add("source_verify")
    elif "data" in types or any(w in q for w in ("data", "dataset", "json", "csv")):
        add("data_consistency")
        add("source_verify")

    if any(w in q for w in ("http", "url", "website", "site", "domain", "seller", "store")) or "url" in types:
        add("domain_lookup")
        add("ssl_scan")
        add("content_extract")
        add("source_verify")

    add("original_source")
    add("claim_support")
    add("independent_source")
    if any(w in q for w in ("fake", "misleading", "scam", "genuine", "authentic", "true")):
        add("contradictory_evidence")

    return [{**r, "id": f"req_{i + 1}"} for i, r in enumerate(result[:6])]


def _make_planner(keys):
    def plan(question, inputs, force=()):
        seen = set()
        result = []

        def add(key):
            if key in seen:
                return
            seen.add(key)
            cap = CAPABILITY_BANK.get(key)
            if not cap:
                return
            result.append({
                "id": f"req_{len(seen)}_{key}",
                "type": cap["type"],
                "capability": cap["capability"],
                "reason": cap["reason"],
            })

        for key in list(force) + list(keys):
            add(key)
        return result[:6]

    return plan


plan_claim_requirements = _make_planner(["original_source", "claim_support", "independent_source", "contradictory_evidence"])
plan_image_requirements = _make_planner(["image_provenance", "reverse_image", "image_metadata", "source_verify"])
plan_video_requirements = _make_planner(["video_analysis", "frame_evidence", "image_metadata", "source_verify"])
plan_document_requirements = _make_planner(["document_verify", "source_verify"])
plan_source_requirements = _make_planner(["domain_lookup", "ssl_scan", "content_extract", "source_verify"])
plan_data_requirements = _make_planner(["data_consistency", "source_verify"])
plan_audio_requirements = _make_planner(["audio_transcription", "source_verify"])