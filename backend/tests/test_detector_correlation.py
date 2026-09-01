"""Focused regression tests for deterministic correlation evidence."""

from opportunity_engine.detector import PatternDetector


def _clusters(detector, signals):
    fingerprints = {signal.id: detector._fingerprint(signal) for signal in signals}
    return detector._cluster(signals, fingerprints)


def test_recurring_time_cost_shape_clusters_paraphrased_operational_burden(make_signal):
    detector = PatternDetector()
    signals = [
        make_signal(title="Monthly reporting consumes two mornings"),
        make_signal(title="Every week, data-entry cleanup takes three hours", source="reddit"),
    ]

    assert len(_clusters(detector, signals)) == 1


def test_recurring_shape_without_explicit_time_cost_does_not_override_topic_separation(make_signal):
    detector = PatternDetector()
    signals = [
        make_signal(title="Every Friday I reconcile invoices manually"),
        make_signal(title="Bookkeeping cleanup eats an afternoon every week", source="reddit"),
    ]

    assert len(_clusters(detector, signals)) == 2


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
