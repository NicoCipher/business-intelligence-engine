"""Durable Slack reaction → Linear ticket → Slack completion sync."""

import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx

import config
import database

logger = logging.getLogger(__name__)
SLACK_API = "https://slack.com/api"
LINEAR_API = "https://api.linear.app/graphql"


def verify_slack_signature(body: bytes, timestamp: str, signature: str, now: int | None = None) -> bool:
    if not config.SLACK_SIGNING_SECRET or not timestamp or not signature:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else int(time.time())) - request_time) > 300:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(
        config.SLACK_SIGNING_SECRET.encode(), base, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_linear_signature(body: bytes, signature: str) -> bool:
    if not config.LINEAR_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(
        config.LINEAR_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_event(source: str, event_id: str) -> bool:
    """Claim a new event, or retry one whose previous processing failed."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM integration_events WHERE source = ? AND event_id = ?",
            (source, event_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO integration_events "
                "(source, event_id, status, received_at) VALUES (?, ?, 'received', ?)",
                (source, event_id, _now()),
            )
            conn.commit()
            return True
        if row["status"] == "failed":
            conn.execute(
                "UPDATE integration_events SET status = 'received', error = '' "
                "WHERE source = ? AND event_id = ? AND status = 'failed'",
                (source, event_id),
            )
            conn.commit()
            return conn.total_changes == 1
        return False


def _finish_event(source: str, event_id: str, error: str = "") -> None:
    with database.get_connection() as conn:
        conn.execute(
            "UPDATE integration_events SET status = ?, error = ?, completed_at = ? "
            "WHERE source = ? AND event_id = ?",
            ("failed" if error else "completed", error[:1000], _now(), source, event_id),
        )
        conn.commit()


def _slack_call(method: str, **params) -> dict:
    response = httpx.post(
        f"{SLACK_API}/{method}",
        headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
        json=params,
        timeout=10.0,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {result.get('error', 'unknown_error')}")
    return result


def _linear_call(query: str, variables: dict) -> dict:
    response = httpx.post(
        LINEAR_API,
        headers={"Authorization": config.LINEAR_API_KEY},
        json={"query": query, "variables": variables},
        timeout=10.0,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("errors"):
        raise RuntimeError(f"Linear GraphQL failed: {result['errors'][0].get('message', 'unknown_error')}")
    return result["data"]


def _message_at(channel: str, message_ts: str) -> dict:
    result = _slack_call(
        "conversations.history",
        channel=channel,
        oldest=message_ts,
        latest=message_ts,
        inclusive=True,
        limit=1,
    )
    messages = result.get("messages", [])
    if not messages:
        raise RuntimeError("Slack message was not found")
    return messages[0]


def _create_linear_issue(title: str, description: str) -> dict:
    issue_input = {
        "teamId": config.LINEAR_TEAM_ID,
        "title": title[:240],
        "description": description,
    }
    if config.LINEAR_BACKLOG_STATE_ID:
        issue_input["stateId"] = config.LINEAR_BACKLOG_STATE_ID
    data = _linear_call(
        """
        mutation CreateBiaTicket($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue { id identifier url title }
          }
        }
        """,
        {"input": issue_input},
    )
    created = data["issueCreate"]
    if not created.get("success") or not created.get("issue"):
        raise RuntimeError("Linear did not create the issue")
    return created["issue"]


def process_slack_event(payload: dict) -> None:
    event_id = payload.get("event_id", "")
    if not event_id or not _claim_event("slack", event_id):
        return
    try:
        event = payload.get("event", {})
        item = event.get("item", {})
        channel = item.get("channel", "")
        message_ts = item.get("ts", "")
        if (
            event.get("type") != "reaction_added"
            or event.get("reaction") != config.SLACK_TICKET_REACTION
            or item.get("type") != "message"
            or channel != config.SLACK_OPS_CHANNEL_ID
            or not message_ts
        ):
            _finish_event("slack", event_id)
            return

        team_id = payload.get("team_id", "")
        with database.get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM ticket_links WHERE slack_team_id = ? "
                "AND slack_channel_id = ? AND slack_message_ts = ?",
                (team_id, channel, message_ts),
            ).fetchone()
        if existing:
            _finish_event("slack", event_id)
            return

        message = _message_at(channel, message_ts)
        title = " ".join(message.get("text", "").split()) or "Slack ticket"
        permalink = _slack_call(
            "chat.getPermalink", channel=channel, message_ts=message_ts
        )["permalink"]
        author = message.get("user", "unknown")
        description = (
            "Created by BIA from a `:ticket:` reaction in Slack.\n\n"
            f"- Slack author: <@{author}>\n"
            f"- Slack message: {permalink}\n"
            f"- Slack channel: {channel}"
        )
        issue = _create_linear_issue(title, description)
        now = _now()
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO ticket_links (
                    id, slack_team_id, slack_channel_id, slack_message_ts,
                    slack_permalink, linear_issue_id, linear_identifier,
                    linear_url, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'backlog', ?, ?)
                """,
                (
                    str(uuid.uuid4()), team_id, channel, message_ts, permalink,
                    issue["id"], issue["identifier"], issue.get("url", ""), now, now,
                ),
            )
            conn.commit()
        _finish_event("slack", event_id)
    except Exception as exc:
        logger.exception("Slack ticket event %s failed", event_id)
        _finish_event("slack", event_id, str(exc))


