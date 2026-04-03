from signaldeck.decoders.registry import DecoderRegistry
from signaldeck.decoders.fm_am import FmAmDecoder
from signaldeck.decoders.rds import RdsDecoder
from signaldeck.decoders.weather_radio import WeatherRadioDecoder
from signaldeck.decoders.ism import IsmDecoder
from signaldeck.decoders.pocsag import PocsagDecoder
from signaldeck.decoders.aprs import AprsDecoder
from signaldeck.decoders.adsb import AdsbDecoder

def create_default_registry(recording_dir: str = "data/recordings") -> DecoderRegistry:
    registry = DecoderRegistry()
    registry.register(FmAmDecoder(recording_dir=recording_dir))
    registry.register(RdsDecoder())
    registry.register(WeatherRadioDecoder(recording_dir=recording_dir))
    registry.register(IsmDecoder())
    registry.register(PocsagDecoder())
    registry.register(AprsDecoder())
    registry.register(AdsbDecoder())
    return registry
