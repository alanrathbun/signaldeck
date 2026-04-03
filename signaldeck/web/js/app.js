/**
 * SignalDeck - Alpine.js Application Store
 * Main application logic, routing, data fetching, and WebSocket management.
 */

document.addEventListener('alpine:init', () => {
  // The main dashboard component is defined below via Alpine.data
});

function dashboard() {
  return {
    // --- Routing ---
    currentPage: 'live',
    mobileMenuOpen: false,

    // --- Scanner State ---
    scanning: false,
    scanMode: 'sweep',
    wsConnected: false,

    // --- Live Signals ---
    liveSignals: [],

    // --- Signals Page ---
    signals: [],
    signalSortKey: 'frequency',
    signalSortAsc: true,

    // --- Activity ---
    activity: [],
    activityLimit: 50,
    activityAutoRefresh: false,
    activityRefreshTimer: null,

    // --- Recordings ---
    recordings: [],

    // --- Bookmarks ---
    bookmarks: [],
    newBookmark: {
      frequency: null,
      label: '',
      modulation: '',
      decoder: '',
      priority: 3,
    },

    // --- Audio ---
    audioFreqMhz: null,
    audioPlaying: false,
    audioVolume: 0.7,
    audioLevel: 0,
    audioPlayer: null,

    // --- Scanner Status / Settings ---
    scannerStatus: {},
    settings: {},
    editSettings: {
      gain: 40,
      squelch_offset: 10,
      dwell_time_ms: 50,
      fft_size: 1024,
      scan_ranges: [],
    },

    // --- Map ---
    signalMap: null,

    // --- Charts ---
    charts: null,

    // --- Auth ---
    authenticated: false,
    authRequired: false,
    apiToken: localStorage.getItem('signaldeck_token') || null,
    loginError: '',

    // --- Toasts ---
    toasts: [],
    toastCounter: 0,

    // --- WebSockets ---
    wsSignals: null,
    wsWaterfall: null,
    wsReconnectTimer: null,

    // --- Waterfall ---
    waterfall: null,

    // =====================================================
    // Initialization
    // =====================================================
    async init() {
      // Restore page from hash
      const hash = window.location.hash.replace('#', '');
      if (hash && ['live', 'signals', 'activity', 'recordings', 'bookmarks', 'map', 'settings'].includes(hash)) {
        this.currentPage = hash;
      }

      // Check auth before anything else
      await this.checkAuth();

      // Connect WebSockets
      this.connectWebSockets();

      // Initialize waterfall after DOM is ready
      this.$nextTick(() => {
        if (typeof Waterfall !== 'undefined') {
          this.waterfall = new Waterfall('waterfall-canvas');
        }
        if (typeof AudioPlayer !== 'undefined') {
          this.audioPlayer = new AudioPlayer();
        }
        if (typeof Charts !== 'undefined') {
          this.charts = new Charts();
        }
      });

      // Fetch initial data for current page
      this.fetchPageData();

      // Handle hash changes
      window.addEventListener('hashchange', () => {
        const h = window.location.hash.replace('#', '');
        if (h) this.navigate(h, false);
      });
    },

    // =====================================================
    // Navigation
    // =====================================================
    navigate(page, updateHash = true) {
      this.currentPage = page;
      this.mobileMenuOpen = false;
      if (updateHash) window.location.hash = page;
      this.fetchPageData();

      // Initialize map when switching to map page
      if (page === 'map') {
        this.$nextTick(() => {
          if (!this.signalMap && typeof SignalMap !== 'undefined') {
            this.signalMap = new SignalMap('signal-map');
          } else if (this.signalMap && this.signalMap.map) {
            this.signalMap.map.invalidateSize();
          }
        });
      }

      // Draw charts on settings page
      if (page === 'settings') {
        this.$nextTick(() => this.fetchAnalytics());
      }
    },

    fetchPageData() {
      switch (this.currentPage) {
        case 'signals': this.fetchSignals(); break;
        case 'activity': this.fetchActivity(); break;
        case 'recordings': this.fetchRecordings(); break;
        case 'bookmarks': this.fetchBookmarks(); break;
        case 'settings': this.fetchStatus(); break;
      }
    },

    // =====================================================
    // WebSocket Connections
    // =====================================================
    connectWebSockets() {
      const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsBase = `${wsProto}//${window.location.host}`;

      // Live signals WebSocket
      this.connectWs(`${wsBase}/ws/signals`, (data) => {
        this.handleSignalMessage(data);
      });

      // Waterfall FFT WebSocket
      this.connectWsWaterfall(`${wsBase}/ws/waterfall`);
    },

    connectWs(url, onMessage) {
      try {
        const ws = new WebSocket(url);
        ws.onopen = () => {
          this.wsConnected = true;
          this.wsSignals = ws;
        };
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            onMessage(data);
          } catch (e) {
            // Binary or non-JSON data
          }
        };
        ws.onclose = () => {
          this.wsConnected = false;
          this.wsSignals = null;
          // Reconnect after 3 seconds
          clearTimeout(this.wsReconnectTimer);
          this.wsReconnectTimer = setTimeout(() => this.connectWebSockets(), 3000);
        };
        ws.onerror = () => {
          this.wsConnected = false;
        };
      } catch (e) {
        this.wsConnected = false;
      }
    },

    connectWsWaterfall(url) {
      try {
        const ws = new WebSocket(url);
        ws.binaryType = 'arraybuffer';
        ws.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            const fftData = new Float32Array(event.data);
            window.dispatchEvent(new CustomEvent('fft', { detail: { data: fftData } }));
          } else {
            try {
              const msg = JSON.parse(event.data);
              if (msg.type === 'fft' && msg.data) {
                window.dispatchEvent(new CustomEvent('fft', { detail: { data: new Float32Array(msg.data) } }));
              }
            } catch (e) {
              // Ignore parse errors
            }
          }
        };
        ws.onclose = () => {
          this.wsWaterfall = null;
        };
        this.wsWaterfall = ws;
      } catch (e) {
        // WebSocket not available
      }
    },

    handleSignalMessage(data) {
      if (data.type === 'signal' || data.frequency) {
        const sig = data.signal || data;
        const idx = this.liveSignals.findIndex(s => s.frequency === sig.frequency);
        if (idx >= 0) {
          this.liveSignals[idx] = { ...this.liveSignals[idx], ...sig, _updated: Date.now() };
        } else {
          this.liveSignals.push({ ...sig, _updated: Date.now() });
        }
        // Remove stale signals (older than 30 seconds)
        const cutoff = Date.now() - 30000;
        this.liveSignals = this.liveSignals.filter(s => s._updated > cutoff);

        // Forward to map if position data
        if (sig.latitude && sig.longitude && this.signalMap) {
          if (sig.protocol === 'ADS-B' || sig.type === 'adsb') {
            this.signalMap.addAircraft(sig);
          } else if (sig.protocol === 'APRS' || sig.type === 'aprs') {
            this.signalMap.addAprs(sig);
          }
        }
      }
    },

    // =====================================================
    // Auth
    // =====================================================
    authHeaders() {
      if (this.apiToken) {
        return { 'Authorization': 'Bearer ' + this.apiToken };
      }
      return {};
    },

    async checkAuth() {
      // Health endpoint is always accessible — use /api/signals to probe for auth
      try {
        const resp = await fetch('/api/signals', { headers: this.authHeaders() });
        if (resp.status === 401) {
          this.authRequired = true;
          this.authenticated = false;
        } else {
          this.authRequired = false;
          this.authenticated = true;
        }
      } catch (err) {
        // Network error: assume no auth required
        this.authenticated = true;
      }
    },

    async login(username, password) {
      this.loginError = '';
      try {
        const resp = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          this.loginError = err.detail || 'Invalid credentials';
          return;
        }
        const data = await resp.json();
        const token = data.api_token || data.session_token;
        this.apiToken = token;
        localStorage.setItem('signaldeck_token', token);
        // Also set as cookie for session-based auth
        document.cookie = `session_token=${token}; path=/; SameSite=Strict`;
        this.authenticated = true;
        this.authRequired = false;
        this.loginError = '';
        // Load initial data now that we're authenticated
        this.fetchPageData();
      } catch (err) {
        this.loginError = 'Login failed: ' + err.message;
      }
    },

    logout() {
      this.apiToken = null;
      localStorage.removeItem('signaldeck_token');
      // Clear the cookie
      document.cookie = 'session_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
      this.authenticated = false;
      this.authRequired = true;
    },

    // =====================================================
    // API Calls
    // =====================================================
    async apiFetch(url, options = {}) {
      try {
        const resp = await fetch(url, {
          headers: { 'Content-Type': 'application/json', ...this.authHeaders(), ...options.headers },
          ...options,
        });
        if (resp.status === 401) {
          this.authRequired = true;
          this.authenticated = false;
          return null;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
      } catch (err) {
        this.showToast(`API error: ${err.message}`, 'error');
        return null;
      }
    },

    async fetchSignals() {
      const data = await this.apiFetch('/api/signals');
      if (data) this.signals = Array.isArray(data) ? data : (data.signals || []);
    },

    async fetchActivity() {
      const data = await this.apiFetch(`/api/activity?limit=${this.activityLimit}`);
      if (data) this.activity = Array.isArray(data) ? data : (data.activity || []);
    },

    async fetchRecordings() {
      const data = await this.apiFetch('/api/recordings');
      if (data) this.recordings = Array.isArray(data) ? data : (data.recordings || []);
    },

    async fetchBookmarks() {
      const data = await this.apiFetch('/api/bookmarks');
      if (data) this.bookmarks = Array.isArray(data) ? data : (data.bookmarks || []);
    },

    async fetchStatus() {
      const [status, settings] = await Promise.all([
        this.apiFetch('/api/scanner/status'),
        this.apiFetch('/api/settings'),
      ]);
      if (status) {
        this.scannerStatus = { ...this.scannerStatus, ...status };
        this.scanning = status.status === 'running';
      }
      if (settings) {
        this.settings = settings;
        // Populate editable settings from current config
        if (settings.devices) {
          this.editSettings.gain = settings.devices.gain ?? 40;
        }
        if (settings.scanner) {
          this.editSettings.squelch_offset = settings.scanner.squelch_offset ?? 10;
          this.editSettings.dwell_time_ms = settings.scanner.dwell_time_ms ?? 50;
          this.editSettings.fft_size = settings.scanner.fft_size ?? 1024;
          this.editSettings.scan_ranges = (settings.scanner.sweep_ranges || []).map(r => ({
            label: r.label || '',
            start_mhz: r.start_mhz,
            end_mhz: r.end_mhz,
          }));
          this.scannerStatus.scan_ranges = this.editSettings.scan_ranges;
          this.scannerStatus.squelch_offset = this.editSettings.squelch_offset;
          this.scannerStatus.fft_size = this.editSettings.fft_size;
          this.scannerStatus.dwell_time_ms = this.editSettings.dwell_time_ms;
        }
        if (settings.devices) {
          this.scannerStatus.gain = settings.devices.gain;
        }
      }
    },

    async saveSettings() {
      const data = await this.apiFetch('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(this.editSettings),
      });
      if (data) {
        this.showToast('Settings saved. Changes take effect on next scan cycle.', 'success');
        await this.fetchStatus();
      }
    },

    addScanRange() {
      this.editSettings.scan_ranges.push({ label: '', start_mhz: 0, end_mhz: 0 });
    },

    removeScanRange(index) {
      this.editSettings.scan_ranges.splice(index, 1);
    },

    async fetchAnalytics() {
      const data = await this.apiFetch('/api/analytics/summary');
      if (data && this.charts) {
        this.$nextTick(() => {
          if (data.protocols || data.protocol_counts) {
            this.charts.drawProtocolChart('protocol-chart', data.protocols || data.protocol_counts);
          }
          if (data.hourly || data.hourly_counts) {
            this.charts.drawActivityChart('activity-chart', data.hourly || data.hourly_counts);
          }
        });
      }
    },

    // =====================================================
    // Scanner Controls
    // =====================================================
    async toggleScanner() {
      const endpoint = this.scanning ? '/api/scanner/stop' : '/api/scanner/start';
      const body = this.scanning ? {} : { mode: this.scanMode };
      const data = await this.apiFetch(endpoint, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (data) {
        this.scanning = !this.scanning;
        this.showToast(this.scanning ? 'Scanner started' : 'Scanner stopped', 'success');
      }
    },

    // =====================================================
    // Bookmarks CRUD
    // =====================================================
    async addBookmark() {
      if (!this.newBookmark.frequency) {
        this.showToast('Frequency is required', 'error');
        return;
      }
      const payload = {
        frequency: this.newBookmark.frequency * 1e6, // MHz to Hz
        label: this.newBookmark.label,
        modulation: this.newBookmark.modulation,
        decoder: this.newBookmark.decoder,
        priority: this.newBookmark.priority,
      };
      const data = await this.apiFetch('/api/bookmarks', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (data) {
        this.showToast('Bookmark added', 'success');
        this.newBookmark = { frequency: null, label: '', modulation: '', decoder: '', priority: 3 };
        this.fetchBookmarks();
      }
    },

    async deleteBookmark(id) {
      const data = await this.apiFetch(`/api/bookmarks/${id}`, { method: 'DELETE' });
      if (data !== null) {
        this.showToast('Bookmark deleted', 'success');
        this.bookmarks = this.bookmarks.filter(b => b.id !== id);
      }
    },

    // =====================================================
    // Audio
    // =====================================================
    tuneFrequency(freqHz) {
      this.audioFreqMhz = freqHz / 1e6;
    },

    startAudio() {
      if (!this.audioFreqMhz) {
        this.showToast('Enter a frequency first', 'error');
        return;
      }
      if (this.audioPlayer) {
        this.audioPlayer.subscribe(this.audioFreqMhz * 1e6);
        this.audioPlayer.setVolume(this.audioVolume);
        this.audioPlaying = true;

        // Poll VU level
        this._vuInterval = setInterval(() => {
          if (this.audioPlayer) {
            this.audioLevel = this.audioPlayer.peakLevel || 0;
          }
        }, 50);
      }
    },

    stopAudio() {
      if (this.audioPlayer) {
        this.audioPlayer.stop();
      }
      this.audioPlaying = false;
      this.audioLevel = 0;
      clearInterval(this._vuInterval);
    },

    setAudioVolume(val) {
      this.audioVolume = parseFloat(val);
      if (this.audioPlayer) this.audioPlayer.setVolume(this.audioVolume);
    },

    // =====================================================
    // Activity Auto-refresh
    // =====================================================
    toggleActivityRefresh() {
      if (this.activityAutoRefresh) {
        this.activityRefreshTimer = setInterval(() => {
          if (this.currentPage === 'activity') this.fetchActivity();
        }, 5000);
      } else {
        clearInterval(this.activityRefreshTimer);
        this.activityRefreshTimer = null;
      }
    },

    // =====================================================
    // Sorting
    // =====================================================
    sortSignals(key) {
      if (this.signalSortKey === key) {
        this.signalSortAsc = !this.signalSortAsc;
      } else {
        this.signalSortKey = key;
        this.signalSortAsc = true;
      }
    },

    get sortedSignals() {
      const key = this.signalSortKey;
      const asc = this.signalSortAsc;
      return [...this.signals].sort((a, b) => {
        let va = a[key], vb = b[key];
        if (va == null) va = '';
        if (vb == null) vb = '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
      });
    },

    sortIcon(key) {
      if (this.signalSortKey !== key) return '';
      return this.signalSortAsc ? '\u25B2' : '\u25BC';
    },

    // =====================================================
    // Formatters
    // =====================================================
    formatFreq(hz) {
      if (hz == null) return '--';
      const mhz = hz / 1e6;
      if (mhz >= 1000) return (mhz / 1000).toFixed(3) + ' GHz';
      if (mhz >= 1) return mhz.toFixed(4) + ' MHz';
      return (hz / 1000).toFixed(1) + ' kHz';
    },

    formatTime(ts) {
      if (!ts) return '--';
      try {
        const d = new Date(ts);
        if (isNaN(d.getTime())) return ts;
        const now = new Date();
        const diff = now - d;
        // If less than 24 hours ago, show relative
        if (diff < 86400000 && diff > 0) {
          if (diff < 60000) return Math.floor(diff / 1000) + 's ago';
          if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
          return Math.floor(diff / 3600000) + 'h ago';
        }
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      } catch (e) {
        return ts;
      }
    },

    formatPower(dbm) {
      if (dbm == null) return '--';
      return dbm.toFixed(1) + ' dBm';
    },

    powerPct(dbm) {
      if (dbm == null) return 0;
      // Map -100..0 dBm to 0..100%
      return Math.max(0, Math.min(100, (dbm + 100)));
    },

    powerColor(dbm) {
      if (dbm == null) return '#30363d';
      if (dbm > -50) return '#3fb950';  // Strong - green
      if (dbm > -70) return '#d29922';  // Medium - orange
      return '#f85149';                  // Weak - red
    },

    modBadge(mod) {
      if (!mod) return 'badge-blue';
      const m = mod.toUpperCase();
      if (['FM', 'NFM', 'WFM', 'AM'].includes(m)) return 'badge-blue';
      if (['P25', 'DMR', 'DSTAR', 'NXDN', 'DIGITAL'].includes(m)) return 'badge-green';
      if (['ADSB', 'ADS-B', 'ACARS', 'AIS', 'POCSAG'].includes(m)) return 'badge-orange';
      if (['USB', 'LSB', 'CW'].includes(m)) return 'badge-purple';
      return 'badge-blue';
    },

    // =====================================================
    // Toast Notifications
    // =====================================================
    showToast(message, type = 'info') {
      const id = ++this.toastCounter;
      this.toasts.push({ id, message, type, visible: true });
      setTimeout(() => this.dismissToast(id), 4000);
    },

    dismissToast(id) {
      const toast = this.toasts.find(t => t.id === id);
      if (toast) toast.visible = false;
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, 200);
    },
  };
}
