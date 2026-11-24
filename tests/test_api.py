from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db

def test_health():
    init_db()
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
