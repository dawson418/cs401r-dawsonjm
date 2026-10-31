"""Task 1 fairness check: FLAGS a recall gap across loyalty tiers, never blocks the build.

Reads the same metrics file as test_model.py (--eval-metrics-path or EVAL_METRICS_PATH).
train() in models/churn/churn_model.py writes flat keys: recall_tier_<tier>,
positives_tier_<tier>, n_tier_<tier>, auc_tier_<tier>.
"""
import json
import os
import warnings

import pytest

GAP_THRESHOLD = 0.10      # flag if highest-tier recall - lowest-tier recall exceeds 10 points
MIN_POSITIVES = 30        # tiers with fewer churners than this cannot support a claim


@pytest.fixture(scope="module")
def fairness_metrics(request):
    path = None
    try:
        path = request.config.getoption("--eval-metrics-path")
    except ValueError:
        pass
    path = path or os.environ.get("EVAL_METRICS_PATH")
    assert path and os.path.exists(path), "set --eval-metrics-path or EVAL_METRICS_PATH to evaluation_metrics.json"
    with open(path) as f:
        return json.load(f)


def _tiers(m):
    return sorted(k[len("recall_tier_"):] for k in m if k.startswith("recall_tier_"))


def _supported_tiers(m):
    return [t for t in _tiers(m) if m.get("positives_tier_" + t, 0) >= MIN_POSITIVES]


def test_per_tier_metrics_are_present_and_valid(fairness_metrics):
    tiers = _tiers(fairness_metrics)
    assert len(tiers) >= 2, "evaluation_metrics.json has per-tier recall for fewer than 2 loyalty tiers"
    for t in tiers:
        assert 0.0 <= fairness_metrics["recall_tier_" + t] <= 1.0
        assert fairness_metrics.get("n_tier_" + t, 0) > 0


def test_tiers_too_small_to_judge_are_excluded(fairness_metrics):
    supported = _supported_tiers(fairness_metrics)
    small = [t for t in _tiers(fairness_metrics) if t not in supported]
    if small:
        warnings.warn("FAIRNESS NOTE: tiers with <%d test churners are excluded from the gap: %s"
                      % (MIN_POSITIVES, ", ".join(small)))
    assert len(supported) >= 2, "need at least 2 tiers with >= %d churners to compare" % MIN_POSITIVES


def test_recall_gap_across_loyalty_tiers_is_flagged_not_blocking(fairness_metrics):
    supported = _supported_tiers(fairness_metrics)
    rec = {t: fairness_metrics["recall_tier_" + t] for t in supported}
    hi, lo = max(rec, key=rec.get), min(rec, key=rec.get)
    gap = rec[hi] - rec[lo]
    if gap > GAP_THRESHOLD:
        warnings.warn("FAIRNESS FLAG: recall@top10%% gap is %.1f points between %s (%.3f) and %s (%.3f), "
                      "above the %.0f-point threshold. Flag only; the build is not blocked."
                      % (gap * 100, hi, rec[hi], lo, rec[lo], GAP_THRESHOLD * 100))
    else:
        warnings.warn("FAIRNESS CHECK: recall@top10%% gap is %.1f points between %s and %s, within the %.0f-point threshold."
                      % (gap * 100, hi, lo, GAP_THRESHOLD * 100))
    assert 0.0 <= gap <= 1.0
