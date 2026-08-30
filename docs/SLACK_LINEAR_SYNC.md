# BIA Slack → Linear ticket sync

BIA can replace the paid multi-step Zap while preserving the simple free Zap
during rollout.

## Behavior

- A `:ticket:` reaction on a message in `#ops` creates one Linear Backlog issue.
- BIA stores the Slack message timestamp and Linear issue ID in SQLite.
- When that Linear issue moves to Done, BIA replies in the original Slack thread.
- Signed requests, event deduplication, and a per-ticket completion claim prevent
  normal webhook retries from creating duplicate work or duplicate replies.

## Safe cutover

1. Deploy BIA at a public HTTPS URL with the environment variables in
   `.env.example`. Leave `BIA_TICKET_SYNC_ENABLED=false`.
2. In the Slack app, add the bot scopes `channels:history`, `chat:write`, and
   `reactions:read` (plus `groups:history` if `#ops` is private). Subscribe to
   the bot event `reaction_added`. Set the request URL to
   `https://<bia-host>/api/v1/integrations/slack/events`.
3. Invite the Slack app to `#ops` and set `SLACK_OPS_CHANNEL_ID` to the channel
   ID, not its display name.
4. In Linear API settings, create an Issue webhook pointing to
   `https://<bia-host>/api/v1/integrations/linear/events`. Copy its signing
   secret into `LINEAR_WEBHOOK_SECRET`.
5. Set the Linear team, Backlog state, and Done state UUIDs. Restart BIA and
   confirm both webhook URLs accept their verification/test requests.
6. Turn off `BIA — Slack Ticket → Linear Backlog` in Zapier.
7. Set `BIA_TICKET_SYNC_ENABLED=true`, restart BIA, and test with one new
   `:ticket:` reaction. Move that issue to Done and verify the Slack thread reply.

Do not enable BIA before disabling the Zap: both systems would receive the same
reaction and could create two Linear issues.
