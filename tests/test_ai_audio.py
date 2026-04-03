import numpy as np
import pytest

from signaldeck.ai.audio_classifier import AudioContentClassifier, compute_mfcc


def test_compute_mfcc_shape():
    """MFCC features have expected shape."""
    audio = np.random.randn(48000).astype(np.float32)
    mfcc = compute_mfcc(audio, sample_rate=48000, n_mfcc=13)
    assert mfcc.ndim == 2
    assert mfcc.shape[0] == 13  # n_mfcc coefficients


def test_classifier_predict_returns_label():
    """Classifier returns a content type label and confidence."""
    classifier = AudioContentClassifier()
    audio = np.random.randn(48000).astype(np.float32) * 0.01  # quiet noise
    label, confidence = classifier.predict(audio)
    assert label in classifier.labels
    assert 0.0 <= confidence <= 1.0


def test_classifier_labels():
    """Has expected content labels."""
    classifier = AudioContentClassifier()
    assert "speech" in classifier.labels
    assert "noise" in classifier.labels
    assert "digital_data" in classifier.labels


def test_classify_silence_as_noise():
    """Near-silence should be classified as noise."""
    classifier = AudioContentClassifier()
    audio = np.zeros(48000, dtype=np.float32) + 1e-6 * np.random.randn(48000).astype(np.float32)
    label, conf = classifier.predict(audio)
    assert label == "noise"


def test_classify_tone_not_noise():
    """A pure tone should not be classified as noise."""
    classifier = AudioContentClassifier()
    t = np.arange(48000) / 48000.0
    audio = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    label, conf = classifier.predict(audio)
    assert label != "noise"
