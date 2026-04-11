# DSP patterns reference

> Distilled from an abandoned RDS pipeline plan (2026-04-03). The RDS-specific
> protocol layer (biphase-mark, BCH parity, frame sync) was dropped in favor
> of gqrx's built-in RDS decoder. What's left here is the generic SDR DSP
> toolkit — filter design, FM demodulation, resampling, and coherent carrier
> recovery — worth keeping around for any future decoder that needs them.

## When you'd reach for this

- **NOAA APT** continuation (`signaldeck/decoders/noaa_apt.py` already exists,
  may need DSP tightening)
- **HF weather fax** (WeFAX) — no current decoder
- **SSTV** (slow scan TV — audio tones carrying still images)
- **Any narrowband analog subcarrier** where you already have I/Q and want
  to pull a specific band out
- **Any "let me just implement this decoder from scratch in numpy instead
  of wrapping an external CLI" case**

If the decoder you're building has a mature Linux tool (`rtl_433`,
`multimon-ng`, `direwolf`, `acarsdec`, `dsd`, `fldigi`, `slowrx`, `satdump`),
**prefer wrapping that tool via subprocess** — that's how the existing
`ism.py`, `p25.py`, `pocsag.py`, `aprs.py`, `acars.py`, `dsd.py` decoders work.
Pure Python DSP is the right choice only when no mature tool exists, the
tool is too heavy to ship, or you need tight control over a stage that the
tool hides.

## Imports

```python
from math import gcd
import numpy as np
from numpy.typing import NDArray
from scipy.signal import firwin, lfilter, resample_poly
```

## 1. FIR filter design

`scipy.signal.firwin` builds finite-impulse-response filter coefficients
for lowpass, bandpass, or highpass. Use odd tap counts for linear-phase
filters. Pick a window: Blackman for sharp stopband, Hann for
shorter/faster, Hamming as a balanced default.

```python
def design_filters(fs: int) -> dict[str, NDArray]:
    """Build a handful of FIR filters at the working sample rate."""
    # Bandpass: pass 18.8–19.2 kHz, reject everything else (e.g., pilot tone)
    pilot_bpf = firwin(193, [18800, 19200], pass_zero=False,
                       window="blackman", fs=fs)

    # Bandpass: pass 54.6–59.4 kHz (e.g., RDS subcarrier)
    sub_bpf = firwin(193, [54600, 59400], pass_zero=False,
                     window="blackman", fs=fs)

    # Lowpass: pass 0–2.4 kHz (e.g., post-demod smoothing)
    lpf = firwin(65, 2400, window="hann", fs=fs)

    return {"pilot_bpf": pilot_bpf, "sub_bpf": sub_bpf, "lpf": lpf}
```

**Notes:**
- `pass_zero=False` turns a lowpass spec into a bandpass spec (the first
  frequency becomes the lower cutoff).
- Filter length (tap count) trades off transition width against CPU cost.
  193 taps gives a few-hundred-Hz transition at 228 kHz sample rate —
  plenty for subcarrier separation. Use smaller (65–129) for less critical
  paths.
- Always use `fs=...` so the cutoffs are in Hz, not normalized frequency.
  (Normalized form is older scipy style and error-prone.)
- Apply a filter with `lfilter(taps, 1.0, signal)`. For long signals where
  you care about zero-phase, use `filtfilt` instead (applies the filter
  forward and backward).

## 2. FM baseband demodulation (polar discriminator)

Converts I/Q samples to the FM modulation envelope. The full FM multiplex
spectrum — audio, pilot, stereo subcarrier, RDS — is preserved if you
don't downsample too aggressively.

```python
def fm_demodulate_baseband(
    iq: NDArray[np.complex64],
    input_rate: float,
    output_rate: float,
) -> NDArray[np.float32]:
    """FM-demodulate I/Q samples, keeping the full multiplex spectrum.

    Returns a real-valued signal at output_rate. For broadcast FM the useful
    output rate is ~228 kHz (4 × the 57 kHz RDS subcarrier) — enough to
    cleanly represent everything from audio to RDS.
    """
    # Polar discriminator: phase difference between adjacent samples.
    product = iq[1:] * np.conj(iq[:-1])
    phase_diff = np.angle(product)
    baseband = (phase_diff / np.pi).astype(np.float32)

    # Resample from input_rate to output_rate with clean integer ratios.
    inp = int(input_rate)
    out = int(output_rate)
    divisor = gcd(inp, out)
    up = out // divisor
    down = inp // divisor
    return resample_poly(baseband, up, down).astype(np.float32)
```

