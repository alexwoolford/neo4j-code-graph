#!/usr/bin/env python3
"""Fast unit tests for the pure helpers in src/security/reachability.py."""

import pytest

from src.security.reachability import (
    MAX_HOPS_CEILING,
    MAX_HOPS_FLOOR,
    _build_reachability_query,
    _bus_factor,
    _entry_predicate,
    _validate_max_hops,
)


class TestValidateMaxHops:
    def test_clamps_low_to_floor(self):
        assert _validate_max_hops(0) == MAX_HOPS_FLOOR == 1
        assert _validate_max_hops(-5) == 1

    def test_clamps_high_to_ceiling(self):
        assert _validate_max_hops(99) == MAX_HOPS_CEILING == 12
        assert _validate_max_hops(13) == 12

    def test_in_range_passthrough(self):
        assert _validate_max_hops(1) == 1
        assert _validate_max_hops(6) == 6
        assert _validate_max_hops(12) == 12

    @pytest.mark.parametrize("bad", ["6", 6.0, None, [6], True, False])
    def test_non_int_rejected(self, bad):
        with pytest.raises(ValueError):
            _validate_max_hops(bad)


class TestBusFactor:
    def test_empty_history(self):
        assert _bus_factor([]) == 0
        assert _bus_factor([0]) == 0

    def test_single_committer(self):
        assert _bus_factor([10]) == 1

    def test_dominant_committer(self):
        # 3 of 4 commits >= 50% -> one committer suffices
        assert _bus_factor([3, 1]) == 1

    def test_even_split(self):
        # 4 equal committers: two needed to reach 2/4
        assert _bus_factor([1, 1, 1, 1]) == 2

    def test_unsorted_input(self):
        # order must not matter: top-down coverage of [5,4,3,2,1] needs 2 (9/15)
        assert _bus_factor([1, 3, 5, 2, 4]) == 2

    def test_exact_half_counts(self):
        # 2 of 4 is exactly 50% -> counts as covered
        assert _bus_factor([2, 1, 1]) == 1


class TestQueryBuilding:
    def test_max_hops_interpolated_into_bound(self):
        query = _build_reachability_query(6, ("annotated", "main"), include_tests=False)
        assert "[:CALLS*0..6]" in query

    def test_max_hops_clamped_in_query(self):
        query = _build_reachability_query(99, ("annotated",), include_tests=False)
        assert "[:CALLS*0..12]" in query

    def test_include_tests_toggles_filter(self):
        excluded = _build_reachability_query(6, ("annotated",), include_tests=False)
        included = _build_reachability_query(6, ("annotated",), include_tests=True)
        assert "NOT coalesce(entry.is_test_method, false)" in excluded
        assert "NOT coalesce(entry.is_test_method, false)" not in included

    def test_unknown_entry_set_rejected(self):
        with pytest.raises(ValueError):
            _entry_predicate(["annotated", "bogus"])

    def test_empty_entry_sets_rejected(self):
        with pytest.raises(ValueError):
            _entry_predicate([])

    def test_entry_sets_or_combined(self):
        pred = _entry_predicate(["annotated", "main", "public"])
        assert "entry.name = 'main'" in pred
        assert "$entry_annotations" in pred
        assert pred.count("OR ") >= 2
