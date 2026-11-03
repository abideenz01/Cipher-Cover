import pytest

from evals import stats


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [(20, 35, 0.4086, 0.7202), (0, 10, 0.0, 0.2775), (10, 10, 0.7225, 1.0)],
)
def test_wilson_matches_known_intervals(k, n, low, high):
    found = stats.wilson(k, n)
    assert found is not None
    assert found[0] == pytest.approx(low, abs=1e-4)
    assert found[1] == pytest.approx(high, abs=1e-4)


def test_proportions_carry_n_and_flag_small_samples():
    assert stats.wilson(0, 0) is None
    empty = stats.proportion(0, 0)
    assert (empty["rate"], empty["ci95"], empty["sufficient_sample"]) == (
        None,
        None,
        False,
    )
    assert stats.proportion(3, 8)["sufficient_sample"] is False
    assert stats.proportion(20, 35)["sufficient_sample"] is True


def test_percentiles_interpolate():
    assert stats.percentile([1, 2, 3, 4], 50) == 2.5
    assert stats.percentile([5], 90) == 5
    assert stats.percentile([0, 10], 90) == 9


def test_distributions_get_a_median_interval_only_when_n_permits():
    small = stats.distribution([1.0, 2.0, 3.0])
    assert small["median"] == 2.0
    assert small["median_ci95"] is None
    assert small["sufficient_sample"] is False
    values = [float(v) for v in range(40)]
    large = stats.distribution(values)
    assert large["median_ci95"] == stats.distribution(values)["median_ci95"]
    low, high = large["median_ci95"]
    assert low <= large["median"] <= high
    assert large["sufficient_sample"] is True
    assert stats.distribution([]) == {
        "kind": "distribution",
        "n": 0,
        "sufficient_sample": False,
    }


def test_overlap():
    assert stats.overlap([0.1, 0.5], [0.4, 0.9]) is True
    assert stats.overlap([0.1, 0.3], [0.4, 0.9]) is False
    assert stats.overlap(None, [0.4, 0.9]) is None
