"""Batch image investigation — dHash clustering and duplicate detection."""
from __future__ import annotations

from ..libraries import image_forensics
from ..libraries.image_check_utils import load_input_bytes, input_label


def _hamming(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 999
    return sum(c1 != c2 for c1, c2 in zip(a, b))


def cluster_images(inputs: list[dict], *, threshold: int = 8) -> dict:
    """Cluster submitted images by perceptual hash proximity."""
    records = []
    for i, inp in enumerate(inputs):
        data = load_input_bytes(inp)
        if not data:
            continue
        h = image_forensics.perceptual_hash(data)
        records.append({
            "index": i,
            "label": input_label(inp, f"image_{i + 1}"),
            "fileName": inp.get("fileName"),
            "filePath": inp.get("filePath"),
            "perceptualHash": h,
        })

    clusters: list[dict] = []
    assigned = set()

    for i, rec in enumerate(records):
        if i in assigned:
            continue
        cluster = [rec]
        assigned.add(i)
        for j, other in enumerate(records):
            if j in assigned or j <= i:
                continue
            dist = _hamming(rec["perceptualHash"], other["perceptualHash"])
            if dist <= threshold:
                cluster.append({**other, "hammingDistance": dist})
                assigned.add(j)
        clusters.append({
            "clusterId": len(clusters) + 1,
            "memberCount": len(cluster),
            "members": cluster,
            "suspiciousDuplicateCluster": len(cluster) > 1,
        })

    duplicate_clusters = [c for c in clusters if c["memberCount"] > 1]
    return {
        "imageCount": len(records),
        "clusterCount": len(clusters),
        "duplicateClusterCount": len(duplicate_clusters),
        "clusters": clusters,
        "threshold": threshold,
        "note": (
            "Clusters group near-duplicate images by dHash — not semantic similarity. "
            "Cross-cluster images may still be related."
        ),
    }


def describe(result: dict) -> str:
    if not result:
        return ""
    lines = [
        f"BATCH ANALYSIS: {result.get('imageCount')} images, "
        f"{result.get('clusterCount')} cluster(s), "
        f"{result.get('duplicateClusterCount')} duplicate cluster(s):",
    ]
    for c in result.get("clusters") or []:
        if c.get("memberCount", 0) <= 1:
            continue
        labels = ", ".join(m.get("label", "?") for m in c.get("members") or [])
        lines.append(f"- cluster {c['clusterId']}: {c['memberCount']} near-duplicate(s) — {labels}")
    return "\n".join(lines)
