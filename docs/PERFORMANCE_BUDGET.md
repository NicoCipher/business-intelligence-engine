# Operations Console Performance Budget

Phase 1 preserves a server-rendered operations workstation rather than a client dashboard.

- Root client runtime: at most **150 KiB gzip**, enforced by `npm run check:performance` after `npm run build`.
- No charting, rich-text, data-grid, or client data-fetching dependencies.
- Backend reads happen in Server Components. The only client code is the Next.js-required error recovery boundary.
- Lists are server-paginated; the signal feed is capped at 50 rows per view and Problems/Opportunities at 20.
- Independent Overview panels stream behind narrow Suspense boundaries.

Any change that adds client interactivity must document why server rendering or native HTML forms cannot meet the requirement, and must remain within the enforced runtime budget.
