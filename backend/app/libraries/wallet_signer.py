"""Downstream payer signer for x402 (Tx #2): the key lives OUTSIDE Core.

Core only ever holds the payer ADDRESS and a way to ask an external key owner
for signatures. Every signer integration (AWS KMS, HashiCorp Vault, a hosted
signer service) is a `KeyOwner`; `RemoteAvmSigner` adapts it to x402-avm's
`ClientAvmSigner` protocol so ExactAvmScheme signs the ASA transfer to the
provider's payTo automatically, with no human approval and no private key in
Core. `HttpKeyOwner` is the wire contract a key-owning service exposes.

The reference key-owning service (tools/signer_service.py) keeps the mnemonic
in ITS OWN process environment; Core's .env carries only SIGNER_URL/TOKEN.

Incorrect SIGNER_URL or a failing signer FAILS CLOSED (SignerUnavailable) --
Core never falls back to a local key or asks the user to sign.
"""
import base64
import logging
from typing import Protocol

import httpx

from .. import config

logger = logging.getLogger(__name__)

SIGN_TIMEOUT = 20.0


class SignerUnavailable(RuntimeError):
    """The configured external signer cannot produce a signature now."""


class KeyOwner(Protocol):
    """Anything that owns the payer key and can sign transactions.

    Implementations hold the private key (KMS, vault, hardware, signer
    service); Core never possesses it.
    """

    @property
    def address(self) -> str:
        """58-char Algorand address of the payer account."""

    def sign_transactions(
        self, unsigned_txns: list[bytes], indexes_to_sign: list[int]
    ) -> list[bytes | None]:
        """Return fully assembled signed transaction bytes (msgpack).

        None for indexes the owner should not sign (e.g. the fee-payer txn
        that the x402 facilitator signs itself).
        """


def wrap_bare_signatures(unsigned_txns: list[bytes], indexes_to_sign: list[int],
                         signature_for: dict[int, bytes]) -> list[bytes | None]:
    """Assemble SignedTransaction bytes from bare 64-byte Ed25519 signatures.

    This is the shape AWS KMS / HashiCorp Vault transit return for the
    message b"TX" + msgpack(txn). Core wraps the returned signature into the
    algosdk SignedTransaction, so the key never has to leave the KMS.
    """
    import msgpack as _mp

    from algosdk import encoding as _enc
    from algosdk import transaction as _txn

    out: list[bytes | None] = []
    for i, blob in enumerate(unsigned_txns):
        sig = signature_for.get(i)
        if sig is None:
            out.append(None)
            continue
        txn = _txn.Transaction.undictify(_mp.unpackb(blob, raw=False))
        stx = _txn.SignedTransaction(txn, base64.b64encode(sig).decode())
        out.append(base64.b64decode(_enc.msgpack_encode(stx)))
    return out


class HttpKeyOwner:
    """Key owner fronted by an HTTP signer service (the /sign contract)."""

    def __init__(self, base_url: str, api_key: str | None = None,
                 http: httpx.Client | None = None):
        self._url = base_url.rstrip("/")
        self._token = api_key
        self._http = http or httpx.Client(timeout=SIGN_TIMEOUT)
        self._address: str | None = None
        self._load_address()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _load_address(self) -> None:
        try:
            r = self._http.get(f"{self._url}/address", headers=self._headers())
            body = r.json()
        except Exception as e:
            raise SignerUnavailable(f"Signer /address unavailable: {e}") from e
        if r.status_code != 200 or not str(body.get("address", "")).strip():
            raise SignerUnavailable(
                f"Signer /address rejected: {r.status_code} {str(body)[:120]}")
        self._address = body["address"]

    @property
    def address(self) -> str:
        if not self._address:
            raise SignerUnavailable("Signer address not loaded")
        return self._address

    def sign_transactions(self, unsigned_txns: list[bytes],
                          indexes_to_sign: list[int]) -> list[bytes | None]:
        body = {
            "unsignedTxns": [base64.b64encode(b).decode() for b in unsigned_txns],
            "indexesToSign": list(indexes_to_sign),
        }
        try:
            r = self._http.post(f"{self._url}/sign", json=body, headers=self._headers())
            data = r.json()
        except Exception as e:
            raise SignerUnavailable(f"Signer /sign unavailable: {e}") from e
        if r.status_code != 200 or not isinstance(data.get("signedTxns"), list):
            raise SignerUnavailable(
                f"Signer /sign rejected: {r.status_code} {str(data)[:120]}")
        signed = data["signedTxns"]
        if len(signed) != len(unsigned_txns):
            raise SignerUnavailable("Signer /sign returned the wrong number of transactions")
        return [
            base64.b64decode(s) if s else None
            for s in signed
        ]


class RemoteAvmSigner:
    """Adapts a KeyOwner to x402-avm's ClientAvmSigner protocol.

    ExactAvmScheme signs the ASA transfer (sender == signer.address) through
    this object; the fee-payer transaction stays unsigned for the facilitator.
    """

    def __init__(self, owner: KeyOwner):
        self._owner = owner

    @property
    def address(self) -> str:
        return self._owner.address

    def sign_transactions(self, unsigned_txns: list[bytes],
                          indexes_to_sign: list[int]) -> list[bytes | None]:
        return self._owner.sign_transactions(unsigned_txns, indexes_to_sign)


def get_default_signer() -> RemoteAvmSigner | None:
    """RemoteAvmSigner for the configured SIGNER_URL, or None when unset."""
    if not config.SIGNER_URL:
        return None
    owner = HttpKeyOwner(config.SIGNER_URL, api_key=config.SIGNER_TOKEN or None)
    return RemoteAvmSigner(owner)


def _demo():
    """Self-check: bare-signature wrap is wire-identical to local signing."""
    import base64 as _b64

    from algosdk import account, encoding as _enc, transaction as _txn
    from nacl.signing import SigningKey

    sk, addr = account.generate_account()
    sp = _txn.SuggestedParams(fee=1000, flat_fee=True, first=1000, last=2000,
                              gh="SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
                              gen="testnet-v1.0")
    _, provider = account.generate_account()
    pay = _txn.AssetTransferTxn(sender=addr, sp=sp, receiver=provider,
                                amt=500_000, index=10458941, note=b"demo")
    raw = _b64.b64decode(_enc.msgpack_encode(pay))
    sig = SigningKey(_b64.b64decode(sk)[:32]).sign(b"TX" + raw).signature

    wrapped = wrap_bare_signatures([raw], [0], {0: sig})[0]
    local = _b64.b64decode(_enc.msgpack_encode(pay.sign(sk)))
    assert wrapped == local, "wrapped signature must equal local signing"
    print("wallet_signer demo: all checks passed")


if __name__ == "__main__":
    _demo()