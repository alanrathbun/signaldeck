"""Tests for signaldeck.engine.rds_pipeline — RDS DSP pipeline."""

import numpy as np
import pytest

from signaldeck.engine.rds_pipeline import (
    RDS_BCH_POLY,
    RDS_OFFSETS,
    RDS_SAMPLES_PER_BIT,
    RDS_WORKING_RATE,
    _bits_to_uint16,
    bmc_decode,
    compute_syndrome,
    design_rds_filters,
    extract_rds_subcarrier,
    find_rds_groups,
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


# ── helpers ────────────────────────────────────────────────────────────────

def encode_block(data_16: int, offset: int) -> list[int]:
    """Encode a 16-bit word with BCH parity and offset into 26-bit block."""
    msg = data_16 << 10
    poly = 0b10110111001
    for i in range(15, -1, -1):
        if (msg >> (i + 10)) & 1:
            msg ^= poly << i
    parity = (msg & 0x3FF) ^ offset
    full = (data_16 << 10) | parity
    return [(full >> (25 - b)) & 1 for b in range(26)]


# ── Task 4 — Frame sync + BCH parity ─────────────────────────────────────

class TestComputeSyndrome:
    def test_encode_and_check_block(self) -> None:
        """Encode blocks with BCH + offset and verify syndrome matches."""
        for name, offset in RDS_OFFSETS.items():
            data = 0xABCD
            block_bits = encode_block(data, offset)
            assert len(block_bits) == 26
            syn = compute_syndrome(block_bits)
            assert syn == offset, f"Syndrome mismatch for offset {name}"


class TestFindRdsGroups:
    def test_find_rds_groups_synthetic(self) -> None:
        """Build a complete valid RDS group and verify extraction."""
        a_data = 0x1234
        b_data = 0x5678
        c_data = 0x9ABC
        d_data = 0xDEF0

        bits: list[int] = []
        bits.extend(encode_block(a_data, RDS_OFFSETS["A"]))
        bits.extend(encode_block(b_data, RDS_OFFSETS["B"]))
        bits.extend(encode_block(c_data, RDS_OFFSETS["C"]))
        bits.extend(encode_block(d_data, RDS_OFFSETS["D"]))

        groups = find_rds_groups(bits)
        assert len(groups) == 1
        assert groups[0] == (a_data, b_data, c_data, d_data)

    def test_find_rds_groups_empty(self) -> None:
        assert find_rds_groups([]) == []
        assert find_rds_groups([0] * 103) == []
        assert find_rds_groups([0] * 200) == []


# ── Task 5 — Stateful RdsPipeline class ──────────────────────────────────

def test_rds_pipeline_process_returns_groups():
    from signaldeck.engine.rds_pipeline import RdsPipeline
    pipeline = RdsPipeline(input_sample_rate=2_000_000)
    # Feed silence — should get no groups but no crash
    iq = np.zeros(100_000, dtype=np.complex64)
    groups = pipeline.process(iq)
    assert isinstance(groups, list)
    assert len(groups) == 0


def test_rds_pipeline_reset():
    from signaldeck.engine.rds_pipeline import RdsPipeline
    pipeline = RdsPipeline(input_sample_rate=2_000_000)
    pipeline.process(np.zeros(50_000, dtype=np.complex64))
    pipeline.reset()
    assert pipeline._bit_buffer == []


# ── Task 7 — rds_callback parameter in sweep_once ────────────────────────

@pytest.mark.asyncio
async def test_sweep_once_rds_callback():
    """sweep_once should accept rds_callback and call it for FM frequencies."""
    from signaldeck.engine.scanner import FrequencyScanner, ScanRange

    class FakeDevice:
        def set_sample_rate(self, r): pass
        def start_stream(self): pass
        def stop_stream(self): pass
        def tune(self, f): self._freq = f
        def read_samples(self, n):
            rng = np.random.default_rng(42)
            return (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64) * 0.01

    callback_data = []

    async def on_rds(freq_hz, iq_samples):
        callback_data.append((freq_hz, len(iq_samples)))

    scanner = FrequencyScanner(
        device=FakeDevice(),
        scan_ranges=[ScanRange(start_hz=88e6, end_hz=89e6, step_hz=200_000)],
        fft_size=1024,
        squelch_offset_db=100,
    )

    await scanner.sweep_once(rds_callback=on_rds, rds_sample_count=8192)
    assert len(callback_data) > 0
    for freq, n_samples in callback_data:
        assert 88e6 <= freq < 89e6
        assert n_samples == 8192


# ── Task 8 — Database persistence for decoder results ────────────────────

@pytest.mark.asyncio
async def test_insert_and_get_decoder_result(tmp_path):
    from signaldeck.storage.database import Database
    from signaldeck.storage.models import Signal, ActivityEntry
    from datetime import datetime, timezone

    db = Database(str(tmp_path / "test.db"))
    await db.initialize()

    now = datetime.now(timezone.utc)
    sig = Signal(frequency=98_500_000, bandwidth=200_000, modulation="FM",
                 protocol="broadcast_fm", first_seen=now, last_seen=now,
                 hit_count=1, avg_strength=-30.0, confidence=0.6)
    signal_id = await db.upsert_signal(sig)

    entry = ActivityEntry(signal_id=signal_id, timestamp=now, duration=0.05,
                          strength=-30.0, decoder_used="rds",
                          result_type="rds_group", summary="98.500 MHz [broadcast_fm]")
    activity_id = await db.insert_activity(entry)

    row_id = await db.insert_decoder_result(
        activity_id=activity_id, decoder="rds", protocol="rds",
        result_type="rds_group",
        content={"ps_name": "WXYZ FM", "radio_text": "Now playing: Test Song"},
    )
    assert row_id > 0

    rds = await db.get_rds_for_frequency(98_500_000)
    assert rds is not None
    assert rds["ps_name"] == "WXYZ FM"

    await db.close()
