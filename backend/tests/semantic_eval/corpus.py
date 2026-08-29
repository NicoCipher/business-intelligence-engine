"""
tests/semantic_eval/corpus.py — Semantic Evaluation Baseline V1 corpus.

Reviewed design: see the Semantic Evaluation Baseline V1 design milestone
(docs/HANDOFF.md history around fda65bd). This file is data only — no
production code is imported for its side effects, no assertions live
here, and nothing in this module executes anything against the real
pipeline. `run_baseline.py` reads this corpus and dispatches each case
to exactly one real, existing function, isolated by layer; nothing here
decides how a case is evaluated.

Every case carries one of four classifications, and the classification
is the whole point of this corpus existing rather than being an
ordinary test suite:

  PRESERVE      — desirable current behavior. Only these five cases
                  (C1, C3, P1, P2, S3) become ordinary pytest regression
                  tests, in test_semantic_eval_controls.py.
  LIMITATION    — a real, currently-measurable gap in today's system.
                  Diagnostic-only. Must never be asserted as correct
                  behavior to preserve -- a future fix is expected to
                  change these results, and that should read as
                  progress, not a regression.
  INEXPRESSIBLE — no function, field, or return value anywhere in this
                  codebase represents the concept being asked about
                  (see CONTESTED_VERDICT_NOTE below). Not a Case at
                  all -- there is nothing to call. Documented as prose,
                  not as an executable fixture, on purpose.
  UNRESOLVED    — the mechanism produces an answer, but no ADR/RFC
                  defines what the *correct* answer should be (see P3).
                  The runner reports the observed behavior without an
                  expected value -- asserting one here would decide an
                  open architectural question through a test fixture.

Layer isolation: every case is scoped to exactly one mechanism.
Clustering cases call `_fingerprint`/`_cluster` directly on two Signals.
Canonicalization cases call `find_match()` directly against a
hand-inserted candidate Problem row, bypassing extraction entirely.
Extraction cases call `EntityExtractor.extract()` directly, bypassing
clustering/scoring. Scoring cases call one `compute_*` function
directly with a hand-built blob, bypassing extraction/clustering/
canonicalization. Nothing in this corpus runs the full pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from models import Signal


class Classification(str, Enum):
    PRESERVE = "preserve"
    LIMITATION = "limitation"
    UNRESOLVED = "unresolved"


class Layer(str, Enum):
    CLUSTERING = "clustering"
    CANONICALIZATION = "canonicalization"
    EXTRACTION = "extraction"
    SCORING = "scoring"
    CONFIDENCE = "confidence"


@dataclass
class SignalSpec:
    """A minimal, declarative description of a Signal fixture. Kept
    separate from `models.Signal` itself so the corpus stays pure data
    -- `to_signal()` is the only place this touches production code,
    and it does nothing but construct an object, no side effects."""
    title: str
    content: str = ""
    source: str = "hn"
    platform_score: int = 0
    comment_count: int = 0

    def to_signal(self) -> Signal:
        return Signal(
            source=self.source,
            source_id=f"semantic-eval-{uuid4()}",
            title=self.title,
            content=self.content,
            platform_score=self.platform_score,
            comment_count=self.comment_count,
        )


@dataclass
class Case:
    id: str
    capability: str
    layer: Layer
    classification: Classification
    mechanism: str
    rationale: str

    # ── Clustering payload ──────────────────────────────────────────
    signal_a: SignalSpec | None = None
    signal_b: SignalSpec | None = None
    expected_cluster: bool | None = None   # only set for PRESERVE cases

    # ── Canonicalization payload ────────────────────────────────────
    candidate_entity_ids: list[str] | None = None
    candidate_title: str | None = None
    new_entity_ids: list[str] | None = None
    new_title: str | None = None
    expected_match: bool | None = None     # only set for PRESERVE cases; None for UNRESOLVED

    # ── Extraction payload (paired comparison) ──────────────────────
    extraction_signal_a: SignalSpec | None = None
    extraction_signal_b: SignalSpec | None = None

    # ── Scoring payload ──────────────────────────────────────────────
    scoring_signals: list[SignalSpec] | None = None
    scoring_function: str | None = None    # "demand" | "competition" | "risk"

    # ── Confidence payload (paired comparison) ───────────────────────
    confidence_agreeing: list[SignalSpec] | None = None
    confidence_contradicting: list[SignalSpec] | None = None


# ── 3.1 / 3.2 Clustering equivalence and separation ─────────────────────

C1 = Case(
    id="C1", capability="clustering equivalence (positive control)",
    layer=Layer.CLUSTERING, classification=Classification.PRESERVE,
    mechanism="PatternDetector()._fingerprint() + ._cluster()",
    rationale=(
        "Near-identical phrasing describing the same funding event -- "
        "should trivially cluster; this is what the mechanism was built for."
    ),
    signal_a=SignalSpec(title="AI coding assistant startup raises $50M in funding round"),
    signal_b=SignalSpec(title="AI coding assistant raises $50M funding"),
    expected_cluster=True,
)

C2 = Case(
    id="C2", capability="clustering equivalence (paraphrase drift)",
    layer=Layer.CLUSTERING, classification=Classification.LIMITATION,
    mechanism="PatternDetector()._fingerprint() + ._cluster()",
    rationale=(
        "Both signals describe the identical underlying pain (manual, "
        "recurring, time-consuming financial admin) with zero shared "
        "vocabulary after stopword removal. Ground truth: should cluster. "
        "Diagnostic only -- not asserted as correct behavior to preserve."
    ),
    signal_a=SignalSpec(title="I spend three hours every Friday reconciling invoices manually"),
    signal_b=SignalSpec(title="Bookkeeping cleanup eats an afternoon every week"),
)

C3 = Case(
    id="C3", capability="clustering separation (positive control)",
    layer=Layer.CLUSTERING, classification=Classification.PRESERVE,
    mechanism="PatternDetector()._fingerprint() + ._cluster()",
    rationale="Unrelated topics, zero shared vocabulary -- must not cluster.",
    signal_a=SignalSpec(title="Best restaurants in Austin for tacos"),
    signal_b=SignalSpec(title="New JavaScript framework released this week"),
    expected_cluster=False,
)

C4 = Case(
    id="C4", capability="clustering separation (lexical homonym, sentiment held constant)",
    layer=Layer.CLUSTERING, classification=Classification.LIMITATION,
    mechanism="PatternDetector()._fingerprint() + ._cluster()",
    rationale=(
        "Both sentences are structurally parallel complaints (same polarity "
        "-- 'broken', both) about unambiguously different real-world "
        "processes (a sales pipeline vs. a software deployment pipeline), "
        "sharing vocabulary purely through the business homonym 'pipeline'. "
        "This deliberately holds sentiment/polarity constant so the failure "
        "being measured is topic separation, not claim agreement. Ground "
        "truth: must not cluster. Diagnostic only."
    ),
    signal_a=SignalSpec(title="Our sales pipeline is broken and deals keep stalling before close"),
    signal_b=SignalSpec(title="Our CI/CD pipeline is broken and builds keep failing before deploy"),
)


# ── 3.3 / 3.4 Problem identity equivalence and separation ───────────────

P1 = Case(
    id="P1", capability="Problem identity equivalence (positive control)",
    layer=Layer.CANONICALIZATION, classification=Classification.PRESERVE,
    mechanism="canonicalizer.find_match()",
    rationale="Same entities, close title wording -- should match the existing Problem.",
    candidate_entity_ids=["problem:invoicing", "market:freelancer"],
    candidate_title="Freelancers struggle with manual invoicing",
    new_entity_ids=["problem:invoicing", "market:freelancer"],
    new_title="Freelancer invoicing is a manual struggle",
    expected_match=True,
)

P2 = Case(
    id="P2", capability="Problem identity equivalence (wording drift, entities already correct)",
    layer=Layer.CANONICALIZATION, classification=Classification.PRESERVE,
    mechanism="canonicalizer.find_match()",
    rationale=(
        "Substantially different title wording, but entities are already "
        "identical -- shows wording drift is not actually a canonicalization "
        "problem as long as entity extraction captured the right entities. "
        "This is a positive control precisely because it isolates that the "
        "ceiling sits at extraction, not here."
    ),
    candidate_entity_ids=["problem:invoicing", "market:freelancer"],
    candidate_title="Freelancers hate manually creating invoices every week",
    new_entity_ids=["problem:invoicing", "market:freelancer"],
    new_title="Independent contractors are frustrated with invoice paperwork",
    expected_match=True,
)

P3 = Case(
    id="P3", capability="Problem identity separation (actor/context distinction)",
    layer=Layer.CANONICALIZATION, classification=Classification.UNRESOLVED,
    mechanism="canonicalizer.find_match()",
    rationale=(
        "Same nominal topic (invoicing), different customer segments "
        "(freelancer vs. enterprise IT), entity extraction under-specified "
        "(only a single 'problem:invoicing' entity in both, no market "
        "entity). Neither ADR-001 (Problem as Canonical Identity) nor "
        "ADR-009 (Weighted Canonical Matching, the currently-Accepted "
        "matching design) takes a position on whether actor/market scope "
        "should be part of Problem identity -- ADR-009 explicitly pools "
        "all entity types into one flat set, type-agnostic, by design, and "
        "reserves any Problem-level eligibility change for a future, "
        "explicitly-reasoned ADR that does not yet exist. RFC-002's "
        "'Customer' facet gathers evidence about an already-identified "
        "Problem; it does not redefine find_match()'s matching boundary "
        "either. The runner reports current behavior only -- no expected "
        "value is asserted, because asserting one would decide this open "
        "question through a test fixture rather than through governance."
    ),
    candidate_entity_ids=["problem:invoicing"],
    candidate_title="Freelancer invoicing is a nightmare",
    new_entity_ids=["problem:invoicing"],
    new_title="Enterprise IT invoicing reconciliation nightmare",
    expected_match=None,
)


# ── 3.5 Negation/polarity — extraction layer (paired diagnostic) ────────

N1_N2 = Case(
    id="N1_N2", capability="negation/polarity sensitivity (extraction)",
    layer=Layer.EXTRACTION, classification=Classification.LIMITATION,
    mechanism="EntityExtractor().extract()",
    rationale=(
        "N1 describes a RESOLVED problem; N2 describes an ACTIVE, ongoing "
        "one. A human reader would treat these very differently. Ground "
        "truth: extraction should distinguish them, or at minimum represent "
        "polarity/resolution-state as an attribute. Diagnostic only -- not "
        "desirable behavior to preserve. A future extractor that correctly "
        "distinguishes these should be free to make this pair diverge, and "
        "that divergence should read as improvement, not a broken test."
    ),
    extraction_signal_a=SignalSpec(title="We finally fixed our invoicing headaches with a new tool"),
    extraction_signal_b=SignalSpec(title="We still have no fix for our invoicing headaches"),
)


# ── 3.6 Scoring: semantic support per dimension ──────────────────────────

S1 = Case(
    id="S1", capability="scoring dimension semantic support (relevance-blind keyword match)",
    layer=Layer.SCORING, classification=Classification.LIMITATION,
    mechanism="domains.business.scoring_functions.compute_risk()",
    rationale=(
        "'apple announced' is a literal RISK_KEYWORDS entry, meant to flag "
        "a major incumbent entering this exact market. Here Apple's "
        "announcement is about an unrelated OS accessibility feature -- the "
        "keyword fires with zero relevance to whatever market/problem this "
        "Problem cluster is actually about. Tests whether an inferred "
        "dimension is semantically supported by the evidence that triggered "
        "it, not whether evidence is reused across dimensions (evidence "
        "legitimately supporting multiple dimensions is not itself a "
        "problem). Diagnostic only."
    ),
    scoring_signals=[SignalSpec(
        title="I love how Apple announced better accessibility features in their new OS update"
    )],
    scoring_function="risk",
)

S2 = Case(
    id="S2", capability="scoring dimension semantic support (existing solution as market gap)",
    layer=Layer.SCORING, classification=Classification.LIMITATION,
    mechanism="domains.business.scoring_functions.compute_competition()",
    rationale=(
        "'I built this because nothing like it existed' is a founder's own "
        "launch-announcement phrasing for an EXISTING product -- the "
        "opposite of an unmet need. Both 'built this because' and 'nothing "
        "like it' are literal LOW_COMPETITION_SIGNALS entries, so this "
        "fires the mechanism's strongest, most confident market-gap reading "
        "in exactly the wrong direction. A stronger, more concrete "
        "wrong-direction case than S1. Diagnostic only."
    ),
    scoring_signals=[SignalSpec(title="I built this because nothing like it existed")],
    scoring_function="competition",
)

S3 = Case(
    id="S3", capability="scoring dimension semantic support (positive control)",
    layer=Layer.SCORING, classification=Classification.PRESERVE,
    mechanism="domains.business.scoring_functions.compute_demand()",
    rationale="Textbook, unambiguous active solution-seeking language.",
    scoring_signals=[SignalSpec(title="Is there a tool to automate weekly invoice reconciliation?")],
    scoring_function="demand",
)


# ── 3.8 Contradiction — confidence layer (paired diagnostic) ────────────

CONFIDENCE_PAIR = Case(
    id="CONFIDENCE_PAIR", capability="contradiction handling (confidence blindness)",
    layer=Layer.CONFIDENCE, classification=Classification.LIMITATION,
    mechanism="opportunity_engine.scorer.compute_confidence()",
    rationale=(
        "Signal count, engagement, and source diversity held constant "
        "between an all-agreeing set and a set where half the evidence "
        "contradicts the other half. compute_confidence() takes `blob` as "
        "an unused parameter -- confidence is computed purely from signal "
        "structure, never text content -- so it cannot distinguish "
        "corroborated from contested evidence. Diagnostic only, and "
        "explicitly NOT a regression control: a future contradiction-aware "
        "confidence calculation is expected to make these diverge, and "
        "that divergence should read as success, not a broken test."
    ),
    confidence_agreeing=[
        SignalSpec(title="We need X"), SignalSpec(title="Really need X"),
        SignalSpec(title="X would help us"), SignalSpec(title="Please build X"),
    ],
    confidence_contradicting=[
        SignalSpec(title="We need X"), SignalSpec(title="Really need X"),
        SignalSpec(title="We tried X and it didn't help"),
        SignalSpec(title="Existing tool Y already does X fine"),
    ],
)


CORPUS: list[Case] = [C1, C2, C3, C4, P1, P2, P3, N1_N2, S1, S2, S3, CONFIDENCE_PAIR]

PRESERVE_CASE_IDS = frozenset({"C1", "C3", "P1", "P2", "S3"})


# ── Inexpressible — documented as prose, not as a runnable Case ─────────
#
# "Does the system recognize this cluster of evidence as CONTESTED
# (meaningful disagreement) vs. SUPPORTED (corroborated)?" cannot be
# expressed as a Case at all. No function, field, database column, or
# return value anywhere in this codebase represents a contested/
# supported verdict over a set of evidence. Writing an executable
# assertion here would require inventing the very capability under
# discussion -- exactly what this milestone was told not to do. This is
# deliberately not a Case with a layer/mechanism/expected value; it is
# recorded here only as a named gap for run_baseline.py's report to
# quote verbatim, never as something the runner attempts to call.
CONTESTED_VERDICT_NOTE = (
    "INEXPRESSIBLE: no interface exists to ask whether a set of evidence "
    "is CONTESTED vs. SUPPORTED. compute_confidence() (see CONFIDENCE_PAIR, "
    "a LIMITATION case) measures corroboration volume, not agreement, and "
    "is the closest existing mechanism -- but it has no contested/supported "
    "output slot at all, only a scalar score. No new interface was created "
    "to make this executable, per the reviewed design."
)
