import json

import pytest

from scripts.phase5.followup import cohort, sample, SEED
from scripts.phase5.gemini_critic import GeminiBudget, GeminiCritic, body_for, cost_for
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


def test_gemini_wire_and_actual_usage_accounting(tmp_path, monkeypatch):
    import httpx
    from services.critic.accounting import CostLedger
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only-key")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json=dict(modelVersion="fixture-version",
            usageMetadata=dict(promptTokenCount=1000,totalTokenCount=1100),
            candidates=[dict(finishReason="STOP",content=dict(parts=[dict(text='{"answer":"same"}')]))]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = GeminiCritic(root=tmp_path,heal_id="dev-1",ledger=CostLedger(tmp_path/"critic.jsonl",cap_usd=2),client=http)
        assert provider.complete_diagnosis("unchanged prompt") == '{"answer":"same"}'
    request = requests[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.headers["x-goog-api-key"] == "fixture-only-key"
    assert b"fixture-only-key" not in request.content
    assert provider.budget.snapshot()["actual_usage_priced_usd"] == pytest.approx(.00055)
    assert provider.last_provenance.model_version == "fixture-version"


def test_lag_growth_and_fixed_sample():
    stable = [dict(s=i,assembler=3,classifier=4) for i in range(0,181,10)]
    assert not any(s["growing"] for s in grows(stable,20).values())
    rising = [dict(s=i,assembler=3,classifier=i) for i in range(0,181,10)]
    assert grows(rising,20)["classifier"]["growing"]
    import random
    ids = [r["item_id"] for r in random.Random(SEED).sample(sample(),10)]
    assert len(set(ids)) == 10
