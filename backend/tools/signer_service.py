"""Reference out-of-process signer for downstream x402 payments (Tx #2).

The payer private key lives HERE, in THIS process's own environment
(SIGNER_ACCOUNT_MNEMONIC) — never in Core's .env. Core only ever sees the
payer address and the signatures returned over HTTP. Any secure key owner
(AWS KMS Ed25519, HashiCorp Vault transit, a custodial signer) can be mounted
behind the same two-endpoint contract:

  GET  /address -> {"address": "..."}
  POST /sign    -> {"signedTxns": [base64 | null, ...]}
       body: {"unsignedTxns": [base64...], "indexesToSign": [int...]}
       Auth: optional Bearer token matching SIGNER_BEARER_TOKEN

Run (signer's own shell, its own secrets):
    $env:SIGNER_ACCOUNT_MNEMONIC = "<25 words>"
    $env:SIGNER_BEARER_TOKEN = "<secret>"      # optional
    uvicorn app.tools.signer_service:app --port 8201   # or: python -m backend.tools.signer_service

SIGNER_URL=http://<signer-host>:8201 SIGNER_TOKEN=<secret> in Core's .env.
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)


def _account():
    from algosdk import account, mnemonic

    raw = (os.environ.get("SIGNER_ACCOUNT_MNEMONIC") or "").strip()
    if not raw:
        raise RuntimeError("SIGNER_ACCOUNT_MNEMONIC is not set for the signer service")
    sk = mnemonic.to_private_key(raw)
    return sk, account.address_from_private_key(sk)


def _sign_batch(unsigned_b64: list[str], indexes_to_sign: list[int]) -> list[str | None]:
    import base64 as _b64
    import msgpack as _mp

    from algosdk import encoding as _enc
    from algosdk import transaction as _txn

    sk, _addr = _account()
    to_sign = set(indexes_to_sign)
    out: list[str | None] = []
    for i, b64 in enumerate(unsigned_b64):
        if i not in to_sign:
            out.append(None)
            continue
        txn = _txn.Transaction.undictify(_mp.unpackb(_b64.b64decode(b64), raw=False))
        signed = _enc.msgpack_encode(txn.sign(sk))
        out.append(_b64.b64encode(_b64.b64decode(signed)).decode())
    return out


def app_factory():
    """Lazy Starlette app so fastapi/starlette are only required at runtime."""
    from fastapi import Depends, FastAPI, Header, HTTPException
    from pydantic import BaseModel

    class SignRequest(BaseModel):
        unsignedTxns: list[str]
        indexesToSign: list[int]

    app = FastAPI(title="Inquvia Downstream Signer")

    def authorized(authorization: str | None = Header(default=None)):
        token = os.environ.get("SIGNER_BEARER_TOKEN", "")
        if token:
            if (authorization or "") != f"Bearer {token}":
                raise HTTPException(status_code=401, detail="unauthorized")
        return True

    @app.get("/address")
    def address():
        _sk, addr = _account()
        return {"address": addr}

    @app.post("/sign")
    def sign(req: SignRequest, _: bool = Depends(authorized)):
        try:
            signed = _sign_batch(req.unsignedTxns, req.indexesToSign)
        except Exception as e:
            logger.error("sign failed: %s", e)
            raise HTTPException(status_code=400, detail="signing failed")
        return {"signedTxns": signed}

    return app


app = app_factory()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8201)