def process_linear_event(payload: dict, raw_body: bytes) -> None:
    data = payload.get("data", {})
    issue_id = data.get("id", "")
    event_id = hashlib.sha256(raw_body).hexdigest()
    if not _claim_event("linear", event_id):
        return
    try:
        state = data.get("state") or {}
        is_done = (
            payload.get("type") == "Issue"
            and payload.get("action") == "update"
            and issue_id
            and (
                (config.LINEAR_DONE_STATE_ID and state.get("id") == config.LINEAR_DONE_STATE_ID)
                or state.get("name", "").strip().lower() == "done"
            )
        )
        if not is_done:
            _finish_event("linear", event_id)
            return

        claim_marker = f"pending:{event_id}"
        with database.get_connection() as conn:
            link = conn.execute(
                "SELECT * FROM ticket_links WHERE linear_issue_id = ?", (issue_id,)
            ).fetchone()
            if link is not None and not link["completion_sent_at"]:
                conn.execute(
                    "UPDATE ticket_links SET completion_sent_at = ? WHERE id = ? "
                    "AND completion_sent_at = ''",
                    (claim_marker, link["id"]),
                )
                claimed = conn.total_changes == 1
                conn.commit()
            else:
                claimed = False
        if link is None or not claimed:
            _finish_event("linear", event_id)
            return

        identifier = data.get("identifier") or link["linear_identifier"]
        url = data.get("url") or link["linear_url"]
        text = f"✅ {identifier} is Done"
        if url:
            text += f" — {url}"
        _slack_call(
            "chat.postMessage",
            channel=link["slack_channel_id"],
            thread_ts=link["slack_message_ts"],
            text=text,
            unfurl_links=False,
        )
        now = _now()
        with database.get_connection() as conn:
            conn.execute(
                "UPDATE ticket_links SET status = 'done', completion_sent_at = ?, "
                "updated_at = ? WHERE id = ? AND completion_sent_at = ?",
                (now, now, link["id"], claim_marker),
            )
            conn.commit()
        _finish_event("linear", event_id)
    except Exception as exc:
        logger.exception("Linear ticket event %s failed", event_id)
        if issue_id:
            with database.get_connection() as conn:
                conn.execute(
                    "UPDATE ticket_links SET completion_sent_at = '' "
                    "WHERE linear_issue_id = ? AND completion_sent_at = ?",
                    (issue_id, f"pending:{event_id}"),
                )
                conn.commit()
        _finish_event("linear", event_id, str(exc))
