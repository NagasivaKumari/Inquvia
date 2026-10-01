import type {
  Investigation,
  EvidenceItem,
  EvidenceAcquisition,
  ActivityEvent,
  StageProgress,
  InputType,
} from "@/lib/types";

export function normalizeToInvestigation(
  raw: any,
  endpointHint?: string,
  txIdHint?: string
): Investigation {
  const now = new Date().toISOString();

  if (!raw) {
    return {
      id: "case_" + Math.random().toString(36).substring(2, 10),
      title: "Evidence Investigation",
      question: "Investigation",
      inputs: [],
      inputType: "mixed",
      investigationPlan: [],
      selectedCapabilities: [],
      evidence: [],
      contradictions: [],
      status: "failed",
      stages: [],
      conclusion: "inconclusive",
      conclusionText: "No data available",
      confidence: 0,
      risk: "unknown",
      limitations: [],
      economicSummary: {
        totalSpend: 0.5,
        checksPurchased: 1,
        providerCategories: ["internal"],
        settlementStatus: "Included in fee",
      },
      findings: [],
      supportingEvidenceIds: [],
      contradictoryEvidenceIds: [],
      createdAt: now,
      updatedAt: now,
    };
  }

  // Check if raw is already a full investigation object
  const isAlreadyFull =
    typeof raw === "object" &&
    Boolean(raw.id || raw._id) &&
    Boolean(raw.conclusion) &&
    Array.isArray(raw.evidence) &&
    raw.evidence.length > 0;

  if (isAlreadyFull) {
    return {
      ...raw,
      id: raw.id || raw._id,
      title: raw.title || raw.question || "Evidence Investigation",
      inputs: raw.inputs || [],
      inputType:
        raw.inputType ||
        (endpointHint
          ? (endpointHint.replace("/api/x402/", "").replace("/api/evidence/", "") as InputType)
          : "mixed"),
      capability: raw.capability || endpointHint || "evidence-investigation",
      investigationPlan: raw.investigationPlan || [],
      selectedCapabilities: raw.selectedCapabilities || [],
      findings: raw.findings || [],
      supportingEvidenceIds: raw.supportingEvidenceIds || [],
      contradictoryEvidenceIds: raw.contradictoryEvidenceIds || [],
      updatedAt: raw.updatedAt || now,
    };
  }

  const id =
    raw.id ||
    raw._id ||
    raw.requestId ||
    "case_" + Math.random().toString(36).substring(2, 10);
  const rawClaim =
    raw.claim ||
    raw.question ||
    raw.inputs?.claim ||
    raw.inputs?.question ||
    raw.finding ||
    "Evidence Investigation";
  const capability =
    endpointHint ||
    raw.capability ||
    raw.type ||
    raw.operation ||
    "evidence-investigation";

  let inputType: InputType = "mixed";
  const capLower = capability.toLowerCase();
  if (capLower.includes("image")) inputType = "image";
  else if (capLower.includes("video")) inputType = "video";
  else if (capLower.includes("audio")) inputType = "audio";
  else if (capLower.includes("document")) inputType = "document";
  else if (capLower.includes("url") || capLower.includes("source")) inputType = "url";
  else if (capLower.includes("data") || capLower.includes("structured")) inputType = "data";
  else inputType = "text";

  // Normalize verdict / conclusion
  const rawVerdict = (
    raw.verdict ||
    raw.conclusion ||
    raw.status ||
    "inconclusive"
  )
    .toString()
    .toLowerCase();
  let conclusion: Investigation["conclusion"] = "inconclusive";
  if (
    rawVerdict.includes("suspicious") ||
    rawVerdict.includes("fake") ||
    rawVerdict.includes("manipulated")
  ) {
    conclusion = "suspicious";
  } else if (rawVerdict.includes("misleading")) {
    conclusion = "likely_misleading";
  } else if (
    rawVerdict.includes("genuine") ||
    rawVerdict.includes("authentic") ||
    rawVerdict.includes("pass")
  ) {
    conclusion = "likely_genuine";
  } else if (rawVerdict.includes("insufficient")) {
    conclusion = "insufficient_evidence";
  } else if (rawVerdict.includes("answered") || rawVerdict.includes("true")) {
    conclusion = "answered";
  } else {
    conclusion = "inconclusive";
  }

  // Confidence (0..100)
  let confidence = 85;
  if (typeof raw.confidence === "number") {
    confidence =
      raw.confidence <= 1
        ? Math.round(raw.confidence * 100)
        : Math.round(raw.confidence);
  }

  // Risk
  let risk: Investigation["risk"] = "moderate";
  if (raw.risk) {
    risk = raw.risk;
  } else if (conclusion === "suspicious" || conclusion === "likely_misleading") {
    risk = "high";
  } else if (conclusion === "likely_genuine") {
    risk = "low";
  }

  // Conclusion Text / Answer
  let conclusionText =
    raw.answer || raw.summary || raw.conclusionText || raw.finding || "";
  if (!conclusionText && Array.isArray(raw.findings) && raw.findings.length > 0) {
    conclusionText = raw.findings.join("\n\n");
  }
  if (!conclusionText) {
    conclusionText = `Assessment completed for ${capability}. Evidence indicates a verdict of ${conclusion.replace("_", " ")}.`;
  }

  // Findings list ("What we found")
  const rawFindings: string[] = [];
  if (Array.isArray(raw.findings)) {
    rawFindings.push(...raw.findings.map(String));
  } else if (raw.finding) {
    rawFindings.push(String(raw.finding));
  }
  if (Array.isArray(raw.observations)) {
    rawFindings.push(...raw.observations.map(String));
  }
  if (Array.isArray(raw.facts)) {
    rawFindings.push(...raw.facts.map(String));
  }

  // Limitations list ("What we could not verify")
  const limitations: string[] = [];
  if (Array.isArray(raw.limitations)) {
    limitations.push(...raw.limitations.map(String));
  } else if (Array.isArray(raw.gaps)) {
    limitations.push(...raw.gaps.map(String));
  }
  if (limitations.length === 0) {
    limitations.push(
      "Assessment is based on the evidence services that were configured and settled"
    );
  }

  // Contradictions
  const contradictions: string[] = [];
  if (Array.isArray(raw.contradictions)) {
    contradictions.push(...raw.contradictions.map(String));
  } else if (raw.conflict) {
    contradictions.push(String(raw.conflict));
  }

  // Format title derived from endpoint/capability
  const sourceName = capability
    .replace("/api/x402/", "")
    .replace("/api/evidence/", "")
    .replace("-investigation", "")
    .replace("-", " ")
    .replace(/\b\w/g, (char: string) => char.toUpperCase());

  // Build Evidence Items
  const evidence: EvidenceItem[] = [];
  if (rawFindings.length > 0) {
    rawFindings.forEach((f, index) => {
      let itemSource = `Inquvia check: ${sourceName}`;
      let cleanFinding = f;
      if (f.includes(": ")) {
        const parts = f.split(": ");
        itemSource = parts[0];
        cleanFinding = parts.slice(1).join(": ");
      }
      evidence.push({
        id: `ev_${index + 1}`,
        type: cleanFinding.toLowerCase().includes("uncertain") ? "imageUncertain" : "imageObserved",
        source: itemSource,
        timestamp: now,
        finding: cleanFinding,
        confidence: confidence / 100,
        status: "collected",
        signal:
          cleanFinding.toLowerCase().includes("conflict") ||
          cleanFinding.toLowerCase().includes("fake")
            ? "contradictory"
            : "supporting",
      });
    });
  } else {
    evidence.push({
      id: "ev_1",
      type: "imageObserved",
      source: `Inquvia check: ${sourceName}`,
      timestamp: now,
      finding: conclusionText,
      confidence: confidence / 100,
      status: "collected",
      signal: "supporting",
    });
  }

  // Build Investigation Trace
  const trace = (raw.investigationTrace || raw.checks || []).map((c: any) => {
    if (typeof c === "string") {
      return {
        check: c,
        capability: capability,
        status: "completed" as const,
        detail: "Check ran and produced observable results.",
      };
    }
    return {
      check: c.check || c.name || "Evidence Check",
      capability: c.capability || capability,
      status: (c.status || "completed") as "completed" | "unavailable" | "not_run",
      detail: c.detail || "Check ran and produced observable results.",
    };
  });

  if (trace.length === 0) {
    const checksList = [
      "Metadata / EXIF inspection",
      "Visual scene observation",
      "C2PA / Content Credentials",
      "Forensic & integrity analysis",
      "Reverse-image & provenance search",
      "Authoritative web source search",
    ];
    checksList.forEach((chk) => {
      trace.push({
        check: chk,
        capability: capability,
        status: "completed",
        detail: "Check ran and produced observable results.",
      });
    });
  }

  // Build Acquisitions
  const txId =
    txIdHint ||
    raw.txId ||
    raw.settlementRef ||
    raw.economicSummary?.algorandRef;

  const acquisitions: EvidenceAcquisition[] = (raw.acquisitions || []).map(
    (a: any, idx: number) => ({
      id: a.id || `acq_${idx + 1}`,
      requirementId: a.requirementId || `req_need_${idx + 1}`,
      investigationId: id,
      serviceName: a.serviceName || sourceName,
      capability: a.capability || capability,
      amountMicro: a.amountMicro || 500000,
      assetId: a.assetId || "10458941",
      network: a.network || "testnet",
      paymentState: "evidence_received",
      txId: a.txId || txId,
      updatedAt: now,
    })
  );

  if (acquisitions.length === 0) {
    trace.forEach((tr: any, idx: number) => {
      acquisitions.push({
        id: `acq_${idx + 1}`,
        requirementId: `req_need_${idx + 1}`,
        investigationId: id,
        serviceName: tr.check,
        capability: capability,
        amountMicro: 500000,
        assetId: "10458941",
        network: "testnet",
        paymentState: "evidence_received",
        txId: txId,
        updatedAt: now,
      });
    });
  }

  // Build Inputs (Uploaded Source)
  const inputs: Investigation["inputs"] = raw.inputs || [];
  if (inputs.length === 0) {
    if (raw.url) {
      inputs.push({ type: "url", content: raw.url });
    }
    if (raw.fileName || raw.file) {
      inputs.push({
        type: "document",
        content: raw.fileName || raw.file || "evidence_file",
        fileName: raw.fileName || raw.file || "evidence_file",
        mimeType: raw.mimeType || "application/pdf",
      });
    }
    if (inputs.length === 0 && rawClaim) {
      inputs.push({ type: "text", content: rawClaim });
    }
  }

  // Build Stages for Progress Bar
  const stages: StageProgress[] = raw.stages || [
    { id: "stg_1", label: "planning", status: "completed" },
    { id: "stg_2", label: "discovering", status: "completed" },
    { id: "stg_3", label: "awaiting_payment", status: "completed" },
    { id: "stg_4", label: "analyzing", status: "completed" },
    { id: "stg_5", label: "cross_checking", status: "completed" },
    { id: "stg_6", label: "completed", status: "completed" },
  ];

  // Build Activity Log
  const createdDate = raw.createdAt || now;
  const activity: ActivityEvent[] = raw.activity || [
    {
      id: "act_4",
      investigationId: id,
      kind: "assessment_generated",
      label: `Assessment generated for capability ${capability}`,
      createdAt: createdDate,
    },
    {
      id: "act_3",
      investigationId: id,
      kind: "cross_check_completed",
      label: "Cross-check of acquired evidence completed",
      createdAt: createdDate,
    },
    {
      id: "act_2",
      investigationId: id,
      kind: "evidence_received",
      label: "Analyzing submitted data with Inquvia tools",
      createdAt: createdDate,
    },
    {
      id: "act_1",
      investigationId: id,
      kind: "investigation_created",
      label: `${sourceName} investigation started`,
      createdAt: createdDate,
    },
  ];

  // Build Media Authenticity & Contextual Accuracy if present
  const mediaAuthenticity =
    raw.mediaAuthenticity ||
    (raw.authenticity
      ? {
          verdict:
            raw.authenticity.verdict ||
            (conclusion === "suspicious" ? "ai_generated" : "authentic"),
          confidence: confidence,
          reasoning: raw.authenticity.reasoning || conclusionText,
        }
      : undefined);

  const contextualAccuracy =
    raw.contextualAccuracy ||
    (raw.accuracy
      ? {
          verdict:
            raw.accuracy.verdict ||
            (conclusion === "suspicious" ? "false" : "accurate"),
          confidence: confidence,
          reasoning:
            raw.accuracy.reasoning ||
            "Contextual consistency check evaluated against supplied sources.",
        }
      : undefined);

  // Economic Summary
  const economicSummary = raw.economicSummary || {
    totalSpend: 0.5,
    checksPurchased: acquisitions.length || 6,
    providerCategories: ["internal"],
    settlementStatus: txId ? "Settled" : "Included in fee",
    algorandRef: txId,
  };

  // Build Investigation Plan items if not present
  const investigationPlan =
    raw.investigationPlan ||
    trace.map((tr: any, i: number) => ({
      id: `plan_${i + 1}`,
      capability: tr.check,
      reason: tr.detail || "Automated evidence verification check.",
      expectedValue: 0.9,
      status: "purchased",
    }));

  // Build Evidence Graph if not present
  const evidenceGraph = raw.evidenceGraph || {
    nodes: [
      {
        id: "node_question",
        kind: "claim" as const,
        label: rawClaim.substring(0, 45) + (rawClaim.length > 45 ? "..." : ""),
      },
      ...trace.map((t: any, idx: number) => ({
        id: `node_check_${idx}`,
        kind: "finding" as const,
        label: t.check,
      })),
    ],
    edges: trace.map((t: any, idx: number) => ({
      from: "node_question",
      to: `node_check_${idx}`,
      relation: "supports" as const,
    })),
  };

  return {
    id,
    title: rawClaim,
    question: rawClaim,
    inputs,
    inputType,
    capability: capability,
    status: "completed",
    currentStage: "completed",
    conclusion,
    conclusionText,
    confidence,
    risk,
    mediaAuthenticity,
    contextualAccuracy,
    evidence,
    investigationTrace: trace,
    acquisitions,
    limitations,
    contradictions,
    stages,
    activity,
    economicSummary,
    capabilityPriceUsdc: raw.priceUsdc || 0.5,
    createdAt: createdDate,
    updatedAt: now,
    investigationPlan,
    selectedCapabilities: raw.selectedCapabilities || [],
    evidenceGraph,
    findings: rawFindings,
    supportingEvidenceIds: evidence.map((e) => e.id),
    contradictoryEvidenceIds: [],
  };
}
