from __future__ import annotations

import asyncio
from typing import Any

import numpy as np


async def capture_iq_burst(
    device,
    frequency_hz: float,
    sample_rate: float,
    duration_s: float,
    settle_time_s: float = 0.015,
    chunk_size: int = 65_536,
) -> np.ndarray:
    target_samples = max(1024, int(sample_rate * duration_s))
    device.set_sample_rate(sample_rate)
    device.tune(frequency_hz)
    await asyncio.sleep(settle_time_s)

    chunks: list[np.ndarray] = []
    remaining = target_samples
    empty_reads = 0

    device.start_stream()
    try:
        while remaining > 0:
            read_len = min(remaining, chunk_size)
            samples = device.read_samples(read_len)
            if samples is None or len(samples) == 0:
                empty_reads += 1
                if empty_reads > 8:
                    break
                await asyncio.sleep(0.005)
                continue
            empty_reads = 0
            chunks.append(samples)
            remaining -= len(samples)
    finally:
        device.stop_stream()

    if not chunks:
        return np.zeros(0, dtype=np.complex64)
    return np.concatenate(chunks).astype(np.complex64, copy=False)


def triage_ism_burst(iq_samples: np.ndarray, sample_rate: float) -> dict[str, Any]:
    if iq_samples is None or len(iq_samples) == 0:
        return {
            "duration_ms": 0.0,
            "occupied_ratio": 0.0,
            "burst_count": 0,
            "pulse_count": 0,
            "suspected_modulation": "unknown",
            "signature": "empty_capture",
            "occupied_bandwidth_hz": 0.0,
        }

    amp = np.abs(iq_samples).astype(np.float64)
    power = amp * amp
    median_power = float(np.median(power))
    mad_power = float(np.median(np.abs(power - median_power)))
    threshold = median_power + max(mad_power * 8.0, median_power * 0.35, 1e-9)
    active = power > threshold

    segments = _active_segments(active)
    pulse_lengths_ms = [round((end - start) * 1000.0 / sample_rate, 3) for start, end in segments]
    occupied_ratio = float(active.mean()) if len(active) else 0.0
    burst_count = len(segments)

    fft_size = min(8192, len(iq_samples))
    occupied_bandwidth_hz = 0.0
    if fft_size >= 256:
        spectrum = np.fft.fftshift(np.fft.fft(iq_samples[:fft_size] * np.hanning(fft_size)))
        power_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
        cutoff = float(np.max(power_db) - 20.0)
        occupied_bins = np.nonzero(power_db >= cutoff)[0]
        if len(occupied_bins) > 0:
            bin_span = occupied_bins[-1] - occupied_bins[0] + 1
            occupied_bandwidth_hz = float(bin_span * sample_rate / fft_size)

    suspected_modulation, signature = _classify_signature(
        occupied_ratio=occupied_ratio,
        burst_count=burst_count,
        median_pulse_ms=float(np.median(pulse_lengths_ms)) if pulse_lengths_ms else 0.0,
        occupied_bandwidth_hz=occupied_bandwidth_hz,
    )

    return {
        "duration_ms": round(len(iq_samples) * 1000.0 / sample_rate, 2),
        "sample_rate": int(sample_rate),
        "median_power": round(median_power, 6),
        "mad_power": round(mad_power, 6),
        "occupied_ratio": round(occupied_ratio, 4),
        "burst_count": burst_count,
        "pulse_count": burst_count,
        "pulse_lengths_ms": pulse_lengths_ms[:16],
        "occupied_bandwidth_hz": round(occupied_bandwidth_hz, 1),
        "peak_amplitude": round(float(np.max(amp)), 6),
        "crest_db": round(_crest_factor_db(amp), 2),
        "suspected_modulation": suspected_modulation,
        "signature": signature,
    }


def summarize_burst_triage(frequency_hz: float, triage: dict[str, Any]) -> str:
    return (
        f"{frequency_hz / 1e6:.3f} MHz ISM burst "
        f"[{triage.get('signature', 'unknown')}] "
        f"mod={triage.get('suspected_modulation', 'unknown')} "
        f"occ={triage.get('occupied_ratio', 0):.2f} "
        f"bursts={triage.get('burst_count', 0)} "
        f"bw={triage.get('occupied_bandwidth_hz', 0):.0f} Hz"
    )


def _active_segments(active: np.ndarray) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for idx, value in enumerate(active):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            segments.append((start, idx))
            start = None
    if start is not None:
        segments.append((start, len(active)))
    return segments


def _crest_factor_db(amplitude: np.ndarray) -> float:
    peak = float(np.max(amplitude)) if len(amplitude) else 0.0
    rms = float(np.sqrt(np.mean(amplitude * amplitude))) if len(amplitude) else 0.0
    if peak <= 0 or rms <= 0:
        return 0.0
    return 20.0 * np.log10(peak / rms)


def _classify_signature(
    occupied_ratio: float,
    burst_count: int,
    median_pulse_ms: float,
    occupied_bandwidth_hz: float,
) -> tuple[str, str]:
    if burst_count == 0:
        return "unknown", "no_discernible_burst"
    if occupied_ratio <= 0.05 and burst_count >= 2:
        return "OOK/ASK", "sparse_pulse_train"
    if occupied_ratio <= 0.20 and occupied_bandwidth_hz <= 150_000:
        return "FSK/OOK", "narrowband_data_burst"
    if occupied_bandwidth_hz >= 250_000:
        return "wideband_digital", "wideband_burst"
    if median_pulse_ms >= 20.0:
        return "slow_telemetry", "slow_repeating_burst"
    return "unknown", "unclassified_burst"
