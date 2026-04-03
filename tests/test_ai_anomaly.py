import numpy as np
import pytest

from signaldeck.ai.anomaly_detector import AnomalyDetector


def test_detector_starts_empty():
    detector = AnomalyDetector()
    assert detector.num_profiles == 0


def test_update_profile():
    """Can update a frequency band profile with observations."""
    detector = AnomalyDetector()
    detector.update("vhf_high", power=-50.0, bandwidth=12500.0, modulation="FM")
    detector.update("vhf_high", power=-48.0, bandwidth=12500.0, modulation="FM")
    detector.update("vhf_high", power=-52.0, bandwidth=12500.0, modulation="FM")
    assert detector.num_profiles == 1


def test_no_anomaly_on_normal_signal():
    """Normal signal within learned profile is not anomalous."""
    detector = AnomalyDetector()
    for _ in range(20):
        detector.update("uhf", power=-50.0 + np.random.randn() * 2,
                        bandwidth=12500.0, modulation="FM")
    is_anomaly, score, reasons = detector.check("uhf", power=-49.0, bandwidth=12500.0, modulation="FM")
    assert not is_anomaly
    assert score < 0.5


def test_anomaly_on_unusual_power():
    """Signal much stronger than normal is flagged."""
    detector = AnomalyDetector()
    for _ in range(30):
        detector.update("uhf", power=-60.0 + np.random.randn(), bandwidth=12500.0, modulation="FM")
    is_anomaly, score, reasons = detector.check("uhf", power=-20.0, bandwidth=12500.0, modulation="FM")
    assert is_anomaly
    assert score > 0.5
    assert any("power" in r.lower() for r in reasons)


def test_anomaly_on_new_modulation():
    """New modulation type on a known band is flagged."""
    detector = AnomalyDetector()
    for _ in range(20):
        detector.update("uhf", power=-50.0, bandwidth=12500.0, modulation="FM")
    is_anomaly, score, reasons = detector.check("uhf", power=-50.0, bandwidth=12500.0, modulation="4FSK")
    assert is_anomaly
    assert any("modulation" in r.lower() for r in reasons)


def test_unknown_band_is_novel():
    """Signal on an unknown band is flagged as novel."""
    detector = AnomalyDetector()
    detector.update("uhf", power=-50.0, bandwidth=12500.0, modulation="FM")
    is_anomaly, score, reasons = detector.check("new_band", power=-50.0, bandwidth=12500.0, modulation="FM")
    assert is_anomaly
    assert any("new" in r.lower() or "unknown" in r.lower() for r in reasons)


def test_save_and_load(tmp_path):
    """Can save and load profiles."""
    detector = AnomalyDetector()
    for _ in range(10):
        detector.update("uhf", power=-50.0, bandwidth=12500.0, modulation="FM")
    path = str(tmp_path / "profiles.json")
    detector.save(path)

    detector2 = AnomalyDetector()
    detector2.load(path)
    assert detector2.num_profiles == 1
