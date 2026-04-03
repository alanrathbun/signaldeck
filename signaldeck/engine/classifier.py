import logging
from dataclasses import replace
from signaldeck.decoders.base import SignalInfo

logger = logging.getLogger(__name__)

_WEATHER_FREQS = [162_400_000, 162_425_000, 162_450_000, 162_475_000, 162_500_000, 162_525_000, 162_550_000]
_NOAA_APT_FREQS = [137_100_000, 137_912_500]

class SignalClassifier:
    def classify(self, signal: SignalInfo) -> SignalInfo:
        freq = signal.frequency_hz
        bw = signal.bandwidth_hz
        protocol, modulation = self._check_known_frequencies(freq, bw)
        if protocol:
            return replace(signal, modulation=modulation, protocol_hint=protocol)
        protocol, modulation = self._check_frequency_bands(freq, bw)
        if protocol:
            return replace(signal, modulation=modulation, protocol_hint=protocol)
        modulation = self._guess_modulation(freq, bw)
        return replace(signal, modulation=modulation)

    def _check_known_frequencies(self, freq, bw):
        for wf in _WEATHER_FREQS:
            if abs(freq - wf) < 5000: return "weather_radio", "FM"
        for nf in _NOAA_APT_FREQS:
            if abs(freq - nf) < 25000: return "noaa_apt", "FM"
        if abs(freq - 1_090_000_000) < 500_000: return "adsb", "PULSE"
        if abs(freq - 131_550_000) < 12500: return "acars", "AM"
        return "", ""

    def _check_frequency_bands(self, freq, bw):
        if 87.5e6 <= freq <= 108e6 and bw > 100_000: return "broadcast_fm", "FM"
        if 118e6 <= freq <= 137e6: return "aviation", "AM"
        if 430e6 <= freq <= 440e6 and bw < 200_000: return "ism", "unknown"
        if 902e6 <= freq <= 928e6 and bw < 500_000: return "ism", "unknown"
        if bw <= 12_500 and (130e6 <= freq <= 175e6 or 400e6 <= freq <= 512e6): return "narrowband_fm", "FM"
        if 87.5e6 <= freq <= 108e6: return "broadcast_fm", "FM"
        return "", ""

    def _guess_modulation(self, freq, bw):
        if 118e6 <= freq <= 137e6: return "AM"
        if freq > 30e6: return "FM"
        return "unknown"
