import asyncio
import logging
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@dataclass
class ScanRange:
    start_hz: float
    end_hz: float
    step_hz: float = 200_000
    label: str = ""

    def frequencies(self) -> NDArray[np.float64]:
        return np.arange(self.start_hz, self.end_hz, self.step_hz)

    @classmethod
    def from_config(cls, cfg: dict) -> "ScanRange":
        return cls(
            start_hz=cfg["start_mhz"] * 1e6,
            end_hz=cfg["end_mhz"] * 1e6,
            label=cfg.get("label", ""),
        )


@dataclass
class DetectedSignal:
    frequency_hz: float
    bandwidth_hz: float
    peak_power: float
    avg_power: float
    bin_start: int
    bin_end: int


def compute_power_spectrum(samples: NDArray[np.complex64], fft_size: int = 1024) -> NDArray[np.float64]:
    windowed = samples[:fft_size] * np.hanning(fft_size)
    spectrum = np.fft.fftshift(np.fft.fft(windowed, n=fft_size))
    magnitude_sq = np.real(spectrum * np.conj(spectrum)) / (fft_size * fft_size)
    magnitude_sq = np.maximum(magnitude_sq, 1e-20)
    return 10.0 * np.log10(magnitude_sq)


def estimate_noise_floor(power_db: NDArray[np.float64]) -> float:
    return float(np.median(power_db))


def find_signals_in_spectrum(
    power_db: NDArray[np.float64],
    center_freq_hz: float,
    sample_rate: float,
    squelch_db: float,
) -> list[DetectedSignal]:
    n = len(power_db)
    hz_per_bin = sample_rate / n

    above = power_db > squelch_db
    signals: list[DetectedSignal] = []

    in_signal = False
    start = 0
    for i in range(n):
        if above[i] and not in_signal:
            start = i
            in_signal = True
        elif not above[i] and in_signal:
            _add_signal(signals, power_db, start, i, center_freq_hz, sample_rate, n, hz_per_bin)
            in_signal = False

    if in_signal:
        _add_signal(signals, power_db, start, n, center_freq_hz, sample_rate, n, hz_per_bin)

    signals.sort(key=lambda s: s.peak_power, reverse=True)
    return signals


def _add_signal(
    signals: list[DetectedSignal],
    power_db: NDArray[np.float64],
    bin_start: int,
    bin_end: int,
    center_freq_hz: float,
    sample_rate: float,
    n: int,
    hz_per_bin: float,
) -> None:
    segment = power_db[bin_start:bin_end]
    peak_bin = bin_start + int(np.argmax(segment))
    freq = center_freq_hz + (peak_bin - n / 2) * hz_per_bin
    bandwidth = (bin_end - bin_start) * hz_per_bin

    signals.append(DetectedSignal(
        frequency_hz=freq,
        bandwidth_hz=bandwidth,
        peak_power=float(np.max(segment)),
        avg_power=float(np.mean(segment)),
        bin_start=bin_start,
        bin_end=bin_end,
    ))


class FrequencyScanner:
    def __init__(
        self,
        device,
        scan_ranges: list[ScanRange],
        fft_size: int = 1024,
        squelch_offset_db: float = 10.0,
        sample_rate: float = 2_000_000,
        dwell_time_s: float = 0.05,
    ) -> None:
        self._device = device
        self._scan_ranges = scan_ranges
        self._fft_size = fft_size
        self._squelch_offset = squelch_offset_db
        self._sample_rate = sample_rate
        self._dwell_time = dwell_time_s
        self._running = False

    async def sweep_once(self) -> list[DetectedSignal]:
        all_signals: list[DetectedSignal] = []
        self._device.set_sample_rate(self._sample_rate)
        self._device.start_stream()

        try:
            for scan_range in self._scan_ranges:
                for freq in scan_range.frequencies():
                    self._device.tune(freq)
                    await asyncio.sleep(self._dwell_time)

                    samples = self._device.read_samples(self._fft_size)
                    if samples is None or len(samples) < self._fft_size:
                        continue

                    power_db = compute_power_spectrum(samples, self._fft_size)
                    noise_floor = estimate_noise_floor(power_db)
                    squelch = noise_floor + self._squelch_offset

                    signals = find_signals_in_spectrum(
                        power_db=power_db,
                        center_freq_hz=freq,
                        sample_rate=self._sample_rate,
                        squelch_db=squelch,
                    )
                    all_signals.extend(signals)
                    if signals:
                        logger.info(
                            "Found %d signal(s) near %.3f MHz",
                            len(signals), freq / 1e6,
                        )
        finally:
            self._device.stop_stream()

        return all_signals

    async def run(self, callback=None) -> None:
        self._running = True
        while self._running:
            signals = await self.sweep_once()
            if callback and signals:
                await callback(signals)

    def stop(self) -> None:
        self._running = False
