"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    from lab9.eval import aggregate
    from lab9.graders import GRADERS

    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    def bad_number(v) -> bool:
        return isinstance(v, float) and (math.isnan(v) or math.isinf(v))

    for who, rep in (("PR", pr), ("baseline", base)):
        tag = "" if who == "PR" else "baseline "
        # 1. NaN / inf metric values (nan < min is False, so a naive gate lets them through)
        for k, v in (rep.get("metrics") or {}).items():
            if bad_number(v):
                problems.append(f"{tag}metric {k} is {v}")
        # 4. crashed graders: failures recorded, or the field missing (cannot prove graders ran)
        if "evaluator_failures" not in rep:
            problems.append(f"{tag}report has no evaluator_failures field")
        elif rep["evaluator_failures"]:
            problems.append(f"{tag}{len(rep['evaluator_failures'])} evaluator failure(s): "
                            f"{str(rep['evaluator_failures'][0])[:80]}")
        rows = rep.get("rows") or []
        ungraded = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded
                    if not isinstance(r.get(m), bool)]
        if ungraded:
            problems.append(f"{tag}{len(ungraded)} row value(s) not graded (None/NaN), first {ungraded[0]}")
        # 2. row count must equal items x seeds; no duplicated (item, seed)
        man = rep.get("manifest") or {}
        want = int(man.get("items") or 0) * len(man.get("seeds") or [])
        if len(rows) != want:
            problems.append(f"{tag}{len(rows)} rows, manifest says {man.get('items')} items x "
                            f"{len(man.get('seeds') or [])} seeds = {want}")
        pairs = [(r.get("item_id"), r.get("seed")) for r in rows]
        dup = len(pairs) - len(set(pairs))
        if dup:
            problems.append(f"{tag}{dup} duplicated (item, seed) row(s)")
        seeds_in_rows = sorted({r.get("seed") for r in rows}, key=str)
        if sorted(man.get("seeds") or [], key=str) != seeds_in_rows:
            problems.append(f"{tag}row seeds {seeds_in_rows} differ from manifest seeds {man.get('seeds')}")
        # metrics must be what the rows say (a hand-edited aggregate)
        if rows and not ungraded:
            ids = [m for m in graded if all(m in r for r in rows)]
            try:
                has_cost = all("cost" in r for r in rows)
                again = aggregate([{"cost": 0.0, **r} for r in rows], ids, k_values=spec.get("pass_k", []))
                if not has_cost:
                    again.pop("cost_per_success", None)
            except Exception as exc:  # malformed rows
                problems.append(f"{tag}cannot recompute metrics from rows: {exc}")
                again = {}
            for k, v in again.items():
                got = (rep.get("metrics") or {}).get(k)
                if isinstance(v, (int, float)) and isinstance(got, (int, float)) and not bad_number(got):
                    if abs(float(v) - float(got)) > 1e-3:
                        problems.append(f"{tag}metric {k}={got} but rows give {v}")
                elif k in graded and got is None and v is not None:
                    problems.append(f"{tag}metric {k} missing but rows give {v}")

    # 3. same (item, seed) set and same seeds as the baseline (no cherry-picked items/seeds)
    pr_pairs = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows") or []}
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pr_pairs != base_pairs:
        problems.append(f"(item, seed) set differs from baseline: {len(base_pairs - pr_pairs)} missing, "
                        f"{len(pr_pairs - base_pairs)} extra")
    pr_seeds = sorted((pr.get("manifest") or {}).get("seeds") or [], key=str)
    base_seeds = sorted((base.get("manifest") or {}).get("seeds") or [], key=str)
    if pr_seeds != base_seeds:
        problems.append(f"seeds {pr_seeds} differ from the baseline's {base_seeds}")

    # 6. slice tags per item must match the baseline's (and be consistent across seeds)
    def tags(rep: dict) -> dict:
        out: dict = {}
        for r in rep.get("rows") or []:
            out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
        return out

    pt, bt = tags(pr), tags(base)
    relabelled = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if relabelled:
        problems.append(f"slice tags differ from baseline on {relabelled[:5]}")
    inconsistent = sorted(i for i, v in pt.items() if len(v) > 1)
    if inconsistent:
        problems.append(f"item(s) with different slice tags across seeds: {inconsistent[:5]}")

    # 5. ratchet: same eval-set version => thresholds may only get stricter
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _looser(new: dict, old: dict) -> list[str]:
    """Compare two threshold dicts (or slice entries); return what got looser."""
    out = []
    if "max" in old and ("max" not in new or new["max"] > old["max"]):
        out.append(f"max {old['max']} -> {new.get('max')}")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"min {old['min']} -> {new.get('min')}")
    if "max_increase" in old and ("max_increase" not in new or new["max_increase"] > old["max_increase"]):
        out.append(f"max_increase {old['max_increase']} -> {new.get('max_increase')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append("no_significant_drop removed")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Thresholds may only get stricter while the eval-set version stays the same."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []  # new eval-set version: new baseline, thresholds restart
    problems = []
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        n = new_m.get(m["id"])
        if n is None:
            problems.append(f"RATCHET metric {m['id']} removed from the spec")
            continue
        if m.get("blocking") and not n.get("blocking"):
            problems.append(f"RATCHET metric {m['id']} no longer blocking")
        for what in _looser(n.get("threshold") or {}, m.get("threshold") or {}):
            problems.append(f"RATCHET metric {m['id']}: {what}")
    new_s = {(x["name"], x.get("metric")): x for x in spec.get("slices") or []}
    for x in base_spec.get("slices") or []:
        sid = f"{x['name']}/{x.get('metric')}"
        n = new_s.get((x["name"], x.get("metric")))
        if n is None:
            problems.append(f"RATCHET slice {sid} removed")
            continue
        if x.get("blocking") and not n.get("blocking"):
            problems.append(f"RATCHET slice {sid} no longer blocking")
        for what in _looser(n, x):
            problems.append(f"RATCHET slice {sid}: {what}")
    if base_spec.get("seeds") and sorted(spec.get("seeds") or []) != sorted(base_spec["seeds"]):
        problems.append("RATCHET seeds changed on the same eval-set version")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"  # an empty slice proves nothing
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
