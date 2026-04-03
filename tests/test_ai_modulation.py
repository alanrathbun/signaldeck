import numpy as np
import pytest

from signaldeck.ai.modulation_cnn import ModulationClassifier, iq_to_spectrogram


def test_iq_to_spectrogram_shape():
    """Convert IQ samples to spectrogram with expected shape."""
    iq = np.random.randn(2048) + 1j * np.random.randn(2048)
    iq = iq.astype(np.complex64)
    spec = iq_to_spectrogram(iq, fft_size=64, hop=32)
    assert spec.ndim == 2
    assert spec.shape[1] == 64  # frequency bins


def test_iq_to_spectrogram_values():
    """Spectrogram values are in dB (negative for normalized signals)."""
    iq = 0.01 * (np.random.randn(2048) + 1j * np.random.randn(2048)).astype(np.complex64)
    spec = iq_to_spectrogram(iq, fft_size=64, hop=32)
    assert np.all(np.isfinite(spec))
    assert np.mean(spec) < 0  # dB values for weak signal


def test_classifier_predict_returns_label_and_confidence():
    """Classifier returns a modulation label and confidence."""
    classifier = ModulationClassifier()
    iq = np.random.randn(4096) + 1j * np.random.randn(4096)
    iq = iq.astype(np.complex64)
    label, confidence = classifier.predict(iq)
    assert isinstance(label, str)
    assert label in classifier.labels
    assert 0.0 <= confidence <= 1.0


def test_classifier_labels():
    """Classifier has expected modulation labels."""
    classifier = ModulationClassifier()
    assert "FM" in classifier.labels
    assert "AM" in classifier.labels
    assert "noise" in classifier.labels
    assert len(classifier.labels) >= 5


def test_classifier_predict_batch():
    """Can classify multiple signals."""
    classifier = ModulationClassifier()
    samples = [
        (np.random.randn(4096) + 1j * np.random.randn(4096)).astype(np.complex64)
        for _ in range(3)
    ]
    results = classifier.predict_batch(samples)
    assert len(results) == 3
    for label, conf in results:
        assert isinstance(label, str)
        assert 0.0 <= conf <= 1.0
