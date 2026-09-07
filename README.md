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
# Install dependencies
npm install

# Copy environment config
cp .env.example .env

# Start development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Configuration

Brand name is configurable in `.env`:

```env
APP_NAME=Inquvia
```

Algorand Mainnet / x402 settings:

```env
ALGORAND_NETWORK=mainnet
ALGORAND_USDC_ASA=31566704
X402_FACILITATOR_URL=https://facilitator.goplausible.xyz
X402_WALLET_MNEMONIC=your_mnemonic_here
X402_CHALLENGE_TAG=x402-global-challenge
```

## Architecture

```
User Input â†’ Investigation Plan â†’ Provider Discovery â†’ x402 Payment â†’ Evidence â†’ Conclusion
```

- **Frontend**: Next.js 15 + TypeScript + custom CSS
- **Backend**: Next.js API routes + JSON file storage (SQLite-compatible abstraction)
- **Providers**: Abstraction layer for x402/Bazaar discovery
- **Payments**: x402 client with GoPlausible facilitator support

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/investigate` | Start investigation |
| GET | `/api/investigations` | List investigations |
| GET | `/api/investigations/:id` | Get investigation |
| GET | `/api/investigations/:id/evidence` | Get evidence |
| GET | `/api/providers` | List providers |
| POST | `/api/providers/discover` | Discover providers |
| GET | `/api/x402/activity` | Payment activity |

## License

MIT
