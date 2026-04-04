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
    signalEnrichment: {},
    _enrichmentTimer: null,
    liveFilterMod: '',
    liveFilterProto: '',
    liveFilterMinPower: null,
    liveFilterFreq: '',
    liveFilterDecoder: '',
    liveFilterBandwidthMin: null,
    liveFilterBandwidthMax: null,
    liveSortKey: 'power',
    liveSortAsc: false,
    showColumnPicker: false,
    liveVisibleCols: JSON.parse(localStorage.getItem('signaldeck_live_cols') || 'null')
      || ['frequency', 'power', 'modulation', 'protocol', 'hits', 'last_seen'],
    allLiveColumns: [
      { key: 'frequency', label: 'Frequency' },
      { key: 'bandwidth', label: 'Bandwidth' },
      { key: 'power', label: 'Power' },
      { key: 'modulation', label: 'Modulation' },
      { key: 'protocol', label: 'Protocol' },
      { key: 'hits', label: 'Hits' },
      { key: 'last_seen', label: 'Last Seen' },
      { key: 'first_seen', label: 'First Seen' },
      { key: 'confidence', label: 'Confidence' },
      { key: 'decoder', label: 'Decoder' },
      { key: 'activity_type', label: 'Activity Type' },
      { key: 'activity_summary', label: 'Last Activity' },
    ],

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
    statusData: {},
    editSettings: {
      gain: 40,
      squelch_offset: 10,
      min_signal_strength: -50,
      dwell_time_ms: 50,
      fft_size: 1024,
      scan_ranges: [],
      sample_rate: 48000,
      recording_dir: 'data/recordings',
      log_level: 'INFO',
      scanner_device: 'none',
      tuner_device: 'none',
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
    showApiToken: false,
    currentApiToken: null,
    changePass: { current: '', newPass: '', confirm: '' },

    // --- Logs ---
    logFiles: [],
    currentLog: { name: '', content: '' },
    logFilter: '',

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
      if (hash && ['live', 'recordings', 'bookmarks', 'map', 'status', 'settings', 'logs'].includes(hash)) {
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

      // Fetch scanner status (needed to know if gqrx backend)
      this.fetchStatus();

      // Periodic enrichment sync for database fields
      this.fetchEnrichment();
      this._enrichmentTimer = setInterval(() => this.fetchEnrichment(), 10000);

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

      // Draw charts on status page
      if (page === 'status') {
        this.$nextTick(() => this.fetchAnalytics());
      }
    },

    fetchPageData() {
      if (this.currentPage === 'status') {
        this.fetchStatusPage();
        this.fetchAnalytics();
      }
      if (this.currentPage === 'logs') {
        this.fetchLogFiles();
        this.fetchCurrentLog();
      }
      switch (this.currentPage) {
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
          const prev = this.liveSignals[idx];
          this.liveSignals[idx] = { ...prev, ...sig, _updated: Date.now(), _hits: (prev._hits || 1) + 1 };
        } else {
          this.liveSignals.push({ ...sig, _updated: Date.now(), _hits: 1 });
        }
        // Remove stale signals (older than 60 seconds)
        const cutoff = Date.now() - 60000;
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

    async fetchEnrichment() {
      const data = await this.apiFetch('/api/signals/enrichment');
      if (data) this.signalEnrichment = data;
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
          this.editSettings.min_signal_strength = settings.scanner.min_signal_strength ?? -50;
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
        if (settings.audio) {
          this.editSettings.sample_rate = settings.audio.sample_rate || 48000;
          this.editSettings.recording_dir = settings.audio.recording_dir || 'data/recordings';
        }
        if (settings.logging) {
          this.editSettings.log_level = settings.logging.level || 'INFO';
        }
      }
    },

    async saveSettings() {
      const payload = {
        ...this.editSettings,
        log_level: this.editSettings.log_level,
        sample_rate: this.editSettings.sample_rate,
        recording_dir: this.editSettings.recording_dir,
      };
      const data = await this.apiFetch('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
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

    async fetchStatusPage() {
      try {
        const data = await this.apiFetch('/api/status');
        if (data) this.statusData = data;
      } catch (e) { /* status page is non-critical */ }
      await this.fetchStatus();
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

    async fetchLogFiles() {
      try {
        const data = await this.apiFetch('/api/logs');
        if (data) this.logFiles = data;
      } catch (e) { /* ignore */ }
    },

    async fetchCurrentLog() {
      try {
        const data = await this.apiFetch('/api/logs/current');
        if (data) this.currentLog = data;
      } catch (e) { /* ignore */ }
    },

    async selectLogFile(filename) {
      try {
        const data = await this.apiFetch(`/api/logs/${filename}`);
        if (data) this.currentLog = data;
      } catch (e) {
        this.showToast('Failed to load log file', 'error');
      }
    },

    get filteredLogLines() {
      if (!this.currentLog.content) return [];
      const lines = this.currentLog.content.split('\n');
      if (!this.logFilter) return lines;
      const levels = { 'ERROR': 3, 'WARNING': 2, 'INFO': 1 };
      const minLevel = levels[this.logFilter] || 0;
      return lines.filter(line => {
        if (line.includes(' ERROR:')) return levels['ERROR'] >= minLevel;
        if (line.includes(' WARNING:')) return levels['WARNING'] >= minLevel;
        if (line.includes(' INFO:')) return levels['INFO'] >= minLevel;
        if (line.includes(' DEBUG:')) return 0 >= minLevel;
        return true;
      });
    },

    async toggleAuth() {
      const current = this.settings.auth && this.settings.auth.enabled;
      const action = current ? 'disable' : 'enable';
      if (!confirm(`${action.charAt(0).toUpperCase() + action.slice(1)} authentication?`)) return;
      try {
        const resp = await this.apiFetch('/api/auth/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !current }),
        });
        if (resp) {
          this.showToast(`Authentication ${!current ? 'enabled' : 'disabled'}`, 'success');
          this.fetchStatus();
        }
      } catch (e) {
        this.showToast('Failed to toggle auth', 'error');
      }
    },

    async fetchApiToken() {
      try {
        const data = await this.apiFetch('/api/auth/token');
        if (data) {
          this.currentApiToken = data.api_token;
        }
      } catch (e) { /* ignore */ }
    },

    async copyApiToken() {
      if (this.currentApiToken) {
        await navigator.clipboard.writeText(this.currentApiToken);
        this.showToast('Token copied to clipboard', 'success');
      }
    },

    async regenerateToken() {
      try {
        const data = await this.apiFetch('/api/auth/regenerate-token', { method: 'POST' });
        if (data) {
          this.currentApiToken = data.api_token;
          this.apiToken = data.api_token;
          localStorage.setItem('signaldeck_token', data.api_token);
          this.showToast('API token regenerated', 'success');
        }
      } catch (e) {
        this.showToast('Failed to regenerate token', 'error');
      }
    },

    async changePassword() {
      if (this.changePass.newPass !== this.changePass.confirm) {
        this.showToast('Passwords do not match', 'error');
        return;
      }
      try {
        const data = await this.apiFetch('/api/auth/change-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: 'admin',
            current_password: this.changePass.current,
            new_password: this.changePass.newPass,
          }),
        });
        if (data) {
          this.showToast('Password changed', 'success');
          this.changePass = { current: '', newPass: '', confirm: '' };
        } else {
          this.showToast('Invalid current password', 'error');
        }
      } catch (e) {
        this.showToast('Failed to change password', 'error');
      }
    },

    async clearData(target) {
      if (!confirm(`Clear ${target}? This cannot be undone.`)) return;
      try {
        const data = await this.apiFetch(`/api/data/${target}`, { method: 'DELETE' });
        if (data) {
          this.showToast(`${target} cleared`, 'success');
        }
      } catch (e) {
        this.showToast(`Failed to clear ${target}`, 'error');
      }
    },

    async deleteLogs() {
      if (!confirm('Delete all log files except the current session?')) return;
      try {
        const data = await this.apiFetch('/api/logs', { method: 'DELETE' });
        if (data) {
          this.showToast(`Deleted ${data.deleted} log file(s)`, 'success');
        }
      } catch (e) {
        this.showToast('Failed to delete logs', 'error');
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
    // --- Live signal filtering ---
    get filteredLiveSignals() {
      return this.liveSignals.filter(s => {
        if (this.liveFilterMod && s.modulation !== this.liveFilterMod) return false;
        if (this.liveFilterProto && s.protocol !== this.liveFilterProto) return false;
        if (this.liveFilterMinPower && s.power < this.liveFilterMinPower) return false;
        if (this.liveFilterFreq) {
          const mhz = (s.frequency || 0) / 1e6;
          const f = this.liveFilterFreq.trim();
          if (f.includes('-')) {
            const [lo, hi] = f.split('-').map(Number);
            if (mhz < lo || mhz > hi) return false;
          } else {
            if (!mhz.toFixed(3).includes(f)) return false;
          }
        }
        if (this.liveFilterDecoder) {
          const freqKey = String(Math.round(s.frequency || 0));
          const enrich = this.signalEnrichment[freqKey] || {};
          const activity = enrich.last_activity || {};
          if ((activity.decoder || '') !== this.liveFilterDecoder) return false;
        }
        if (this.liveFilterBandwidthMin && (s.bandwidth || 0) < this.liveFilterBandwidthMin) return false;
        if (this.liveFilterBandwidthMax && (s.bandwidth || 0) > this.liveFilterBandwidthMax) return false;
        return true;
      });
    },

    get enrichedLiveSignals() {
      return this.filteredLiveSignals.map(sig => {
        const freqKey = String(Math.round(sig.frequency || 0));
        const enrich = this.signalEnrichment[freqKey] || {};
        const activity = enrich.last_activity || {};
        return {
          ...sig,
          first_seen: enrich.first_seen || null,
          db_hits: enrich.hit_count || 0,
          confidence: enrich.confidence || 0,
          decoder: activity.decoder || null,
          activity_type: activity.type || null,
          activity_summary: activity.summary || null,
        };
      });
    },

    get sortedLiveSignals() {
      const key = this.liveSortKey;
      const asc = this.liveSortAsc;
      return [...this.enrichedLiveSignals].sort((a, b) => {
        let va = a[key], vb = b[key];
        if (key === 'hits') { va = a._hits || 1; vb = b._hits || 1; }
        if (typeof va === 'string') va = (va || '').toLowerCase();
        if (typeof vb === 'string') vb = (vb || '').toLowerCase();
        if (va == null) va = '';
        if (vb == null) vb = '';
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
      });
    },

    sortLive(key) {
      if (this.liveSortKey === key) {
        this.liveSortAsc = !this.liveSortAsc;
      } else {
        this.liveSortKey = key;
        this.liveSortAsc = key === 'frequency';  // ascending for freq, descending for others
      }
    },

    liveSortIcon(key) {
      if (this.liveSortKey !== key) return '';
      return this.liveSortAsc ? '\u25B2' : '\u25BC';
    },

    toggleLiveCol(key) {
      const idx = this.liveVisibleCols.indexOf(key);
      if (idx >= 0) {
        this.liveVisibleCols.splice(idx, 1);
      } else {
        this.liveVisibleCols.push(key);
      }
      localStorage.setItem('signaldeck_live_cols', JSON.stringify(this.liveVisibleCols));
    },

    clearLiveFilters() {
      this.liveFilterMod = '';
      this.liveFilterProto = '';
      this.liveFilterMinPower = null;
      this.liveFilterFreq = '';
      this.liveFilterDecoder = '';
      this.liveFilterBandwidthMin = null;
      this.liveFilterBandwidthMax = null;
    },

    get liveModulations() {
      const mods = new Set(this.liveSignals.map(s => s.modulation).filter(Boolean));
      return [...mods].sort();
    },

    get liveProtocols() {
      const protos = new Set(this.liveSignals.map(s => s.protocol).filter(Boolean));
      return [...protos].sort();
    },

    get liveDecoders() {
      const decoders = new Set();
      for (const s of this.liveSignals) {
        const freqKey = String(Math.round(s.frequency || 0));
        const enrich = this.signalEnrichment[freqKey] || {};
        const decoder = (enrich.last_activity || {}).decoder;
        if (decoder) decoders.add(decoder);
      }
      return [...decoders].sort();
    },

    tuneFrequency(freqHz) {
      this.audioFreqMhz = freqHz / 1e6;
    },

    tuneAndListen(freqHz) {
      this.audioFreqMhz = freqHz / 1e6;
      this.startAudio();
    },

    async quickBookmark(sig) {
      const label = (sig.protocol || sig.modulation || 'Signal') + ' ' + this.formatFreq(sig.frequency);
      await this.apiFetch('/api/bookmarks', {
        method: 'POST',
        body: JSON.stringify({
          frequency_hz: sig.frequency,
          label: label,
          modulation: sig.modulation || 'FM',
          decoder: sig.protocol || null,
          priority: 3,
        }),
      });
      this.showToast('Bookmarked ' + this.formatFreq(sig.frequency), 'success');
      this.fetchBookmarks();
    },

    isGqrxBackend() {
      return this.scannerStatus && (this.scannerStatus.backend === 'gqrx' || this.scannerStatus.backend === 'both');
    },

    startAudio() {
      if (!this.audioFreqMhz) {
        this.showToast('Enter a frequency first', 'error');
        return;
      }
      if (this.audioPlayer) {
        // Always subscribe via WebSocket — this tells the backend to tune
        this.audioPlayer.subscribe(this.audioFreqMhz * 1e6);
        this.audioPlaying = true;

        if (this.isGqrxBackend()) {
          // gqrx handles audio output directly — no web audio needed
          this.showToast('Tuned gqrx to ' + this.audioFreqMhz + ' MHz — audio plays through gqrx', 'success');
        } else {
          this.audioPlayer.setVolume(this.audioVolume);
          // Poll VU level
          this._vuInterval = setInterval(() => {
            if (this.audioPlayer) {
              this.audioLevel = this.audioPlayer.peakLevel || 0;
            }
          }, 50);
        }
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
