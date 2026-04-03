import logging

import numpy as np
from numpy.typing import NDArray
from scipy.fft import dct

logger = logging.getLogger(__name__)

DEFAULT_AUDIO_LABELS = ["speech", "digital_data", "noise", "music", "tones"]


def compute_mfcc(
    audio: NDArray[np.float32],
    sample_rate: int = 48000,
    n_mfcc: int = 13,
    n_fft: int = 1024,
    hop: int = 512,
    n_mels: int = 40,
) -> NDArray[np.float32]:
    """Compute Mel-frequency cepstral coefficients from audio.

    Returns:
        2D array of shape (n_mfcc, num_frames).
    """
    # Frame the signal
    n = len(audio)
    num_frames = max(1, (n - n_fft) // hop + 1)
    window = np.hanning(n_fft).astype(np.float32)

    # Compute power spectrum for each frame
    power_frames = np.zeros((num_frames, n_fft // 2 + 1), dtype=np.float32)
    for i in range(num_frames):
        start = i * hop
        frame = audio[start:start + n_fft]
        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        windowed = frame * window
        spectrum = np.fft.rfft(windowed)
        power_frames[i] = np.abs(spectrum) ** 2 / n_fft

    # Mel filter bank
    low_mel = 0
    high_mel = 2595 * np.log10(1 + (sample_rate / 2) / 700)
    mel_points = np.linspace(low_mel, high_mel, n_mels + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    filters = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(n_mels):
        left = bin_points[m]
        center = bin_points[m + 1]
        right = bin_points[m + 2]
        for k in range(left, center):
            if center > left:
                filters[m, k] = (k - left) / (center - left)
        for k in range(center, right):
            if right > center:
                filters[m, k] = (right - k) / (right - center)

    # Apply mel filters and take log
    mel_spec = np.dot(power_frames, filters.T)
    mel_spec = np.maximum(mel_spec, 1e-10)
    log_mel = np.log(mel_spec)

    # DCT to get MFCCs
    mfcc = dct(log_mel, type=2, axis=1, norm='ortho')[:, :n_mfcc]

    return mfcc.T  # (n_mfcc, num_frames)


class AudioContentClassifier:
    """Classifies audio content as speech, digital data, noise, music, or tones.

    Uses MFCC features with simple statistical analysis.
    Can be upgraded to a neural net when training data is available.
    """

    def __init__(self, labels: list[str] | None = None) -> None:
        self.labels = labels or DEFAULT_AUDIO_LABELS

    def predict(self, audio: NDArray[np.float32], sample_rate: int = 48000) -> tuple[str, float]:
        """Classify audio content.

        Returns:
            (label, confidence) tuple.
        """
        # Check for silence/noise
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 0.001:
            return "noise", 0.9

        # Compute MFCCs
        mfcc = compute_mfcc(audio, sample_rate=sample_rate)

        # Feature extraction from MFCCs
        mfcc_mean = np.mean(mfcc, axis=1)
        mfcc_std = np.std(mfcc, axis=1)

        # Zero crossing rate
        signs = np.sign(audio)
        zcr = np.mean(np.abs(np.diff(signs))) / 2

        # Spectral flatness (Wiener entropy)
        spectrum = np.abs(np.fft.rfft(audio))
        spectrum = np.maximum(spectrum, 1e-10)
        geo_mean = np.exp(np.mean(np.log(spectrum)))
        arith_mean = np.mean(spectrum)
        flatness = geo_mean / (arith_mean + 1e-10)

        # Heuristic classification based on features
        # Digital data: high ZCR, high spectral flatness, low MFCC variance
        if zcr > 0.3 and flatness > 0.3:
            return "digital_data", 0.6

        # Tones: low spectral flatness (peaky spectrum), low ZCR
        if flatness < 0.05 and zcr < 0.15:
            return "tones", 0.6

        # Music: moderate spectral flatness, moderate variance in MFCCs
        if 0.05 < flatness < 0.3 and np.mean(mfcc_std) > 1.5:
            return "music", 0.4

        # Speech: characteristic MFCC patterns
        # First MFCC (energy) has high variance, moderate ZCR
        if mfcc_std[0] > 1.0 and 0.05 < zcr < 0.3:
            return "speech", 0.5

        # Default based on energy
        if rms > 0.05:
            return "speech", 0.3
        return "noise", 0.5

    def predict_batch(
        self, audio_chunks: list[NDArray[np.float32]], sample_rate: int = 48000
    ) -> list[tuple[str, float]]:
        """Classify multiple audio chunks."""
        return [self.predict(chunk, sample_rate) for chunk in audio_chunks]
