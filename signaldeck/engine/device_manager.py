from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

try:
    import SoapySDR
except ImportError:
    SoapySDR = None

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    label: str
    driver: str
    serial: str
    hardware_key: str = ""


class SDRDevice:
    """Wrapper around a SoapySDR device for receive operations."""

    def __init__(self, soapy_dev, info: DeviceInfo) -> None:
        self._dev = soapy_dev
        self.info = info
        self._stream = None
        self._sample_rate: float = 2_000_000

    def tune(self, frequency_hz: float) -> None:
        self._dev.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, frequency_hz)
        logger.debug("Tuned to %.6f MHz", frequency_hz / 1e6)

    def set_sample_rate(self, rate: float) -> None:
        self._dev.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, rate)
        self._sample_rate = rate
        logger.debug("Sample rate set to %.1f MS/s", rate / 1e6)

    def set_gain(self, gain_db: float) -> None:
        self._dev.setGain(SoapySDR.SOAPY_SDR_RX, 0, gain_db)
        logger.debug("Gain set to %.1f dB", gain_db)

    def start_stream(self) -> None:
        if self._stream is None:
            self._stream = self._dev.setupStream(SoapySDR.SOAPY_SDR_RX, "CF32")
        self._dev.activateStream(self._stream)
        logger.debug("Stream activated")

    def stop_stream(self) -> None:
        if self._stream is not None:
            self._dev.deactivateStream(self._stream)
            logger.debug("Stream deactivated")

    def read_samples(self, num_samples: int) -> np.ndarray | None:
        buf = np.zeros(num_samples, dtype=np.complex64)
        status = self._dev.readStream(self._stream, [buf], num_samples)
        if hasattr(status, "ret"):
            ret_code = status.ret
        elif isinstance(status, tuple):
            ret_code = status[0]
        else:
            ret_code = status
        if ret_code < 0:
            self._consecutive_errors = getattr(self, "_consecutive_errors", 0) + 1
            # Log first error and then every 50th to avoid spam
            if self._consecutive_errors == 1 or self._consecutive_errors % 50 == 0:
                logger.warning("Read error: %d (occurred %d times)", ret_code, self._consecutive_errors)
            return None
        self._consecutive_errors = 0
        return buf[:ret_code] if ret_code < num_samples else buf

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._dev.deactivateStream(self._stream)
            except Exception:
                pass
            self._dev.closeStream(self._stream)
            self._stream = None
        logger.debug("Device %s closed", self.info.driver)


class DeviceManager:
    """Discovers and manages SDR devices via SoapySDR."""

    def enumerate(self) -> list[DeviceInfo]:
        if SoapySDR is None:
            logger.error("SoapySDR not installed")
            return []
        results = SoapySDR.Device.enumerate()
        devices = []
        for r in results:
            # SoapySDRKwargs may not support .get(); convert to dict first
            rd = dict(r)
            info = DeviceInfo(
                label=rd.get("label", rd.get("driver", "unknown")),
                driver=rd.get("driver", "unknown"),
                serial=rd.get("serial", ""),
                hardware_key=rd.get("hardware", ""),
            )
            devices.append(info)
            logger.info("Found device: %s (driver=%s)", info.label, info.driver)
        return devices

    def open(self, driver: str = "", serial: str = "") -> SDRDevice:
        args = {}
        if driver:
            args["driver"] = driver
        if serial:
            args["serial"] = serial

        soapy_dev = SoapySDR.Device(args)
        hw_key = soapy_dev.getHardwareKey()
        hw_info = dict(soapy_dev.getHardwareInfo())

        info = DeviceInfo(
            label=hw_key,
            driver=driver or "unknown",
            serial=hw_info.get("serial", serial),
            hardware_key=hw_key,
        )
        logger.info("Opened device: %s (serial=%s)", info.label, info.serial)
        return SDRDevice(soapy_dev, info)

    async def enumerate_async(
        self,
        gqrx_auto_detect: bool = True,
        gqrx_host: str = "localhost",
        gqrx_port: int = 7356,
        gqrx_instances: list[dict] | None = None,
    ) -> list[DeviceInfo]:
        """Discover SDR devices including gqrx instances."""
        devices = self.enumerate()  # existing SoapySDR discovery

        # Try auto-detecting gqrx on the default or configured host:port
        if gqrx_auto_detect:
            info = await self._probe_gqrx(gqrx_host, gqrx_port)
            if info:
                devices.append(info)

        # Check explicitly configured gqrx instances
        for inst in (gqrx_instances or []):
            host = inst.get("host", "localhost")
            port = inst.get("port", 7356)
            if host == gqrx_host and port == gqrx_port:
                continue  # already checked above
            info = await self._probe_gqrx(host, port)
            if info:
                devices.append(info)

        return devices

    async def _probe_gqrx(self, host: str, port: int) -> DeviceInfo | None:
        """Try connecting to a gqrx instance and return DeviceInfo if it responds."""
        import asyncio
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=1.0,
            )
            writer.write(b"f\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.readline(), timeout=1.0)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            # If we got a valid frequency back, gqrx is running
            int(resp.decode().strip())
            info = DeviceInfo(
                label=f"gqrx @ {host}:{port}",
                driver="gqrx",
                serial=f"{host}:{port}",
            )
            logger.info("Found gqrx at %s:%d", host, port)
            return info
        except Exception:
            return None

    async def open_gqrx(self, host: str = "localhost", port: int = 7356) -> GqrxDevice:
        """Open a connection to a gqrx instance."""
        from signaldeck.engine.gqrx_client import GqrxClient
        from signaldeck.engine.gqrx_device import GqrxDevice

        client = GqrxClient(host=host, port=port)
        await client.connect()
        info = DeviceInfo(
            label=f"gqrx @ {host}:{port}",
            driver="gqrx",
            serial=f"{host}:{port}",
        )
        logger.info("Opened gqrx device at %s:%d", host, port)
        return GqrxDevice(client, info)
