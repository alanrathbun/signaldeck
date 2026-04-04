"""Tests for signaldeck.engine.rds_pipeline — RDS DSP pipeline."""

import numpy as np
import pytest

from signaldeck.engine.rds_pipeline import (
    RDS_WORKING_RATE,
    design_rds_filters,
    fm_demodulate_baseband,
)


# ── Task 1 — filter design + FM demod ─────────────────────────────────────

class TestDesignRdsFilters:
    def test_design_rds_filters_returns_four_filters(self) -> None:
        filters = design_rds_filters()
        expected_keys = {"pilot_bpf", "rds_bpf", "ref_bpf", "rds_lpf"}
        assert set(filters.keys()) == expected_keys
        for key in expected_keys:
            arr = filters[key]
            assert isinstance(arr, np.ndarray)
            assert len(arr) % 2 == 1, f"{key} tap count should be odd"


class TestFmDemodulateBaseband:
    def test_fm_demodulate_baseband_output_rate(self) -> None:
        rng = np.random.default_rng(42)
        iq = (rng.standard_normal(200_000) + 1j * rng.standard_normal(200_000)).astype(
            np.complex64
        )
        out = fm_demodulate_baseband(iq, input_rate=2_000_000, output_rate=228_000)
        expected = int(round(199_999 * 228_000 / 2_000_000))
        assert abs(len(out) - expected) <= 2
        assert out.dtype == np.float32
