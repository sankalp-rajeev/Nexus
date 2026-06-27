"""Unit tests: validator logic (Section 9.5)."""

from __future__ import annotations


from services.critic.validator import validate_patch_proposal


def _good_proposal(**overrides) -> dict:
    base = {
        "patch_type": "PROMPT_PATCH",
        "target_component": "llm_system_prompt",
        "explanation": "The LLM output was ungrounded because the system prompt lacked a context-restriction instruction.",
        "patch_content": "SYSTEM: Answer only using information present in the provided context. If absent, say so.",
        "confidence": "HIGH",
        "estimated_impact": "Hallucination rate expected to decrease by 60-80%",
    }
    base.update(overrides)
    return base


def test_valid_proposal_passes():
    ok, reason = validate_patch_proposal(_good_proposal())
    assert ok is True
    assert reason == ""


def test_missing_field_rejected():
    p = _good_proposal()
    del p["patch_content"]
    ok, reason = validate_patch_proposal(p)
    assert ok is False
    assert "patch_content" in reason


def test_too_short_field_rejected():
    ok, reason = validate_patch_proposal(_good_proposal(explanation="short"))
    assert ok is False
    assert "explanation" in reason


def test_invalid_patch_type_rejected():
    ok, reason = validate_patch_proposal(_good_proposal(patch_type="INVALID_TYPE"))
    assert ok is False
    assert "patch_type" in reason


def test_invalid_confidence_rejected():
    ok, reason = validate_patch_proposal(_good_proposal(confidence="VERY_HIGH"))
    assert ok is False
    assert "confidence" in reason


def test_vague_phrase_try_improving_rejected():
    ok, reason = validate_patch_proposal(
        _good_proposal(explanation="You should try improving the prompt to reduce hallucinations in the pipeline.")
    )
    assert ok is False
    assert "vague" in reason.lower()


def test_vague_phrase_might_help_rejected():
    ok, reason = validate_patch_proposal(
        _good_proposal(explanation="Adding a constraint to the prompt might help reduce hallucination errors.")
    )
    assert ok is False


def test_vague_phrase_could_be_better_rejected():
    ok, reason = validate_patch_proposal(
        _good_proposal(explanation="The context retrieval could be better to prevent context bleed issues.")
    )
    assert ok is False


def test_all_valid_patch_types_accepted():
    for pt in ["PROMPT_PATCH", "TOOL_CONFIG_PATCH", "MEMORY_PATCH", "RETRY_POLICY_PATCH"]:
        ok, reason = validate_patch_proposal(_good_proposal(patch_type=pt))
        assert ok is True, f"{pt} should be valid, got: {reason}"


def test_all_valid_confidence_values_accepted():
    for conf in ["HIGH", "MEDIUM", "LOW"]:
        ok, _ = validate_patch_proposal(_good_proposal(confidence=conf))
        assert ok is True


def test_intentionally_vague_proposals_five_cases():
    vague_cases = [
        "try improving the system prompt to reduce failures",
        "consider changing the memory retrieval logic",
        "this might help with the hallucination issue here",
        "the retry logic could be better designed",
        "you should look into the tool configuration",
    ]
    rejected = sum(
        1 for text in vague_cases
        if not validate_patch_proposal(_good_proposal(explanation=text + " additional text here"))[0]
    )
    assert rejected == 5, f"Expected 5 rejections, got {rejected}"
