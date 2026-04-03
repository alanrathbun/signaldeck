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
  subscribe(freqHz) {
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
      if (this.bufferQueue.length > 0) {
        const chunk = this.bufferQueue.shift();
        const len = Math.min(output.length, chunk.length);
        for (let i = 0; i < len; i++) {
          output[i] = chunk[i];
        }
        // Fill remainder with silence
        for (let i = len; i < output.length; i++) {
          output[i] = 0;
        }
      } else {
        // Silence
        for (let i = 0; i < output.length; i++) {
          output[i] = 0;
        }
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
        this.ws.send(JSON.stringify({
          type: 'subscribe',
          frequency: freqHz,
        }));
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
