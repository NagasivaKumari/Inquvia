# Inquvia

Inquvia is an evidence-acquisition agent for the Algorand x402 ecosystem. It
is designed to reduce unsupported AI answers by acquiring and tracking evidence
before producing an assessment.

## What It Does

Given a question and optional URL, file, image, video, document, or structured
data, Inquvia:

1. Selects an investigation capability and plans the evidence types required.
2. Runs deterministic forensic checks against the submitted input (C2PA
   credentials, EXIF, reverse image search, audio, video, document, structured).
3. Queries the configured AI model providers for interpretation and source
   context, routed per task.
4. Normalizes every result into a single evidence record with its source,
   citation, and confidence.
5. De-weights duplicate and explicitly dependent evidence.
6. Checks contradictions, provenance signals, missing evidence, and limitations.
7. Produces a confidence-based result or reports `evidence_unavailable` when
   there is not enough usable evidence.

Inquvia does not invent evidence when a check or model provider is unavailable.

## Architecture

```text
User input
  -> User pays Inquvia through x402/Algorand
  -> Capability-specific investigation
  -> Deterministic forensic checks
  -> AI model providers for interpretation
  -> Normalize, de-weight, contradiction checks
  -> Final report
```

### Evidence acquisition

Inquvia acquires evidence in-house. There is no third-party evidence provider
and no second payment path.

Evidence comes from two sources:

- **Deterministic checks** run locally against the input: C2PA content
  credential verification, EXIF/metadata forensics, reverse image search, audio
  and video analysis, document extraction, and structured-data computation.
- **AI model providers** configured by API key (Gemini, Groq, OpenRouter,
  EXPLABS, optional OpenAI and SerpAPI). Routing per task is defined by
  `MODEL_TASKS` in `backend/app/config.py`.

Findings from both sources are normalized into the same evidence record so
provenance and confidence survive the merge. When the AI provider is
unavailable, the deterministic analysis is used on its own.

## Payment Model

There is one x402 payment: the user to Inquvia.

### User to Inquvia

Each capability endpoint has the shared core price configured by:

```env
INVESTIGATION_PRICE_USDC=0.5
```

Video uses its own price, `VIDEO_INVESTIGATION_PRICE_USDC`, falling back to the
core price.

The browser wallet signs this payment. The facilitator verifies and settles it
to `INQUVIA_PAYTO_ADDRESS` before the investigation runs. The gate is
fail-closed: when the x402 middleware is unavailable, endpoints return `402`
rather than running free.

### How the amount is decided

The amount is not guessed by the AI:

- The price comes from `INVESTIGATION_PRICE_USDC`, never from model output.
- The facilitator verifies and settles the signed amount.
- `/.well-known/x402` publishes the same prices and `payTo` address, so the
  challenge Bazaar listing stays consistent with the code.

## Fallback and Safety Behavior

| Situation | Result |
|---|---|
| Core x402 payment missing | HTTP `402`; capability does not run |
| x402 middleware unavailable | HTTP `402`; never runs free |
| No evidence collected | No AI verdict; insufficient evidence result |
| Only duplicate/dependent evidence | AI is skipped; evidence is inconclusive |
| AI provider unavailable | Deterministic analysis is used when evidence exists |

## Production Configuration

Core backend example:

```env
PUBLIC_APP_URL=https://inquvia.onrender.com
ALGORAND_NETWORK=testnet
ALGORAND_USDC_ASA=10458941
X402_FACILITATOR_URL=https://facilitator.goplausible.xyz
X402_CHALLENGE_TAG=x402-global-challenge
INVESTIGATION_PRICE_USDC=0.5
INQUVIA_PAYTO_ADDRESS=<inquvia-wallet>
MONGODB_URI=<mongodb-connection-string>
JWT_SECRET=<strong-random-secret>
GEMINI_API_KEY=<gemini>
GROQ_API_KEY=<groq>
OPENROUTER_API_KEY=<openrouter>
EXPLABS_API_KEY=<explabs>
```

For mainnet, the network and USDC asset must match across the app and the
facilitator:

```env
ALGORAND_NETWORK=mainnet
ALGORAND_USDC_ASA=31566704
```

Never commit private keys, database credentials, or API keys.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/investigate` | Capability metadata and prices |
| `GET` | `/api/investigations` | List investigations |
| `GET` | `/api/investigations/:id` | Get investigation status and result |
| `GET` | `/api/investigations/:id/evidence` | Get the evidence trail |
| `GET` | `/api/providers` | List paid investigation capabilities and prices |
| `POST` | `/api/providers/discover` | Match capabilities to input types |
| `GET` | `/api/x402/activity` | Payment activity |
| `POST` | `/api/x402/{capability}` | Run a paid investigation capability |
| `GET` | `/.well-known/x402` | x402 resource discovery catalogue |

Paid capabilities are claim, image, video, audio, document, source, and data
investigation. All use the shared `INVESTIGATION_PRICE_USDC` value.

## Development

```bash
npm install
npm run dev
```

Run the FastAPI backend separately with its Python dependencies installed. The
frontend uses the backend API URL configured for the environment. MongoDB is
required for users, investigations, evidence, budgets, and payment records.

Validation commands:

```bash
npm run build
python -m pytest -p no:asyncio backend/tests/test_api.py -q
python backend/tests/test_audit_fixes.py
```

## License

MIT
