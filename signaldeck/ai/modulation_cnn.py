import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Modulation labels the classifier can identify
DEFAULT_LABELS = [
    "AM", "FM", "4FSK", "GMSK", "OOK", "OFDM",
    "PSK", "noise", "unknown",
]


def iq_to_spectrogram(
    iq_samples: NDArray[np.complex64],
    fft_size: int = 64,
    hop: int = 32,
) -> NDArray[np.float32]:
    """Convert IQ samples to a power spectrogram in dB.

    Args:
        iq_samples: Complex IQ samples.
        fft_size: FFT window size.
        hop: Hop size between windows.

    Returns:
        2D array of shape (num_frames, fft_size) in dB.
    """
    n = len(iq_samples)
    num_frames = max(1, (n - fft_size) // hop + 1)
    window = np.hanning(fft_size).astype(np.float32)

    frames = np.zeros((num_frames, fft_size), dtype=np.float32)
    for i in range(num_frames):
        start = i * hop
        segment = iq_samples[start:start + fft_size]
        windowed = segment * window
        spectrum = np.fft.fftshift(np.fft.fft(windowed))
        power = np.real(spectrum * np.conj(spectrum)) / (fft_size * fft_size)
        power = np.maximum(power, 1e-20)
        frames[i] = 10.0 * np.log10(power).astype(np.float32)

    return frames


class _SmallCNN(nn.Module):
    """Small CNN for spectrogram classification."""

    def __init__(self, num_classes: int, freq_bins: int = 64) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((8, 8)),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.fc = nn.Sequential(
            nn.Flatten(),
            nn.Linear(32 * 4 * 4, 64),
            nn.ReLU(),
            nn.Linear(64, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        return self.fc(x)


class ModulationClassifier:
    """CNN-based modulation classifier for IQ signals.

    Uses a small CNN on spectrograms to classify modulation type.
    Without a trained model, falls back to heuristic classification.
    """

    def __init__(
        self,
        model_path: str | None = None,
        labels: list[str] | None = None,
        fft_size: int = 64,
    ) -> None:
        self.labels = labels or DEFAULT_LABELS
        self._fft_size = fft_size
        self._model = _SmallCNN(num_classes=len(self.labels), freq_bins=fft_size)
        self._model.eval()
        self._trained = False

        if model_path and Path(model_path).exists():
            self._model.load_state_dict(torch.load(model_path, map_location="cpu"))
            self._trained = True
            logger.info("Loaded modulation classifier from %s", model_path)
        else:
            logger.info("Modulation classifier initialized (untrained, using heuristics)")

    def predict(self, iq_samples: NDArray[np.complex64]) -> tuple[str, float]:
        """Classify modulation type from IQ samples.

        Returns:
            (label, confidence) tuple.
        """
        if not self._trained:
            return self._heuristic_classify(iq_samples)

        spec = iq_to_spectrogram(iq_samples, fft_size=self._fft_size)
        tensor = torch.from_numpy(spec).unsqueeze(0).unsqueeze(0)  # (1, 1, T, F)

        with torch.no_grad():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)
            conf, idx = torch.max(probs, dim=1)

        return self.labels[idx.item()], conf.item()

    def predict_batch(
        self, samples_list: list[NDArray[np.complex64]]
    ) -> list[tuple[str, float]]:
        """Classify multiple signals."""
        return [self.predict(s) for s in samples_list]

    def _heuristic_classify(self, iq_samples: NDArray[np.complex64]) -> tuple[str, float]:
        """Fallback heuristic when no trained model is available."""
        # Compute basic signal properties
        power = np.mean(np.abs(iq_samples) ** 2)
        if power < 1e-8:
            return "noise", 0.8

        # Check for FM characteristics (constant envelope)
        envelope = np.abs(iq_samples)
        envelope_std = np.std(envelope) / (np.mean(envelope) + 1e-10)

        if envelope_std < 0.15:
            # Constant envelope — likely FM or FSK
            # Check instantaneous frequency variance for FSK detection
            phase_diff = np.angle(iq_samples[1:] * np.conj(iq_samples[:-1]))
            freq_std = np.std(phase_diff)
            if freq_std > 0.5:
                return "4FSK", 0.4
            return "FM", 0.5
        elif envelope_std > 0.5:
            # High envelope variation — likely AM
            return "AM", 0.4
        else:
            return "unknown", 0.3

    def save(self, path: str) -> None:
        """Save model weights."""
        torch.save(self._model.state_dict(), path)
        logger.info("Model saved to %s", path)
