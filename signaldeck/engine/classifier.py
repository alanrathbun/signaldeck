import logging
from dataclasses import replace
from signaldeck.decoders.base import SignalInfo

logger = logging.getLogger(__name__)

_WEATHER_FREQS = [162_400_000, 162_425_000, 162_450_000, 162_475_000, 162_500_000, 162_525_000, 162_550_000]
_NOAA_APT_FREQS = [137_100_000, 137_912_500]
_KEY_FOB_FREQS = [315_000_000, 390_000_000, 433_920_000]

class SignalClassifier:
    def classify(self, signal: SignalInfo) -> SignalInfo:
        freq = signal.frequency_hz
        bw = signal.bandwidth_hz
        features = signal.signal_features or {}
        protocol, modulation = self._check_known_frequencies(freq, bw)
        if protocol:
            signal_class, content_confidence = self._characterize(freq, bw, modulation, protocol, features)
            return replace(
                signal,
                modulation=modulation,
                protocol_hint=protocol,
                signal_class=signal_class,
                content_confidence=content_confidence,
            )
        protocol, modulation = self._check_frequency_bands(freq, bw)
        if protocol:
            signal_class, content_confidence = self._characterize(freq, bw, modulation, protocol, features)
            return replace(
                signal,
                modulation=modulation,
                protocol_hint=protocol,
                signal_class=signal_class,
                content_confidence=content_confidence,
            )
        modulation = self._guess_modulation(freq, bw)
        signal_class, content_confidence = self._characterize(freq, bw, modulation, "", features)
        return replace(
            signal,
            modulation=modulation,
            signal_class=signal_class,
            content_confidence=content_confidence,
        )

    def _check_known_frequencies(self, freq, bw):
        for wf in _WEATHER_FREQS:
            if abs(freq - wf) < 5000: return "weather_radio", "FM"
        for nf in _NOAA_APT_FREQS:
            if abs(freq - nf) < 25000: return "noaa_apt", "FM"
        if abs(freq - 1_090_000_000) < 500_000: return "adsb", "PULSE"
        if abs(freq - 131_550_000) < 12500: return "acars", "AM"
        for kf in _KEY_FOB_FREQS:
            if abs(freq - kf) < 300_000: return "ism", "OOK"
        return "", ""

    def _check_frequency_bands(self, freq, bw):
        if 87.5e6 <= freq <= 108e6 and bw > 100_000: return "broadcast_fm", "FM"
        if 118e6 <= freq <= 137e6: return "aviation", "AM"
        if 156e6 <= freq <= 163e6 and bw <= 25_000: return "marine", "FM"
        if 144e6 <= freq <= 148e6 and bw <= 25_000: return "amateur_radio", "FM"
        if 420e6 <= freq <= 450e6 and bw <= 25_000: return "amateur_radio", "FM"
        if 54e6 <= freq <= 88e6 and bw >= 100_000: return "tv_broadcast", "WBFM"
        if 174e6 <= freq <= 216e6 and bw >= 100_000: return "tv_broadcast", "WBFM"
        if 470e6 <= freq <= 608e6 and bw >= 100_000: return "tv_broadcast", "WBFM"
        if 152e6 <= freq <= 154e6 and bw <= 25_000: return "pager", "FM"
        if 430e6 <= freq <= 440e6 and bw < 200_000: return "ism", "unknown"
        if 314.8e6 <= freq <= 315.3e6 and bw < 500_000: return "ism", "OOK"
        if 389.8e6 <= freq <= 390.3e6 and bw < 500_000: return "ism", "OOK"
        if 902e6 <= freq <= 928e6 and bw < 500_000: return "ism", "unknown"
        if 769e6 <= freq <= 776e6 and bw <= 25_000: return "public_safety", "FM"
        if 851e6 <= freq <= 869e6 and bw <= 25_000: return "public_safety", "FM"
        if bw <= 12_500 and (130e6 <= freq <= 175e6 or 400e6 <= freq <= 512e6): return "narrowband_fm", "FM"
        if 87.5e6 <= freq <= 108e6 and bw >= 30_000: return "broadcast_fm", "FM"
        return "", ""

    def _guess_modulation(self, freq, bw):
        if 118e6 <= freq <= 137e6: return "AM"
        if freq > 30e6: return "FM"
        return "unknown"

    def _characterize(self, freq, bw, modulation, protocol, features):
        modulation = (modulation or "unknown").upper()
        protocol = protocol or ""
        has_features = bool(features)
        prominence_db = float(features.get("prominence_db", 0.0))
        peak_to_avg_db = float(features.get("peak_to_avg_db", 0.0))
        occupied_bins = int(features.get("occupied_bins", 1))
        spectral_flatness = float(features.get("spectral_flatness", 0.0))

        # When the sweep sees only a one/two-bin narrow peak with little internal
        # structure, treat it as a likely carrier/tone rather than voice.
        if has_features and modulation not in ("OOK", "PULSE"):
            if bw <= 3_000 or (occupied_bins <= 2 and prominence_db >= 8 and peak_to_avg_db < 2.0):
                return "carrier_or_tone", 0.78

        if protocol in ("weather_radio", "marine", "aviation", "amateur_radio", "public_safety"):
            if bw <= 16_000 and spectral_flatness < 0.18:
                return "likely_analog_voice", 0.8
            if bw <= 20_000:
                return "likely_voice", 0.85
            return "digital_voice_or_data", 0.65
        if protocol in ("broadcast_fm", "tv_broadcast"):
            return "broadcast_program", 0.95
        if protocol in ("adsb", "acars", "pager", "noaa_apt"):
            return "structured_data", 0.95
        if protocol == "ism":
            if modulation in ("OOK", "PULSE") or peak_to_avg_db >= 10:
                return "burst_telemetry", 0.9
            return "short_burst_data", 0.75

        if modulation == "AM" and 118e6 <= freq <= 137e6:
            return "likely_analog_voice", 0.8
        if modulation in ("FM", "NFM"):
            if bw <= 4_000 and peak_to_avg_db > 12:
                return "carrier_or_tone", 0.75
            if bw <= 16_000:
                if spectral_flatness < 0.18 and prominence_db > 10:
                    return "likely_analog_voice", 0.7
                if peak_to_avg_db < 5 and prominence_db > 8:
                    return "digital_voice_or_data", 0.65
                return "likely_voice", 0.65
            if bw <= 50_000:
                return "narrowband_channel", 0.55
            if bw >= 150_000:
                return "wideband_program", 0.8
        if modulation in ("OOK", "PULSE"):
            return "burst_telemetry", 0.85
        if bw < 5_000:
            return "carrier_or_tone", 0.5
        if bw > 250_000:
            return "wideband_data_or_video", 0.6
        return "unknown", 0.3
