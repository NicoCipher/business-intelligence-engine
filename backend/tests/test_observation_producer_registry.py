"""Tests for BIA-59 -- the producer registry and authorization boundary."""

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from collectors.base import persist_signals
from models import (
    CitationSourcePart,
    ObservationCitation,
    ObservationConditionState,
    ObservationProducerKind,
    Signal,
)
from observation_producer_registry import (
    PRODUCER_REGISTRY,
    ApprovedProducerProfile,
    ObservationProducerNotAuthorized,
    ObservationProducerRegistry,
    ObservationProducer,
    authorize_attempt,
    invoke_authorized_producer,
)
from observation_service import (
    AuthorizedObservationAttempt,
    ObservationResultInput,
    ObservationRunInput,
    ObservationServiceError,
    persist_produced,
)


def citation(text="condition remains active"):
    return ObservationCitation(CitationSourcePart.CONTENT, text)


def rule_profile(name="reviewed", revision="r1", versions=("condition-state/v1",)):
    return ApprovedProducerProfile(
        ObservationProducerKind.RULE, name, revision, frozenset(versions)
    )


def human_profile(name="operator", versions=("condition-state/v1",)):
    return ApprovedProducerProfile(
        ObservationProducerKind.HUMAN, name, None, frozenset(versions)
    )


def run_input(kind=ObservationProducerKind.RULE, name="reviewed", revision="r1",
              version="condition-state/v1", signal_id="canonical-1"):
    return ObservationRunInput(
        "run-1", signal_id, citation(), version, kind, "attempted", name, revision,
    )


# --- Production registry starts empty -------------------------------------

def test_production_registry_ships_empty():
    assert PRODUCER_REGISTRY.profiles == ()
    assert PRODUCER_REGISTRY.profile_for(ObservationProducerKind.RULE, "anything", "anything") is None


def test_production_registry_authorizes_nothing():
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(PRODUCER_REGISTRY, run_input())


# --- Registry construction / immutability ----------------------------------

def test_registry_is_frozen():
    registry = ObservationProducerRegistry((rule_profile(),))
    with pytest.raises(FrozenInstanceError):
        registry.profiles = ()


def test_profile_is_frozen():
    profile = rule_profile()
    with pytest.raises(FrozenInstanceError):
        profile.producer_name = "other"


def test_registry_rejects_mutable_profile_container():
    with pytest.raises(TypeError, match="immutable tuple"):
        ObservationProducerRegistry([rule_profile()])  # type: ignore[arg-type]


def test_registry_rejects_non_profile_entries():
    with pytest.raises(TypeError, match="ApprovedProducerProfile"):
        ObservationProducerRegistry((object(),))  # type: ignore[arg-type]


def test_duplicate_profile_rejected_at_construction():
    with pytest.raises(ValueError):
        ObservationProducerRegistry((rule_profile(), rule_profile()))


def test_profile_for_linear_lookup():
    registry = ObservationProducerRegistry((rule_profile(), human_profile()))
    assert registry.profile_for(ObservationProducerKind.RULE, "reviewed", "r1") is not None
    assert registry.profile_for(ObservationProducerKind.HUMAN, "operator", None) is not None
    assert registry.profile_for(ObservationProducerKind.MODEL, "reviewed", "r1") is None


# --- Identity policy ---------------------------------------------------------

def test_given_name_or_revision_must_be_non_empty_if_provided():
    # BIA-6 ("name/revision when defined by the approved profile") makes
    # these fields optional per-profile, not mandatory per kind -- but a
    # value that IS supplied still can't be an empty string.
    with pytest.raises(ValueError):
        ApprovedProducerProfile(ObservationProducerKind.RULE, "", "r1", frozenset({"condition-state/v1"}))
    with pytest.raises(ValueError):
        ApprovedProducerProfile(ObservationProducerKind.RULE, "reviewed", "", frozenset({"condition-state/v1"}))


def test_no_kind_based_identity_requirement_rule_and_model_may_have_null_name_or_revision():
    # The authoritative contract imposes no blanket "RULE/MODEL always
    # need a revision" rule -- whether a profile uses None is a property
    # of that specific profile, not of its kind.
    rule_no_revision = ApprovedProducerProfile(
        ObservationProducerKind.RULE, "reviewed", None, frozenset({"condition-state/v1"})
    )
    assert rule_no_revision.producer_revision is None
    model_no_name_or_revision = ApprovedProducerProfile(
        ObservationProducerKind.MODEL, None, None, frozenset({"condition-state/v1"})
    )
    assert model_no_name_or_revision.producer_name is None
    assert model_no_name_or_revision.producer_revision is None


