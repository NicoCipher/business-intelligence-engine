"""
tests/test_domain_system.py — Domain system tests (Milestones 1–4)

Covers:
  - DomainConfig and sub-type correctness
  - DomainRegistry lifecycle (register, get, clear, env-var parsing)
  - Business domain completeness and internal consistency
  - No import-time side effects
  - discover_and_register() end-to-end

Run directly (no pytest needed):
    cd backend && python3 tests/test_domain_system.py

Run with pytest when available:
    cd backend && pytest tests/test_domain_system.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from domains.base import (
    DomainConfig,
    DomainKeywords,
    DomainKnowledgeGraph,
    DomainMetadata,
    DomainReporting,
    DomainScoring,
    DomainSources,
    EntityType,
    RelationshipType,
    ReportSection,
    RSSFeed,
    ScoringDimension,
    ScoringThresholds,
)
from domains.registry import DomainRegistry


# ── Helpers ───────────────────────────────────────────────────────────────

def _minimal_config(domain_id: str = "test") -> DomainConfig:
    """Smallest valid DomainConfig — used for registry isolation tests."""
    return DomainConfig(
        metadata=DomainMetadata(
            id=domain_id,
            name="Test Domain",
            description="Unit-test fixture",
            version="0.0.1",
            icon="star",
            color="#000000",
            category="test",
        ),
        sources=DomainSources(),
        keywords=DomainKeywords(),
        graph=DomainKnowledgeGraph(),
        scoring=DomainScoring(
            dimensions=[
                ScoringDimension(
                    id="signal",
                    label="Signal",
                    description="Test dimension",
                    weight=1.0,
                )
            ]
        ),
        reporting=DomainReporting(title="Test Report", description=""),
    )


# ── Test classes ──────────────────────────────────────────────────────────

class TestBase:
    """Types defined in domains/base.py."""

    def test_entity_type_is_frozen(self):
        et = EntityType(name="t", description="d", keywords=("a", "b"))
        try:
            et.name = "changed"
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass  # expected

    def test_relationship_type_is_frozen(self):
        rt = RelationshipType(
            name="affects", description="d",
            valid_from=("a",), valid_to=("b",),
        )
        try:
            rt.name = "changed"
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass

    def test_scoring_thresholds_frozen(self):
        st = ScoringThresholds(high=8.0, medium=6.5)
        try:
            st.high = 9.0
            assert False
        except Exception:
            pass

    def test_report_section_frozen(self):
        rs = ReportSection(id="s", title="T", order=1)
        try:
            rs.title = "changed"
            assert False
        except Exception:
            pass

    def test_rss_feed_named_tuple(self):
        feed = RSSFeed(url="https://example.com/rss", description="Test feed")
        assert feed.url == "https://example.com/rss"
        assert feed.description == "Test feed"

    def test_scoring_validate_empty_dimensions_raises(self):
        empty = DomainScoring(dimensions=[])
        try:
            empty.validate("test")
            assert False, "Should raise with no dimensions"
        except ValueError as e:
            assert "dimension" in str(e).lower()

    def test_domain_scoring_validate_weights_sum(self):
        bad = DomainScoring(dimensions=[
            ScoringDimension(id="a", label="A", description="", weight=0.6),
            ScoringDimension(id="b", label="B", description="", weight=0.6),
        ])
        try:
            bad.validate("test")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "1.0" in str(e)

    def test_domain_scoring_validate_duplicate_ids(self):
        bad = DomainScoring(dimensions=[
            ScoringDimension(id="dup", label="D1", description="", weight=0.5),
            ScoringDimension(id="dup", label="D2", description="", weight=0.5),
        ])
        try:
            bad.validate("test")
            assert False, "Should have raised ValueError for duplicates"
        except ValueError as e:
            assert "dup" in str(e)

    def test_domain_scoring_weights_property(self):
        scoring = DomainScoring(dimensions=[
            ScoringDimension(id="x", label="X", description="", weight=0.7),
            ScoringDimension(id="y", label="Y", description="", weight=0.3),
        ])
        w = scoring.weights
        assert w == {"x": 0.7, "y": 0.3}

    def test_domain_config_validate_bad_id(self):
        cfg = _minimal_config()
        cfg.metadata = DomainMetadata(
            id="has spaces", name="Bad", description="",
            version="1.0", icon="x", color="#000000", category="test",
        )
        try:
            cfg.validate()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "alphanumeric" in str(e)

    def test_domain_config_validate_bad_color(self):
        cfg = _minimal_config()
        cfg.metadata = DomainMetadata(
            id="ok", name="OK", description="",
            version="1.0", icon="x", color="purple", category="test",
        )
        try:
            cfg.validate()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "color" in str(e)

    def test_domain_config_id_and_name_properties(self):
        cfg = _minimal_config("mytest")
        assert cfg.id == "mytest"
        assert cfg.name == "Test Domain"

    def test_knowledge_graph_get_display_name_known(self):
        kg = DomainKnowledgeGraph(display_names={"llm": "LLM"})
        assert kg.get_display_name("llm") == "LLM"

    def test_knowledge_graph_get_display_name_fallback(self):
        kg = DomainKnowledgeGraph()
        assert kg.get_display_name("unknown") == "Unknown"


class TestRegistry:
    """DomainRegistry lifecycle."""

    def setup_method(self):
        DomainRegistry.clear()

    def teardown_method(self):
        DomainRegistry.clear()

    def test_register_and_get(self):
        cfg = _minimal_config("alpha")
        DomainRegistry.register(cfg)
        result = DomainRegistry.get("alpha")
        assert result.id == "alpha"

    def test_get_unknown_raises_key_error(self):
        try:
            DomainRegistry.get("nonexistent")
            assert False, "Should have raised KeyError"
        except KeyError as e:
            assert "nonexistent" in str(e)

    def test_count_empty(self):
        assert DomainRegistry.count() == 0

    def test_count_after_register(self):
        DomainRegistry.register(_minimal_config("a"))
        DomainRegistry.register(_minimal_config("b"))
        assert DomainRegistry.count() == 2

    def test_names_sorted(self):
        DomainRegistry.register(_minimal_config("zebra"))
        DomainRegistry.register(_minimal_config("apple"))
        assert DomainRegistry.names() == ["apple", "zebra"]

    def test_is_registered_true(self):
        DomainRegistry.register(_minimal_config("x"))
        assert DomainRegistry.is_registered("x") is True

    def test_is_registered_false(self):
        assert DomainRegistry.is_registered("missing") is False

    def test_all_returns_copy(self):
        DomainRegistry.register(_minimal_config("a"))
        d1 = DomainRegistry.all()
        d1["injected"] = None  # mutate the copy
        assert "injected" not in DomainRegistry.all()  # original unchanged

    def test_get_active_returns_registered_domains(self):
        DomainRegistry.register(_minimal_config("a"))
        DomainRegistry.register(_minimal_config("b"))
        active = DomainRegistry.get_active()
        assert len(active) == 2

    def test_clear_empties_registry(self):
        DomainRegistry.register(_minimal_config("a"))
        DomainRegistry.clear()
        assert DomainRegistry.count() == 0

    def test_env_var_parsing_default(self):
        os.environ.pop("ACTIVE_DOMAINS", None)
        ids = DomainRegistry._parse_active_ids()
        assert ids == ["business"]

    def test_env_var_parsing_multiple(self):
        os.environ["ACTIVE_DOMAINS"] = "business,cybersecurity"
        ids = DomainRegistry._parse_active_ids()
        assert ids == ["business", "cybersecurity"]
        del os.environ["ACTIVE_DOMAINS"]

    def test_env_var_parsing_strips_whitespace(self):
        os.environ["ACTIVE_DOMAINS"] = " business , cybersecurity "
        ids = DomainRegistry._parse_active_ids()
        assert ids == ["business", "cybersecurity"]
        del os.environ["ACTIVE_DOMAINS"]

    def test_env_var_empty_defaults_to_business(self):
        os.environ["ACTIVE_DOMAINS"] = ""
        ids = DomainRegistry._parse_active_ids()
        assert ids == ["business"]
        del os.environ["ACTIVE_DOMAINS"]

    def test_invalid_config_raises_on_register(self):
        cfg = _minimal_config()
        cfg.metadata = DomainMetadata(
            id="bad id!", name="Bad", description="",
            version="1.0", icon="x", color="#000000", category="test",
        )
        try:
            DomainRegistry.register(cfg)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        assert not DomainRegistry.is_registered("bad id!")

    def test_discover_registers_business(self):
        os.environ["ACTIVE_DOMAINS"] = "business"
        DomainRegistry.discover_and_register()
        assert DomainRegistry.is_registered("business")
        del os.environ["ACTIVE_DOMAINS"]

    def test_discover_skips_unimplemented_domain(self):
        os.environ["ACTIVE_DOMAINS"] = "business,cybersecurity"
        DomainRegistry.discover_and_register()
        assert DomainRegistry.is_registered("business")
        assert not DomainRegistry.is_registered("cybersecurity")
        del os.environ["ACTIVE_DOMAINS"]

    def test_discover_logs_missing_domain_config(self):
        # cybersecurity __init__.py exists but has no DOMAIN_CONFIG
        os.environ["ACTIVE_DOMAINS"] = "cybersecurity"
        DomainRegistry.discover_and_register()
        assert DomainRegistry.count() == 0  # nothing registered
        del os.environ["ACTIVE_DOMAINS"]


class TestBusinessDomain:
    """Business domain module — completeness and correctness."""

    def setup_method(self):
        DomainRegistry.clear()

    def teardown_method(self):
        DomainRegistry.clear()

    def test_import_has_no_side_effects(self):
        import importlib
        import domains.business as biz_mod
        importlib.reload(biz_mod)
        assert DomainRegistry.count() == 0, (
            "Importing domains.business must not register anything"
        )

    def test_domain_config_exported(self):
        from domains.business import DOMAIN_CONFIG
        assert DOMAIN_CONFIG is not None
        assert DOMAIN_CONFIG.id == "business"

    def test_metadata_fields(self):
        from domains.business import DOMAIN_CONFIG
        m = DOMAIN_CONFIG.metadata
        assert m.id == "business"
        assert m.name == "Business Intelligence"
        assert m.icon == "briefcase"
        assert m.color.startswith("#")
        assert len(m.color) == 7
        assert m.category == "business"
        assert m.version == "1.0.0"

    def test_sources_reddit(self):
        from domains.business import DOMAIN_CONFIG
        subs = DOMAIN_CONFIG.sources.reddit_sources
        assert len(subs) >= 5
        assert "entrepreneur" in subs
        assert "freelance" in subs

    def test_sources_rss_feeds(self):
        from domains.business import DOMAIN_CONFIG
        feeds = DOMAIN_CONFIG.sources.rss_feeds
        assert len(feeds) >= 3
        for feed in feeds:
            assert feed.url.startswith("http")
            assert len(feed.description) > 0

    def test_keywords_populated(self):
        from domains.business import DOMAIN_CONFIG
        kw = DOMAIN_CONFIG.keywords
        assert len(kw.include) > 10
        assert len(kw.exclude) > 5
        assert len(kw.boost) > 5
        assert len(kw.priority) > 5

    def test_keywords_no_overlap_include_exclude(self):
        from domains.business import DOMAIN_CONFIG
        kw = DOMAIN_CONFIG.keywords
        overlap = kw.include & kw.exclude
        assert len(overlap) == 0, f"include/exclude overlap: {overlap}"

    def test_graph_entity_types(self):
        from domains.business import DOMAIN_CONFIG
        ets = DOMAIN_CONFIG.graph.entity_types
        assert set(ets.keys()) == {
            "market", "technology", "problem", "skill", "regulation"
        }
        for et in ets.values():
            assert len(et.keywords) > 0

    def test_graph_relationship_types(self):
        from domains.business import DOMAIN_CONFIG
        rts = DOMAIN_CONFIG.graph.relationship_types
        assert "affects" in rts
        assert "co-occurs" in rts
        assert len(rts) == 5

    def test_graph_display_names(self):
        from domains.business import DOMAIN_CONFIG
        g = DOMAIN_CONFIG.graph
        assert g.get_display_name("llm") == "LLM"
        assert g.get_display_name("saas") == "SaaS"
        assert g.get_display_name("smb") == "SMB"

    def test_scoring_dimension_ids(self):
        from domains.business import DOMAIN_CONFIG
        ids = [d.id for d in DOMAIN_CONFIG.scoring.dimensions]
        assert ids == [
            "demand", "competition", "revenue_potential",
            "confidence", "execution_difficulty",
            "time_to_revenue", "risk",
        ]

    def test_scoring_weights_sum_to_one(self):
        from domains.business import DOMAIN_CONFIG
        total = sum(d.weight for d in DOMAIN_CONFIG.scoring.dimensions)
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}"

    def test_scoring_dimensions_self_contained(self):
        """scoring.py must not import from keywords.py."""
        import inspect
        import domains.business.scoring as sc
        src = inspect.getsource(sc)
        assert "from domains.business.keywords" not in src
        assert "KEYWORDS" not in src

    def test_scoring_demand_dimension_keywords(self):
        from domains.business import DOMAIN_CONFIG
        demand = next(
            d for d in DOMAIN_CONFIG.scoring.dimensions if d.id == "demand"
        )
        assert "looking for" in demand.positive_keywords
        assert "frustrated" in demand.positive_keywords
        assert len(demand.negative_keywords) == 0

    def test_scoring_thresholds(self):
        from domains.business import DOMAIN_CONFIG
        t = DOMAIN_CONFIG.scoring.thresholds
        assert t.high == 8.0
        assert t.medium == 6.5
        assert t.high > t.medium

    def test_reporting_sections_ordered(self):
        from domains.business import DOMAIN_CONFIG
        sections = DOMAIN_CONFIG.reporting.sections
        assert len(sections) == 6
        orders = [s.order for s in sections]
        assert orders == sorted(orders)
        assert sections[0].id == "executive_summary"
        assert sections[-1].id == "recommendations"

    def test_validate_passes(self):
        from domains.business import DOMAIN_CONFIG
        DOMAIN_CONFIG.validate()  # must not raise

    def test_register_via_registry(self):
        from domains.business import DOMAIN_CONFIG
        DomainRegistry.register(DOMAIN_CONFIG)
        assert DomainRegistry.is_registered("business")
        retrieved = DomainRegistry.get("business")
        assert retrieved.id == "business"


# ── Simple runner (no pytest required) ───────────────────────────────────

def _run_all() -> None:
    suites = [TestBase, TestRegistry, TestBusinessDomain]
    passed = failed = 0

    for Suite in suites:
        instance = Suite()
        methods = [m for m in dir(Suite) if m.startswith("test_")]
        print(f"\n{Suite.__name__} ({len(methods)} tests)")

        for method_name in sorted(methods):
            # Call setup if defined
            if hasattr(instance, "setup_method"):
                instance.setup_method()
            try:
                getattr(instance, method_name)()
                print(f"  PASS  {method_name}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {method_name}")
                print(f"        {type(exc).__name__}: {exc}")
                failed += 1
            finally:
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method()

    print(f"\n{'='*50}")
    print(f"  {passed} passed  |  {failed} failed  |  {passed+failed} total")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    _run_all()
