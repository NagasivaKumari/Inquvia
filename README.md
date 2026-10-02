<div align="center">

<img src="public/logo.jpeg" alt="Inquvia" width="160" />

# Inquvia

**Autonomous Evidence Investigation powered by Algorand + x402**

[Application](https://inquvia.vercel.app/) · [API](https://inquvia.onrender.com) · [GitHub](https://github.com/NagasivaKumari/Inquvia) · [Bazaar](https://facilitator.goplausible.xyz/dashboard/merchants/0dc0511dd349c8fe)

</div>

---

## 1. What is Inquvia?

Inquvia is an evidence investigation platform designed for questions where a simple AI-generated answer is not enough.

Instead of only generating a conclusion, Inquvia acquires and analyzes evidence, selects relevant investigation checks, cross-checks evidence, identifies contradictions and gaps, and produces an evidence-backed result with confidence, provenance, and limitations.

It turns an investigation question into a structured evidence workflow:

```text
Question
   ↓
Determine what evidence is needed
   ↓
Select relevant evidence services
   ↓
Acquire evidence
   ↓
Analyze and cross-check
   ↓
Detect contradictions / duplicates / dependencies
   ↓
Identify evidence gaps
   ↓
Evaluate support and confidence
   ↓
Investigation report
```

The goal is not to claim absolute truth.

The goal is to show:

- what the available evidence supports,
- what evidence conflicts,
- what evidence is missing,
- how confident the investigation is,
- and what limitations remain.

---

## 2. The Problem

AI systems are increasingly capable of producing convincing answers, but the underlying evidence may be incomplete, conflicting, duplicated, outdated, manipulated, or unavailable.

Evidence is often distributed across different formats and sources:

- Images
- Videos
- Audio
- Documents
- URLs and web pages
- Structured data
- Claims and supplied evidence

Manually investigating all of these sources is slow and difficult to scale.

Inquvia is designed to make that investigation process systematic.

---

## 3. The Solution

Inquvia provides a set of specialized evidence services and an investigation planner.

A user asks a question and provides the available source material. Inquvia determines which checks are relevant instead of requiring the user to manually run every service.

The investigation can combine multiple evidence types and analytical checks before producing the final result.

### Core principles

**Evidence first**  
Conclusions should be grounded in acquired evidence.

**Cross-checking**  
Important findings are compared across available evidence.

**Explicit uncertainty**  
Uncertainty and limitations are surfaced instead of being hidden.

**Traceability**  
The investigation report keeps the relationship between findings and their source evidence visible.

**Adaptive investigation**  
The planner can select additional checks when the available evidence is not sufficient.

---

## 4. Evidence Services

Inquvia currently provides **12 evidence investigation services**.

| Service | ID | Purpose |
|---|---|---|
| Image Evidence | `evidence-image` | Extract and analyze evidence from an image |
| Video Evidence | `evidence-video` | Extract and analyze evidence from a video |
| URL Evidence | `evidence-url` | Inspect and analyze a public source URL |
| Document Evidence | `evidence-document` | Extract and analyze evidence from a document |
| Structured Evidence | `evidence-structured` | Analyze structured JSON/CSV-style data sources |
| Audio Evidence | `evidence-audio` | Extract and analyze evidence from audio |
| Evidence Assessment | `evidence-assess` | Assess a claim against supplied evidence |
| Contradictions | `evidence-contradictions` | Find conflicting claims or evidence |
| Duplicate Analysis | `evidence-duplicates` | Identify duplicate or dependent evidence |
| Timeline | `evidence-timeline` | Reconstruct a timeline from supplied evidence |
| Authenticity | `evidence-authenticity` | Report forensic consistency signals for media |
| Evidence Gaps | `evidence-gaps` | Identify missing evidence and unresolved questions |

These services are intentionally different investigation primitives.

For example:

- **Video Evidence** asks what can be established from the video content.
- **Authenticity** focuses on forensic consistency and manipulation-related signals.
- **Contradictions** looks for conflicts between evidence.
- **Duplicate Analysis** checks whether apparently independent evidence is actually duplicated or dependent.
- **Evidence Gaps** identifies what is still missing.

A single investigation may use several of these services when the question requires it.

---

## 5. Example Investigation

A question such as:

> **"Does this uploaded video provide enough evidence to support the claim?"**

may result in a workflow such as:

```text
Video Evidence
      ↓
Timestamped visual observations
      +
Audio / transcript evidence
      ↓
Evidence Assessment
      ↓
Contradiction Check
      ↓
Evidence Gaps
      ↓
Confidence + Limitations
      ↓
Final Investigation Report
```

The exact checks are selected according to the investigation requirements.

---

## 6. Investigation Output

An investigation result is designed to contain more than a single AI answer.

A typical result includes:

- Investigation question
- Sources and uploaded inputs
- Selected evidence checks
- Evidence findings
- Supporting evidence
- Contradictory evidence
- Duplicate/dependency relationships
- Timeline information where relevant
- Evidence gaps
- Confidence
- Provenance
- Limitations
- Economic/payment information
- Final conclusion

The source remains distinguishable from extracted evidence and AI interpretation.

---

## 7. AI Investigation Planner

Inquvia includes an investigation planner that determines which evidence capabilities are relevant to a question.

Conceptually:

```text
User Question
      ↓
Planner
      ↓
Evidence Requirements
      ↓
Relevant Services
      ↓
Acquisition
      ↓
Analysis
      ↓
Cross-checking
      ↓
Sufficient Evidence?
   ┌───────┴───────┐
   │               │
  YES              NO
   │               │
 Stop         Acquire more
   │           evidence
   └───────┬───────┘
           ↓
   Final Investigation
```

The planner is intended to avoid blindly running every available check.

---

## 8. x402 + Algorand

Inquvia uses **x402 on Algorand** for pay-per-request access to evidence services.

The payment layer allows an evidence resource to be exposed as a paid service rather than relying on subscriptions or manual billing.

### Conceptual flow

```text
Client / User
      ↓
Inquvia
      ↓
Investigation request
      ↓
Relevant paid evidence resource
      ↓
HTTP 402 Payment Required
      ↓
x402 payment
      ↓
GoPlausible facilitator
      ↓
Algorand settlement
      ↓
Paid evidence response
      ↓
Inquvia investigation
```

The application treats payment as part of the evidence-acquisition workflow.

### Why Algorand?

Inquvia uses Algorand as the settlement network for the x402 payment flow.

The project is designed around:

- fast settlement,
- low transaction overhead,
- stablecoin payments,
- and machine-to-machine pay-per-use interactions.

### Competition configuration

For the Global x402 Challenge, the Mainnet configuration uses:

- **Network:** Algorand Mainnet
- **USDC ASA:** `31566704`
- **Facilitator:** GoPlausible
- **Discovery:** Bazaar
- **Challenge tag:** `x402-global-challenge`

---

## 9. Competition Entry Type

### **Composite Entry**

Inquvia is being submitted as a **Composite** project. The product is composed of multiple evidence services under one project, with the individual capabilities exposed as distinct resources while belonging to the same overall investigation product.

The investigation planner can select the capabilities required for a particular question.

Every capability points at **one shared `payTo` address**, so the individual endpoints are listed separately in the Bazaar but consolidate into a single merchant entry and a single leaderboard total.

### Paid capabilities

These are the x402 metered routes. All are prefixed with `/api/x402/` and return `402 Payment Required` when called without a payment.

| Capability | Endpoint | Price | Analysis |
|---|---|---|---|
| Claim | `claim-investigation` | 0.50 USDC | Cross-source verification, contradiction detection |
| Image | `image-investigation` | 0.50 USDC | EXIF forensics, C2PA credential verification, manipulation and AI-generation detection, OCR, PII, visual observation |
| Image batch | `image-batch-investigation` | 0.50 USDC | Multi-file pipeline for duplicates, clusters, and common sources |
| Video | `video-investigation` | 1.50 USDC | `ffprobe` container forensics, adaptive timestamped frame extraction, audio transcription, scene/object/person analysis, AV sync |
| Audio | `audio-investigation` | 0.50 USDC | Synthetic-voice detection, transcription, speaker consistency, forensics |
| Document | `document-investigation` | 0.50 USDC | PDF text and table extraction, structure, metadata |
| Source | `source-investigation` | 0.50 USDC | DNS, TLS, title and content extraction, Playwright rendering |
| Data | `data-investigation` | 0.50 USDC | CSV/JSON profiling, schema, statistics |

These paid capabilities are the commercial surface. The 12 evidence services in
section 4 are the internal primitives the planner draws on to fulfil them.

### Payment integrity

The gate is fail-closed. Every path to an unpaid response is closed by design.

| Situation | Result |
|---|---|
| No payment header | `402` — capability does not run |
| Payment middleware unavailable | `402` — never serves free |
| Facilitator unreachable | Payments stop; no unpaid access |
| No evidence collected | No AI verdict; insufficient-evidence result |
| Only duplicate or dependent evidence | AI skipped; evidence marked inconclusive |
| AI provider unavailable | Deterministic analysis used when evidence exists |

The price is never guessed by the AI. It comes from `INVESTIGATION_PRICE_USDC`,
the facilitator verifies the signed amount, and `/.well-known/x402` publishes the
same figures — so the discovery catalogue cannot drift from the code that charges.

The payment gate is [`backend/app/x402/gate.py`](backend/app/x402/gate.py), built
on the official `x402-avm` Python SDK using `ExactAvmServerScheme`. There is no
forked or shimmed protocol code, and no second payment path.

---

## 10. Technology Stack

The exact implementation is split into application, investigation, storage, AI, and payment layers.

### Frontend

- Next.js
- TypeScript
- Custom UI components
- Responsive investigation workspace

### Backend

- Python
- FastAPI
- REST APIs
- Investigation engine
- Evidence processing pipeline

### AI

- Provider abstraction for AI analysis
- Multimodal analysis where required
- Audio transcription
- Evidence-oriented reasoning
- Question-driven analyzers

### Evidence Processing

- Image processing
- Video frame extraction
- Audio extraction and transcription
- PDF/document extraction
- Structured-data analysis
- URL/web-source extraction
- OCR where source text is not directly available

### Storage

- Database-backed investigation records
- Source/evidence storage
- Secure source retrieval
- Investigation history and report data

### Blockchain / Payments

- Algorand
- x402
- GoPlausible facilitator
- USDC
- Bazaar discovery

---

## 11. Source and Evidence Separation

Inquvia distinguishes between:

```text
Original Source
      ↓
Extraction
      ↓
Evidence
      ↓
AI Interpretation
      ↓
Investigation Conclusion
```

This distinction is important because an AI interpretation should not be presented as though it were the original source.

Where possible, evidence retains source references such as:

- page numbers,
- timestamps,
- extracted text,
- media observations,
- source URLs,
- metadata,
- and other provenance information.


---

## 12. Evidence Analysis Features

### Contradiction Analysis

Compares evidence and identifies information that cannot be simultaneously supported.

### Duplicate / Dependency Analysis

Looks for evidence that is duplicated, copied, or dependent on the same underlying source.

### Timeline Reconstruction

Combines temporal information into a reconstructed sequence of events when timestamps are available.

### Authenticity Analysis

Reports forensic consistency signals.

This is intentionally different from claiming that content is definitively authentic or fake.

### Evidence Gaps

Identifies unresolved questions and the additional evidence that would be useful to answer them.

### Claim Assessment

Assesses a specific claim against the supplied evidence.

---

## 13. Local Development

### Prerequisites

- Node.js 20+
- Python 3.12+
- A running MongoDB instance
- `ffmpeg` on `PATH`, or set `FFMPEG_PATH` and `FFPROBE_PATH`

### Clone

```bash
git clone https://github.com/NagasivaKumari/Inquvia.git
cd Inquvia
```

### Backend

```bash
pip install -r backend/requirements.txt
playwright install chromium
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Linux, `ffmpeg` can be installed from `backend/apt.txt`. `pyzbar` additionally
requires the system `libzbar` library.

### Frontend

Run from the project root, in a separate terminal:

```bash
npm install
npm run dev          # http://localhost:3000
```

The frontend proxies `/api/*` and `/.well-known/x402` to the backend through
`next.config.ts`, defaulting to `http://127.0.0.1:8000`. Set
`NEXT_PUBLIC_API_URL` to point it elsewhere.

### Call a paid endpoint

```bash
curl -i -X POST http://localhost:8000/api/x402/claim-investigation \
  -H 'Content-Type: application/json' \
  -d '{"question":"Is this claim true?","text":"The seller promises overnight delivery."}'
```

The response is `402 Payment Required` with the challenge terms. Sign it with an
x402 client wallet, retry with the `X-PAYMENT` header, and the paid response
comes back.

---

## 14. Environment Configuration

Copy `.env.example` to `.env`. Nothing is hardcoded in the application.

```env
# x402 payment layer
INQUVIA_PAYTO_ADDRESS=<mainnet address receiving settlements>
ALGORAND_NETWORK=mainnet
ALGORAND_USDC_ASA=31566704
X402_FACILITATOR_URL=https://facilitator.goplausible.xyz
X402_CHALLENGE_TAG=x402-global-challenge
X402_PUBLIC_BASE_URL=<public https origin serving the API>
INVESTIGATION_PRICE_USDC=0.50
VIDEO_INVESTIGATION_PRICE_USDC=1.50

# Application
PUBLIC_APP_URL=<public https origin>
NEXT_PUBLIC_API_URL=<public https origin of the backend>
PORT=10000
MAX_UPLOAD_SIZE_MB=10

# Storage
MONGODB_URI=<mongodb connection string>
MONGODB_DB_NAME=Inquvia
JWT_SECRET=<strong random secret>

# AI providers — each optional, used for interpretation only
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
EXPLABS_API_KEY=
OPENAI_API_KEY=

# Optional. Unlocks only reverse image search and authoritative web search.
# Without it those two layers report "unavailable" and every other check still runs.
SERPAPI_API_KEY=

# Admin allowlists
ADMIN_EMAILS=
ADMIN_WALLETS=
```

`INQUVIA_PAYTO_ADDRESS` must stay **stable for the duration of the competition** —
it is the key the facilitator uses to attribute the leaderboard entry.

Testnet and Mainnet are selected by the same variables, only the values differ:

| | Network | USDC ASA |
|---|---|---|
| Testnet | `testnet` | `10458941` |
| Mainnet | `mainnet` | `31566704` |

The facilitator URL is identical on both.

Never commit private keys, database credentials, or API keys.

---

## 15. Running a Test Investigation

A basic local test should follow this flow:

```text
1. Start backend
2. Start frontend
3. Open the investigation workspace
4. Enter an investigation question
5. Add the required source or file
6. Submit the investigation
7. Observe selected evidence checks
8. Inspect acquired evidence
9. Review contradictions / gaps / relationships
10. Review confidence and limitations
11. Open the final investigation report
```

For x402 testing, use the configured Testnet flow before using Mainnet funds.

---

## 16. Testing

Commands that run from a fresh clone of this repository:

```bash
npm run build                                             # frontend build
python backend/demo.py                                    # offline end-to-end self-check
```

`backend/demo.py` exercises the pipeline end to end with no network access and
no USDC spend.

> The pytest suite under `backend/tests/` is developed and run locally but is
> excluded from version control by `.gitignore`, so it is not present in a fresh
> clone. Two useful checks when you have the full working tree:
>
> ```bash
> python -m pytest -p no:asyncio backend/tests/test_api.py -q
> python backend/tests/test_audit_fixes.py                  # network-free audit checks
> ```
>
> Backend tests run against `mongomock` with testnet defaults, so they never
> touch a live network or spend real USDC.

---

## 17. Live Project

**Application:**  
https://inquvia.vercel.app/

**Public API / x402 Resource:**  
https://inquvia.onrender.com

Paid capabilities are served from this origin under `/api/x402/{capability}`.
Resource discovery is published at `https://inquvia.onrender.com/.well-known/x402`.

**Bazaar Listing:**  
https://facilitator.goplausible.xyz/dashboard/merchants/0dc0511dd349c8fe

Merchant entry keyed by the `payTo` address. The individual capability resources
are listed separately in the Bazaar resource catalog.

**GitHub Repository:**  
https://github.com/NagasivaKumari/Inquvia

### Verifying a live entry

The entry is live when all of the following hold:

- the endpoint is deployed to a public HTTPS host, not localhost
- one real MainNet payment has settled end-to-end through the GoPlausible facilitator
- USDC has landed in the `payTo` address
- the endpoint appears in the Bazaar resource catalog under the `x402-global-challenge` tag
- the endpoint appears on the leaderboard with the global hackathon filter on

---

## 18. Repository Structure

A simplified view of the repository:

```text
inquvia/
├── backend/
│   ├── app/
│   │   ├── libraries/
│   │   ├── x402/
│   │   └── main.py
│   └── ...
│
├── src/
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── ...
│
├── public/
├── package.json
├── README.md
├── LICENSE
└── ...
```

---

## 19. Demonstration

The implemented Inquvia workflow takes an investigation from a user question to a traceable final report.

### End-to-end investigation

```text
User question + source
        ↓
Investigation created
        ↓
Inquvia planner determines required evidence checks
        ↓
Relevant evidence services are selected
        ↓
Evidence is extracted and acquired
        ↓
Evidence is analyzed with source references
        ↓
Evidence is cross-checked
        ↓
Contradictions / duplicates / dependencies / gaps are identified
        ↓
Confidence and limitations are calculated
        ↓
Final investigation report is generated
```

### Example: Video Investigation

A user can submit a video with a question such as:

> **"How many people are visible in the video? Give the approximate timestamps and distinguish fully visible people from partially visible people."**

Inquvia processes the video and produces an investigation containing:

```text
VIDEO
  ↓
Timestamped frame extraction
  ↓
Visual observations
  +
Audio/transcript evidence when available
  ↓
Question-driven analysis
  ↓
Evidence items with timestamps
  ↓
Support / contradiction / uncertainty signals
  ↓
Confidence + limitations
  ↓
Final answer
```

The report keeps the underlying video source available alongside the extracted observations and the final interpretation.

### Example: Document Investigation

For a document-based question, the workflow is:

```text
Document
   ↓
Text / table extraction
   ↓
OCR fallback when required
   ↓
Page-level evidence
   ↓
Question-specific analysis
   ↓
Cross-checking
   ↓
Evidence-backed result
   ↓
Final report with source references and limitations
```

### Example: Multi-check Investigation

For a question that requires more than one kind of evidence, Inquvia can combine services:

```text
Question
   ↓
Planner
   ├── Image Evidence
   ├── URL Evidence
   ├── Structured Evidence
   ├── Contradictions
   └── Evidence Gaps
          ↓
     Combined findings
          ↓
     Investigation report
```

The important point is that the user does not need to manually run all 12 services. The investigation system selects the checks that are relevant to the question.

### Payment and investigation record

The investigation is tied to its payment and activity record.

```text
Investigation request
        ↓
x402 payment
        ↓
Investigation starts
        ↓
Selected evidence checks
        ↓
Evidence + analysis
        ↓
Report
```

The report and activity view preserve the investigation result together with the recorded payment information rather than presenting payment activity as a simulated result.

---

## 20. Limitations

Inquvia is an evidence investigation system, not an absolute truth oracle.

Its conclusions depend on:

- the quality of the supplied sources,
- the availability of evidence,
- the quality of extraction,
- the quality of the analysis models,
- and the independence and reliability of external sources.

A high confidence result does not mean absolute certainty.

The system is designed to make the available evidence and remaining uncertainty visible.

---

## 21. Data & Database Architecture

Inquvia uses a Dual-Cluster MongoDB Architecture for data preservation and scalability:

```
                         INQUVIA
                            |
                         Backend
                            |
                +-----------+-----------+
                |                       |
                v                       v
        LIVE MONGODB              ARCHIVE MONGODB
        NEW CLUSTER               EXISTING CLUSTER
        (READ + WRITE)            (READ-ONLY)
                |                       |
                +-----------+-----------+
                            |
                            v
                   UNIFIED DATA LAYER
                            |
                 +----------+----------+
                 |                     |
                 v                     v
            HISTORY UI           INVESTIGATION UI
```

* **LIVE DB (`MONGODB_URI_LIVE`, `MONGODB_DB_LIVE`):** Primary writable database for new investigations, new users, evidence uploads, and ongoing operations.
* **ARCHIVE DB (`MONGODB_URI_ARCHIVE`, `MONGODB_DB_ARCHIVE`):** Protected read-only database preserving historical investigations, evidence files (GridFS), and reports. Enforced with read-only proxy safeguards.
* **Unified History:** Transparent single-view history and dashboard experience combining records seamlessly across both clusters without duplication.

---

## 22. Team

- **Nagasiva Kumari Kota**
- **Akash Kumar Guntur**

---

## 22. Acknowledgements

Built with and around:

- Algorand
- x402
- GoPlausible
- Bazaar
- Open-source AI and media-processing technologies used by the project

---

## 23. License

MIT — see [LICENSE](LICENSE).

This repository is submitted to the
[Electric Capital Open Dev Data](https://github.com/electric-capital/open-dev-data)
taxonomy under the Algorand ecosystem.

---

## 24. Contact

**Project:** Inquvia

**Website:** https://inquvia.vercel.app/

**API:** https://inquvia.onrender.com

**GitHub:** https://github.com/NagasivaKumari/Inquvia

---

## Final Note

Inquvia is built around a simple idea:

> **Don't just generate an answer. Investigate the evidence behind it.**
