# Inquvia

Inquvia is an evidence-acquisition agent for the Algorand x402 ecosystem. It
is designed to reduce unsupported AI answers by acquiring, paying for, and
tracking evidence before producing an assessment.

## What It Does

Given a question and optional URL, file, image, video, document, or structured
data, Inquvia:

1. Selects an investigation capability and plans the evidence types required.
2. Discovers services from the configured evidence provider catalogue.
3. Compares advertised service cost with the investigation budget and expected
   value.
4. Acquires evidence through x402-protected provider endpoints.
5. Pays providers automatically through Algorand x402 when a `402` challenge is
   returned and a server signer is configured.
6. Normalizes evidence and preserves provider, source, payment, and citation
   metadata.
7. De-weights duplicate and explicitly dependent evidence.
8. Checks contradictions, provenance signals, missing evidence, and limitations.
9. Produces a confidence-based result or reports `evidence_unavailable` when
   there is not enough usable evidence.

Inquvia does not invent evidence when a provider or payment path is unavailable.

## Architecture

```text
User input
  -> User pays Inquvia through x402/Algorand
  -> Capability-specific investigation
  -> Primary evidence service discovery
  -> Budget and value decision
  -> Provider returns 402 when payment is required
  -> Server signer signs provider payment
  -> GoPlausible settles provider payment
  -> Evidence provider returns evidence
  -> Analysis, contradiction checks, and final report
```

### Primary evidence provider

`EVIDENCE_SERVICE_URL` is the main provider for the active investigation path.
It exposes `/api/services` and evidence endpoints for URLs, images, video,
documents, structured data, and audio. The core backend keeps this provider as
the reliable fallback and returns no fabricated provider when it is unavailable.

Additional catalogues can be supplied through `EXTERNAL_EVIDENCE_SERVICES_URL`.
When configured, their services are discovered alongside the primary provider,
identified by provider URL, and compared by advertised price. The primary
`EVIDENCE_SERVICE_URL` remains compatible and is sufficient for a single-provider
deployment.

## Payment Model

There are two separate x402 payments.

### User to Inquvia

Each capability endpoint has the shared core price configured by:

```env
INVESTIGATION_PRICE_USDC=0.5
```

The browser wallet signs this payment. The facilitator verifies and settles it
to `INQUVIA_PAYTO_ADDRESS` before the investigation runs.

### Inquvia to evidence provider

The provider catalogue advertises an estimated price, but the provider's
`402 Payment Required` challenge is authoritative. Inquvia:

1. Calls the provider endpoint.
2. Reads the provider's `payTo`, amount, asset, and network from the challenge.
3. Checks the per-check, per-investigation, session, and total budgets.
4. Uses `SIGNER_URL` to obtain an automated signature from the server wallet.
5. Sends the signed payment to the GoPlausible facilitator.
6. Retries the provider request with the x402 payment proof.
7. Records the settlement transaction and provider cost.

No user approval is required for this second payment. The signer must be
configured and funded with the correct USDC asset and ALGO fees. Without a
signer, the request fails closed and the investigation reports unavailable
evidence instead of asking the user to pay the provider.

### How the amount is decided

The amount is not guessed by the AI:

- Inquvia's own charge comes from `INVESTIGATION_PRICE_USDC`.
- Provider selection uses the catalogue's advertised price.
- The actual provider payment uses the signed amount from the provider's x402
  challenge.
- Budget checks run before the signer or facilitator is called.

The default budget policy is defined in `backend/app/config.py` and includes
per-evidence, per-investigation, session, and total limits. A payment that
exceeds a limit is not attempted.

## Fallback and Safety Behavior

| Situation | Result |
|---|---|
| Core x402 payment missing | HTTP `402`; capability does not run |
| Primary provider unavailable | No fake provider; `evidence_unavailable` |
| Provider payment exceeds budget | Payment is blocked before signing |
| Signer unavailable | Provider acquisition fails closed |
| Provider returns malformed payment challenge | Payment is rejected |
| No evidence collected | No AI verdict; insufficient evidence result |
| Only duplicate/dependent evidence | AI is skipped; evidence is inconclusive |
| AI provider unavailable | Deterministic analysis is used when evidence exists |

## Production Configuration

Core backend example:

```env
PUBLIC_APP_URL=https://inquvia.onrender.com
EVIDENCE_SERVICE_URL=https://endpoints-24tb.onrender.com
ALGORAND_NETWORK=testnet
ALGORAND_USDC_ASA=10458941
X402_FACILITATOR_URL=https://facilitator.goplausible.xyz
X402_CHALLENGE_TAG=x402-global-challenge
INVESTIGATION_PRICE_USDC=0.5
INQUVIA_PAYTO_ADDRESS=<inquvia-wallet>
SIGNER_URL=<automated-signer-url>
SIGNER_TOKEN=<signer-token>
MONGODB_URI=<mongodb-connection-string>
JWT_SECRET=<strong-random-secret>
```

Evidence service example:

```env
X402_ENABLED=true
X402_NETWORK=algorand:testnet
X402_USDC_ASSET_ID=10458941
X402_PAYMENT_PRICE_USDC=0.002
AVM_ADDRESS=<provider-wallet>
```

For mainnet, all services must use the mainnet network and asset consistently:

```env
ALGORAND_NETWORK=mainnet
X402_NETWORK=algorand:mainnet
ALGORAND_USDC_ASA=31566704
X402_USDC_ASSET_ID=31566704
```

Never commit private keys, signer tokens, database credentials, or API keys.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/investigate` | Capability metadata and prices |
| `GET` | `/api/investigations` | List investigations |
| `GET` | `/api/investigations/:id` | Get investigation status and result |
| `GET` | `/api/investigations/:id/evidence` | Get the evidence trail |
| `GET` | `/api/providers` | View configured provider services |
| `POST` | `/api/providers/discover` | Refresh provider discovery |
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