def test_human_profile_may_have_a_revision_if_the_profile_declares_one():
    # Likewise, nothing in this module forbids a HUMAN profile from
    # declaring a revision -- that would be an unusual profile to
    # register, but it is not this module's call to reject it.
    profile = ApprovedProducerProfile(
        ObservationProducerKind.HUMAN, "operator", "r1", frozenset({"condition-state/v1"})
    )
    assert profile.producer_revision == "r1"


def test_human_profile_allows_null_revision():
    profile = human_profile()
    assert profile.producer_revision is None


def test_profile_requires_nonempty_contract_versions():
    with pytest.raises(ValueError):
        ApprovedProducerProfile(ObservationProducerKind.RULE, "reviewed", "r1", frozenset())


# --- authorize_attempt() -----------------------------------------------------

def test_authorized_rule_attempt_succeeds():
    registry = ObservationProducerRegistry((rule_profile(),))
    attempt = authorize_attempt(registry, run_input())
    assert isinstance(attempt, AuthorizedObservationAttempt)
    assert attempt.run.producer_name == "reviewed"


def test_unknown_kind_name_revision_combination_rejected():
    registry = ObservationProducerRegistry((rule_profile(),))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(name="unlisted"))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(revision="unlisted"))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(kind=ObservationProducerKind.MODEL))


def test_unlisted_contract_version_rejected_for_known_producer():
    registry = ObservationProducerRegistry((rule_profile(versions=("condition-state/v1",)),))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(version="condition-state/v2"))


