"""
tests/condition_state_eval/rules_interpreter.py — the deterministic
rules-based Condition State baseline (NIC-18).

A reference baseline only, per NIC-18's own framing: not the production
InterpretedObservation implementation, and its output is never read by
BIA's production intelligence pipeline. It exists to give the external
model (NIC-19) something deterministic to be compared against.

Operates on `InterpreterCase.target_span`, not the full `source_text`.
NIC-17's dataset already pre-segments multi-condition Signals into
separate cases with distinct target_spans (see CS-CORE-013a/b,
CS-CORE-014a/b) -- a human dataset author already decided "which
condition" each case is about. This means the interpreter itself does
not need its own sentence/clause segmentation logic: classifying the
given span is the whole task. (`source_text` is still carried on
InterpreterCase and available for a future interpreter that wants
surrounding context; this one deliberately doesn't use it, to stay
"intentionally small.")

Cue vocabulary, negation, and hedging rules below are exactly the
finalized design from the Condition State pressure-testing pass:
deliberately narrow, deliberately abstaining rather than guessing.
Nothing here should be extended to make a specific NIC-17 case pass --
see run_rules_baseline.py's report for the honest, measured result,
including known failures this vocabulary does not attempt to fix.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from tests.condition_state_eval.dataset import ConditionState
from tests.condition_state_eval.result import InterpreterCase, InterpreterResult, now_iso

INTERPRETER_ID = "rules-reference-baseline"
INTERPRETER_VERSION = "1.0.0"

# ── Cue vocabulary ────────────────────────────────────────────────────

_RESOLVED_CUES = ["fixed", "solved", "resolved"]
_ACTIVE_CUES = ["no fix", "remains broken", "isn't working", "doesn't work", "broken"]

# "still" and "continues to" are deliberately NOT cues -- both are
# sign-neutral continuation markers ("still profitable", "still
# available" are positive), and neither is needed: N2 already fires
# correctly on "no fix" alone.

_FIXED_BLOCKLIST = ["price", "assets", "effects", "schedule", "point", "rate", "income", "term", "cost"]
_RESOLVED_BLOCKLIST = ["to", "into"]
# "solved" has no blocklist -- its false-positive sense ("solved a
# puzzle/equation") has an open-ended object, not a closed noun set.
# Named, accepted residual risk, not silently ignored.

_NEGATORS = ["not", "never", "isn't", "wasn't"]
_DEGREE_MODIFIERS = ["fully", "really", "completely", "entirely"]
_NO_LONGER_TARGETS = ["broken", "failing"]

# Reporting-verb hedges: the natural phrasing takes a copula
# ("thought it was fixed"), not the bare verb directly against the cue.
_REPORTING_HEDGE_PREFIXES = [
    r"thought\s+it\s+(?:was|is)", r"believed\s+it\s+(?:was|is)",
    r"seemed(?:\s+to\s+be)?", r"appeared\s+to\s+be",
]
# Modal/evidentiality hedges -- includes both "may be" and "maybe",
# which are not the same string.
_MODAL_HEDGE_PREFIXES = [
    r"may\s+be", r"maybe(?:\s+it(?:'s|\s+is|\s+was))?", r"might\s+be", r"could\s+be",
    r"supposedly", r"allegedly", r"apparently",
]


def _word_boundary_pattern(phrase: str) -> str:
    """A regex fragment matching `phrase` as whole word(s) -- prevents
    e.g. 'solved' from matching inside 'resolved', or 'broken' inside
    'unbroken'."""
    return r"\b" + re.escape(phrase) + r"\b"


def _find_cue(text: str, cue: str) -> Optional[re.Match]:
    return re.search(_word_boundary_pattern(cue), text)


def _prefix_immediately_precedes(text: str, prefix_patterns: list[str], cue: str) -> bool:
    for prefix in prefix_patterns:
        pattern = re.compile(prefix + r"\s+" + _word_boundary_pattern(cue))
        if pattern.search(text):
            return True
    return False


def _is_blocklisted(text: str, match: re.Match, blocklist: list[str]) -> bool:
    after = text[match.end():].lstrip(" -")
    return any(re.match(_word_boundary_pattern(word), after) for word in blocklist)


def _negation_state(text: str, cue: str) -> Optional[str]:
    """Returns 'flip', 'abstain', or None, checking degree-modified
    negation (abstain) before plain negation (flip)."""
    for negator in _NEGATORS:
        for modifier in _DEGREE_MODIFIERS:
            combo_pattern = _word_boundary_pattern(negator) + r"\s+" + _word_boundary_pattern(modifier)
            if re.search(combo_pattern + r"\s+" + _word_boundary_pattern(cue), text):
                return "abstain"
    for negator in _NEGATORS:
        if re.search(_word_boundary_pattern(negator) + r"\s+" + _word_boundary_pattern(cue), text):
            return "flip"
    return None


def _classify(target_span: str) -> tuple[Optional[ConditionState], Optional[str]]:
    """Returns (label, matched_cue). (None, None) means abstain."""
    lowered = target_span.lower()

    # "no longer" + {broken, failing} -> resolved
    for cue in _NO_LONGER_TARGETS:
        if re.search(_word_boundary_pattern("no longer") + r"\s+" + _word_boundary_pattern(cue), lowered):
            return ConditionState.RESOLVED, f"no longer {cue}"

    for cue in _RESOLVED_CUES:
        match = _find_cue(lowered, cue)
        if not match:
            continue

        if (_prefix_immediately_precedes(lowered, _REPORTING_HEDGE_PREFIXES, cue)
                or _prefix_immediately_precedes(lowered, _MODAL_HEDGE_PREFIXES, cue)):
            return None, None

        negation = _negation_state(lowered, cue)
        if negation == "abstain":
            return None, None
        if negation == "flip":
            return ConditionState.ACTIVE, f"not {cue}"

        if cue == "fixed" and _is_blocklisted(lowered, match, _FIXED_BLOCKLIST):
            continue
        if cue == "resolved" and _is_blocklisted(lowered, match, _RESOLVED_BLOCKLIST):
            continue

        return ConditionState.RESOLVED, cue

    for cue in _ACTIVE_CUES:
        if _find_cue(lowered, cue):
            return ConditionState.ACTIVE, cue

    return None, None


def interpret(case: InterpreterCase) -> InterpreterResult:
    """
    The NIC-15 common interpreter interface: interpret(case) -> InterpreterResult.
    Deterministic and local -- no error path exists for this
    interpreter (see run_rules_baseline.py's docstring for why `error`
    is still part of the shared contract despite being unused here).
    """
    start = time.perf_counter()
    label, cue = _classify(case.target_span)
    latency_ms = (time.perf_counter() - start) * 1000

    evidence_span = case.target_span if label is not None else None

    return InterpreterResult(
        case_id=case.case_id,
        label=label,
        error=None,
        evidence_span=evidence_span,
        matched_cue=cue,
        interpreter_id=INTERPRETER_ID,
        interpreter_version=INTERPRETER_VERSION,
        run_timestamp=now_iso(),
        latency_ms=latency_ms,
    )
