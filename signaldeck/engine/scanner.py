import asyncio
import logging
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

FM_BROADCAST_LOW = 87_500_000   # Hz
FM_BROADCAST_HIGH = 108_000_000 # Hz


@dataclass
class ScanRange:
    start_hz: float
    end_hz: float
    step_hz: float = 200_000
    label: str = ""
    priority: int = 10

    def frequencies(self) -> NDArray[np.float64]:
        return np.arange(self.start_hz, self.end_hz, self.step_hz)

    @classmethod
    def from_config(cls, cfg: dict) -> "ScanRange":
        return cls(
            start_hz=cfg["start_mhz"] * 1e6,
            end_hz=cfg["end_mhz"] * 1e6,
            step_hz=cfg.get("step_khz", 200) * 1e3,
            label=cfg.get("label", ""),
            priority=cfg.get("priority", 10),
        )


@dataclass
class DetectedSignal:
    frequency_hz: float
    bandwidth_hz: float
    peak_power: float
    avg_power: float
    bin_start: int
    bin_end: int
    features: dict | None = None


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
    noise_floor = estimate_noise_floor(power_db)

    above = power_db > squelch_db
    signals: list[DetectedSignal] = []

    in_signal = False
    start = 0
    for i in range(n):
        if above[i] and not in_signal:
            start = i
            in_signal = True
        elif not above[i] and in_signal:
            _add_signal(signals, power_db, start, i, center_freq_hz, sample_rate, n, hz_per_bin, noise_floor)
            in_signal = False

    if in_signal:
        _add_signal(signals, power_db, start, n, center_freq_hz, sample_rate, n, hz_per_bin, noise_floor)

    if FM_BROADCAST_LOW <= center_freq_hz <= FM_BROADCAST_HIGH:
        fm_signal = _detect_broadcast_fm_signal(
            power_db=power_db,
            center_freq_hz=center_freq_hz,
            sample_rate=sample_rate,
            n=n,
            hz_per_bin=hz_per_bin,
            noise_floor=noise_floor,
            squelch_db=squelch_db,
            existing=signals,
        )
        if fm_signal is not None:
            signals.append(fm_signal)

    signals.sort(key=lambda s: s.peak_power, reverse=True)
    return signals


def _detect_broadcast_fm_signal(
    power_db: NDArray[np.float64],
    center_freq_hz: float,
    sample_rate: float,
    n: int,
    hz_per_bin: float,
    noise_floor: float,
    squelch_db: float,
    existing: list[DetectedSignal],
) -> DetectedSignal | None:
    # If the generic detector already found a wide signal here, do not add a duplicate.
    for sig in existing:
        if sig.bandwidth_hz >= 80_000:
            return None

    window_bins = max(48, int(round(150_000 / hz_per_bin)))
    if window_bins >= n:
        return None

    kernel = np.ones(window_bins, dtype=np.float64) / window_bins
    smoothed = np.convolve(power_db, kernel, mode="valid")
    best_start = int(np.argmax(smoothed))
    best_avg = float(smoothed[best_start])
    best_end = min(n, best_start + window_bins)
    segment = power_db[best_start:best_end]
    if len(segment) == 0:
        return None

    peak_power = float(np.max(segment))
    prominence_db = best_avg - noise_floor
    if prominence_db < 4.5 or peak_power < (squelch_db + 2.0):
        return None

    peak_bin = best_start + int(np.argmax(segment))
    freq = center_freq_hz + (peak_bin - n / 2) * hz_per_bin
    bandwidth = (best_end - best_start) * hz_per_bin
    peak_to_avg_db = peak_power - best_avg
    occupied_bins = max(1, best_end - best_start)
    flatness = float(np.std(segment)) / max(1.0, abs(best_avg))

    return DetectedSignal(
        frequency_hz=freq,
        bandwidth_hz=bandwidth,
        peak_power=peak_power,
        avg_power=best_avg,
        bin_start=best_start,
        bin_end=best_end,
        features={
            "prominence_db": prominence_db,
            "peak_to_avg_db": peak_to_avg_db,
            "occupied_bins": occupied_bins,
            "spectral_flatness": flatness,
            "relative_bandwidth": bandwidth / sample_rate if sample_rate else 0.0,
        },
    )


