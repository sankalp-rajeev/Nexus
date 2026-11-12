import json

import pytest

from scripts.phase5.followup import cohort, sample, SEED
from scripts.phase5.gemini_critic import GeminiBudget, body_for, cost_for
from scripts.phase5.ingestion_load import grows
from scripts.phase5.measurement import BudgetExceeded
from services.critic.proposal import StructuredDiagnosis, response_schema


def test_gemini_preserves_prompt_and_schema():
    prompt = json.dumps({"trace": "fictional DEV fixture"})
    body = body_for(prompt, StructuredDiagnosis)
    assert body["contents"][0]["parts"][0]["text"] == prompt
    config = body["generationConfig"]
    assert config["responseJsonSchema"] == response_schema(StructuredDiagnosis)
    assert config["temperature"] == .2 and config["maxOutputTokens"] == 800


def test_gemini_cost_includes_thoughts_and_cache():
    assert cost_for(dict(promptTokenCount=1000, cachedContentTokenCount=200,
                         candidatesTokenCount=100, thoughtsTokenCount=50, totalTokenCount=1150)) == pytest.approx(.000621)
    assert cost_for({}) is None


def test_gemini_shared_reservations_fail_closed(tmp_path):
    budget = GeminiBudget(tmp_path, cap=.004)
    body = {"request": "small"}
    cid = budget.reserve("h1", body)
    with pytest.raises(BudgetExceeded):
        GeminiBudget(tmp_path, cap=.004).reserve("h2", body)
    assert budget.snapshot()["stopped"]
    budget.settle(cid, {}, 5, "ReadTimeout", None, None)
    assert budget.snapshot()["unknown_calls"] == 1
    assert budget.snapshot()["accounted_usd"] > 0


def test_zero_denominators_and_stage_based_full_gate():
    assert cohort([])["full_gate_time_s"] == dict(n=0,p50=None,p90=None)
    rows = [dict(status="ok",gate_decision="rejected",total_s=999,stage_status={},stages_s={})]
    assert cohort(rows)["full_gate_n"] == 0


def test_lag_growth_and_fixed_sample():
    stable = [dict(s=i,assembler=3,classifier=4) for i in range(0,181,10)]
    assert not any(s["growing"] for s in grows(stable,20).values())
    rising = [dict(s=i,assembler=3,classifier=i) for i in range(0,181,10)]
    assert grows(rising,20)["classifier"]["growing"]
    import random
    ids = [r["item_id"] for r in random.Random(SEED).sample(sample(),10)]
    assert len(set(ids)) == 10
