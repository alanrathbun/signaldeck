import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LLM_URL = "http://localhost:8080/v1/chat/completions"

_SYSTEM_PROMPT = """You are a radio monitoring assistant. Summarize the SDR scanner activity data provided.
Be concise but informative. Highlight interesting findings, unusual signals, and activity patterns.
Format: 2-4 short paragraphs. Use plain language a radio hobbyist would understand."""


def format_activity_for_llm(entries: list[dict], hours: float) -> str:
    """Format activity data into a human-readable text for LLM input."""
    lines = [f"Activity summary for the last {hours:.0f} hours:", ""]

    # Group by protocol
    by_protocol: dict[str, list] = {}
    for e in entries:
        proto = e.get("protocol", "unknown")
        by_protocol.setdefault(proto, []).append(e)

    for proto, items in sorted(by_protocol.items()):
        total_count = sum(e.get("count", 1) for e in items)
        freqs = set(e.get("frequency_mhz", 0) for e in items)
        lines.append(f"- {proto.upper()}: {total_count} events across {len(freqs)} frequency(s)")
        for item in items[:5]:  # Show up to 5 per protocol
            lines.append(f"  - {item.get('frequency_mhz', '?')} MHz: "
                         f"{item.get('summary', 'no details')} "
                         f"(×{item.get('count', 1)})")
        if len(items) > 5:
            lines.append(f"  - ... and {len(items) - 5} more")

    return "\n".join(lines)


class ActivitySummarizer:
    """LLM-powered activity summarizer.

    Calls a local llama-server (OpenAI-compatible API) to generate
    human-readable summaries of scanner activity. Falls back to
    a formatted text summary if no LLM is available.
    """

    def __init__(self, llm_url: str | None = _DEFAULT_LLM_URL, model: str = "") -> None:
        self.llm_url = llm_url
        self._model = model

    def build_prompt(self, entries: list[dict], hours: float) -> str:
        """Build the prompt to send to the LLM."""
        data_text = format_activity_for_llm(entries, hours)
        return f"Summarize this SDR scanner activity:\n\n{data_text}"

    def summarize_sync(self, entries: list[dict], hours: float = 6) -> str:
        """Generate a summary. Uses LLM if available, otherwise formatted text."""
        if not entries:
            return "No activity recorded in this period."

        if not self.llm_url:
            return self._fallback_summary(entries, hours)

        # Try LLM
        try:
            return self._call_llm(entries, hours)
        except Exception as e:
            logger.warning("LLM unavailable (%s), using fallback summary", e)
            return self._fallback_summary(entries, hours)

    async def summarize(self, entries: list[dict], hours: float = 6) -> str:
        """Async version of summarize."""
        if not entries:
            return "No activity recorded in this period."

        if not self.llm_url:
            return self._fallback_summary(entries, hours)

        try:
            return await self._call_llm_async(entries, hours)
        except Exception as e:
            logger.warning("LLM unavailable (%s), using fallback summary", e)
            return self._fallback_summary(entries, hours)

    def _call_llm(self, entries: list[dict], hours: float) -> str:
        """Call the LLM synchronously."""
        import urllib.request

        prompt = self.build_prompt(entries, hours)
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 500,
            "temperature": 0.7,
        }).encode()

        req = urllib.request.Request(
            self.llm_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]

    async def _call_llm_async(self, entries: list[dict], hours: float) -> str:
        """Call the LLM asynchronously."""
        import asyncio
        return await asyncio.to_thread(self._call_llm, entries, hours)

    def _fallback_summary(self, entries: list[dict], hours: float) -> str:
        """Generate a basic text summary without LLM."""
        text = format_activity_for_llm(entries, hours)

        # Add basic stats
        total = sum(e.get("count", 1) for e in entries)
        protocols = set(e.get("protocol", "unknown") for e in entries)
        freqs = set(e.get("frequency_mhz", 0) for e in entries)

        header = (f"Summary: {total} events across {len(protocols)} protocol(s) "
                  f"on {len(freqs)} frequency(s) in the last {hours:.0f} hours.\n\n")

        return header + text
