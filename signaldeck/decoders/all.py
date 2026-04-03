from signaldeck.decoders.registry import DecoderRegistry
from signaldeck.decoders.fm_am import FmAmDecoder
from signaldeck.decoders.rds import RdsDecoder
from signaldeck.decoders.weather_radio import WeatherRadioDecoder
from signaldeck.decoders.ism import IsmDecoder
from signaldeck.decoders.pocsag import PocsagDecoder
from signaldeck.decoders.aprs import AprsDecoder
from signaldeck.decoders.adsb import AdsbDecoder
from signaldeck.decoders.acars import AcarsDecoder
from signaldeck.decoders.dsd import DsdDecoder
from signaldeck.decoders.p25 import P25Decoder
from signaldeck.decoders.noaa_apt import NoaaAptDecoder

def create_default_registry(recording_dir: str = "data/recordings") -> DecoderRegistry:
    registry = DecoderRegistry()
    registry.register(FmAmDecoder(recording_dir=recording_dir))
    registry.register(RdsDecoder())
    registry.register(WeatherRadioDecoder(recording_dir=recording_dir))
    registry.register(IsmDecoder())
    registry.register(PocsagDecoder())
    registry.register(AprsDecoder())
    registry.register(AdsbDecoder())
    registry.register(AcarsDecoder())
    registry.register(DsdDecoder(recording_dir=recording_dir))
    registry.register(P25Decoder())
    registry.register(NoaaAptDecoder())
    return registry
