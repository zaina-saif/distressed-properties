from fastapi.testclient import TestClient

import app.api.contact as contact
from app.main import app

GOOD = {"name": "Jane Investor", "email": "jane@example.com", "topic": "sales", "message": "I would like to ask about Pro."}


def test_honeypot_is_accepted_without_storing(monkeypatch):
    monkeypatch.setattr(contact, "engine", None)  # any database use would fail
    response = TestClient(app).post("/api/v1/contact", json={**GOOD, "website": "http://spam.example"})
    assert response.status_code == 200 and response.json() == {"received": True}


def test_invalid_email_and_short_message_are_rejected():
    client = TestClient(app)
    assert client.post("/api/v1/contact", json={**GOOD, "email": "not-an-email"}).status_code == 400
    assert client.post("/api/v1/contact", json={**GOOD, "message": "hi"}).status_code == 422
    assert client.post("/api/v1/contact", json={**GOOD, "topic": "other"}).status_code == 422


def test_rate_limit_per_address():
    contact._recent.clear()
    assert all(contact.allowed("1.2.3.4", now=1000 + i) for i in range(contact.LIMIT))
    assert not contact.allowed("1.2.3.4", now=1010)
    assert contact.allowed("5.6.7.8", now=1010)
    assert contact.allowed("1.2.3.4", now=1000 + contact.WINDOW + 10)  # the window has moved on


def test_email_goes_to_the_inbox_with_reply_to(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, timeout, headers, json):
        sent.update(url=url, auth=headers["Authorization"], **json)
        return Response()

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("CONTACT_TO_EMAIL", "sam@sheriffsalehunter.ai")
    monkeypatch.setattr(contact.httpx, "post", fake_post)
    contact.send_email(contact.ContactMessage(**GOOD))
    assert sent["to"] == ["sam@sheriffsalehunter.ai"] and sent["reply_to"] == "jane@example.com"
    assert sent["subject"] == "[Contact] Plans and pricing: Jane Investor" and "I would like to ask about Pro." in sent["text"]
    assert sent["auth"] == "Bearer re_test"
