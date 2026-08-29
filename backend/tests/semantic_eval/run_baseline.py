"""
tests/semantic_eval/run_baseline.py — Semantic Evaluation Baseline V1
diagnostic runner.

Reads tests/semantic_eval/corpus.py and dispatches each Case to exactly
one real, existing, unmodified production function, isolated by layer
(see corpus.py's module docstring for the full layer-isolation
rationale). Prints a report grouped by capability and by layer, with
per-layer metrics kept separate rather than collapsed into one
"semantic accuracy" number.

This is a diagnostic, not a test suite: LIMITATION and UNRESOLVED cases
are *expected* to disagree with what a human would want, and that's the
entire point of running this -- it's how the baseline gets recorded
before anything changes. Only PRESERVE cases (also covered by
test_semantic_eval_controls.py) have a right/wrong answer this script
enforces via a nonzero exit code.

Uses a throwaway, isolated SQLite database (not the project's real
data) for the canonicalization cases only -- clustering, extraction,
scoring, and confidence cases touch no database at all.

Run with:
    cd backend && python -m tests.semantic_eval.run_baseline
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import database
from domains.business.scoring_functions import compute_competition, compute_demand, compute_risk
from knowledge_graph.extractor import EntityExtractor
from opportunity_engine.canonicalizer import find_match
from opportunity_engine.detector import PatternDetector
from tests.semantic_eval.corpus import (
    CONTESTED_VERDICT_NOTE,
    CORPUS,
    PRESERVE_CASE_IDS,
    Case,
    Classification,
    Layer,
)

_SCORING_FUNCTIONS = {
    "demand": compute_demand,
    "competition": compute_competition,
    "risk": compute_risk,
}


# ── Per-layer dispatch — each function calls exactly one real mechanism ──

def _run_clustering(case: Case) -> dict:
    detector = PatternDetector()
    sig_a = case.signal_a.to_signal()
    sig_b = case.signal_b.to_signal()
    fp_a = detector._fingerprint(sig_a)
    fp_b = detector._fingerprint(sig_b)
    jaccard = detector._jaccard(fp_a, fp_b)

    clusters = detector._cluster([sig_a, sig_b], {sig_a.id: fp_a, sig_b.id: fp_b})
    clustered_together = len(clusters) == 1 and len(clusters[0]) == 2

    return {
        "fingerprint_a": sorted(fp_a), "fingerprint_b": sorted(fp_b),
        "jaccard": round(jaccard, 4), "clustered_together": clustered_together,
    }


def _run_canonicalization(case: Case, conn) -> dict:
    # Fresh candidate Problem row per case, isolated by a unique domain
    # tag so cases never see each other's fixtures.
    candidate_id = f"cand-{case.id}"
    domain = f"semantic-eval-{case.id}"
    import json
    conn.execute(
        """
        INSERT INTO problems
          (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at,
           lifecycle_state, lifecycle_updated_at, trend, trend_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'new', ?, 'unknown', ?)
        """,
        (candidate_id, domain, case.candidate_title, json.dumps(case.candidate_entity_ids),
         database._now(), database._now(), database._now(), database._now(),
         database._now(), database._now()),
    )
    conn.commit()

    result = find_match(case.new_entity_ids, case.new_title, domain, conn)
    matched = result is not None and result["problem_id"] == candidate_id
    return {"matched": matched, "raw_result": result}


def _run_extraction(case: Case) -> dict:
    extractor = EntityExtractor()
    entities_a = {(e.type, e.name) for e in extractor.extract(case.extraction_signal_a.to_signal()).entities}
    entities_b = {(e.type, e.name) for e in extractor.extract(case.extraction_signal_b.to_signal()).entities}
    return {
        "entities_a": sorted(entities_a), "entities_b": sorted(entities_b),
        "identical": entities_a == entities_b,
    }


def _run_scoring(case: Case) -> dict:
    signals = [s.to_signal() for s in case.scoring_signals]
    blob = " ".join(s.full_text for s in signals)
    fn = _SCORING_FUNCTIONS[case.scoring_function]
    score, reason, evidence = fn(signals, blob)
    return {"score": score, "reason": reason, "evidence": evidence}


def _run_confidence(case: Case) -> dict:
    from domains.business.scoring_functions import compute_confidence
    agreeing = [s.to_signal() for s in case.confidence_agreeing]
    contradicting = [s.to_signal() for s in case.confidence_contradicting]
    blob_a = " ".join(s.full_text for s in agreeing)
    blob_b = " ".join(s.full_text for s in contradicting)
    score_a, reason_a, evidence_a = compute_confidence(agreeing, blob_a)
    score_b, reason_b, evidence_b = compute_confidence(contradicting, blob_b)
    return {
        "agreeing": {"score": score_a, "reason": reason_a, "evidence": evidence_a},
        "contradicting": {"score": score_b, "reason": reason_b, "evidence": evidence_b},
        "identical": (score_a, reason_a, evidence_a) == (score_b, reason_b, evidence_b),
    }


_DISPATCH = {
    Layer.CLUSTERING: _run_clustering,
    Layer.EXTRACTION: _run_extraction,
    Layer.SCORING: _run_scoring,
    Layer.CONFIDENCE: _run_confidence,
}


def run_case(case: Case, conn) -> dict:
    if case.layer is Layer.CANONICALIZATION:
        return _run_canonicalization(case, conn)
    return _DISPATCH[case.layer](case)


# ── Report ────────────────────────────────────────────────────────────

def _preserve_check(case: Case, result: dict) -> bool | None:
    """Only meaningful for PRESERVE cases -- returns whether the actual
    result matched the case's expected value. None for every other
    classification, since LIMITATION/UNRESOLVED cases have no
    pass/fail by design."""
    if case.classification is not Classification.PRESERVE:
        return None
    if case.layer is Layer.CLUSTERING:
        return result["clustered_together"] == case.expected_cluster
    if case.layer is Layer.CANONICALIZATION:
        return result["matched"] == case.expected_match
    if case.layer is Layer.SCORING:
        return result["score"] is not None  # S3: any computed score confirms the path ran
    return None


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="bia-semantic-eval-")
    database.DB_PATH = Path(tmp_dir) / "semantic_eval.db"
    database.initialize()

    print("=" * 78)
    print("Semantic Evaluation Baseline V1 — diagnostic run")
    print(f"(isolated database: {database.DB_PATH})")
    print("=" * 78)

    results: dict[str, dict] = {}
    preserve_failures: list[str] = []

    with database.get_connection() as conn:
        for case in CORPUS:
            result = run_case(case, conn)
            results[case.id] = result
            check = _preserve_check(case, result)

            print(f"\n[{case.classification.value.upper():10s}] {case.id} — {case.capability}")
            print(f"  layer:     {case.layer.value}")
            print(f"  mechanism: {case.mechanism}")
            print(f"  result:    {result}")
            if check is not None:
                status = "PASS" if check else "FAIL"
                print(f"  preserve check: {status}")
                if not check:
                    preserve_failures.append(case.id)

    print("\n" + "=" * 78)
    print("INEXPRESSIBLE (documented, not run — no interface exists):")
    print(f"  {CONTESTED_VERDICT_NOTE}")

    print("\n" + "=" * 78)
    print("Per-layer aggregate measurements")
    print("=" * 78)
    _print_layer_metrics(results)

    print("\n" + "=" * 78)
    if preserve_failures:
        print(f"PRESERVE case(s) FAILED: {preserve_failures} — investigate before relying on this baseline.")
    else:
        print(f"All {len(PRESERVE_CASE_IDS)} PRESERVE cases behaved as expected.")
    print("=" * 78)

    return 1 if preserve_failures else 0


def _print_layer_metrics(results: dict[str, dict]) -> None:
    clustering_eq = [c for c in CORPUS if c.layer is Layer.CLUSTERING and "equivalence" in c.capability]
    clustering_sep = [c for c in CORPUS if c.layer is Layer.CLUSTERING and "separation" in c.capability]
    canon_eq = [c for c in CORPUS if c.layer is Layer.CANONICALIZATION and "equivalence" in c.capability]
    canon_unresolved = [c for c in CORPUS if c.layer is Layer.CANONICALIZATION and c.classification is Classification.UNRESOLVED]

    def _rate(cases, key_fn):
        if not cases:
            return "n/a"
        hits = sum(1 for c in cases if key_fn(results[c.id]))
        return f"{hits}/{len(cases)}"

    print(f"  Clustering — equivalence cases clustering together: "
          f"{_rate(clustering_eq, lambda r: r['clustered_together'])}")
    print(f"  Clustering — separation cases NOT clustering together: "
          f"{_rate(clustering_sep, lambda r: not r['clustered_together'])}")
    print(f"  Canonicalization — equivalence cases matched: "
          f"{_rate(canon_eq, lambda r: r['matched'])}")
    print(f"  Canonicalization — UNRESOLVED cases (reported, not scored): "
          f"{[(c.id, results[c.id]['matched']) for c in canon_unresolved]}")

    if "N1_N2" in results:
        print(f"  Extraction — polarity pair identical entity output: {results['N1_N2']['identical']}")

    for sid in ("S1", "S2", "S3"):
        if sid in results:
            r = results[sid]
            print(f"  Scoring — {sid}: score={r['score']} reason={r['reason']!r}")

    if "CONFIDENCE_PAIR" in results:
        r = results["CONFIDENCE_PAIR"]
        print(f"  Confidence — agreeing vs. contradicting sets produce identical output: {r['identical']}")


if __name__ == "__main__":
    sys.exit(main())
