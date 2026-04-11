/**
 * SignalDeck - WebSocket Audio Player
 *
 * Connects to /ws/audio, subscribes to a frequency, receives PCM audio,
 * and plays it via the Web Audio API.
 */

class AudioPlayer {
  constructor() {
    this.audioContext = null;
    this.ws = null;
    this.sampleRate = 48000;
    this.volume = 0.7;
    this.playing = false;
    this.peakLevel = 0;
    this.gainNode = null;
    this.analyser = null;
    this.scriptNode = null;
    this.bufferQueue = [];
    this.subscribedFreq = null;
  }

  /**
   * Subscribe to audio for a given frequency (Hz).
   */
  subscribe(freqHz, modulation, volume = null) {
    this.stop(); // Clean up any existing connection

    // Create AudioContext on user gesture
    if (!this.audioContext) {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: this.sampleRate,
      });
    }

    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }

    // Set up audio graph: scriptProcessor -> gain -> analyser -> destination
    this.gainNode = this.audioContext.createGain();
    this.gainNode.gain.value = this.volume;

    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;

    this.gainNode.connect(this.analyser);
    this.analyser.connect(this.audioContext.destination);

    // Use ScriptProcessorNode for PCM playback
    // (AudioWorklet would be preferred but requires HTTPS and a separate file)
    const bufferSize = 4096;
    this.scriptNode = this.audioContext.createScriptProcessor(bufferSize, 1, 1);
    this.bufferQueue = [];

    this.scriptNode.onaudioprocess = (e) => {
      const output = e.outputBuffer.getChannelData(0);
      let outputPos = 0;

      // Fill the output buffer by consuming as many chunks from the queue
      // as needed. If a chunk is larger than the remaining output space,
      // we keep the remainder at the front of the queue for the next
      // callback. This is necessary because the server's chunk size
      // (40 ms worth of audio, ~1920 samples at 48 kHz) is smaller than
      // the ScriptProcessor's buffer (4096 samples ≈ 85 ms), so each
      // callback needs ~2 chunks to fill a single output buffer. The
      // previous version only consumed one chunk per callback and padded
      // the remainder with silence, producing ~47% audio / ~53% silence —
      // the "high-frequency chopping" the user heard.
      while (outputPos < output.length && this.bufferQueue.length > 0) {
        const chunk = this.bufferQueue[0];
        const remaining = output.length - outputPos;
        const take = Math.min(remaining, chunk.length);

        for (let i = 0; i < take; i++) {
          output[outputPos + i] = chunk[i];
        }
        outputPos += take;

        if (take === chunk.length) {
          // Consumed the entire chunk — remove it from the queue.
          this.bufferQueue.shift();
        } else {
          // Partial consumption — replace the head with the remainder so
          // the next callback picks up where we left off.
          this.bufferQueue[0] = chunk.subarray(take);
        }
      }

      // Fill any still-empty output with silence (queue ran dry).
      for (let i = outputPos; i < output.length; i++) {
        output[i] = 0;
      }

      // Update peak level from analyser
      this.updatePeakLevel();
    };

    this.scriptNode.connect(this.gainNode);

    // Connect WebSocket
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${window.location.host}/ws/audio`;

    try {
      this.ws = new WebSocket(wsUrl);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        // Subscribe to the desired frequency
        const msg = { type: 'subscribe', frequency_hz: freqHz };
        if (modulation) msg.modulation = modulation;
        if (volume !== null && volume !== undefined) msg.volume = volume;
        this.ws.send(JSON.stringify(msg));
        this.playing = true;
        this.subscribedFreq = freqHz;
      };

      this.ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          this.handlePCMData(event.data);
        } else {
          // JSON control message
          try {
            const msg = JSON.parse(event.data);
            if (msg.sample_rate) {
              this.sampleRate = msg.sample_rate;
            }
          } catch (e) {
            // Ignore
          }
        }
      };

      this.ws.onclose = () => {
        this.playing = false;
      };

      this.ws.onerror = () => {
        this.playing = false;
      };
    } catch (e) {
      console.error('AudioPlayer: WebSocket connection failed', e);
      this.playing = false;
    }
  }

  /**
   * Decode 16-bit signed PCM mono data and queue for playback.
   */
  handlePCMData(arrayBuffer) {
    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);

    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }

    this.bufferQueue.push(float32);

    // Prevent buffer from growing too large (latency control)
    while (this.bufferQueue.length > 10) {
      this.bufferQueue.shift();
    }
  }

  /**
   * Update peak level from analyser for VU meter display.
   */
  updatePeakLevel() {
    if (!this.analyser) {
      this.peakLevel = 0;
      return;
    }

    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteTimeDomainData(data);

    let peak = 0;
    for (let i = 0; i < data.length; i++) {
      const val = Math.abs(data[i] - 128) / 128;
      if (val > peak) peak = val;
    }

    // Smooth the level with decay
    this.peakLevel = Math.max(peak, this.peakLevel * 0.9);
  }

  /**
   * Stop playback and clean up.
   */
  stop() {
    if (this.ws) {
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'unsubscribe' }));
      }
      this.ws.close();
      this.ws = null;
    }

    if (this.scriptNode) {
      this.scriptNode.disconnect();
      this.scriptNode = null;
    }

    if (this.gainNode) {
      this.gainNode.disconnect();
      this.gainNode = null;
    }

    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }

    this.bufferQueue = [];
    this.playing = false;
    this.peakLevel = 0;
    this.subscribedFreq = null;
  }

  /**
   * Set playback volume (0.0 to 1.0).
   */
  setVolume(val) {
    this.volume = Math.max(0, Math.min(1, parseFloat(val)));
    if (this.gainNode) {
      this.gainNode.gain.value = this.volume;
    }
  }
}
