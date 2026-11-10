"""NexusBench task families with gold answers and deterministic checkers.

Families
  qa      grounded QA over the fictional knowledge base       (search_docs)
  tool    single-hop tool use over orders + arithmetic         (get_order, calculator, ...)
  plan    multi-step: look up, convert, compute, report        (every declared step must run)
  memory  personalised: needs the user's saved tier            (read_memory + get_order)
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from bench.world import TIERS, World

# Which injected faults are meaningful for which family.
COMPATIBLE = {
    "qa": ["NONE", "HALLUCINATION"],
    "tool": ["NONE", "TOOL_MISFIRE", "LOOP_DETECTED", "PLAN_DRIFT"],
    "plan": ["NONE", "TOOL_MISFIRE", "LOOP_DETECTED", "PLAN_DRIFT"],
    "memory": ["NONE", "CONTEXT_BLEED", "TOOL_MISFIRE", "LOOP_DETECTED", "PLAN_DRIFT"],
}

ABSTAIN_PATTERNS = re.compile(
    r"\b(insufficient|not (?:enough|available|found|provided|mentioned|in the)|unknown|"
    r"(?:do|does|did)(?:n'?t| not) (?:know|have|contain|mention|include|say|specify)|"
    r"cannot (?:find|determine|answer|confirm)|could(?:n'?t| not) (?:find|determine|locate|confirm)|"
    r"can'?t (?:find|determine)|unable to|no (?:information|data|record|document|mention))\b",
    re.I,
)


@dataclass
class Task:
    task_id: str
    family: str
    prompt: str
    gold: Any                     # str for text answers, float for numeric answers
    kind: str                     # "text" | "number"
    user_id: str | None = None    # memory tasks: the session's user
    session_id: str | None = None
    target_company: str | None = None
    attr: str | None = None       # qa: which company attribute is asked
    required_tools: list[str] = field(default_factory=list)


def build_tasks(world: World, seed: int = 11) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []

    qa_templates = [
        ("In what year was {name} founded?", "founded", "number"),
        ("Who founded {name}?", "founder", "text"),
        ("In which city is {name} headquartered?", "hq", "text"),
        ("How many people does {name} employ?", "employees", "number"),
    ]
    for i, c in enumerate(world.companies):
        tmpl, attr, kind = qa_templates[i % len(qa_templates)]
        gold = getattr(c, attr)
        tasks.append(Task(f"qa-{i:03d}", "qa", tmpl.format(name=c.name),
                          float(gold) if kind == "number" else gold, kind,
                          target_company=c.name, attr=attr, required_tools=["search_docs"]))

    orders = sorted(world.orders.values(), key=lambda o: o.order_id)
    rng.shuffle(orders)
    tool_orders, plan_orders = orders[:30], orders[30:60]
    for i, o in enumerate(tool_orders):
        k = i % 3
        if k == 0:
            pct = rng.choice([5, 10, 12, 15, 20, 30])
            tasks.append(Task(f"tool-{i:03d}", "tool",
                              f"What is the total of order {o.order_id} after a {pct}% discount? "
                              "Give the amount in USD.",
                              round(o.total_usd * (1 - pct / 100), 2), "number",
                              required_tools=["get_order"]))
        elif k == 1:
            tasks.append(Task(f"tool-{i:03d}", "tool",
                              f"What is the weight of order {o.order_id} in kilograms?",
                              round(o.weight_lb * 0.45359237, 3), "number",
                              required_tools=["get_order"]))
        else:
            tasks.append(Task(f"tool-{i:03d}", "tool",
                              f"How many items are in order {o.order_id}?",
                              float(o.items), "number", required_tools=["get_order"]))
    for i, o in enumerate(plan_orders):
        pack = rng.choice([0.5, 1.0, 1.5, 2.0, 2.5])
        tasks.append(Task(f"plan-{i:03d}", "plan",
                          f"Look up order {o.order_id}, convert its weight from pounds to "
                          f"kilograms, then add {pack} kg of packaging. Report the shipping "
                          "weight in kg.",
                          round(o.weight_lb * 0.45359237 + pack, 3), "number",
                          required_tools=["get_order", "convert_units"]))

    by_user: dict[str, list] = {}
    for o in sorted(world.orders.values(), key=lambda o: o.order_id):
        by_user.setdefault(o.customer_id, []).append(o)
    n = 0
    for u in world.users:
        for o in by_user.get(u.user_id, [])[:2]:
            disc = TIERS[u.tier]
            tasks.append(Task(f"mem-{n:03d}", "memory",
                              f"Apply my membership-tier discount (Bronze 5%, Silver 10%, Gold "
                              f"15%, Platinum 25%) to order {o.order_id}. Check my saved notes "
                              "for my tier. What is the discounted total in USD?",
                              round(o.total_usd * (1 - disc / 100), 2), "number",
                              user_id=u.user_id, session_id=u.session_id,
                              required_tools=["read_memory", "get_order"]))
            n += 1
    return tasks


# -- checkers ----------------------------------------------------------------

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def extract_number(text: str) -> float | None:
    for m in _NUM.finditer(text or ""):
        try:
            return float(m.group(0).replace(",", "").rstrip("."))
        except ValueError:
            continue
    return None


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def is_abstention(answer: str) -> bool:
    return bool(ABSTAIN_PATTERNS.search(answer or ""))


def check_answer(task: Task, answer: str) -> bool:
    """Deterministic pass/fail against gold (no LLM involved)."""
    if not answer:
        return False
    if task.kind == "number":
        # Prefer a number that matches gold anywhere in the answer (answers often
        # restate inputs, e.g. "order B-1043 ... 41.2 kg").
        gold = float(task.gold)
        tol = max(0.011 * abs(gold), 0.02)
        nums = []
        for m in _NUM.finditer(answer):
            try:
                nums.append(float(m.group(0).replace(",", "").rstrip(".")))
            except ValueError:
                pass
        return any(abs(x - gold) <= tol for x in nums)
    return _norm(str(task.gold)) in _norm(answer)


def answer_supported(task: Task, answer: str, context: str, world: World) -> bool:
    """Is the claim in ``answer`` present in the retrieved ``context``?

    Numbers: the stated number appears in context. Text (founder / city): find
    which known world values the answer mentions; supported iff one of them is
    in the context. An answer naming no known value (an invented name) is
    unsupported.
    """
    if task.kind == "number":
        x = extract_number(answer)
        if x is None:
            return False
        for m in _NUM.finditer(context):
            try:
                if abs(float(m.group(0).replace(",", "").rstrip(".")) - x) < 1e-6:
                    return True
            except ValueError:
                continue
        return False
    values = {str(getattr(c, task.attr)) for c in world.companies} if task.attr else set()
    na, nc = _norm(answer), _norm(context)
    mentioned = [v for v in values if _norm(v) in na]
    return any(_norm(v) in nc for v in mentioned)
