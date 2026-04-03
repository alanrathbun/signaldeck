/**
 * SignalDeck - Simple Canvas-based Analytics Charts
 *
 * Draws protocol distribution and hourly activity bar charts
 * without any external charting library.
 */

class Charts {

  /**
   * Draw a horizontal bar chart showing protocol distribution.
   * @param {string} canvasId - Canvas element ID
   * @param {Object|Array} data - { "ADS-B": 150, "FM": 80, ... } or [{ name, count }]
   */
  drawProtocolChart(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Normalize data to array of { name, count }
    let items = [];
    if (Array.isArray(data)) {
      items = data.map(d => ({ name: d.name || d.protocol || d.label, count: d.count || d.value || 0 }));
    } else if (typeof data === 'object') {
      items = Object.entries(data).map(([name, count]) => ({ name, count }));
    }

    if (items.length === 0) {
      this.drawEmpty(ctx, canvas, 'No protocol data available');
      return;
    }

    // Sort descending by count
    items.sort((a, b) => b.count - a.count);
    items = items.slice(0, 12); // Limit to top 12

    const maxCount = Math.max(...items.map(d => d.count), 1);

    // Size canvas
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = rect.height;

    // Colors per protocol
    const colors = {
      'ADS-B': '#58a6ff', 'ADSB': '#58a6ff',
      'FM': '#58a6ff', 'NFM': '#79b8ff', 'AM': '#a5d6ff',
      'P25': '#3fb950', 'DMR': '#56d364', 'DIGITAL': '#2ea043',
      'ACARS': '#d29922', 'POCSAG': '#e3b341', 'AIS': '#db6d28',
      'APRS': '#3fb950',
      'NOAA': '#bc8cff',
    };
    const defaultColor = '#58a6ff';

    // Layout
    const padding = { top: 8, right: 16, bottom: 8, left: 80 };
    const barHeight = Math.min(24, (h - padding.top - padding.bottom) / items.length - 4);
    const barGap = 4;
    const chartWidth = w - padding.left - padding.right;

    // Clear
    ctx.fillStyle = '#161b22';
    ctx.fillRect(0, 0, w, h);

    // Draw bars
    items.forEach((item, i) => {
      const y = padding.top + i * (barHeight + barGap);
      const barWidth = (item.count / maxCount) * chartWidth;
      const color = colors[item.name] || colors[item.name?.toUpperCase()] || defaultColor;

      // Label
      ctx.fillStyle = '#8b949e';
      ctx.font = '11px -apple-system, sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(item.name || '--', padding.left - 8, y + barHeight / 2);

      // Bar
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.85;
      this.roundRect(ctx, padding.left, y, barWidth, barHeight, 3);
      ctx.fill();
      ctx.globalAlpha = 1;

      // Count label
      if (barWidth > 30) {
        ctx.fillStyle = '#e6edf3';
        ctx.font = 'bold 11px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(item.count.toLocaleString(), padding.left + barWidth - 28, y + barHeight / 2);
      } else {
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(item.count.toLocaleString(), padding.left + barWidth + 6, y + barHeight / 2);
      }
    });
  }

  /**
   * Draw a vertical bar chart showing signal count by hour.
   * @param {string} canvasId - Canvas element ID
   * @param {Object|Array} data - { "0": 12, "1": 8, ... } or [count_per_hour]
   */
  drawActivityChart(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Normalize to 24-element array
    let hourly = new Array(24).fill(0);
    if (Array.isArray(data)) {
      data.forEach((val, i) => {
        if (i < 24) hourly[i] = val || 0;
      });
    } else if (typeof data === 'object') {
      Object.entries(data).forEach(([hour, count]) => {
        const h = parseInt(hour);
        if (h >= 0 && h < 24) hourly[h] = count || 0;
      });
    }

    const maxVal = Math.max(...hourly, 1);

    // Size canvas
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = rect.height;

    if (maxVal === 0) {
      this.drawEmpty(ctx, canvas, 'No hourly data available');
      return;
    }

    // Layout
    const padding = { top: 12, right: 8, bottom: 28, left: 36 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;
    const barWidth = chartW / 24 - 2;
    const barGap = 2;

    // Clear
    ctx.fillStyle = '#161b22';
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = '#21262d';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (i / 4) * chartH;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(w - padding.right, y);
      ctx.stroke();

      // Y-axis label
      ctx.fillStyle = '#484f58';
      ctx.font = '10px -apple-system, sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      const val = Math.round(maxVal * (1 - i / 4));
      ctx.fillText(val.toString(), padding.left - 6, y);
    }

    // Draw bars
    hourly.forEach((count, hour) => {
      const x = padding.left + hour * (barWidth + barGap);
      const barH = (count / maxVal) * chartH;
      const y = padding.top + chartH - barH;

      // Color gradient based on activity level
      const intensity = count / maxVal;
      let color;
      if (intensity > 0.7) color = '#f85149';
      else if (intensity > 0.4) color = '#d29922';
      else if (intensity > 0.1) color = '#58a6ff';
      else color = '#21262d';

      ctx.fillStyle = color;
      ctx.globalAlpha = Math.max(0.4, intensity);
      this.roundRect(ctx, x, y, barWidth, barH, 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      // Hour label
      if (hour % 3 === 0) {
        ctx.fillStyle = '#484f58';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(hour.toString().padStart(2, '0'), x + barWidth / 2, h - padding.bottom + 6);
      }
    });
  }

  /**
   * Draw an empty state message on the canvas.
   */
  drawEmpty(ctx, canvas, message) {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#161b22';
    ctx.fillRect(0, 0, rect.width, rect.height);

    ctx.fillStyle = '#484f58';
    ctx.font = '13px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(message, rect.width / 2, rect.height / 2);
  }

  /**
   * Helper to draw a rounded rectangle path.
   */
  roundRect(ctx, x, y, w, h, r) {
    if (w < 0) w = 0;
    if (h < 0) h = 0;
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }
}
