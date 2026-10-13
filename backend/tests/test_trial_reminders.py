from datetime import datetime, timezone

from pipeline.send_trial_reminders import render

ACCOUNT = {"user_id": "11111111-1111-1111-1111-111111111111", "email": "inv@example.com",
           "trial_ends_at": datetime(2026, 10, 20, 15, tzinfo=timezone.utc)}


def test_reminder_names_the_end_date_and_the_free_county_option():
    subject, html, text = render({**ACCOUNT, "kind": "reminder"}, "1 Main St, Red Bank, NJ")
    assert subject == "Your free trial ends Tuesday, Oct 20"
    assert "one county within a state" in text and "Starter ($19.99/mo)" in text and "Pro ($49.99/mo)" in text
    assert "/choose-plan" in html and "1 Main St, Red Bank, NJ" in html


def test_ended_email_offers_staying_free():
    subject, _, text = render({**ACCOUNT, "kind": "ended"}, "1 Main St")
    assert subject.startswith("Your free trial has ended")
    assert "stays free" in text
