"""Tests for signaldeck.engine.rds_pipeline — RDS DSP pipeline."""

import numpy as np
import pytest

from signaldeck.engine.rds_pipeline import (
    RDS_WORKING_RATE,
    design_rds_filters,
    extract_rds_subcarrier,
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


# ── Task 2 — RDS subcarrier extraction ────────────────────────────────────

class TestExtractRdsSubcarrier:
    def test_extract_rds_subcarrier_produces_output(self) -> None:
        fs = RDS_WORKING_RATE
        n = 22800
        t = np.arange(n, dtype=np.float32) / fs
        # Pilot at 19 kHz + RDS tone at 57.05 kHz
        baseband = (
            0.1 * np.sin(2 * np.pi * 19000 * t)
            + 0.05 * np.sin(2 * np.pi * 57050 * t)
        ).astype(np.float32)

        filters = design_rds_filters(fs)
        out = extract_rds_subcarrier(baseband, filters)
        expected_len = n // 24
        assert abs(len(out) - expected_len) <= 2
        assert out.dtype == np.float32

    def test_extract_rds_subcarrier_no_pilot_still_works(self) -> None:
        rng = np.random.default_rng(99)
        baseband = rng.standard_normal(22800).astype(np.float32) * 1e-12
        filters = design_rds_filters()
        out = extract_rds_subcarrier(baseband, filters)
        assert isinstance(out, np.ndarray)
        assert len(out) > 0
