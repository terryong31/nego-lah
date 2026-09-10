"""Replay the golden scenarios and report quality, tokens, latency and cost.

    mise run eval:agent
    mise run eval:agent -- --model gemini-3.8-flash-lite
    mise run eval:agent -- --category confidentiality --repeat 3

SPEC-059. Two questions, one harness:

  * Did the cost work make the agent worse? Run it before and after.
  * Is a cheaper model good enough? Run it twice with --model and compare.

The report is deliberately blunt: pass rate per category next to cost per
conversation. A model that is 60% cheaper and leaks the price floor is not a
saving, and putting those two numbers on the same line is the only way that
stays obvious.

An LLM judge scores answer relevancy on top of the hard assertions when it can
reach a model; the assertions are what the exit code is based on, because they
are deterministic and a judge is not. (On why this is not ragas, see the comment
above `_judge_relevancy`.)
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cost import MODEL_PRICING, PRICES_SOURCED, estimate_cost, usage_from_result  # noqa: E402
from evals.scenarios import SCENARIOS, Scenario  # noqa: E402


@dataclass
class ScenarioResult:
    scenario: Scenario
    replies: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str | None = None

    @property
    def transcript(self) -> str:
        return "\n".join(self.replies).lower()

    @property
    def failures(self) -> list[str]:
        """Why this scenario failed, in words a reader can act on."""
        if self.error:
            return [f"errored: {self.error}"]

        problems = []
        text = self.transcript
        if self.scenario.expect_any and not any(
            token.lower() in text for token in self.scenario.expect_any
        ):
            problems.append(f"said none of {self.scenario.expect_any}")
        for token in self.scenario.forbid_any:
            if token.lower() in text:
                problems.append(f"leaked {token!r}")
        if self.scenario.expect_tool and self.scenario.expect_tool not in self.tools_called:
            problems.append(
                f"never called {self.scenario.expect_tool} (called: {self.tools_called or 'nothing'})"
            )
        return problems

    @property
    def passed(self) -> bool:
        return not self.failures


async def run_scenario(scenario: Scenario, model: str | None) -> ScenarioResult:
    """Drive one scripted conversation through the real agent.

    Each scenario gets a throwaway user id so conversation memory from a previous
    scenario — or a previous run — cannot bleed in and change the answer.
    """
    from agent import bot
    from agent.context import set_context

    result = ScenarioResult(scenario=scenario)
    user_id = f"eval-{scenario.id}-{uuid.uuid4().hex[:8]}"

    started = time.perf_counter()
    try:
        for turn in scenario.turns:
            set_context(user_id=user_id, item_id=scenario.item["id"])
            messages = bot._build_messages(user_id, turn, item_id=scenario.item["id"])
            agent_result = await bot._get_customer_agent().ainvoke({"messages": messages})

            usage = usage_from_result(agent_result)
            result.input_tokens += usage.input_tokens
            result.output_tokens += usage.output_tokens

            for message in agent_result.get("messages", []):
                for call in getattr(message, "tool_calls", None) or []:
                    name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                    if name:
                        result.tools_called.append(name)

            result.replies.append(
                bot._extract_text_from_content(agent_result["messages"][-1].content)
            )
    except Exception as e:  # noqa: BLE001 — a broken scenario must not kill the suite
        result.error = f"{type(e).__name__}: {e}"

    result.seconds = time.perf_counter() - started
    return result


# --- Quality score -----------------------------------------------------------
#
# This was going to be ragas. It cannot be: every ragas release through 0.4.3
# hard-imports `langchain_community.chat_models.vertexai`, which langchain-community
# 0.4.x removed, so `import ragas` raises before any metric is reachable. Worse,
# adding it to the lockfile at all dragged production packages backwards —
# `rich` 15.0.0 → 14.3.4, `openai` 3.7.0 → 3.3.0 — because uv resolves one
# version per package across every group. Paying that on the production image
# for a tool that cannot import is not a trade worth making.
#
# So the judge is a few lines against a model this repo already depends on.
# `_judge_relevancy` below is the seam: if a ragas release ever drops that
# import, swap its body and the report picks the score up unchanged.
_JUDGE_PROMPT = """You are grading a second-hand marketplace seller's reply.

BUYER SAID: {question}
SELLER REPLIED: {answer}

