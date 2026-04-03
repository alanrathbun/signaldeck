import numpy as np
import pytest

from signaldeck.ai.training import TrainingPipeline, TrainingSample


def test_training_sample_creation():
    sample = TrainingSample(
        iq_data=np.zeros(1024, dtype=np.complex64),
        label="FM",
        frequency_hz=98.5e6,
        confidence=0.95,
        source="decoder_confirmed",
    )
    assert sample.label == "FM"
    assert sample.confidence == 0.95


def test_pipeline_add_sample():
    pipeline = TrainingPipeline()
    sample = TrainingSample(
        iq_data=np.zeros(1024, dtype=np.complex64),
        label="FM", frequency_hz=98.5e6, confidence=0.95, source="decoder",
    )
    pipeline.add_sample(sample)
    assert pipeline.sample_count == 1


def test_pipeline_add_multiple_labels():
    pipeline = TrainingPipeline()
    for label in ["FM", "AM", "FM", "4FSK", "FM"]:
        pipeline.add_sample(TrainingSample(
            iq_data=np.zeros(1024, dtype=np.complex64),
            label=label, frequency_hz=100e6, confidence=0.9, source="decoder",
        ))
    stats = pipeline.get_stats()
    assert stats["FM"] == 3
    assert stats["AM"] == 1
    assert stats["4FSK"] == 1


def test_pipeline_min_samples_for_training():
    """Pipeline reports whether enough samples exist for training."""
    pipeline = TrainingPipeline(min_samples_per_class=5)
    for _ in range(4):
        pipeline.add_sample(TrainingSample(
            iq_data=np.zeros(1024, dtype=np.complex64),
            label="FM", frequency_hz=100e6, confidence=0.9, source="decoder",
        ))
    assert not pipeline.ready_to_train()
    pipeline.add_sample(TrainingSample(
        iq_data=np.zeros(1024, dtype=np.complex64),
        label="FM", frequency_hz=100e6, confidence=0.9, source="decoder",
    ))
    # Still not ready — need at least 2 classes
    assert not pipeline.ready_to_train()
