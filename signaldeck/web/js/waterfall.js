/**
 * SignalDeck - Canvas-based Scrolling Waterfall / Spectrogram
 *
 * Renders FFT data as a scrolling color spectrogram.
 * Listens for 'fft' CustomEvents dispatched by app.js.
 */

class Waterfall {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;

    this.ctx = this.canvas.getContext('2d');
    this.freqStart = 24e6;   // Default start frequency (Hz)
    this.freqEnd = 1700e6;   // Default end frequency (Hz)

    // Sizing
    this.resize();
    window.addEventListener('resize', () => this.resize());

    // Listen for FFT events
    window.addEventListener('fft', (e) => this.onFFT(e.detail));

    // Generate color LUT for performance
    this.colorLUT = this.buildColorLUT();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.ctx.scale(dpr, dpr);
    this.width = rect.width;
    this.height = rect.height;
    this.headerHeight = 24;
  }

  /**
   * Build a 256-entry color lookup table mapping power to RGBA.
   * Power range: -100 dBm (index 0) to 0 dBm (index 255)
   *
   * Color mapping:
   *   -100 to -70: black -> deep blue
   *   -70 to -50:  deep blue -> cyan
   *   -50 to -40:  cyan -> green
   *   -40 to -30:  green -> yellow
   *   -30+:        yellow -> red -> white
   */
  buildColorLUT() {
    const lut = new Array(256);
    for (let i = 0; i < 256; i++) {
      const db = -100 + (i / 255) * 100; // Map 0-255 to -100..0
      let r, g, b;

      if (db < -70) {
        // Black to deep blue
        const t = (db + 100) / 30;
        r = 0;
        g = 0;
        b = Math.floor(t * 140);
      } else if (db < -50) {
        // Deep blue to cyan
        const t = (db + 70) / 20;
        r = 0;
        g = Math.floor(t * 200);
        b = 140 + Math.floor(t * 115);
      } else if (db < -40) {
        // Cyan to green
        const t = (db + 50) / 10;
        r = 0;
        g = 200 + Math.floor(t * 55);
        b = 255 - Math.floor(t * 255);
      } else if (db < -30) {
        // Green to yellow
        const t = (db + 40) / 10;
        r = Math.floor(t * 255);
        g = 255;
        b = 0;
      } else if (db < -10) {
        // Yellow to red
        const t = (db + 30) / 20;
        r = 255;
        g = 255 - Math.floor(t * 255);
        b = 0;
      } else {
        // Red to white
        const t = Math.min(1, (db + 10) / 10);
        r = 255;
        g = Math.floor(t * 255);
        b = Math.floor(t * 255);
      }

      lut[i] = `rgb(${r},${g},${b})`;
    }
    return lut;
  }

  /**
   * Map a dBm value to a color string.
   */
  dbToColor(db) {
    const idx = Math.max(0, Math.min(255, Math.floor(((db + 100) / 100) * 255)));
    return this.colorLUT[idx];
  }

  /**
   * Handle incoming FFT data.
   * @param {Object} detail - { data: Float32Array }
   */
  onFFT(detail) {
    if (!detail || !detail.data) return;

    const fftData = detail.data;
    const waterfallHeight = this.height - this.headerHeight;

    // Shift existing image down by 1 pixel
    const imgData = this.ctx.getImageData(0, this.headerHeight, this.width, waterfallHeight);
    this.ctx.putImageData(imgData, 0, this.headerHeight + 1);

    // Draw new FFT row at the top of the waterfall area
    const binWidth = this.width / fftData.length;
    for (let i = 0; i < fftData.length; i++) {
      this.ctx.fillStyle = this.dbToColor(fftData[i]);
      this.ctx.fillRect(i * binWidth, this.headerHeight, Math.ceil(binWidth), 1);
    }

    // Draw frequency axis header
    this.drawHeader(fftData.length);

    // Update frequency range if metadata available
    if (detail.freqStart) this.freqStart = detail.freqStart;
    if (detail.freqEnd) this.freqEnd = detail.freqEnd;
  }

  drawHeader(bins) {
    const ctx = this.ctx;

    // Clear header
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, this.width, this.headerHeight);

    // Frequency labels
    ctx.fillStyle = '#8b949e';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'center';

    const numLabels = Math.min(10, Math.floor(this.width / 90));
    for (let i = 0; i <= numLabels; i++) {
      const x = (i / numLabels) * this.width;
      const freq = this.freqStart + (i / numLabels) * (this.freqEnd - this.freqStart);
      const mhz = freq / 1e6;
      const label = mhz >= 1000 ? (mhz / 1000).toFixed(1) + 'G' : mhz.toFixed(1) + 'M';

      ctx.fillText(label, x, 16);

      // Tick mark
      ctx.strokeStyle = '#30363d';
      ctx.beginPath();
      ctx.moveTo(x, 20);
      ctx.lineTo(x, this.headerHeight);
      ctx.stroke();
    }

    // Bottom border
    ctx.strokeStyle = '#30363d';
    ctx.beginPath();
    ctx.moveTo(0, this.headerHeight - 0.5);
    ctx.lineTo(this.width, this.headerHeight - 0.5);
    ctx.stroke();
  }
}
