# BIA-OS — Business Intelligence Autonomous Operating System

> Version 1 · Opportunity Discovery

---

## What this is

BIA-OS observes the public internet, detects patterns across multiple unrelated sources, scores them as business opportunities, and explains its reasoning. It does not hallucinate trends. It does not invent statistics. Every claim traces to a specific observed signal.

Version 1 has one responsibility: **discover opportunities**. Nothing else.

---

## Architecture

```
Public Internet (HN · Reddit · RSS)
         │
   ┌─────▼──────┐
   │ Collectors │   one file per source · common interface · no cross-dependencies
   └─────┬──────┘
         │  Signal objects (append-only)
   ┌─────▼──────┐
   │  SQLite DB │   WAL mode · explicit SQL · no ORM magic
   └─────┬──────┘
         │  Unprocessed signals
   ┌─────▼──────────────┐
   │  Pattern Detector  │   keyword fingerprinting · Jaccard clustering
   └─────┬──────────────┘
         │  Signal clusters
   ┌─────▼────────────────┐
   │  Opportunity Scorer  │   7 transparent dimensions · documented formulas
   └─────┬────────────────┘
         │  Scored opportunities
   ┌─────▼──────┐
   │  FastAPI   │   thin routes · no business logic
   └─────┬──────┘
         │  JSON
   ┌─────▼──────────┐
   │  React Frontend│   extends Version 1 guide · live data layer
   └────────────────┘
```

Every layer has one job. Replacing the clustering algorithm means editing `detector.py` only. Replacing SQLite with PostgreSQL means editing `database.py` only.

---

## Scoring model

Every opportunity is scored on 7 dimensions, all 0–10. Higher is always better.

| Dimension | What it measures | Default |
|---|---|---|
| **Demand** | Evidence of active unmet need (frequency + keywords + engagement) | — |
| **Competition** | Inverse of market saturation (10 = nothing exists) | 5.5 |
| **Revenue potential** | Signals of willingness to pay, B2B context | 2.0 |
| **Execution difficulty** | Inverted: 10 = start today with free tools | 6.0 |
| **Time to revenue** | Inverted: 10 = can earn this week | 5.5 |
| **Risk** | Inverted: 10 = low regulatory/incumbent risk | 7.0 |
| **Confidence** | Evidence quality: source diversity × count × engagement | — |

**Composite** = weighted average using `config.SCORE_WEIGHTS`.  
Weights are documented, adjustable, and must sum to 1.0.

Tier classification:
- **Gold** (≥ 8.0) — act this week
- **Silver** (≥ 6.5) — validate first, then act
- **Bronze** (< 6.5) — watch list

---

## Data sources

| Source | API | Auth | Rate limit |
|---|---|---|---|
| Hacker News | Official Firebase API | None | None (we self-impose 150ms between requests) |
| Reddit | Official API via PRAW | Free app credentials | 60 req/min |

More sources (RSS, Google Trends) are planned. Each source gets its own file in `collectors/` implementing the `BaseCollector` interface.

---

## Setup

### Backend (Python 3.11+)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Reddit credentials** (one-time, free):

1. Go to https://www.reddit.com/prefs/apps
2. Create app → type: **script**
3. Note your `client_id` and `client_secret`
4. Create `backend/.env`:

```
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
```

**Start the API server:**

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

API docs available at http://127.0.0.1:8000/api/docs

**Trigger a pipeline run:**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/run
```

Then watch the terminal for collection progress.

### Frontend

Open the React artifact in Claude.ai or run locally with your preferred React setup. The frontend auto-detects backend availability and falls back to static content when the API is not running.

---

## Project structure

```
bia-os/
├── backend/
│   ├── config.py                   all configuration in one place
│   ├── database.py                 SQLite schema and connection management
│   ├── models.py                   domain models (pure Python dataclasses)
│   ├── main.py                     FastAPI application
│   ├── requirements.txt
│   ├── collectors/
│   │   ├── base.py                 abstract interface all collectors implement
│   │   ├── hn_collector.py         Hacker News (official Firebase API)
│   │   └── reddit_collector.py     Reddit (official API via PRAW)
│   ├── opportunity_engine/
│   │   ├── scorer.py               7-dimension transparent scoring
│   │   └── detector.py             cross-source clustering + opportunity synthesis
│   └── api/
│       ├── opportunities.py        GET/PATCH opportunity endpoints
│       └── signals.py              GET signal feed + stats
└── README.md
```

---

## Development rules

These rules are enforced by convention, not by tooling (yet):

- **No hardcoded statistics.** If a number appears in the codebase, it must be derivable from collected data or documented as a configuration default.
- **No LLM unless labelled.** Anything described as "AI-powered" must actually call an AI model. Rule-based systems are not AI.
- **No paid APIs.** Every data source must be accessible with zero cost.
- **No giant files.** A file that does two things should be two files.
- **Business logic in engine modules, not in routes.** Routes are translation layers.

---

## Future modules (not Version 1)

These modules are planned but must not be built until Version 1 is reliable:

- **Knowledge Graph** — entity extraction + relationship mapping
- **Business Generator** — from opportunity to business model outline
- **Execution Agents** — draft outreach messages, content, proposals
- **Revenue Tracker** — connect outcomes to opportunities
- **Learning Loop** — improve scoring weights from validated/dismissed feedback

---

## What success looks like

Version 1 succeeds when it can truthfully say every week:

> "I analysed signals from Hacker News and Reddit.  
> These are the highest-confidence opportunities based on cross-source signal matching.  
> Here is the evidence. Here is the score breakdown. Here is what to do next."

Nothing else matters until this works reliably.
