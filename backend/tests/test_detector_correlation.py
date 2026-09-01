"""Focused regression tests for deterministic correlation evidence."""

from itertools import permutations

from opportunity_engine.detector import PatternDetector


def _clusters(detector, signals):
    fingerprints = {signal.id: detector._fingerprint(signal) for signal in signals}
    return detector._cluster(signals, fingerprints)


def _partition(detector, signals):
    return frozenset(
        frozenset(signal.title for signal in cluster)
        for cluster in _clusters(detector, signals)
    )


def test_same_recurrence_and_duration_do_not_establish_topic_identity(make_signal):
    detector = PatternDetector()
    signals = [
        make_signal(title="Payroll takes three hours every Friday"),
        make_signal(
            title="Cleaning the office takes three hours every Friday",
            source="reddit",
        ),
    ]

    assert len(_clusters(detector, signals)) == 2


def test_zero_overlap_financial_admin_paraphrase_requires_topic_identity(make_signal):
    detector = PatternDetector()
    signals = [
        make_signal(title="I spend three hours every Friday reconciling invoices manually"),
        make_signal(
            title="Bookkeeping cleanup eats an afternoon every week",
            source="reddit",
        ),
    ]

    assert len(_clusters(detector, signals)) == 2


def test_ambiguous_effort_words_remain_topical_outside_effort_constructions(make_signal):
    detector = PatternDetector()
    examples = {
        "spend": "Cloud spend governance reduces technology spend",
        "waste": "Waste management procurement backlog",
        "quarter": "Quarter fiscal reporting requirements",
        "lost": "Lost customer analysis identifies churn",
    }

    for word, title in examples.items():
        assert word in detector._fingerprint(make_signal(title=title))


def test_effort_filter_removes_only_the_matched_expression_not_its_topic(make_signal):
    detector = PatternDetector()
    fingerprint = detector._fingerprint(
        make_signal(title="Cloud spend review takes three hours every Friday")
    )

    assert {"cloud", "spend", "review"} <= fingerprint
    assert fingerprint.isdisjoint({"takes", "three", "hours", "every", "friday"})


def test_loose_lexical_overlap_needs_shared_local_context(make_signal):
    detector = PatternDetector()
    signals = [
        make_signal(title="Our sales pipeline is broken and deals keep stalling before close"),
        make_signal(
            title="Our CI/CD pipeline is broken and builds keep failing before deploy",
            source="reddit",
        ),
    ]

    assert len(_clusters(detector, signals)) == 2


def test_generic_effort_shape_does_not_select_an_arbitrary_cluster_by_input_order(make_signal):
    detector = PatternDetector()
    signals = [
        make_signal(title="Payroll processing takes three hours every Friday"),
        make_signal(title="Office cleaning takes three hours every Friday", source="reddit"),
        make_signal(title="Invoice reconciliation takes three hours every Friday", source="rss"),
    ]
    expected = frozenset(frozenset([signal.title]) for signal in signals)

    assert {
        _partition(detector, list(ordering))
        for ordering in permutations(signals)
    } == {expected}
