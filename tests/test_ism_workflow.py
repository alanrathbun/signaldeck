import numpy as np

from signaldeck.engine.ism_workflow import summarize_burst_triage, triage_ism_burst


def test_triage_sparse_pulse_train():
    sample_rate = 250_000
    samples = np.zeros(4096, dtype=np.complex64)
    samples[100:120] = 1.0 + 0j
    samples[400:420] = 1.0 + 0j
    samples[900:930] = 1.0 + 0j

    triage = triage_ism_burst(samples, sample_rate)

    assert triage["burst_count"] >= 3
    assert triage["occupied_ratio"] < 0.1
    assert triage["signature"] in ("sparse_pulse_train", "narrowband_data_burst")


def test_summarize_burst_triage():
    summary = summarize_burst_triage(
        433_920_000,
        {
            "signature": "sparse_pulse_train",
            "suspected_modulation": "OOK/ASK",
            "occupied_ratio": 0.03,
            "burst_count": 4,
            "occupied_bandwidth_hz": 24000,
        },
    )
    assert "433.920 MHz ISM burst" in summary
    assert "OOK/ASK" in summary
