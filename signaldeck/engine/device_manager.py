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
        if isinstance(status, tuple):
            ret_code = status[0]
        else:
            ret_code = status
        if ret_code < 0:
            logger.warning("Read error: %d", ret_code)
            return None
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
            info = DeviceInfo(
                label=r.get("label", r.get("driver", "unknown")),
                driver=r.get("driver", "unknown"),
                serial=r.get("serial", ""),
                hardware_key=r.get("hardware", ""),
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
        hw_info = soapy_dev.getHardwareInfo()

        info = DeviceInfo(
            label=hw_key,
            driver=driver or "unknown",
            serial=hw_info.get("serial", serial),
            hardware_key=hw_key,
        )
        logger.info("Opened device: %s (serial=%s)", info.label, info.serial)
        return SDRDevice(soapy_dev, info)
