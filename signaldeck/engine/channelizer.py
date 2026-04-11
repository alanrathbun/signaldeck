"""Snap detected frequencies to standard FCC/ITU channel spacing."""

# Table entries: (priority, label, start_hz, end_hz, step_hz, anchor_hz)
# anchor_hz defines the base point for the channel grid so channels fall at:
# anchor_hz + n*step_hz
# An anchor of 0 means channels are multiples of step from 0.
_CHANNEL_TABLE: list[tuple[int, str, float, float, float, float]] = [
    (1, "NOAA Weather",    162_400_000, 162_550_000,  25_000,   0),
    (2, "Marine VHF",      156_000_000, 162_000_000,  25_000,   0),
    (3, "ISM 433",         433_050_000, 434_790_000,  25_000,   0),
    (4, "GMRS/FRS",        462_000_000, 467_000_000,  12_500,   0),
    # US FM: channels at 87.9, 88.1, 88.3 ... MHz
    (5, "FM Broadcast",     87_500_000, 108_000_000, 200_000, 87_900_000),
    (6, "VHF Low",          30_000_000,  87_500_000,  20_000,   0),
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
    for _prio, label, start, end, step, anchor in _CHANNEL_TABLE:
        if start <= freq <= end:
            snapped = round(round((freq - anchor) / step) * step + anchor, 1)
            if label == "FM Broadcast":
                snapped = min(max(snapped, 87_900_000.0), 107_900_000.0)
            return float(snapped)
    return freq
