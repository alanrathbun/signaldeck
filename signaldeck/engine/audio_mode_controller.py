"""AudioModeController — debounced mode flips for gqrx AF gain.

The scanner loop calls `apply_effective_mode(mode, user_volume_db)` on
every tick. The controller tracks the last-applied mode and only issues
a rigctl command when the mode actually changes, so idle ticks don't
spam gqrx. Exceptions from the rigctl call are logged and swallowed —
the scanner loop must keep running even if gqrx is temporarily
unreachable.
"""
import logging

logger = logging.getLogger(__name__)


class AudioModeController:
    def __init__(self, gqrx) -> None:
        """
        Args:
            gqrx: An object with an async `set_audio_gain(db_value: float)` method.
                  This is typically a GqrxClient instance.
        """
        self._gqrx = gqrx
        self._last_applied_mode: str | None = None

    async def apply_effective_mode(
        self,
        effective_mode: str,
        user_volume_db: float,
    ) -> None:
        """Apply the effective audio mode to gqrx.

        - "gqrx"       → set AF gain to user_volume_db
        - "pcm_stream" → set AF gain to 0 (muted, still tuned)

        No-op if the mode hasn't changed since the last call. rigctl
        failures are logged and swallowed.
        """
        if effective_mode == self._last_applied_mode:
            return
        try:
            if effective_mode == "pcm_stream":
                await self._gqrx.set_audio_gain(0.0)
            elif effective_mode == "gqrx":
                await self._gqrx.set_audio_gain(user_volume_db)
            else:
                logger.warning("Unknown effective audio mode: %r", effective_mode)
                return
            self._last_applied_mode = effective_mode
            logger.info(
                "Audio mode flip: applied effective_mode=%s (af_gain=%s)",
                effective_mode,
                0.0 if effective_mode == "pcm_stream" else user_volume_db,
            )
        except Exception as e:
            logger.warning(
                "Failed to apply audio mode %s via gqrx rigctl: %s",
                effective_mode,
                e,
            )
