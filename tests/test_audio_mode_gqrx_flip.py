"""Integration test for audio mode flip: verify gqrx AF gain is muted to a
very negative dB value when effective mode is pcm_stream, and restored to
stored volume when effective mode is gqrx."""
import pytest

from signaldeck.api.websocket import audio_stream
from signaldeck.engine.audio_mode_controller import AudioModeController


@pytest.fixture(autouse=True)
def clear_clients():
    audio_stream._audio_clients.clear()
    yield
    audio_stream._audio_clients.clear()


class FakeGqrx:
    def __init__(self):
        self.af_gain_history: list[float] = []
        self._af_gain = 5.0

    async def set_audio_gain(self, db_value: float) -> None:
        self.af_gain_history.append(db_value)
        self._af_gain = db_value

    async def get_audio_gain(self) -> float:
        return self._af_gain


async def test_flip_to_pcm_stream_mutes_gqrx():
    from signaldeck.engine.audio_mode_controller import MUTE_AF_GAIN_DB
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("pcm_stream", user_volume_db=5.0)
    # gqrx rigctl's AF gain is attenuation in dB — 0.0 is FULL VOLUME, not mute.
    # The controller must pass a very negative value to actually silence gqrx.
    assert gqrx.af_gain_history[-1] == MUTE_AF_GAIN_DB
    assert gqrx.af_gain_history[-1] < -60.0  # sanity check: well below "quiet"


async def test_flip_to_gqrx_restores_stored_volume():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("pcm_stream", user_volume_db=7.5)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=7.5)
    assert gqrx.af_gain_history[-1] == 7.5


async def test_no_op_when_mode_unchanged():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=5.0)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=5.0)
    # Only one call — the second was a no-op
    assert len(gqrx.af_gain_history) == 1


async def test_initial_state_is_unknown_first_call_always_applies():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=5.0)
    assert len(gqrx.af_gain_history) == 1


async def test_flip_survives_gqrx_failure_without_raising():
    """If gqrx rigctl fails, we log and swallow — the controller must not
    propagate the exception up to the scanner loop."""
    class BrokenGqrx:
        async def set_audio_gain(self, db_value: float) -> None:
            raise RuntimeError("rigctl unreachable")

    ctrl = AudioModeController(gqrx=BrokenGqrx())
    # Should not raise
    await ctrl.apply_effective_mode("pcm_stream", user_volume_db=5.0)
