"""Pytest fixtures for Inquvia backend tests."""
import os
import sys
import pytest
import mongomock
from fastapi.testclient import TestClient

# Ensure backend package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure env is set before importing app
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB_NAME", "inquvia_test")
os.environ.setdefault("ALGORAND_NETWORK", "testnet")
os.environ.setdefault("ALGORAND_USDC_ASA", "10458941")
os.environ.setdefault("X402_FACILITATOR_URL", "https://facilitator.goplausible.com")
os.environ.setdefault("X402_CHALLENGE_TAG", "inquvia")
os.environ.setdefault("INQUVIA_PAYTO_ADDRESS", "TESTPAYTOADDRESS")
os.environ.setdefault("SERVER_WALLET_MNEMONIC", "")
os.environ.setdefault("ALGOD_SERVER", "https://testnet-api.algonode.cloud")
os.environ.setdefault("ALGOD_TOKEN", "")
os.environ.setdefault("EXTERNAL_EVIDENCE_SERVICES_URL", "")
os.environ.setdefault("EXTERNAL_EVIDENCE_SERVICES_JSON", "")
os.environ.setdefault("INQUVIA_X402_OFFLINE", "1")  # Offline for tests by default


@pytest.fixture(autouse=True)
def _mongo(monkeypatch):
    """Replace the real MongoDB client with mongomock for isolation."""
    import backend.app.db as db_module
    mock_client = mongomock.MongoClient()
    db_module._client = mock_client
    # Pre-create indexes that code expects
    mock_client[db_module.config.MONGODB_DB_NAME].sessions.create_index("expiresAt", expireAfterSeconds=0)
    yield
    db_module._client = None


@pytest.fixture
def client():
    from backend.app.main import app
    return TestClient(app)


@pytest.fixture
def mock_transport():
    """Build an httpx.MockTransport for faking external HTTP calls."""
    import httpx

    def _make(handler):
        return httpx.MockTransport(handler)

    return _make


@pytest.fixture
def algod_ok():
    """Handler that returns a confirmed axfer txn on algod pending endpoint."""
    import json

    def handler(request):
        tx_id = request.url.path.split("/")[-1]
        body = {
            "confirmed-round": 12345678,
            "txn": {
                "type": "axfer",
                "xaid": 10458941,
                "arcv": "TESTPAYTOADDRESS",
                "asnd": "TESTPAYERADDRESS",
                "aamt": 500000,
            },
        }
        return httpx.Response(200, json=body)

    return handler


@pytest.fixture
def algod_unconfirmed():
    def handler(request):
        return httpx.Response(200, json={"confirmed-round": 0, "txn": {}})
    return handler


@pytest.fixture
def algod_wrong_asset():
    def handler(request):
        body = {
            "confirmed-round": 12345678,
            "txn": {"type": "axfer", "xaid": 99999999, "arcv": "TESTPAYTOADDRESS", "asnd": "TESTPAYERADDRESS", "aamt": 500000},
        }
        return httpx.Response(200, json=body)
    return handler


@pytest.fixture
def algod_wrong_receiver():
    def handler(request):
        body = {
            "confirmed-round": 12345678,
            "txn": {"type": "axfer", "xaid": 10458941, "arcv": "WRONGRECEIVERADDRESS", "asnd": "TESTPAYERADDRESS", "aamt": 500000},
        }
        return httpx.Response(200, json=body)
    return handler


@pytest.fixture
def algod_insufficient_amount():
    def handler(request):
        body = {
            "confirmed-round": 12345678,
            "txn": {"type": "axfer", "xaid": 10458941, "arcv": "TESTPAYTOADDRESS", "asnd": "TESTPAYERADDRESS", "aamt": 100000},
        }
        return httpx.Response(200, json=body)
    return handler


@pytest.fixture
def probe_402_ok():
    """Handler for provider 402 probe returning a valid PAYMENT-REQUIRED header."""
    import base64, json

    def handler(request):
        payment_required = {
            "x402Version": 2,
            "accepts": [{
                "scheme": "exact",
                "payTo": "TESTPROVIDERPAYTO",
                "asset": "10458941",
                "amount": "500000",
                "network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
            }],
            "resourceUrl": "https://example-provider.com/evidence",
        }
        header = base64.b64encode(json.dumps(payment_required).encode()).decode()
        return httpx.Response(402, headers={"payment-required": header})

    return handler


@pytest.fixture
def probe_no_402():
    """Handler for provider returning 200 (no payment required)."""
    def handler(request):
        return httpx.Response(200, json={"ok": True})
    return handler


@pytest.fixture
def test_user():
    return {"id": "user_test_1", "email": "test@example.com", "walletAddress": "TESTWALLETADDRESS"}


@pytest.fixture
def test_user2():
    return {"id": "user_test_2", "email": "test2@example.com", "walletAddress": "TESTWALLETADDRESS2"}