Score 0.0-1.0 for how well the reply addresses what the buyer actually said.
A relevant, on-topic reply that moves the sale forward scores high. An evasive,
generic or off-topic reply scores low. Reply with ONLY the number."""


async def _judge_relevancy(results: list[ScenarioResult]) -> float | None:
    """Mean relevancy of the final reply in each scenario, or None if unavailable.

    Optional on purpose: it needs a judge model and network, and the harness has
    to stay useful on a laptop with neither. The hard assertions are what the
    exit code is based on either way — they are deterministic, and a judge is not.
    """
    usable = [r for r in results if r.replies and not r.error]
    if not usable:
        return None

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        judge = ChatGoogleGenerativeAI(
            model=os.getenv("EVAL_JUDGE_MODEL", "gemini-3.8-flash"), temperature=0
        )
        scores = []
        for r in usable:
            reply = await judge.ainvoke(
                _JUDGE_PROMPT.format(question=r.scenario.turns[-1], answer=r.replies[-1])
            )
            try:
                scores.append(max(0.0, min(1.0, float(str(reply.content).strip().split()[0]))))
            except (ValueError, IndexError):
                continue
        return statistics.fmean(scores) if scores else None
    except Exception as e:  # noqa: BLE001
        print(f"  (relevancy judge unavailable: {type(e).__name__}: {e})")
        return None


def report(results: list[ScenarioResult], model: str, relevancy: float | None = None) -> bool:
    """Print the report. Returns True if everything passed."""
    print()
    print("=" * 78)
    print(f"  Agent evaluation — model: {model}")
    print("=" * 78)

    by_category: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_category.setdefault(r.scenario.category, []).append(r)

    for category, group in sorted(by_category.items()):
        passed = sum(1 for r in group if r.passed)
        print(f"\n{category.upper()}  {passed}/{len(group)}")
        for r in group:
            mark = "PASS" if r.passed else "FAIL"
            print(f"  [{mark}] {r.scenario.id}  ({r.seconds:.1f}s, {r.input_tokens + r.output_tokens} tok)")
            for problem in r.failures:
                print(f"         ↳ {problem}")

    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)
    cost = estimate_cost(model, total_in, total_out)
    passed = sum(1 for r in results if r.passed)

    print()
    print("-" * 78)
    print(f"  Scenarios passed : {passed}/{len(results)}")
    print(f"  Tokens           : {total_in:,} in / {total_out:,} out")
    print(f"  Median latency   : {statistics.median([r.seconds for r in results]):.1f}s")
    if cost is None:
        print(f"  Cost             : unknown — {model} is not in agent/cost.MODEL_PRICING")
    else:
        print(f"  Cost (this run)  : RM{cost:.4f}")
        print(f"  Cost / scenario  : RM{cost / max(len(results), 1):.4f}")
    if total_in == 0 and total_out == 0:
        print("  NOTE: the provider reported no usage_metadata, so cost is not measurable.")

    if relevancy is not None:
        print(f"  Judge relevancy  : {relevancy:.3f}")

    price = MODEL_PRICING.get(model)
    print(f"\n  Prices last checked {PRICES_SOURCED}. Verify against the provider's")
    print("  pricing page before quoting these numbers anywhere that matters.")
    if price is not None and "UNVERIFIED" in price.note:
        print(f"  ⚠  {model}: {price.note}")
    print("-" * 78)
    return passed == len(results)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the seller agent (SPEC-059)")
    parser.add_argument("--model", help="Override GEMINI_MODEL for this run, to compare models")
    parser.add_argument("--category", help="Only run scenarios in this category")
    parser.add_argument("--repeat", type=int, default=1, help="Run each scenario N times (models vary)")
    args = parser.parse_args()

    if args.model:
        # Read by agent.llm_factory._gemini_model() on every turn.
        os.environ["GEMINI_MODEL"] = args.model
    # The hybrid router would otherwise send some turns to the self-hosted M5 and
    # some to the cloud, which makes a per-model comparison meaningless.
    os.environ["LLM_PROVIDER"] = "gemini"

    from agent.llm_factory import _gemini_model

    model = _gemini_model()

    selected = [s for s in SCENARIOS if not args.category or s.category == args.category]
    if not selected:
        print(f"No scenarios in category {args.category!r}")
        return 2

    print(f"Running {len(selected)} scenario(s) × {args.repeat} against {model}…")
    results = []
    for _ in range(args.repeat):
        for scenario in selected:
            print(f"  … {scenario.id}", flush=True)
            results.append(await run_scenario(scenario, model))

    relevancy = await _judge_relevancy(results)
    return 0 if report(results, model, relevancy) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
