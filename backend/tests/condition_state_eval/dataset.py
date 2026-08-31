"""
tests/condition_state_eval/dataset.py — NIC-17 Condition State evaluation
dataset (Core + Adversarial sets only).

Uses the NIC-15 EvidenceCase contract exactly as finalized: a case is
{case_id, source_text, target_span, expected_label}, where target_span
is a literal substring of source_text identifying which condition the
label refers to (NIC-15's resolution to the multi-condition-Signal
granularity question — see CS-CORE-013a/b and CS-CORE-014a/b below for
the pattern in use: one source_text, multiple cases, one target_span
and one expected_label each).

This module is data only, deliberately mirroring
tests/semantic_eval/corpus.py's own shape and separation of data from
behavior. It does NOT touch, import for mutation, or in any way modify
that existing corpus -- test_condition_state_dataset.py verifies this
explicitly.

Three cases are DIAGNOSTIC, not scored -- see each one's `notes` field.
A gold-label audit (recorded in the NIC-17 project history) found that
NIC-15's Condition State definition does not specify:
  (1) whether an attributed/reported claim ("X said Y was fixed")
      counts as the evidence's own explicit description of a state, or
      defaults to unknown regardless of content (CS-CORE-007, -008);
  (2) whether a WH-question's grammatical presupposition counts as an
      explicit state description, or whether interrogative form always
      routes to unknown regardless of presupposed content (CS-ADV-004).
Inventing a gold label for either would mean the label reflects this
dataset author's judgment on an open question, not NIC-15's contract --
exactly the kind of undocumented policy an earlier audit pass of this
same dataset caught and corrected for CS-CORE-009/010/CS-ADV-001 (all
three were originally mislabeled by an invented "first-hand evidence
overrides attributed evidence" rule; NIC-15 already covers that shape
explicitly under "conflicting signals within the same evidence" =>
unknown, and all three are corrected below, not just flagged).

The real-world holdout set is deliberately absent from this module and
from this repository -- it is being constructed independently, sampled
from the production BIA database, and must remain unseen by anyone
tuning against Core/Adversarial. Nothing in this file should ever be
extended to include it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ConditionState(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class CaseSet(str, Enum):
    CORE = "core"
    ADVERSARIAL = "adversarial"


@dataclass(frozen=True)
class EvidenceCase:
    """
    The NIC-15 EvidenceCase contract, plus dataset-organization metadata.

    `expected_label` is None if and only if `scored` is False -- this
    invariant is what test_condition_state_dataset.py's
    test_diagnostic_cases_carry_no_label() / test_labels_valid_for_scored_cases()
    enforce, and it is the mechanism that makes scored and diagnostic
    cases structurally impossible to confuse: a diagnostic case can
    never accidentally carry a label that looks like a gold answer, and
    a scored case can never silently be missing one.
    """
    case_id: str
    source_text: str
    target_span: str
    expected_label: Optional[ConditionState]
    scored: bool
    category: str
    case_set: CaseSet
    notes: str = ""
    critical_inversion_probe: bool = False


# ── Core set (30 cases: 28 scored + 2 diagnostic) ───────────────────────

CORE_CASES: list[EvidenceCase] = [

    # Negation
    EvidenceCase("CS-CORE-001", "The bug is not fixed yet.", "The bug is not fixed yet.",
                 ConditionState.ACTIVE, True, "negation", CaseSet.CORE),
    EvidenceCase("CS-CORE-002", "This issue was never resolved.", "This issue was never resolved.",
                 ConditionState.ACTIVE, True, "negation", CaseSet.CORE),

    # Historical statements
    EvidenceCase("CS-CORE-003", "Last year we struggled with invoicing, but that's long behind us now.",
                 "Last year we struggled with invoicing, but that's long behind us now.",
                 ConditionState.RESOLVED, True, "historical_statements", CaseSet.CORE),
    EvidenceCase("CS-CORE-004", "Back in 2019 the checkout flow used to crash constantly.",
                 "Back in 2019 the checkout flow used to crash constantly.",
                 ConditionState.UNKNOWN, True, "historical_statements", CaseSet.CORE,
                 notes="'used to' confirms a past active state but says nothing about now."),

    # Recurring conditions
    EvidenceCase("CS-CORE-005", "The export bug keeps coming back every few weeks.",
                 "The export bug keeps coming back every few weeks.",
                 ConditionState.ACTIVE, True, "recurring_conditions", CaseSet.CORE),
    EvidenceCase("CS-CORE-006", "The issue was fixed, but it came back again last week.",
                 "The issue was fixed, but it came back again last week.",
                 ConditionState.ACTIVE, True, "recurring_conditions", CaseSet.CORE,
                 notes="Single coherent narrative reporting a state transition -- most-recent-state "
                       "reading of one account, not an arbitration between competing simultaneous claims."),

    # Reported/attributed statements -- DIAGNOSTIC, NIC-15 gap
    EvidenceCase("CS-CORE-007", "My coworker said the login problem was fixed.",
                 "My coworker said the login problem was fixed.",
                 None, False, "reported_attributed", CaseSet.CORE,
                 notes="DIAGNOSTIC: NIC-15 does not specify whether an attributed claim counts as the "
                       "evidence's own explicit description of a state. No gold label assigned."),
    EvidenceCase("CS-CORE-008", "According to the vendor's changelog, the bug was resolved in v2.3.",
                 "According to the vendor's changelog, the bug was resolved in v2.3.",
                 None, False, "reported_attributed", CaseSet.CORE,
                 notes="DIAGNOSTIC: same underlying NIC-15 gap as CS-CORE-007 -- must not be split from "
                       "it by source-credibility judgment. No gold label assigned."),

    # Conflicting clauses (same target, contradictory claims)
    EvidenceCase("CS-CORE-009", "Support says it's fixed, but I'm still getting the same error.",
                 "Support says it's fixed, but I'm still getting the same error.",
                 ConditionState.UNKNOWN, True, "conflicting_clauses", CaseSet.CORE,
                 notes="Corrected by gold-label audit: NIC-15 explicitly covers 'conflicting signals "
                       "within the same evidence' -> unknown. Was previously mislabeled 'active' via an "
                       "undocumented first-hand-overrides-attributed rule."),
    EvidenceCase("CS-CORE-010", "I keep hearing it's resolved, but nothing has actually changed on my end.",
                 "I keep hearing it's resolved, but nothing has actually changed on my end.",
                 ConditionState.UNKNOWN, True, "conflicting_clauses", CaseSet.CORE,
                 notes="Corrected by gold-label audit; same reasoning as CS-CORE-009."),

    # Partial resolution
    EvidenceCase("CS-CORE-011", "The crash is less frequent now but still happens occasionally.",
                 "The crash is less frequent now but still happens occasionally.",
                 ConditionState.ACTIVE, True, "partial_resolution", CaseSet.CORE),
    EvidenceCase("CS-CORE-012", "It's mostly fixed, just a couple of edge cases remain.",
                 "It's mostly fixed, just a couple of edge cases remain.",
                 ConditionState.UNKNOWN, True, "partial_resolution", CaseSet.CORE),

    # Multiple conditions in one Signal -- shared source_text, distinct target_span
    EvidenceCase("CS-CORE-013a", "The homepage loads fine now, but the search feature is still broken.",
                 "The homepage loads fine now",
                 ConditionState.RESOLVED, True, "multiple_conditions", CaseSet.CORE),
    EvidenceCase("CS-CORE-013b", "The homepage loads fine now, but the search feature is still broken.",
                 "the search feature is still broken",
                 ConditionState.ACTIVE, True, "multiple_conditions", CaseSet.CORE),
    EvidenceCase("CS-CORE-014a", "We fixed invoicing, but onboarding is still painful.",
                 "We fixed invoicing",
                 ConditionState.RESOLVED, True, "multiple_conditions", CaseSet.CORE,
                 notes="NIC-15's own worked multi-condition example."),
    EvidenceCase("CS-CORE-014b", "We fixed invoicing, but onboarding is still painful.",
                 "onboarding is still painful",
                 ConditionState.ACTIVE, True, "multiple_conditions", CaseSet.CORE,
                 notes="NIC-15's own worked multi-condition example."),

    # Hypothetical statements
    EvidenceCase("CS-CORE-015", "If this bug isn't fixed soon, we'll lose customers.",
                 "If this bug isn't fixed soon, we'll lose customers.",
                 ConditionState.UNKNOWN, True, "hypothetical", CaseSet.CORE),
    EvidenceCase("CS-CORE-016", "Imagine if the onboarding flow were this confusing for new users.",
                 "Imagine if the onboarding flow were this confusing for new users.",
                 ConditionState.UNKNOWN, True, "hypothetical", CaseSet.CORE),

    # Questions
    EvidenceCase("CS-CORE-017", "Is the invoicing bug fixed yet?", "Is the invoicing bug fixed yet?",
                 ConditionState.UNKNOWN, True, "questions", CaseSet.CORE,
                 notes="Yes/no question, presupposes nothing -- contrast with CS-ADV-004."),
    EvidenceCase("CS-CORE-018", "Has anyone found a workaround for the export issue?",
                 "Has anyone found a workaround for the export issue?",
                 ConditionState.UNKNOWN, True, "questions", CaseSet.CORE),

    # Hedging
    EvidenceCase("CS-CORE-019", "I think the issue might be resolved, not totally sure.",
                 "I think the issue might be resolved, not totally sure.",
                 ConditionState.UNKNOWN, True, "hedging", CaseSet.CORE),
    EvidenceCase("CS-CORE-020", "It seemed to be working fine when I checked earlier.",
                 "It seemed to be working fine when I checked earlier.",
                 ConditionState.UNKNOWN, True, "hedging", CaseSet.CORE),

    # Ambiguous wording
    EvidenceCase("CS-CORE-021", "The situation with onboarding has changed.",
                 "The situation with onboarding has changed.",
                 ConditionState.UNKNOWN, True, "ambiguous_wording", CaseSet.CORE),
    EvidenceCase("CS-CORE-022", "Things are different now with the billing system.",
                 "Things are different now with the billing system.",
                 ConditionState.UNKNOWN, True, "ambiguous_wording", CaseSet.CORE),

    # Text describing no condition
    EvidenceCase("CS-CORE-023", "We're planning to redesign the dashboard next quarter.",
                 "We're planning to redesign the dashboard next quarter.",
                 ConditionState.UNKNOWN, True, "no_condition", CaseSet.CORE),
    EvidenceCase("CS-CORE-024", "Our team grew by three engineers this month.",
                 "Our team grew by three engineers this month.",
                 ConditionState.UNKNOWN, True, "no_condition", CaseSet.CORE),

    # Informal language
    EvidenceCase("CS-CORE-025", "ugh this invoicing thing is still a mess lol",
                 "ugh this invoicing thing is still a mess lol",
                 ConditionState.ACTIVE, True, "informal_language", CaseSet.CORE),
    EvidenceCase("CS-CORE-026", "finally got this sorted, invoicing works now!!",
                 "finally got this sorted, invoicing works now!!",
                 ConditionState.RESOLVED, True, "informal_language", CaseSet.CORE),

    # Misleading keyword matches
    EvidenceCase("CS-CORE-027", "We signed a fixed-term contract with the new vendor.",
                 "We signed a fixed-term contract with the new vendor.",
                 ConditionState.UNKNOWN, True, "misleading_keywords", CaseSet.CORE),
    EvidenceCase("CS-CORE-028", "The report says our churn rate is still within target.",
                 "The report says our churn rate is still within target.",
                 ConditionState.UNKNOWN, True, "misleading_keywords", CaseSet.CORE,
                 notes="'still' present but attached to a stable good metric, not an unresolved problem."),

    # N1/N2 seeds (Semantic Evaluation Baseline V1's original motivating cases)
    EvidenceCase("CS-CORE-N1", "We finally fixed our invoicing headaches with a new tool",
                 "We finally fixed our invoicing headaches with a new tool",
                 ConditionState.RESOLVED, True, "seed", CaseSet.CORE,
                 notes="= Semantic Evaluation Baseline V1's N1_N2 case, extraction_signal_a."),
    EvidenceCase("CS-CORE-N2", "We still have no fix for our invoicing headaches",
                 "We still have no fix for our invoicing headaches",
                 ConditionState.ACTIVE, True, "seed", CaseSet.CORE,
                 notes="= Semantic Evaluation Baseline V1's N1_N2 case, extraction_signal_b."),
]


# ── Adversarial set (12 cases: 11 scored + 1 diagnostic) ────────────────

ADVERSARIAL_CASES: list[EvidenceCase] = [

    EvidenceCase("CS-ADV-001", "It's not resolved, despite what the release notes claim.",
                 "It's not resolved, despite what the release notes claim.",
                 ConditionState.UNKNOWN, True, "conflicting_clauses", CaseSet.ADVERSARIAL,
                 notes="Corrected by gold-label audit: same conflicting-same-evidence shape as "
                       "CS-CORE-009/010, not an inversion trap resolved by negation alone."),
    EvidenceCase("CS-ADV-002", "The service is no longer failing under load.",
                 "The service is no longer failing under load.",
                 ConditionState.RESOLVED, True, "negation", CaseSet.ADVERSARIAL,
                 critical_inversion_probe=True,
                 notes="Inversion trap: naive matching on 'failing' alone would output active."),
    EvidenceCase("CS-ADV-003", "I thought it was fixed, but it broke again the next day.",
                 "I thought it was fixed, but it broke again the next day.",
                 ConditionState.ACTIVE, True, "hedging", CaseSet.ADVERSARIAL,
                 critical_inversion_probe=True,
                 notes="'I thought' is self-hedged and discounted entirely, leaving exactly one "
                       "confident unhedged claim ('broke again') -- not a competing-claims conflict."),
    EvidenceCase("CS-ADV-004", "Why does checkout still fail after the last deploy?",
                 "Why does checkout still fail after the last deploy?",
                 None, False, "questions", CaseSet.ADVERSARIAL,
                 notes="DIAGNOSTIC: NIC-15 does not address whether a WH-question's grammatical "
                       "presupposition counts as an explicit state description. No gold label assigned."),
    EvidenceCase("CS-ADV-005", "We built a fixed-term contract for the client, not a fixed price arrangement.",
                 "We built a fixed-term contract for the client, not a fixed price arrangement.",
                 ConditionState.UNKNOWN, True, "misleading_keywords", CaseSet.ADVERSARIAL,
                 notes="Double lexical false positive plus an inert negator not adjacent to any real cue."),
    EvidenceCase("CS-ADV-006", "This isn't a permanent fix, but it's holding for now.",
                 "This isn't a permanent fix, but it's holding for now.",
                 ConditionState.UNKNOWN, True, "partial_resolution", CaseSet.ADVERSARIAL),
    EvidenceCase("CS-ADV-007", "The equation was finally solved after three attempts.",
                 "The equation was finally solved after three attempts.",
                 ConditionState.UNKNOWN, True, "misleading_keywords", CaseSet.ADVERSARIAL,
                 notes="'solved' outside any business-condition sense."),
    EvidenceCase("CS-ADV-008", "The DNS record resolved to the wrong IP again.",
                 "The DNS record resolved to the wrong IP again.",
                 ConditionState.UNKNOWN, True, "misleading_keywords", CaseSet.ADVERSARIAL,
                 notes="'resolved' in its technical/DNS sense, not a condition-resolution claim."),
    EvidenceCase("CS-ADV-009", "Our margins remain healthy despite rising costs.",
                 "Our margins remain healthy despite rising costs.",
                 ConditionState.UNKNOWN, True, "misleading_keywords", CaseSet.ADVERSARIAL,
                 notes="'remain' attached to a good outcome, not a described problem."),
    EvidenceCase("CS-ADV-010", "The onboarding flow is still confusing, or at least it was last time I checked.",
                 "The onboarding flow is still confusing, or at least it was last time I checked.",
                 ConditionState.UNKNOWN, True, "ambiguous_wording", CaseSet.ADVERSARIAL,
                 notes="Self-walked-back currency of its own claim."),
    EvidenceCase("CS-ADV-011", "Maybe it's resolved now, hard to tell without more testing.",
                 "Maybe it's resolved now, hard to tell without more testing.",
                 ConditionState.UNKNOWN, True, "hedging", CaseSet.ADVERSARIAL,
                 notes="Doubled hedge (modal + explicit self-declared uncertainty)."),
    EvidenceCase("CS-ADV-012", "The vulnerability was patched, but a workaround to bypass the patch was found days later.",
                 "The vulnerability was patched, but a workaround to bypass the patch was found days later.",
                 ConditionState.ACTIVE, True, "recurring_conditions", CaseSet.ADVERSARIAL,
                 critical_inversion_probe=True,
                 notes="Fix-then-defeated pattern, different domain register from CS-CORE-006."),
]


CASES: list[EvidenceCase] = CORE_CASES + ADVERSARIAL_CASES


# ── Validation ────────────────────────────────────────────────────────

def validate_dataset(cases: list[EvidenceCase]) -> list[str]:
    """
    Returns a list of validation error strings (empty if the dataset is
    valid). Pure function, no I/O -- importable by both
    test_condition_state_dataset.py and any future runner.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()

    for c in cases:
        if c.case_id in seen_ids:
            errors.append(f"{c.case_id}: duplicate case_id")
        seen_ids.add(c.case_id)

        if c.target_span not in c.source_text:
            errors.append(f"{c.case_id}: target_span is not a literal substring of source_text")

        if c.scored:
            if c.expected_label is None:
                errors.append(f"{c.case_id}: scored case is missing expected_label")
            elif not isinstance(c.expected_label, ConditionState):
                errors.append(f"{c.case_id}: expected_label is not a valid ConditionState")
        else:
            if c.expected_label is not None:
                errors.append(f"{c.case_id}: diagnostic case must not carry an expected_label")

        if c.case_set not in (CaseSet.CORE, CaseSet.ADVERSARIAL):
            errors.append(f"{c.case_id}: case_set must be core or adversarial only "
                           f"(no real-world holdout content belongs in this module)")

    return errors
