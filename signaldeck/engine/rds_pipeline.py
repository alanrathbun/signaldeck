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

# BCH parity constants
RDS_BCH_POLY = 0b10110111001  # x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1
RDS_OFFSETS = {
    "A":  0b0011111100,   # 0x0FC
    "B":  0b0110011000,   # 0x198
    "C":  0b0101101000,   # 0x168
    "C'": 0b1101010000,   # 0x350
    "D":  0b0110110100,   # 0x1B4
}


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


# ---------------------------------------------------------------------------
# Frame sync + BCH parity
# ---------------------------------------------------------------------------

def compute_syndrome(block_bits: list[int]) -> int:
    """Compute BCH syndrome for a 26-bit RDS block.

    Performs polynomial division of the 26-bit block by :data:`RDS_BCH_POLY`
    (degree 10).  The remainder is the 10-bit syndrome.

    Returns a 10-bit integer.
    """
    # Pack bits into a single integer
    block = 0
    for b in block_bits:
        block = (block << 1) | (b & 1)

    # Polynomial division -- poly is degree 10 (11 bits)
    poly = RDS_BCH_POLY
    for i in range(25, 9, -1):
        if (block >> i) & 1:
            block ^= poly << (i - 10)

    return block & 0x3FF


def _bits_to_uint16(bits: list[int]) -> int:
    """Convert the first 16 bits of *bits* to an unsigned 16-bit integer."""
    value = 0
    for b in bits[:16]:
        value = (value << 1) | (b & 1)
    return value


def find_rds_groups(
    data_bits: list[int],
) -> list[tuple[int, int, int, int]]:
    """Sliding-window frame sync to extract RDS groups.

    Each group consists of four 26-bit blocks (A, B, C/C', D).  The
    function checks BCH syndromes against the known offset words and
    returns a list of ``(block_a, block_b, block_c, block_d)`` tuples
    where each element is a 16-bit data word.
    """
    groups: list[tuple[int, int, int, int]] = []
    n = len(data_bits)
    if n < 104:
        return groups

    offset_a = RDS_OFFSETS["A"]
    offset_b = RDS_OFFSETS["B"]
    offset_c = RDS_OFFSETS["C"]
    offset_cp = RDS_OFFSETS["C'"]
    offset_d = RDS_OFFSETS["D"]

    i = 0
    while i <= n - 104:
        block_a_bits = data_bits[i : i + 26]
        syn_a = compute_syndrome(block_a_bits)
        if syn_a != offset_a:
            i += 1
            continue

        # Block A matched -- check B, C/C', D
        block_b_bits = data_bits[i + 26 : i + 52]
        syn_b = compute_syndrome(block_b_bits)
        if syn_b != offset_b:
            i += 1
            continue

        block_c_bits = data_bits[i + 52 : i + 78]
        syn_c = compute_syndrome(block_c_bits)
        c_ok = syn_c == offset_c or syn_c == offset_cp
        if not c_ok:
            i += 1
            continue

        block_d_bits = data_bits[i + 78 : i + 104]
        syn_d = compute_syndrome(block_d_bits)
        if syn_d != offset_d:
            i += 1
            continue

        # All four blocks valid
        a = _bits_to_uint16(block_a_bits)
        b = _bits_to_uint16(block_b_bits)
        c = _bits_to_uint16(block_c_bits)
        d = _bits_to_uint16(block_d_bits)
        groups.append((a, b, c, d))
        logger.debug(
            "RDS group: A=0x%04X B=0x%04X C=0x%04X D=0x%04X", a, b, c, d,
        )
        i += 104  # advance past this group

    return groups


# ---------------------------------------------------------------------------
# Stateful pipeline
# ---------------------------------------------------------------------------

class RdsPipeline:
    """Stateful pipeline that accumulates IQ chunks and emits decoded RDS groups.
    Caches filter coefficients. Carries over the undecoded bit buffer across
    calls so frame sync persists between short dwells on the same frequency.
    """

    def __init__(self, input_sample_rate: float = 2_000_000) -> None:
        self._input_rate = input_sample_rate
        self._filters = design_rds_filters()
        self._bit_buffer: list[int] = []

    def process(self, iq: NDArray[np.complex64]) -> list[tuple[int, int, int, int]]:
        """Feed IQ samples, return any complete RDS groups decoded.
        Call repeatedly with successive chunks; bit state carries over.
        """
        # If too few samples, skip
        if len(iq) < 1000:
            return []

        # FM demodulate to 228 kHz baseband
        baseband = fm_demodulate_baseband(iq, self._input_rate, RDS_WORKING_RATE)

        # Extract RDS subcarrier and decimate to 9500 Hz
        rds_signal = extract_rds_subcarrier(baseband, self._filters)

        # Recover raw BMC bits
        raw_bits = recover_bits(rds_signal, RDS_SAMPLES_PER_BIT)
        if not raw_bits:
            return []

        # Differential decode
        data_bits = bmc_decode(raw_bits)

        # Append to carry-over buffer
        self._bit_buffer.extend(data_bits)

        # Cap buffer size to prevent unbounded growth (keep last 2000 bits)
        if len(self._bit_buffer) > 2000:
            self._bit_buffer = self._bit_buffer[-2000:]

        # Find complete groups
        groups = find_rds_groups(self._bit_buffer)

        # Trim consumed bits
        if groups:
            consumed = len(self._bit_buffer) - 104
            if consumed > 0:
                self._bit_buffer = self._bit_buffer[consumed:]

        return groups

    def reset(self) -> None:
        """Reset sync state. Call when changing frequency."""
        self._bit_buffer = []
