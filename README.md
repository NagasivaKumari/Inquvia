# Inquvia

Autonomous evidence investigation agent for the Algorand Global x402 Challenge.

**Investigate anything. Get evidence, not guesses.**

Inquvia autonomously gathers and cross-checks the evidence needed to answer your question â€” using pay-per-request services when necessary.

## Features

- **Multi-modal input** â€” text, URLs, images, video, documents, structured data
- **Autonomous investigation** â€” plans evidence needs, discovers providers, purchases via x402
- **Economic decision engine** â€” selects evidence based on value vs cost
- **Transparent payments** â€” full x402/Algorand settlement visibility
- **Evidence-backed conclusions** â€” confidence scores, risk levels, explicit limitations

## Quick Start

```bash
# Frontend dependencies
npm install

# Terminal 1: start the Next.js frontend
npm run dev
```

Run the core FastAPI backend separately from `backend/` with its Python
dependencies installed. The frontend proxies `/api/*` requests to that backend
in development. MongoDB is required for users, sessions, investigations, and
payment records.

Open [http://localhost:3000](http://localhost:3000) after both services are
running.

## Configuration

Brand name is configurable in `.env`:

```env
APP_NAME=Inquvia
```

For production, configure the core backend for Algorand Mainnet, the
GoPlausible facilitator, one USDC-opted-in merchant `payTo` address, MongoDB,
and a separate downstream signer service. The core backend deliberately does
not hold a downstream wallet private key.

## Architecture

```
User Input → x402 Payment → Investigation Plan → Provider Discovery →
Server-side Evidence Acquisition → Conclusion
```

- **Frontend**: Next.js 15 + TypeScript + custom CSS
- **Core backend**: FastAPI + MongoDB for authentication, investigations,
  payments, and budgets
- **Providers**: x402/Bazaar discovery and a separately deployed evidence
  service client
- **Payments**: the browser wallet pays Inquvia's atomic capability; Inquvia
  may pay evidence providers server-side through a separate signer

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/investigate` | List atomic capability metadata and canonical prices |
| GET | `/api/investigations` | List investigations |
| GET | `/api/investigations/:id` | Get investigation |
| GET | `/api/investigations/:id/evidence` | Get evidence |
| GET | `/api/providers` | List providers |
| POST | `/api/providers/discover` | Discover providers |
| GET | `/api/x402/activity` | Payment activity |
| POST | `/api/x402/{capability}` | Run a paid, atomic investigation capability |

`POST /api/investigate` and client-settled `/api/gateway/acquire*` flows are
not part of the active API. Each investigation starts through an x402-gated
atomic capability endpoint; downstream evidence acquisition is orchestrated
and paid by the backend when configured.

## License

MIT
