import pytest
from signaldeck.engine.channelizer import channelize


class TestChannelize:
    """Test frequency channelization against FCC/ITU band plans."""

    # --- NOAA Weather (162.400-162.550 MHz, 25 kHz step) ---
    def test_noaa_exact(self):
        assert channelize(162_400_000) == 162_400_000

    def test_noaa_snaps_up(self):
        assert channelize(162_413_000) == 162_425_000

    def test_noaa_snaps_down(self):
        assert channelize(162_436_000) == 162_425_000

    # --- Marine VHF (156.000-162.000 MHz, 25 kHz step) ---
    def test_marine_vhf(self):
        assert channelize(156_012_000) == 156_000_000

    def test_marine_ch16(self):
        assert channelize(156_800_000) == 156_800_000

    # --- FM Broadcast (88-108 MHz, 200 kHz step) ---
    def test_fm_broadcast_exact(self):
        assert channelize(101_100_000) == 101_100_000

    def test_fm_broadcast_snaps(self):
        assert channelize(99_050_000) == 99_100_000

    def test_fm_broadcast_snaps_down(self):
        assert channelize(99_140_000) == 99_100_000

    # --- Airband (118-137 MHz, 25 kHz step) ---
    def test_airband(self):
        assert channelize(121_512_000) == 121_500_000

    # --- 2m Ham (144-148 MHz, 5 kHz step) ---
    def test_2m_ham(self):
        assert channelize(146_521_000) == 146_520_000

    def test_2m_ham_exact(self):
        assert channelize(146_520_000) == 146_520_000

    # --- VHF High (150-174 MHz, 12.5 kHz step) ---
    def test_vhf_high(self):
        assert channelize(155_007_000) == 155_012_500

    # --- ISM 433 (433.050-434.790 MHz, 25 kHz step) ---
    def test_ism_433(self):
        assert channelize(433_912_000) == 433_900_000

    # --- GMRS/FRS (462.000-467.000 MHz, 12.5 kHz step) ---
    def test_gmrs(self):
        assert channelize(462_567_000) == 462_562_500

    # --- VHF Low (30-88 MHz, 20 kHz step) ---
    def test_vhf_low(self):
        assert channelize(42_015_000) == 42_020_000

    # --- 70cm Ham (420-450 MHz, 5 kHz step) ---
    def test_70cm_ham(self):
        assert channelize(446_002_000) == 446_000_000

    # --- UHF Land Mobile (450-470 MHz, 12.5 kHz step) ---
    def test_uhf_land_mobile(self):
        assert channelize(460_007_000) == 460_012_500

    # --- Priority: specific bands override broader bands ---
    def test_noaa_overrides_marine(self):
        assert channelize(162_425_000) == 162_425_000

    def test_gmrs_overrides_uhf(self):
        assert channelize(462_562_500) == 462_562_500

    # --- Passthrough: outside all bands ---
    def test_passthrough_below_all_bands(self):
        assert channelize(1_000_000) == 1_000_000

    def test_passthrough_above_all_bands(self):
        assert channelize(900_000_000) == 900_000_000

    # --- Types ---
    def test_returns_float(self):
        result = channelize(101_100_000.0)
        assert isinstance(result, float)

    def test_accepts_int(self):
        result = channelize(101_100_000)
        assert isinstance(result, float)