def _add_signal(
    signals: list[DetectedSignal],
    power_db: NDArray[np.float64],
    bin_start: int,
    bin_end: int,
    center_freq_hz: float,
    sample_rate: float,
    n: int,
    hz_per_bin: float,
    noise_floor: float,
) -> None:
    segment = power_db[bin_start:bin_end]
    peak_bin = bin_start + int(np.argmax(segment))
    freq = center_freq_hz + (peak_bin - n / 2) * hz_per_bin
    bandwidth = (bin_end - bin_start) * hz_per_bin
    peak_power = float(np.max(segment))
    avg_power = float(np.mean(segment))
    prominence_db = peak_power - noise_floor
    flatness = float(np.std(segment)) / max(1.0, abs(avg_power))
    occupied_bins = max(1, bin_end - bin_start)

    signals.append(DetectedSignal(
        frequency_hz=freq,
        bandwidth_hz=bandwidth,
        peak_power=peak_power,
        avg_power=avg_power,
        bin_start=bin_start,
        bin_end=bin_end,
        features={
            "prominence_db": prominence_db,
            "peak_to_avg_db": peak_power - avg_power,
            "occupied_bins": occupied_bins,
            "spectral_flatness": flatness,
            "relative_bandwidth": bandwidth / sample_rate if sample_rate else 0.0,
        },
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

    async def sweep_once(
        self,
        fft_callback=None,
        rds_callback=None,
        rds_sample_count: int = 0,
        signal_callback=None,
        progress_callback=None,
    ) -> list[DetectedSignal]:
        all_signals: list[DetectedSignal] = []
        self._device.set_sample_rate(self._sample_rate)
        self._device.start_stream()

        try:
            for scan_range in self._scan_ranges:
                freqs = scan_range.frequencies()
                total_steps = len(freqs)
                for step_index, freq in enumerate(freqs):
                    if progress_callback is not None:
                        await progress_callback(scan_range, float(freq), step_index, total_steps)
                    self._device.tune(freq)
                    await asyncio.sleep(self._dwell_time)

                    samples = self._device.read_samples(self._fft_size)
                    if samples is None or len(samples) < self._fft_size:
                        continue

                    power_db = compute_power_spectrum(samples, self._fft_size)

                    # Broadcast FFT data for waterfall display
                    if fft_callback is not None:
                        await fft_callback(freq, self._sample_rate, power_db)

                    noise_floor = estimate_noise_floor(power_db)
                    squelch = noise_floor + self._squelch_offset

                    signals = find_signals_in_spectrum(
                        power_db=power_db,
                        center_freq_hz=freq,
                        sample_rate=self._sample_rate,
                        squelch_db=squelch,
                    )
                    all_signals.extend(signals)
                    if signals and signal_callback is not None:
                        await signal_callback(signals)
                    # Read extra IQ for RDS decoding on FM broadcast frequencies
                    if (rds_callback and rds_sample_count > 0
                            and FM_BROADCAST_LOW <= freq <= FM_BROADCAST_HIGH):
                        rds_iq = self._device.read_samples(rds_sample_count)
                        if rds_iq is not None and len(rds_iq) >= rds_sample_count:
                            await rds_callback(freq, rds_iq)
                    if signals:
                        logger.debug(
                            "Found %d signal(s) near %.3f MHz",
                            len(signals), freq / 1e6,
                        )
        finally:
            self._device.stop_stream()

        return all_signals

    async def strength_sweep_once(self, fft_callback=None, signal_callback=None) -> list[DetectedSignal]:
        """Sweep by reading signal strength at each frequency (for gqrx backend).

        Instead of computing FFT from IQ samples, tunes to each frequency and
        reads a single signal strength value from the device.
        """
        all_signals: list[DetectedSignal] = []

        for scan_range in self._scan_ranges:
            freqs = scan_range.frequencies()
            strengths = np.full(len(freqs), -100.0)

            for i, freq in enumerate(freqs):
                await self._device.tune(freq)
                if self._dwell_time > 0:
                    await asyncio.sleep(self._dwell_time)
                strengths[i] = await self._device.get_signal_strength()

            # Broadcast the collected strengths as a power array for waterfall
            if fft_callback is not None:
                center = (scan_range.start_hz + scan_range.end_hz) / 2
                bandwidth = scan_range.end_hz - scan_range.start_hz
                await fft_callback(center, bandwidth, strengths)

            # Detect signals above noise floor + squelch offset
            noise_floor = float(np.median(strengths))
            threshold = noise_floor + self._squelch_offset

            for i, freq in enumerate(freqs):
                if strengths[i] > threshold:
                    all_signals.append(DetectedSignal(
                        frequency_hz=freq,
                        bandwidth_hz=scan_range.step_hz,
                        peak_power=float(strengths[i]),
                        avg_power=float(strengths[i]),
                        bin_start=i,
                        bin_end=i + 1,
                    ))
            if all_signals and signal_callback is not None:
                await signal_callback(list(all_signals))

        all_signals.sort(key=lambda s: s.peak_power, reverse=True)
        return all_signals

    async def bookmark_scan_once(self, bookmarks, fft_callback=None, signal_callback=None) -> list[DetectedSignal]:
        """Scan a list of bookmarked frequencies by reading signal strength.

        Args:
            bookmarks: List of Bookmark objects to scan.
            fft_callback: Optional async callback(center_freq, bandwidth, power_array).

        Returns:
            List of DetectedSignal for active bookmarks.
        """
        if not bookmarks:
            return []

        signals: list[DetectedSignal] = []
        freqs = np.array([b.frequency for b in bookmarks])
        strengths = np.full(len(bookmarks), -100.0)

        for i, bk in enumerate(bookmarks):
            await self._device.tune(bk.frequency)
            if self._dwell_time > 0:
                await asyncio.sleep(self._dwell_time)
            strengths[i] = await self._device.get_signal_strength()

        # Broadcast for waterfall
        if fft_callback is not None and len(bookmarks) > 0:
            center = (freqs.min() + freqs.max()) / 2
            bandwidth = freqs.max() - freqs.min() if len(freqs) > 1 else 1e6
            await fft_callback(center, bandwidth, strengths)

        # Detect active signals
        noise_floor = float(np.median(strengths))
        threshold = noise_floor + self._squelch_offset

        for i, bk in enumerate(bookmarks):
            if strengths[i] > threshold:
                signals.append(DetectedSignal(
                    frequency_hz=bk.frequency,
                    bandwidth_hz=0,  # unknown from strength reading
                    peak_power=float(strengths[i]),
                    avg_power=float(strengths[i]),
                    bin_start=i,
                    bin_end=i + 1,
                ))
        if signals and signal_callback is not None:
            await signal_callback(list(signals))

        signals.sort(key=lambda s: s.peak_power, reverse=True)
        return signals

    async def run(self, callback=None, fft_callback=None) -> None:
        self._running = True
        while self._running:
            signals = await self.sweep_once(fft_callback=fft_callback)
            if callback and signals:
                await callback(signals)

    def stop(self) -> None:
        self._running = False