**Contrast with `signaldeck/engine/audio_pipeline.fm_demodulate`:** that
function takes the same IQ input but decimates aggressively and applies an
audio-bandwidth lowpass, throwing away everything above ~15 kHz. Use
`audio_pipeline` when you want playable mono audio. Use the function above
when you need access to anything above the audio band — pilot, stereo,
RDS, or anything a subcarrier could be hiding.

## 3. Resampling with clean integer ratios

`resample_poly(signal, up, down)` is the efficient polyphase resampler.
It wants integer up/down ratios — use `gcd` to reduce whatever your source
and target rates are to the smallest equivalent pair:

```python
def resample_to(signal: NDArray, input_rate: int, output_rate: int) -> NDArray:
    divisor = gcd(input_rate, output_rate)
    up = output_rate // divisor
    down = input_rate // divisor
    return resample_poly(signal, up, down)
```

**Why integer ratios matter:** non-integer or very large ratios force the
resampler to build long anti-aliasing filters, which is slow and can
introduce artifacts. Picking a working rate that's a clean multiple of
your target (e.g., 228 kHz = 4 × 57 kHz for RDS) lets decimation happen
in single clean steps.

## 4. Coherent subcarrier recovery via pilot cubing

When a broadcast signal includes a pilot tone at some frequency (e.g.,
19 kHz for FM broadcast stereo/RDS), you can recover a coherent reference
for the Nth harmonic by raising the pilot to the Nth power. This works
because nonlinear distortion of a sinusoid produces its harmonics at
`N × f₀`.

```python
def recover_57khz_carrier(
    baseband: NDArray[np.float32],
    filters: dict[str, NDArray],
    working_rate: int = 228_000,
) -> NDArray[np.float32]:
    """Recover a coherent 57 kHz reference from a 19 kHz pilot tone.

    Used for RDS but the technique is general — any N:M harmonic
    relationship works. For a 3× reference cube the pilot; for 5× raise
    to the 5th power; etc.
    """
    # Pull the pilot out of the multiplex.
    pilot = lfilter(filters["pilot_bpf"], 1.0, baseband)

    # If the pilot is absent (e.g., mono station), fall back to a
    # free-running oscillator.
    pilot_power = float(np.mean(pilot ** 2))
    if pilot_power < 1e-8:
        t = np.arange(len(baseband)) / working_rate
        return np.cos(2 * np.pi * 57_000 * t).astype(np.float32)

    # Normalize and cube to produce 57 kHz.
    pilot_norm = pilot / (np.sqrt(pilot_power) * np.sqrt(2) + 1e-12)
    pilot_cubed = pilot_norm ** 3

    # Clean up the tripled signal with a tight bandpass around 57 kHz.
    return lfilter(filters["ref_bpf"], 1.0, pilot_cubed)
```

**When this applies:**
- FM broadcast stereo (19 kHz pilot → 38 kHz stereo subcarrier, 2×)
- FM broadcast RDS (19 kHz pilot → 57 kHz, 3×)
- Any digital subcarrier standard that includes a reference pilot

**When it doesn't:**
- Signals without a phase-locked pilot (most simple AM/FM audio, most
  narrowband digital modes)
- When you can just use a free-running oscillator (gets within a few Hz
  before drift matters)

## 5. Coherent demodulation

Once you have a carrier reference, coherent demod is a multiply + lowpass:

```python
def coherent_demod(
    passband: NDArray[np.float32],
    carrier_ref: NDArray[np.float32],
    lpf_taps: NDArray,
) -> NDArray[np.float32]:
    """Shift a bandpassed signal down to baseband using a reference carrier."""
    return lfilter(lpf_taps, 1.0, passband * carrier_ref)
```

The multiply shifts the signal by ±carrier_frequency; the lowpass keeps
the lower sideband at baseband and removes the upper sideband at
2×carrier_frequency.

## Downstream stages that are NOT in this reference

These are deliberately omitted because they don't generalize beyond the
specific protocol they were written for:

- **Biphase-mark clock recovery** — RDS uses a zero-crossing-based PLL
  that only makes sense for biphase signaling
- **BCH parity / syndrome computation** — RDS uses BCH(26,16), HF digital
  modes use different FEC, AIS uses CRC-16
- **Frame synchronization** — every protocol has its own sync word, block
  structure, and offset rules

If you build a new decoder, those bits go in the decoder module, not here.

## Also worth noting

`signaldeck/engine/audio_pipeline.py` has a simpler `fm_demodulate(samples,
sample_rate, audio_rate)` that's the right tool for playable audio. Don't
duplicate it. Reach for this reference only when you need access to the
full FM multiplex spectrum or are building something that isn't just
"play this voice channel."
