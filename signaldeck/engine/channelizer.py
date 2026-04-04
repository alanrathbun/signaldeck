"""Snap detected frequencies to standard FCC/ITU channel spacing."""

# Table entries: (priority, label, start_hz, end_hz, step_hz, grid_offset_hz)
# grid_offset_hz: the channel grid is anchored at (start_hz - grid_offset_hz)
# so channels fall at: anchor + n*step where anchor = start_hz - grid_offset_hz
# Default offset of 0 means channels are multiples of step from 0.
_CHANNEL_TABLE: list[tuple[int, str, float, float, float, float]] = [
    (1, "NOAA Weather",    162_400_000, 162_550_000,  25_000,   0),
    (2, "Marine VHF",      156_000_000, 162_000_000,  25_000,   0),
    (3, "ISM 433",         433_050_000, 434_790_000,  25_000,   0),
    (4, "GMRS/FRS",        462_000_000, 467_000_000,  12_500,   0),
    (5, "VHF Low",          30_000_000,  88_000_000,  20_000,   0),
    # US FM: channels at 87.9, 88.1, 88.3 ... MHz (200 kHz step, anchored at 87.9 MHz)
    (6, "FM Broadcast",     88_000_000, 108_000_000, 200_000, 100_000),
    (7, "Airband",         118_000_000, 137_000_000,  25_000,   0),
    (8, "2m Ham",          144_000_000, 148_000_000,   5_000,   0),
    (9, "VHF High",        150_000_000, 174_000_000,  12_500,   0),
    (10, "70cm Ham",       420_000_000, 450_000_000,   5_000,   0),
    (11, "UHF Land Mobile",450_000_000, 470_000_000,  12_500,   0),
]


def channelize(frequency_hz: float) -> float:
    """Snap a frequency to the nearest standard channel for its band.

    Returns a float. Frequencies outside all known bands are returned unchanged
    (also as float).
    """
    freq = float(frequency_hz)
    for _prio, _label, start, end, step, offset in _CHANNEL_TABLE:
        if start <= freq <= end:
            # Shift frequency into offset-corrected grid, round, shift back
            snapped = round(round((freq - offset) / step) * step + offset, 1)
            return float(snapped)
    return freq
