"""Run the narration evals.

    python -m evals.run                  # every case
    python -m evals.run santa-fe-full    # one or more by slug
    python -m evals.run --list
    python -m evals.run --repeat 3       # sampling noise is real; average it

Deliberately NOT part of `pytest`: every case costs a live Anthropic call, and a
test suite that spends money on every push is a test suite people stop running.
CI runs `tests/`; a human runs this.

Two numbers come out:

  hallucination rate  -- untraceable numbers / all numbers written. The app's
                         central claim is that this is zero.
  refusal accuracy    -- of the cases where the honest answer was "the data
                         does not support that", how many did it get right.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from climatelens import llm
from climatelens.config import load_dotenv

from .cases import CASES, Case, Result
from .numbers import Traceability, extract

load_dotenv()


@dataclass
class CaseRun:
    case: Case
    prose: str
    results: list[Result] = field(default_factory=list)
    numbers_written: int = 0
    unsupported: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)


def _completeness(prose: str) -> Result:
    """Did the read-out actually finish?

    Checked on every case because a truncated narration is still a valid
    string: it renders, it reads fine for four paragraphs, and it stops in the
    middle of a word. The first run of this harness found four of seven cases
    ending mid-sentence against `max_tokens=2000`, which no unit test could
    have seen.
    """
    tail = prose.rstrip()
    ok = tail.endswith((".", "!", "?", '."', ".'", ".)", "…"))
    return Result("the narration is not truncated", "refusal", ok,
                  "ends cleanly" if ok else f"stops mid-sentence: …{tail[-45:]!r}")


def run_case(case: Case) -> CaseRun:
    payload = case.payload()
    prose = llm.explain(payload["label"], payload["comparison"],
                        enso=payload.get("enso"))

    trace = Traceability(payload)
    unsupported = trace.unsupported(prose)
    mentions = extract(prose)

    results = [Result(
        "every number traces to the data", "traceability", not unsupported,
        "all numbers supported" if not unsupported
        else "; ".join(str(m) for m in unsupported[:4]),
    ), _completeness(prose)]
    for expectation in case.expectations:
        results.append(expectation.check(prose, payload))

    return CaseRun(case, prose, results, len(mentions), unsupported)


def report(runs: list[CaseRun], *, verbose: bool) -> int:
    numbers = sum(r.numbers_written for r in runs)
    bad = sum(len(r.unsupported) for r in runs)
    refusals = [res for r in runs for res in r.results if res.kind == "refusal"]
    refusals_ok = sum(1 for r in refusals if r.passed)

    for run in runs:
        mark = "PASS" if run.passed else "FAIL"
        print(f"\n[{mark}] {run.case.name}  ({run.case.slug})")
        for res in run.results:
            print(f"    {'ok  ' if res.passed else 'FAIL'} {res.name}: {res.detail}")
        if verbose or not run.passed:
            print("    ---")
            for line in run.prose.splitlines():
                if line.strip():
                    print(f"    | {line}")

    print("\n" + "=" * 68)
    rate = (bad / numbers * 100) if numbers else 0.0
    accuracy = (refusals_ok / len(refusals) * 100) if refusals else 100.0
    print(f"  cases              {sum(1 for r in runs if r.passed)}/{len(runs)} passed")
    print(f"  hallucination rate {rate:.1f}%   ({bad} untraceable of {numbers} numbers written)")
    print(f"  refusal accuracy   {accuracy:.0f}%   ({refusals_ok}/{len(refusals)} honest-refusal expectations met)")
    print("=" * 68)
    return 0 if all(r.passed for r in runs) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="cases to run (default: all)")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    parser.add_argument("--repeat", type=int, default=1,
                        help="run each case N times; the model is sampled, not deterministic")
    parser.add_argument("--verbose", action="store_true", help="always print the prose")
    parser.add_argument("--json", type=Path, help="also write results here")
    args = parser.parse_args(argv)

    if args.list:
        for case in CASES:
            print(f"{case.slug:34} {case.name}")
            print(f"{'':34} {case.why.splitlines()[0]}")
        return 0

    selected = [c for c in CASES if not args.slugs or c.slug in args.slugs]
    if not selected:
        print(f"no case matches {args.slugs}", file=sys.stderr)
        return 2

    if not llm.available():
        print("ANTHROPIC_API_KEY is not set — these cases need live calls.",
              file=sys.stderr)
        return 2

    runs: list[CaseRun] = []
    for _ in range(args.repeat):
        for case in selected:
            print(f"running {case.slug} …", file=sys.stderr)
            try:
                runs.append(run_case(case))
            except FileNotFoundError as exc:
                print(f"  missing fixture: {exc}. Run "
                      f"`python -m evals.capture_fixtures` first.", file=sys.stderr)
                return 2
            time.sleep(1)

    code = report(runs, verbose=args.verbose)
    if args.json:
        args.json.write_text(json.dumps([{
            "slug": r.case.slug,
            "passed": r.passed,
            "numbers_written": r.numbers_written,
            "unsupported": [{"value": m.value, "text": m.text, "context": m.context}
                            for m in r.unsupported],
            "results": [{"name": x.name, "kind": x.kind, "passed": x.passed,
                         "detail": x.detail} for x in r.results],
            "prose": r.prose,
        } for r in runs], indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