def test_none_is_an_explicit_match_value_not_a_wildcard():
    # A profile declaring producer_revision=None approves only attempts
    # that also supply None -- it does not approve "any revision".
    # Symmetrically, a profile declare¡È„½¹É•Ñ”É•Ù¥Í¥½¸‘½•Ì¹½Ğ(€€€€Œµ…Ñ …¸…ÑÑ•µÁĞÑ¡…ĞÍÕÁÁ±¥•Ì9½¹”¸(€€€É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä  (€€€€€€€ÁÁÉ½Ù•‘AÉ½‘Õ•ÉAÉ½™¥±” (€€€€€€€€€€€=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹IU1°€‰É•Ù¥•İ•ˆ°9½¹”°™É½é•¹Í•Ğ¡ì‰½¹‘¥Ñ¥½¸µÍÑ…Ñ”½ØÄ‰ô¤(€€€€€€€€¤°(€€€€¤¤(€€€…ÍÍ•ÉĞÉ•¥ÍÑÉä¹ÁÉ½™¥±•}™½È¡=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹IU1°€‰É•Ù¥•İ•ˆ°9½¹”¤¥Ì¹½Ğ9½¹”(€€€…ÍÍ•ÉĞÉ•¥ÍÑÉä¹ÁÉ½™¥±•}™½È¡=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹IU1°€‰É•Ù¥•İ•ˆ°€‰ÈÄˆ¤¥Ì9½¹”((€€€½Ñ¡•É}É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä ¡ÉÕ±•}ÁÉ½™¥±”¡É•Ù¥Í¥½¸ô‰ÈÄˆ¤°¤¤(€€€…ÍÍ•ÉĞ½Ñ¡•É}É•¥ÍÑÉä¹ÁÉ½™¥±•}™½È¡=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹IU1°€‰É•Ù¥•İ•ˆ°€‰ÈÄˆ¤¥Ì¹½Ğ9½¹”(€€€…ÍÍ•ÉĞ½Ñ¡•É}É•¥ÍÑÉä¹ÁÉ½™¥±•}™½È¡=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹IU1°€‰É•Ù¥•İ•ˆ°9½¹”¤¥Ì9½¹”(()‘•˜Ñ•ÍÑ}¡Õµ…¹}…ÑÑ•µÁÑ}İ¥Ñ¡}¹Õ±±}É•Ù¥Í¥½¹}ÍÕ••‘Ì ¤è(€€€É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä ¡¡Õµ…¹}ÁÉ½™¥±” ¤°¤¤(€€€…ÑÑ•µÁĞ€ô…ÕÑ¡½É¥é•}…ÑÑ•µÁĞ (€€€€€€€É•¥ÍÑÉä°ÉÕ¹}¥¹ÁÕĞ¡­¥¹õ=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹!U58°¹…µ”ô‰½Á•É…Ñ½Èˆ°É•Ù¥Í¥½¸õ9½¹”¤(€€€€¤(€€€…ÍÍ•ÉĞ…ÑÑ•µÁĞ¹ÉÕ¸¹ÁÉ½‘Õ•É}É•Ù¥Í¥½¸¥Ì9½¹”(()‘•˜Ñ•ÍÑ}¡Õµ…¹}…ÑÑ•µÁÑ}ÍÕÁÁ±å¥¹}…}É•Ù¥Í¥½¹}¥Í}É•©•Ñ• ¤è(€€€€Œ!U58µ­¥¹ÉÕ¸…ÑÑ•µÁĞİ¥Ñ „¹½¸µ¹Õ±°É•Ù¥Í¥½¸µ…Ñ¡•Ì¹¼ÁÉ½™¥±”(€€€€Œ€¡ÁÉ½™¥±•}™½È­•åÌ½¸Ñ¡”•á…ĞÑÕÁ±”°…¹Ñ¡”½¹±äÉ•¥ÍÑ•É•!U58(€€€€ŒÁÉ½™¥±”¡…ÌÁÉ½‘Õ•É}É•Ù¥Í¥½¸õ9½¹”¤€´´É•©•Ñ•Ñ¡”Í…µ”İ…ä…¹ä(€€€€Œ½Ñ¡•ÈÕ¹±¥ÍÑ•¥‘•¹Ñ¥Ñä¥Ì°¹½ĞÙ¥„„Í•Á…É…Ñ”½‘”Á…Ñ ¸(€€€É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä ¡¡Õµ…¹}ÁÉ½™¥±” ¤°¤¤(€€€İ¥Ñ ÁåÑ•ÍĞ¹É…¥Í•Ì¡=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É9½ÑÕÑ¡½É¥é•¤è(€€€€€€€…ÕÑ¡½É¥é•}…ÑÑ•µÁĞ (€€€€€€€€€€€É•¥ÍÑÉä°ÉÕ¹}¥¹ÁÕĞ¡­¥¹õ=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹!U58°¹…µ”ô‰½Á•É…Ñ½Èˆ°É•Ù¥Í¥½¸ô‰ØÄˆ¤(€€€€€€€€¤(((Œ€´´´	åÁ…ÍÌÕ…É½¸Ñ¡”…Á…‰¥±¥ÑäÑåÁ”¥ÑÍ•±˜€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´()‘•˜Ñ•ÍÑ}…ÕÑ¡½É¥é•‘}½‰Í•ÉÙ…Ñ¥½¹}…ÑÑ•µÁÑ}…¹¹½Ñ}‰•}½¹ÍÑÉÕÑ•‘}‘¥É•Ñ±ä ¤è(€€€İ¥Ñ ÁåÑ•ÍĞ¹É…¥Í•Ì¡QåÁ•ÉÉ½È¤è(€€€€€€€ÕÑ¡½É¥é•‘=‰Í•ÉÙ…Ñ¥½¹ÑÑ•µÁĞ¡ÉÕ¸õÉÕ¹}¥¹ÁÕĞ ¤¤(((Œ€´´´AÉ½‘Õ•È¥¹Ñ•É™…”€¼ÍÕÁÁ±¥•Ñ…É•Ğ•á•ÕÑ¥½¸€´´´´´´´´´´´´´´´´´´´´´´´´´´´()±…ÍÌ}Q•ÍÑAÉ½‘Õ•Èè(€€€ÁÉ½‘Õ•É}­¥¹€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É-¥¹¹IU1(€€€ÁÉ½‘Õ•É}¹…µ”€ô€‰É•Ù¥•İ•ˆ(€€€ÁÉ½‘Õ•É}É•Ù¥Í¥½¸€ô€‰ÈÄˆ((€€€‘•˜ÁÉ½‘Õ” (€€€€€€€Í•±˜°Í¥¹…°èM¥¹…°°ÉÕ¸è=‰Í•ÉÙ…Ñ¥½¹IÕ¹%¹ÁÕĞ(€€€€¤€´ø=‰Í•ÉÙ…Ñ¥½¹I•ÍÕ±Ñ%¹ÁÕĞè(€€€€€€€É•ÑÕÉ¸=‰Í•ÉÙ…Ñ¥½¹I•ÍÕ±Ñ%¹ÁÕĞ (€€€€€€€€€€€½‰Í•ÉÙ…Ñ¥½¹}¥ô‰ÁÉ½‘Õ•Èµ½‰Í•ÉÙ…Ñ¥½¸ˆ°(€€€€€€€€€€€…¹½¹¥…±}Í¥¹…±}¥õÍ¥¹…°¹¥°(€€€€€€€€€€€½¹‘¥Ñ¥½¹}¥Ñ…Ñ¥½¸õÉÕ¸¹…ÑÑ•µÁÑ•‘}½¹‘¥Ñ¥½¹}¥Ñ…Ñ¥½¸°(€€€€€€€€€€€½¹‘¥Ñ¥½¹}ÍÑ…Ñ”õ=‰Í•ÉÙ…Ñ¥½¹½¹‘¥Ñ¥½¹MÑ…Ñ”¹Q%Y°(€€€€€€€€€€€Í•µ…¹Ñ¥}½¹ÑÉ…Ñ}Ù•ÉÍ¥½¸õÉÕ¸¹…ÑÑ•µÁÑ•‘}Í•µ…¹Ñ¥}½¹ÑÉ…Ñ}Ù•ÉÍ¥½¸°(€€€€€€€€€€€É•½É‘•‘}…Ğô‰É•½É‘•ˆ°(€€€€€€€€€€€ÍÑ…Ñ•}•Ù¥‘•¹•}¥Ñ…Ñ¥½¸õ=‰Í•ÉÙ…Ñ¥½¹¥Ñ…Ñ¥½¸ (€€€€€€€€€€€€€€€¥Ñ…Ñ¥½¹M½ÕÉ•A…ÉĞ¹=9Q9P°€‰…Ñ¥Ù”ˆ(€€€€€€€€€€€€¤°(€€€€€€€€¤(()‘•˜Ñ•ÍÑ}Ñ•ÍÑ}½¹±å}ÁÉ½‘Õ•É}•á•ÕÑ•Í}Ñ¡É½Õ¡}…ÕÑ¡½É¥é•‘}Í•ÉÙ¥•}‰½Õ¹‘…Éä (€€€µ½¹­•åÁ…Ñ °ÑµÁ}Á…Ñ (¤è(€€€µ½¹­•åÁ…Ñ ¹Í•Ñ…ÑÑÈ¡‘…Ñ…‰…Í”°€‰	}AQ ˆ°ÑµÁ}Á…Ñ €¼€‰‰¥„¹‘ˆˆ¤(€€€‘…Ñ…‰…Í”¹¥¹¥Ñ¥…±¥é” ¤(€€€½±±•Ñ•€ôM¥¹…° (€€€€€€€Í½ÕÉ”ô‰ÉÍÌˆ°(€€€€€€€Í½ÕÉ•}¥ô‰Í½ÕÉ”´Äˆ°(€€€€€€€Ñ¥Ñ±”ô‰½¹‘¥Ñ¥½¸ˆ°(€€€€€€€½¹Ñ•¹Ğô‰Q¡”½¹‘¥Ñ¥½¸É•µ…¥¹Ì…Ñ¥Ù”Ñ½‘…ä¸ˆ°(€€€€€€€¥ô‰½±±•Ñ½ÈµÑ•µÁ½É…Éäµ¥ˆ°(€€€€¤(€€€É•Í½±ÕÑ¥½¸€ôÁ•ÉÍ¥ÍÑ}Í¥¹…±Ì¡m½±±•Ñ•‘t¤¹É•Í½±ÕÑ¥½¹ÍlÁt(€€€Í¥¹…°€ôÉ•Í½±ÕÑ¥½¸¹Á•ÉÍ¥ÍÑ•‘}Í¥¹…°(€€€…ÍÍ•ÉĞÍ¥¹…°¥Ì¹½Ğ9½¹”((€€€É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä ¡ÉÕ±•}ÁÉ½™¥±” ¤°¤¤(€€€…ÕÑ¡½É¥é•€ô…ÕÑ¡½É¥é•}…ÑÑ•µÁĞ (€€€€€€€É•¥ÍÑÉä°ÉÕ¹}¥¹ÁÕĞ¡Í¥¹…±}¥õÍ¥¹…°¹¥¤(€€€€€¤(€€€ÁÉ½‘Õ•Èè=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•È€ô}Q•ÍÑAÉ½‘Õ•È ¤(€€€É•ÍÕ±Ğ€ô¥¹Ù½­•}…ÕÑ¡½É¥é•‘}ÁÉ½‘Õ•È¡ÁÉ½‘Õ•È°Í¥¹…°°…ÕÑ¡½É¥é•¤(€€€Á•ÉÍ¥ÍÑ•€ôÁ•ÉÍ¥ÍÑ}ÁÉ½‘Õ•¡É•ÍÕ±Ğ°…ÕÑ¡½É¥é•°ÁÉ½‘Õ•‘}…Ğô‰ÁÉ½‘Õ•ˆ¤((€€€…ÍÍ•ÉĞÁ•ÉÍ¥ÍÑ•¹É•…Ñ•(€€€…ÍÍ•ÉĞÁ•ÉÍ¥ÍÑ•¹½‰Í•ÉÙ…Ñ¥½¸¹½‰Í•ÉÙ…Ñ¥½¹}¥€ôô€‰ÁÉ½‘Õ•Èµ½‰Í•ÉÙ…Ñ¥½¸ˆ(€€€…ÍÍ•ÉĞÁ•ÉÍ¥ÍÑ•¹ÉÕ¸¹ÁÉ½‘Õ•É}¹…µ”€ôô€‰É•Ù¥•İ•ˆ(()‘•˜Ñ•ÍÑ}¥¹Ù½…Ñ¥½¹}É•©•ÑÍ}ÁÉ½‘Õ•É}¥‘•¹Ñ¥Ñå}µ¥Íµ…Ñ  ¤è(€€€±…ÍÌ]É½¹AÉ½‘Õ•È¡}Q•ÍÑAÉ½‘Õ•È¤è(€€€€€€€ÁÉ½‘Õ•É}É•Ù¥Í¥½¸€ô€‰ÈÈˆ((€€€É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä ¡ÉÕ±•}ÁÉ½™¥±” ¤°¤¤(€€€…ÕÑ¡½É¥é•€ô…ÕÑ¡½É¥é•}…ÑÑ•µÁĞ¡É•¥ÍÑÉä°ÉÕ¹}¥¹ÁÕĞ ¤¤(€€€Í¥¹…°€ôM¥¹…° (€€€€€€€Í½ÕÉ”ô‰ÉÍÌˆ°(€€€€€€€Í½ÕÉ•}¥ô‰Í½ÕÉ”´Äˆ°(€€€€€€€Ñ¥Ñ±”ô‰½¹‘¥Ñ¥½¸ˆ°(€€€€€€€½¹Ñ•¹Ğô‰Q¡”½¹‘¥Ñ¥½¸É•µ…¥¹Ì…Ñ¥Ù”Ñ½‘…ä¸ˆ°(€€€€€€€¥ô‰…¹½¹¥…°´Äˆ°(€€€€¤(€€€İ¥Ñ ÁåÑ•ÍĞ¹É…¥Í•Ì¡=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•É9½ÑÕÑ¡½É¥é•¤è(€€€€€€€¥¹Ù½­•}…ÕÑ¡½É¥é•‘}ÁÉ½‘Õ•È¡]É½¹AÉ½‘Õ•È ¤°Í¥¹…°°…ÕÑ¡½É¥é•¤(()‘•˜Ñ•ÍÑ}¥¹Ù½…Ñ¥½¹}É•©•ÑÍ}¹½¹…¹½¹¥…±}Í¥¹…±}¥‘•¹Ñ¥Ñä ¤è(€€€É•¥ÍÑÉä€ô=‰Í•ÉÙ…Ñ¥½¹AÉ½‘Õ•ÉI•¥ÍÑÉä ¡ÉÕ±•}ÁÉ½™¥±” ¤°¤¤(€€€…ÕÑ¡½É¥é•€ô…ÕÑ¡½É¥é•}…ÑÑ•µÁĞ¡É•¥ÍÑÉä°ÉÕ¹}¥¹ÁÕĞ ¤¤(€€€Í¥¹…°€ôM¥¹…° (€€€€€€€Í½ÕÉ”ô‰ÉÍÌˆ°(€€€€€€€Í½ÕÉ•}¥ô‰Í½ÕÉ”´Èˆ°(€€€€€€€Ñ¥Ñ±”ô‰½¹‘¥Ñ¥½¸ˆ°(€€€€€€€½¹Ñ•¹Ğô‰Q¡”½¹‘¥Ñ¥½¸É•µ…¥¹Ì…Ñ¥Ù”Ñ½‘…ä¸ˆ°(€€€€€€€¥ô‰İÉ½¹œµÍ¥¹…°ˆ°(€€€€¤(€€€İ¥Ñ ÁåÑ•ÍĞ¹É…¥Í•Ì¡=‰Í•ÉÙ…Ñ¥½¹M•ÉÙ¥•ÉÉ½È°µ…Ñ ô‰…¹½¹¥…°M¥¹…°ˆ¤è(€€€€€€€¥¹Ù½­•}…ÕÑ¡½É¥é•‘}ÁÉ½‘Õ•È¡}Q•ÍÑAÉ½‘Õ•È ¤°Í¥¹…°°…ÕÑ¡½É¥é•¤(