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
