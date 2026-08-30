"""Slack ↔ Linear ticket sync security, mapping, and idempotency tests."""

import hashlib
import hmac
import json

import config
import database
from integrations import ticket_sync


def _configure(monkeypatch):
    monkeypatch.setattr(config, "SLACK_SIGNING_SECRET", "slack-secret")
    monkeypatch.setattr(config, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(config, "SLACK_OPS_CHANNEL_ID", "COPS")
    monkeypatch.setattr(config, "SLACK_TICKET_REACTION", "ticket")
    monkeypatch.setattr(config, "LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(config, "LINEAR_WEBHOOK_SECRET", "linear-secret")
    monkeypatch.setattr(config, "LINEAR_TEAM_ID", "team-id")
    monkeypatch.setattr(config, "LINEAR_BACKLOG_STATE_ID", "backlog-id")
    monkeypatch.setattr(config, "LINEAR_DONE_STATE_ID", "done-id")


def _database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "ticket-sync.db")
    database.initialize()


def test_signatures_validate_raw_body_and_reject_stale_requests(monkeypatch):
    _configure(monkeypatch)
    body = b'{"type":"event_callback"}'
    timestamp = "1700000000"
    slack_signature = "v0=" + hmac.new(
        b"slack-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
    ).hexdigest()
    assert ticket_sync.verify_slack_signature(body, timestamp, slack_signature, now=1700000001)
    assert not ticket_sync.verify_slack_signature(body + b" ", timestamp, slack_signature, now=1700000001)
    assert not ticket_sync.verify_slack_signature(body, timestamp, slack_signature, now=1700001000)

    linear_signature = hmac.new(b"linear-secret", body, hashlib.sha256).hexdigest()
    assert ticket_sync.verify_linear_signature(body, linear_signature)
    assert not ticket_sync.verify_linear_signature(body + b" ", linear_signature)


def test_slack_ticket_is_created_once_and_mapped(tmp_path, monkeypatch):
    _configure(monkeypatch)
    _database(tmp_path, monkeypatch)
    slack_calls = []
    linear_calls = []

    def fake_slack(method, **params):
        slack_calls.append((method, params))
        if method == "conversations.history":
            return {"messages": [{"text": "Fix checkout alerts", "user": "U123"}]}
        return {"permalink": "https://bia.slack.com/archives/COPS/p123"}

    def fake_linear(title, description):
        linear_calls.append((title, description))
        return {"id": "lin-1", "identifier": "NIC-22", "url": "https://linear.app/nic-22"}

    monkeypatch.setattr(ticket_sync, "_slack_call", fake_slack)
    monkeypatch.setattr(ticket_sync, "_create_linear_issue", fake_linear)
    payload = {
        "event_id": "Ev1",
        "team_id": "TBIA",
        "event": {
            "type": "reaction_added",
            "reaction": "ticket",
            "item": {"type": "message", "channel": "COPS", "ts": "123.456"},
        },
    }

    ticket_sync.process_slack_event(payload)
    ticket_sync.process_slack_event(payload)

    assert len(linear_calls) == 1
    assert linear_calls[0][0] == "Fix checkout alerts"
    with database.get_connection() as conn:
        link = conn.execute("SELECT * FROM ticket_links").fetchone()
        event = conn.execute("SELECT * FROM integration_events").fetchone()
    assert link["linear_identifier"] == "NIC-22"
    assert link["slack_message_ts"] == "123.456"
    assert event["status"] == "completed"


def test_linear_done_posts_one_thread_reply(tmp_path, monkeypatch):
    _configure(monkeypatch)
    _database(tmp_path, monkeypatch)
    now = "2026-08-30T00:00:00+00:00"
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ticket_links (
              id, slack_team_id, slack_channel_id, slack_message_ts,
              linear_issue_id, linear_identifier, linear_url, created_at, updated_at
            ) VALUES ('link-1', 'TBIA', 'COPS', '123.456', 'lin-1', 'NIC-22',
                      'https://linear.app/nic-22', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
    calls = []
    monkeypatch.setattr(
        ticket_sync, "_slack_call", lambda method, **params: calls.append((method, params)) or {"ok": True}
    )
    payload = {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": "lin-1", "identifier": "NIC-22", "url": "https://linear.app/nic-22",
            "state": {"id": "done-id", "name": "Done"},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()

    ticket_sync.process_linear_event(payload, raw)
    ticket_sync.process_linear_event(payload, raw)

    assert len(calls) == 1
    assert calls[0][0] == "chat.postMessage"
    assert calls[0][1]["thread_ts"] == "123.456"
    with database.get_connection() as conn:
        link = conn.execute("SELECT * FROM ticket_links WHERE id = 'link-1'").fetchone()
    assert link["status"] == "done"
    assert link["completion_sent_at"] and not link["completion_sent_at"].startswith("pending:")


def test_non_ops_reaction_is_ignored_without_api_calls(tmp_path, monkeypatch):
    _configure(monkeypatch)
    _database(tmp_path, monkeypatch)
    monkeypatch.setattr(ticket_sync, "_slack_call", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    payload = {
        "event_id": "Ev-other",
        "team_id": "TBIA",
        "event": {
            "type": "reaction_added", "reaction": "ticket",
            "item": {"type": "message", "channel": "COTHER", "ts": "1.2"},
        },
    }
    ticket_sync.process_slack_event(payload)
    with database.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0] == 0
