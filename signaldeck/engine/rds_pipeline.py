import logging
from math import gcd

import numpy as np
from numpy.typing import NDArray
from scipy.signal import firwin, resample_poly

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RDS_WORKING_RATE = 228_000        # Hz — 4 × 57 kHz
RDS_BIT_RATE = 1187.5             # bps
RDS_SAMPLES_PER_BIT = 8           # at 9500 Hz
RDS_OUTPUT_RATE = 9_500           # Hz
FM_BROADCAST_LOW = 87_500_000     # Hz
FM_BROADCAST_HIGH = 108_000_000   # Hz


# ---------------------------------------------------------------------------
# Filter design + FM baseband demodulation
# ---------------------------------------------------------------------------

def design_rds_filters(fs: int = 228000) -> dict[str, NDArray[np.float64]]:
    """Pre-compute FIR filters for RDS subcarrier extraction.

    Returns a dict with keys ``pilot_bpf``, ``rds_bpf``, ``ref_bpf``,
    ``rds_lpf``, each containing a 1-D FIR coefficient array.
    """
    nyq = fs / 2.0
    pilot_bpf = firwin(
        193, [18800 / nyq, 19200 / nyq], pass_zero=False, window="blackman",
    )
    rds_bpf = firwin(
        193, [54600 / nyq, 59400 / nyq], pass_zero=False, window="blackman",
    )
    ref_bpf = firwin(
        129, [56500 / nyq, 57500 / nyq], pass_zero=False, window="hann",
    )
    rds_lpf = firwin(65, 2400 / nyq, window="hann")
    return {
        "pilot_bpf": pilot_bpf,
        "rds_bpf": rds_bpf,
        "ref_bpf": ref_bpf,
        "rds_lpf": rds_lpf,
    }


def fm_demodulate_baseband(
    iq: NDArray[np.complex64],
    input_rate: float,
    output_rate: float = 228000,
) -> NDArray[np.float32]:
    """FM polar-discriminator demodulation with resampling to *output_rate*.

    Returns a real-valued float32 array at the requested output rate.
    """
    product = iq[1:] * np.conj(iq[:-1])
    phase_diff = np.angle(product)
    baseband = (phase_diff / np.pi).astype(np.float32)

    if int(input_rate) != int(output_rate):
        from_int = int(input_rate)
        to_int = int(output_rate)
        divisor = gcd(from_int, to_int)
        up = to_int // divisor
        down = from_int // divisor
        baseband = resample_poly(baseband, up, down).astype(np.float32)

    return baseband


# ---------------------------------------------------------------------------
# RDS subcarrier extraction
# ---------------------------------------------------------------------------

def extract_rds_subcarrier(
    baseband: NDArray[np.float32],
    filters: dict[str, NDArray[np.float64]],
) -> NDArray[np.float32]:
    """Extract and demodulate the RDS subcarrier from FM baseband.

    *baseband* is expected at :data:`RDS_WORKING_RATE` (228 kHz).
    Returns a float32 array decimated to :data:`RDS_OUTPUT_RATE` (9500 Hz).
    """
    from scipy.signal import lfilter

    fs = RDS_WORKING_RATE
    n = len(baseband)

    # 1. Bandpass the 19 kHz pilot
    pilot = lfilter(filters["pilot_bpf"], 1.0, baseband)

    # 2. Derive 57 kHz carrier reference
    pilot_power = np.mean(pilot ** 2)
    if pilot_power > 1e-8:
        # Cube the pilot (19 kHz -> 57 kHz) and clean up
        carrier_ref = pilot ** 3
        carrier_ref = lfilter(filters["ref_bpf"], 1.0, carrier_ref)
    else:
        # Free-running 57 kHz cosine
        t = np.arange(n, dtype=np.float32) / fs
        carrier_ref = np.cos(2.0 * np.pi * 57000.0 * t)

    # Normalise carrier reference
    peak = np.max(np.abs(carrier_ref))
    if peak > 0:
        carrier_ref = carrier_ref / peak

    # 3. Bandpass the RDS band (54.6 - 59.4 kHz)
    rds_band = lfilter(filters["rds_bpf"], 1.0, baseband)

    # 4. Coherent demodulation
    mixed = rds_band * carrier_ref

    # 5. Lowpass
    demod = lfilter(filters["rds_lpf"], 1.0, mixed).astype(np.float32)

    # 6. Decimate by 24 (228000 / 9500 = 24)
    decimation = fs // RDS_OUTPUT_RATE
    output = demod[::decimation]

    return output.astype(np.float32)


# ---------------------------------------------------------------------------
# BMC bit recovery + differential decode
# ---------------------------------------------------------------------------

def recover_bits(
    signal: NDArray[np.float32],
    samples_per_bit: int = 8,
) -> list[int]:
    """Zero-crossing based clock recovery for biphase-coded RDS signal.

    In biphase/Manchester coding every bit boundary has a transition.
    A '1' bit additionally has a mid-bit transition (~half-bit spacing),
    while a '0' bit has no mid-bit transition (~full-bit spacing to next
    boundary).

    Returns a list of raw BMC bits (0 or 1).
    """
    if len(signal) < 2:
        return []

    hard = np.sign(signal)
    # Replace zeros to avoid ambiguity
    for i in range(len(hard)):
        if hard[i] == 0:
            hard[i] = 1.0

    # Find zero-crossing indices
    crossings: list[int] = []
    for i in range(1, len(hard)):
        if hard[i] != hard[i - 1]:
            crossings.append(i)

    if len(crossings) < 2:
        return []

    threshold = 0.75 * samples_per_bit
    bits: list[int] = []

    # The first crossing is assumed to be a bit boundary.
    # Walk through crossings classifying spacings.
    i = 0
    while i < len(crossings):
        if i + 1 < len(crossings):
            spacing = crossings[i + 1] - crossings[i]
            if spacing < threshold:
                # Short spacing -> mid-bit transition present -> bit is '1'.
                bits.append(1)
                i += 2
            else:
                # Long spacing -> next bit boundary, no mid-bit -> '0'.
                bits.append(0)
                i += 1
        else:
            # Last crossing with remaining signal -- assume '0' (no
            # mid-bit transition visible).
            remaining = len(signal) - crossings[i]
            if remaining >= samples_per_bit // 2:
                bits.append(0)
            i += 1

    return bits


def bmc_decode(raw_bits: list[int]) -> list[int]:
    """Differential decode: ``data[n] = raw[n] XOR raw[n-1]``."""
    if len(raw_bits) < 2:
        return []
    return [raw_bits[i] ^ raw_bits[i - 1] for i in range(1, len(raw_bits))]
