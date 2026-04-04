"""Tests for signaldeck.engine.rds_pipeline — RDS DSP pipeline."""

import numpy as np
import pytest

from signaldeck.engine.rds_pipeline import (
    RDS_SAMPLES_PER_BIT,
    RDS_WORKING_RATE,
    bmc_decode,
    design_rds_filters,
    extract_rds_subcarrier,
    fm_demodulate_baseband,
    recover_bits,
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


# ── Task 3 — BMC bit recovery + differential decode ───────────────────────

class TestBmcDecode:
    def test_bmc_decode_known_sequence(self) -> None:
        assert bmc_decode([1, 0, 1, 1, 0]) == [1, 1, 0, 1]

    def test_bmc_decode_empty(self) -> None:
        assert bmc_decode([]) == []
        assert bmc_decode([1]) == []


class TestRecoverBits:
    def test_recover_bits_from_clean_biphase(self) -> None:
        """Construct a clean BMC waveform for known bits and verify recovery."""
        known_bits = [1, 0, 1, 1, 0, 0, 1, 0]
        spb = RDS_SAMPLES_PER_BIT  # 8

        # Build BMC waveform: every bit boundary has a transition.
        # '1' bits also have a mid-bit transition; '0' bits do not.
        # We prepend a short preamble so the first crossing the
        # algorithm sees is the first bit boundary.
        level = 1.0
        waveform: list[float] = [level] * spb  # preamble
        for bit in known_bits:
            # Bit boundary -- always flip
            level = -level
            if bit == 1:
                waveform.extend([level] * (spb // 2))
                level = -level
                waveform.extend([level] * (spb // 2))
            else:
                waveform.extend([level] * spb)

        signal = np.array(waveform, dtype=np.float32)
        recovered = recover_bits(signal, samples_per_bit=spb)
        assert recovered == known_bits
