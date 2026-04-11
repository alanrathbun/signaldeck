import logging
from signaldeck.engine.device_manager import DeviceInfo

logger = logging.getLogger(__name__)


class GqrxDevice:
    """SDR device adapter that controls gqrx via its rigctl TCP client."""

    def __init__(self, client, info: DeviceInfo) -> None:
        self._client = client
        self.info = info

    @property
    def is_gqrx(self) -> bool:
        return True

    async def tune(self, frequency_hz: float) -> None:
        await self._client.set_frequency(int(frequency_hz))
        logger.debug("gqrx tuned to %.6f MHz", frequency_hz / 1e6)

    def set_gain(self, gain_db: float) -> None:
        pass  # gqrx manages gain internally

    def set_sample_rate(self, rate: float) -> None:
        pass  # gqrx manages sample rate internally

    def start_stream(self) -> None:
        pass  # no IQ stream access

    def stop_stream(self) -> None:
        pass  # no IQ stream access

    def read_samples(self, num_samples: int):
        return None  # no IQ access via rigctl

    async def get_signal_strength(self) -> float:
        return await self._client.get_signal_strength()

    async def set_mode(self, mode: str) -> None:
        await self._client.set_mode(mode)

    async def set_squelch(self, level: float) -> None:
        await self._client.set_squelch(level)

    async def start_recording(self) -> None:
        await self._client.start_recording()

    async def stop_recording(self) -> None:
        await self._client.stop_recording()

    async def enable_rds(self) -> None:
        """Enable RDS decoder in gqrx (WFM mode only)."""
        try:
            await self._client.set_rds(True)
        except Exception as e:
            logger.debug("Could not enable RDS: %s", e)

    async def disable_rds(self) -> None:
        await self._client.set_rds(False)

    async def get_rds(self) -> dict | None:
        """Poll gqrx for current RDS data. Returns dict or None."""
        try:
            pi = await self._client.get_rds_pi()
            if not pi or pi == "0000":
                return None
            ps = await self._client.get_rds_ps_name()
            rt = await self._client.get_rds_radiotext()
            return {
                "pi_code": pi,
                "ps_name": ps.strip() if ps else "",
                "radio_text": rt.strip() if rt else "",
            }
        except Exception:
            return None

    async def close(self) -> None:
        await self._client.disconnect()
        logger.debug("gqrx device %s closed", self.info.label)
