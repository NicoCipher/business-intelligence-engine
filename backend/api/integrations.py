"""Authenticated-by-signature webhook endpoints for BIA integrations."""

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import config
from integrations.ticket_sync import (
    process_linear_event,
    process_slack_event,
    verify_linear_signature,
    verify_slack_signature,
)

router = APIRouter()


@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    if not verify_slack_signature(
        raw,
        request.headers.get("x-slack-request-timestamp", ""),
        request.headers.get("x-slack-signature", ""),
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}
    if not config.TICKET_SYNC_ENABLED:
        return {"ok": True, "ignored": "ticket sync disabled"}
    background_tasks.add_task(process_slack_event, payload)
    return {"ok": True}


@router.post("/linear/events")
async def linear_events(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    if not verify_linear_signature(raw, request.headers.get("linear-signature", "")):
        raise HTTPException(status_code=401, detail="Invalid Linear signature")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if not config.TICKET_SYNC_ENABLED:
        return {"ok": True, "ignored": "ticket sync disabled"}
    background_tasks.add_task(process_linear_event, payload, raw)
    return {"ok": True}
