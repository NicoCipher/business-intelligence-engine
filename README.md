# BIA

BIA is an early-stage, evidence-driven intelligence platform for discovering, tracking, and evaluating emerging problems and opportunities from public signals.

It helps operators move from scattered public observations to a traceable body of evidence they can review over time. BIA supports human judgment; it does not make business decisions or guarantee outcomes.

## What BIA does

- Collects observations from supported public sources.
- Retains raw signals alongside their source references.
- Tracks recurring evidence as persistent Problems.
- Records dated Opportunity assessments with supporting evidence.
- Produces weekly intelligence reports for review.

## What exists today

The current product includes public-signal collection, evidence browsing, persistent Problem tracking, Opportunity assessment and review status, and weekly reports.

The repository also contains the BIA Operations Console: a Next.js interface for reviewing Overview, Signals, Problems, Opportunities, Reports, and System health.

## High-level flow

```text
Public signals → evidence records → tracked Problems and Opportunity assessments → reports → Operations Console
```

## Supported sources

BIA currently supports collection from:

- Hacker News
- Reddit
- RSS feeds
- GitHub
- Google Trends

Source availability depends on local configuration and the source itself.

## Operations Console

The platform pairs a Python/FastAPI service with a Next.js Operations Console. The console is the current interface for inspecting BIA's evidence and intelligence records. It provides views for current context, raw signals, tracked Problems, Opportunity assessments, reports, and system health. Operators can also update an Opportunity's review status.

## Local development

Prerequisites: Python 3.11+ and Node.js 20.9+.

Review [`.env.example`](.env.example) and configure your local environment before running services. Do not commit configuration values.

Start the backend from the repository root:

```bash
python3.11 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn main:app --app-dir backend --reload
```

In a second terminal, install and start the Operations Console:

```bash
npm ci
npm run dev
```

## Testing

Run backend tests:

```bash
backend/.venv/bin/python -m pytest backend/tests
```

Run console checks:

```bash
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e
```

## Status and limitations

BIA is early-stage software for evidence-led research and operational review. Public-source coverage can be incomplete or change over time, and BIA's records and assessments should be verified by a human before they inform a decision. It is not a source of guaranteed opportunities, factual certainty, or business advice.
