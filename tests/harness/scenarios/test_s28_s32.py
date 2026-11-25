import pytest


@pytest.mark.prompt_b
@pytest.mark.xfail(strict=True, reason="Prompt B not yet shipped")
def test_s28_late_signup_after_same_tab_or_cross_tab_rotation():
    """S28. Late signup after same-tab or cross-tab rotation."""
    # TODO: New credential still owns tab; abandoned signup cannot install a key, R3-01.
    pytest.skip("Scenario S28: awaiting Prompt B")


@pytest.mark.prompt_b
@pytest.mark.xfail(strict=True, reason="Prompt B not yet shipped")
def test_s29_rotation_between_real_import_chunks_then_restart():
    """S29. Rotation between real import chunks then restart."""
    # TODO: Only old owner has committed prefix; new owner has no file/draft or rows, R12/R3-02.
    pytest.skip("Scenario S29: awaiting Prompt B")


@pytest.mark.prompt_b
@pytest.mark.xfail(strict=True, reason="Prompt B not yet shipped")
def test_s30_domain_switch_with_detail_search_bulk_in_flight_duplicated_public_ids():
    """S30. Domain switch with detail/search/bulk in flight, duplicated public IDs."""
    # TODO: Stale results cannot display, select or mutate the new project. Review navigation carries identifiers only, F7-01.
    pytest.skip("Scenario S30: awaiting Prompt B")


@pytest.mark.prompt_b
@pytest.mark.xfail(strict=True, reason="Prompt B not yet shipped")
def test_s31_tag_draft_during_category_save_verify_and_navigation():
    """S31. Tag draft during category save/verify and navigation."""
    # TODO: Edit is blocked or explicitly preserved; no silent loss, R3-03.
    pytest.skip("Scenario S31: awaiting Prompt B")


@pytest.mark.prompt_b
@pytest.mark.xfail(strict=True, reason="Prompt B not yet shipped")
def test_s32_incompatible_json_and_failed_lazy_chunk():
    """S32. Incompatible JSON and failed lazy chunk."""
    # TODO: Scoped error, usable navigation, recovery after retry, R3-08.
    pytest.skip("Scenario S32: awaiting Prompt B")
