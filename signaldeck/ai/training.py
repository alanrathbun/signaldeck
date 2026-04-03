import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@dataclass
class TrainingSample:
    """A confirmed training sample for the modulation classifier."""
    iq_data: NDArray[np.complex64]
    label: str
    frequency_hz: float
    confidence: float  # how confident the decoder was
    source: str  # "decoder_confirmed", "user_correction", etc.


class TrainingPipeline:
    """Collects confirmed samples and retrains the modulation classifier.

    Signals successfully decoded by a protocol decoder become confirmed
    training labels. User corrections also feed back as training data.
    """

    def __init__(
        self,
        min_samples_per_class: int = 50,
        storage_dir: str = "data/training",
    ) -> None:
        self._samples: dict[str, list[TrainingSample]] = {}
        self._min_per_class = min_samples_per_class
        self._storage_dir = Path(storage_dir)

    @property
    def sample_count(self) -> int:
        return sum(len(v) for v in self._samples.values())

    def add_sample(self, sample: TrainingSample) -> None:
        """Add a confirmed training sample."""
        self._samples.setdefault(sample.label, []).append(sample)

        # Cap per-class storage
        if len(self._samples[sample.label]) > 1000:
            self._samples[sample.label] = self._samples[sample.label][-500:]

    def get_stats(self) -> dict[str, int]:
        """Return sample count per label."""
        return {label: len(samples) for label, samples in self._samples.items()}

    def ready_to_train(self) -> bool:
        """Check if enough samples exist for retraining."""
        classes_ready = sum(
            1 for samples in self._samples.values()
            if len(samples) >= self._min_per_class
        )
        return classes_ready >= 2  # need at least 2 classes

    def train(self, classifier) -> dict:
        """Retrain the modulation classifier with collected samples.

        Args:
            classifier: ModulationClassifier instance to retrain.

        Returns:
            Training stats dict.
        """
        if not self.ready_to_train():
            logger.warning("Not enough samples for training")
            return {"status": "insufficient_data", "stats": self.get_stats()}

        from signaldeck.ai.modulation_cnn import iq_to_spectrogram
        import torch

        # Prepare dataset
        spectrograms = []
        labels = []
        label_to_idx = {label: i for i, label in enumerate(classifier.labels)}

        for label, samples in self._samples.items():
            if label not in label_to_idx:
                continue
            idx = label_to_idx[label]
            for sample in samples:
                if len(sample.iq_data) < 256:
                    continue
                spec = iq_to_spectrogram(sample.iq_data)
                spectrograms.append(spec)
                labels.append(idx)

        if len(spectrograms) < 10:
            return {"status": "insufficient_valid_data"}

        logger.info("Training with %d samples across %d classes",
                     len(spectrograms), len(set(labels)))

        # Convert to tensors
        X = torch.stack([
            torch.from_numpy(s).unsqueeze(0) for s in spectrograms
        ])
        y = torch.tensor(labels, dtype=torch.long)

        # Simple training loop
        model = classifier._model
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        criterion = torch.nn.CrossEntropyLoss()

        losses = []
        for epoch in range(20):
            optimizer.zero_grad()
            output = model(X)
            loss = criterion(output, y)
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

        model.eval()
        classifier._trained = True

        # Calculate accuracy
        with torch.no_grad():
            preds = model(X).argmax(dim=1)
            accuracy = (preds == y).float().mean().item()

        result = {
            "status": "trained",
            "samples": len(spectrograms),
            "classes": len(set(labels)),
            "final_loss": losses[-1],
            "accuracy": accuracy,
        }
        logger.info("Training complete: %s", result)
        return result
