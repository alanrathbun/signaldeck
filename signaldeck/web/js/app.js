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
    statusPollTimer: null,

    // --- Live Signals ---
    liveSignals: [],
    pendingSignalMessages: [],
    signalFlushTimer: null,
    signalEnrichment: {},
    _enrichmentTimer: null,
    liveFilterMod: '',
    liveFilterProto: '',
    liveFilterSignalClass: '',
    liveFilterMinPower: null,
    liveFilterFreq: '',
    liveFilterDecoder: '',
    liveFilterBandwidthMin: null,
    liveFilterBandwidthMax: null,
    liveSortKey: 'power',
    liveSortAsc: false,
    showColumnPicker: false,
    liveVisibleCols: JSON.parse(localStorage.getItem('signaldeck_live_cols') || 'null')
      || ['frequency', 'power', 'modulation', 'protocol', 'signal_class', 'rds', 'hits', 'last_seen'],
    allLiveColumns: [
      { key: 'frequency', label: 'Frequency' },
      { key: 'bandwidth', label: 'Bandwidth' },
      { key: 'power', label: 'Power' },
      { key: 'modulation', label: 'Modulation' },
      { key: 'protocol', label: 'Protocol' },
      { key: 'rds', label: 'RDS' },
      { key: 'hits', label: 'Hits' },
      { key: 'last_seen', label: 'Last Seen' },
      { key: 'first_seen', label: 'First Seen' },
      { key: 'confidence', label: 'Confidence' },
      { key: 'signal_class', label: 'Signal Class' },
      { key: 'decoder', label: 'Decoder' },
      { key: 'activity_type', label: 'Activity Type' },
      { key: 'activity_summary', label: 'Last Activity' },
    ],

    // --- Recordings ---
    recordings: [],

    // --- Bookmarks ---
    bookmarks: [],
    // ---- Bookmark edit/create modal state ----
    editingBookmark: null,         // null = modal hidden; object = modal open
    editModalMode: 'create',       // 'create' | 'edit'
    editModalSignal: null,         // source Live signal for create-from-signal mode
    editModalError: '',
    savingBookmark: false,         // true while saveBookmarkEdit is in flight (prevents double-submit)
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
    audioMode: 'auto',  // auto | gqrx | pcm_stream
    audioStatus: {
      configured_mode: 'auto',
      effective_mode: 'gqrx',
      subscriber_count: 0,
      remote_subscriber_count: 0,
    },

    // --- Scanner Status / Settings ---
    scannerStatus: {},
    settings: {},
    statusData: {},

    // --- Process lifecycle (systemd --user) ---
    processStatus: {
      pid: null,
      uptime_seconds: null,
      running: true,
      can_control: false,
      supervisor: null,
    },
    processActionBusy: false,
    processActionMessage: '',
    // Connection-health state for the Service badge. We flip to
    // "disconnected" when two consecutive /api/process/status calls fail,
    // and to "restarting" while an active restart is in flight.
    processConnected: true,
    processConsecutiveFailures: 0,
    processRestartInFlight: false,
    processRestartPrevPid: null,

    editSettings: {
      gain: 40,
      squelch_offset: 10,
      min_signal_strength: -50,
      dwell_time_ms: 50,
      fft_size: 1024,
      scan_profiles: [],
      scan_ranges: [],
      sample_rate: 48000,
      recording_dir: 'data/recordings',
      log_level: 'INFO',
      scanner_device: 'none',
      tuner_device: 'none',
    },

    availableScanProfiles: [],

    // --- Default scan range presets ---
    defaultScanRanges: [
      { label: 'NOAA Weather', start_mhz: 162.4, end_mhz: 162.55, step_khz: 25, priority: 22 },
      { label: 'Marine VHF', start_mhz: 156, end_mhz: 163, step_khz: 25, priority: 21 },
      { label: 'Airband', start_mhz: 118, end_mhz: 137, step_khz: 25, priority: 19 },
      { label: 'Broadcast FM', start_mhz: 88, end_mhz: 108, step_khz: 200, priority: 18 },
      { label: '2m Amateur', start_mhz: 144, end_mhz: 148, step_khz: 25, priority: 19 },
      { label: 'MURS', start_mhz: 151.82, end_mhz: 154.6, step_khz: 12.5, priority: 18 },
      { label: 'Pager / POCSAG', start_mhz: 152, end_mhz: 159, step_khz: 12.5, priority: 18 },
      { label: 'ISM 433', start_mhz: 433, end_mhz: 435, step_khz: 25, priority: 20 },
      { label: 'FRS/GMRS', start_mhz: 462.55, end_mhz: 467.725, step_khz: 12.5, priority: 18 },
      { label: 'NOAA APT', start_mhz: 137, end_mhz: 138, step_khz: 25, priority: 16 },
    ],
    showDefaultRanges: false,

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

    // ---- Login overlay state ----
    loginRequired: false,
    loginUsername: 'admin',
    loginPassword: '',
    _retryAfterLogin: null,

    // ---- First-run password modal state ----
    firstRunPassword: null,
    firstRunAcknowledged: false,

    // --- Sessions ---
    sessions: [],

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
    showWaterfall: false,
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

      // Initialize components after DOM is ready
      this.$nextTick(() => {
        if (typeof AudioPlayer !== 'undefined') {
          this.audioPlayer = new AudioPlayer();
        }
        if (typeof Charts !== 'undefined') {
          this.charts = new Charts();
        }
      });

      // Fetch scanner status frequently, but avoid hardware refreshes.
      this.fetchStatus();
      this.statusPollTimer = setInterval(() => {
        this.fetchStatus();
        if (this.currentPage === 'status' || this.currentPage === 'settings' || this.currentPage === 'live') {
          this.fetchStatusPage();
        }
      }, 3000);

      // Load bookmarks up-front so the Live page can flag already-bookmarked
      // signals without waiting for the user to visit the Bookmarks page.
      this.fetchBookmarks();

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
        case 'settings': this.fetchSettings(true); this.fetchSessions(); this.fetchStatusPage(); break;
      }
      // Always refresh /api/status on entry to pages that display audioStatus.
      if (this.currentPage === 'live') {
        this.fetchStatusPage();
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

      // Waterfall FFT WebSocket — only connect when visible
      if (this.showWaterfall) {
        this.connectWsWaterfall(`${wsBase}/ws/waterfall`);
      }
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
                window.dispatchEvent(new CustomEvent('fft', { detail: {
                  data: new Float32Array(msg.data),
                  freqStart: msg.freq_start,
                  freqEnd: msg.freq_end,
                } }));
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
      if (data.type === 'signal_batch' && Array.isArray(data.signals)) {
        this.pendingSignalMessages.push(...data.signals);
      } else if (data.type === 'signal' || data.frequency) {
        this.pendingSignalMessages.push(data.signal || data);
      } else {
        return;
      }
      this.scheduleSignalFlush();
    },

    scheduleSignalFlush() {
      if (this.signalFlushTimer) return;
      this.signalFlushTimer = setTimeout(() => {
        this.flushPendingSignals();
      }, 120);
    },

    flushPendingSignals() {
      this.signalFlushTimer = null;
      if (!this.pendingSignalMessages.length) return;
      const batch = this.pendingSignalMessages.splice(0, this.pendingSignalMessages.length);
      const indexByFrequency = new Map(this.liveSignals.map((sig, idx) => [sig.frequency, idx]));

      for (const sig of batch) {
        const idx = indexByFrequency.get(sig.frequency);
        if (idx !== undefined) {
          const prev = this.liveSignals[idx];
          this.liveSignals[idx] = {
            ...prev,
            ...sig,
            _updated: Date.now(),
            _hits: (prev._hits || 1) + 1,
            rds: sig.rds || prev.rds || null,
          };
        } else {
          indexByFrequency.set(sig.frequency, this.liveSignals.length);
          this.liveSignals.push({ ...sig, _updated: Date.now(), _hits: 1, rds: sig.rds || null });
        }

        if (sig.latitude && sig.longitude && this.signalMap) {
          if (sig.protocol === 'ADS-B' || sig.type === 'adsb') {
            this.signalMap.addAircraft(sig);
          } else if (sig.protocol === 'APRS' || sig.type === 'aprs') {
            this.signalMap.addAprs(sig);
          }
        }
      }
      this.pruneLiveSignals();
    },

    pruneLiveSignals() {
      // Live signals persist until the user explicitly clears them.
      // We still merge repeat hits by frequency in flushPendingSignals().
      return;
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

    async submitLogin() {
      this.loginError = '';
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: this.loginUsername,
          password: this.loginPassword,
        }),
        credentials: 'same-origin',
      });
      if (resp.status === 200) {
        const data = await resp.json().catch(() => ({}));
        const token = data.api_token || data.session_token;
        if (token) {
          this.apiToken = token;
          localStorage.setItem('signaldeck_token', token);
          document.cookie = `session_token=${token}; path=/; SameSite=Strict`;
        }
        this.loginRequired = false;
        this.loginPassword = '';
        this.authenticated = true;
        this.authRequired = false;
        this.showToast('Signed in', 'success');
        if (this._retryAfterLogin) {
          const { url, opts } = this._retryAfterLogin;
          this._retryAfterLogin = null;
          return await this.apiFetch(url, opts);
        }
      } else {
        const body = await resp.json().catch(() => ({}));
        this.loginError = body.detail || 'Invalid username or password';
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
      const silent = options._silent;
      delete options._silent;
      try {
        const resp = await fetch(url, {
          headers: { 'Content-Type': 'application/json', ...this.authHeaders(), ...options.headers },
          ...options,
        });
        if (resp.status === 401) {
          this.loginRequired = true;
          this._retryAfterLogin = { url, opts: options };
          return null;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
      } catch (err) {
        if (!silent) this.showToast(`API error: ${err.message}`, 'error');
        return null;
      }
    },

    async fetchEnrichment() {
      const data = await this.apiFetch('/api/signals/enrichment', { _silent: true });
      if (data) this.signalEnrichment = data;
    },

    async fetchRecordings() {
      const data = await this.apiFetch('/api/recordings', { _silent: true });
      if (data) this.recordings = Array.isArray(data) ? data : (data.recordings || []);
    },

    async fetchBookmarks() {
      const data = await this.apiFetch('/api/bookmarks', { _silent: true });
      if (data) this.bookmarks = Array.isArray(data) ? data : (data.bookmarks || []);
    },

    applySettings(settings) {
      this.settings = settings;
      if (settings.devices) {
        this.editSettings.gain = settings.devices.gain ?? 40;
        // Round-trip persisted device roles so the Settings form shows the
        // real selection instead of snapping back to the default 'none'.
        // Without this, saving any other setting silently clobbers the
        // stored scanner/tuner preference.
        this.editSettings.scanner_device = settings.devices.scanner_device || 'none';
        this.editSettings.tuner_device = settings.devices.tuner_device || 'none';
      }
      if (settings.scanner) {
        this.editSettings.squelch_offset = settings.scanner.squelch_offset ?? 10;
        this.editSettings.min_signal_strength = settings.scanner.min_signal_strength ?? -50;
        this.editSettings.dwell_time_ms = settings.scanner.dwell_time_ms ?? 50;
        this.editSettings.fft_size = settings.scanner.fft_size ?? 1024;
        this.editSettings.scan_profiles = [...(settings.scanner.scan_profiles || [])];
        this.availableScanProfiles = settings.scanner.available_scan_profiles || [];
        this.editSettings.scan_ranges = (settings.scanner.sweep_ranges || []).map(r => ({
          label: r.label || '',
          start_mhz: r.start_mhz,
          end_mhz: r.end_mhz,
          step_khz: r.step_khz ?? 200,
          priority: r.priority ?? 10,
        }));
        this.scannerStatus.scan_ranges = settings.scanner.resolved_sweep_ranges || this.editSettings.scan_ranges;
        this.scannerStatus.scan_profiles = this.editSettings.scan_profiles;
        this.scannerStatus.squelch_offset = this.editSettings.squelch_offset;
        this.scannerStatus.fft_size = this.editSettings.fft_size;
        this.scannerStatus.dwell_time_ms = this.editSettings.dwell_time_ms;
        if (settings.scanner.audio_mode) {
          this.audioMode = settings.scanner.audio_mode;
        }
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
      if (settings.ui && Array.isArray(settings.ui.live_visible_cols)) {
        this.liveVisibleCols = [...settings.ui.live_visible_cols];
      }
    },

    async fetchSettings(refreshDevices = false) {
      const suffix = refreshDevices ? '?refresh_devices=true' : '';
      const settings = await this.apiFetch(`/api/settings${suffix}`, { _silent: true });
      if (settings) this.applySettings(settings);
      return settings;
    },

    async fetchStatus() {
      const status = await this.apiFetch('/api/scanner/status', { _silent: true });
      if (status) {
        this.scannerStatus = { ...this.scannerStatus, ...status };
        this.scanning = status.status === 'running';
      }
    },

    get liveCurrentRange() {
      return this.scannerStatus.current_range || null;
    },

    formatRangeSummary(range) {
      if (!range) return 'Waiting for scan progress';
      const label = range.label || `${(range.start_hz / 1e6).toFixed(3)}-${(range.end_hz / 1e6).toFixed(3)} MHz`;
      const stepPart = range.step_index && range.step_count ? ` ${range.step_index}/${range.step_count}` : '';
      const freqPart = range.frequency_mhz ? ` @ ${range.frequency_mhz.toFixed(3)} MHz` : '';
      return `${label}${stepPart}${freqPart}`;
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
        await this.fetchSettings(true);
        await this.fetchStatus();
      }
    },

    async saveAudioMode() {
      const resp = await this.apiFetch('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ audio_mode: this.audioMode }),
      });
      if (resp) {
        const labels = { auto: 'Automatic', gqrx: 'Local gqrx', pcm_stream: 'Browser stream' };
        this.showToast(`Audio mode: ${labels[this.audioMode] || this.audioMode}`, 'success');
      }
    },

    _clientLooksLocal() {
      // Best-effort: if the browser is accessing via a LAN-ish hostname,
      // we're probably not a remote client and don't need the banner.
      const host = window.location.hostname;
      if (host === 'localhost' || host === '127.0.0.1' || host === '::1') return true;
      // IPv4 private ranges
      if (/^10\./.test(host)) return true;
      if (/^192\.168\./.test(host)) return true;
      if (/^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(host)) return true;
      // Tailscale CGNAT
      if (/^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\./.test(host)) return true;
      return false;
    },

    addScanRange() {
      this.editSettings.scan_ranges.push({ label: '', start_mhz: 0, end_mhz: 0, step_khz: 200, priority: 10 });
    },

    addDefaultRange(preset) {
      const exists = this.editSettings.scan_ranges.some(r =>
        r.start_mhz === preset.start_mhz && r.end_mhz === preset.end_mhz
      );
      if (!exists) {
        this.editSettings.scan_ranges.push({ ...preset });
      } else {
        this.showToast(`${preset.label} range already added`, 'warning');
      }
    },

    addAllDefaults() {
      let added = 0;
      this.defaultScanRanges.forEach(preset => {
        const exists = this.editSettings.scan_ranges.some(r =>
          r.start_mhz === preset.start_mhz && r.end_mhz === preset.end_mhz
        );
        if (!exists) {
          this.editSettings.scan_ranges.push({ ...preset });
          added++;
        }
      });
      this.showToast(added ? `Added ${added} range(s)` : 'All defaults already present', added ? 'success' : 'warning');
    },

    removeScanRange(index) {
      this.editSettings.scan_ranges.splice(index, 1);
    },

    toggleScanProfile(profileKey) {
      if (this.editSettings.scan_profiles.includes(profileKey)) {
        this.editSettings.scan_profiles = this.editSettings.scan_profiles.filter(p => p !== profileKey);
      } else {
        this.editSettings.scan_profiles.push(profileKey);
      }
    },

    async fetchStatusPage() {
      try {
        const data = await this.apiFetch('/api/status', { _silent: true });
        if (data) {
          this.statusData = data;
          if (data.audio) {
            this.audioStatus = data.audio;
          }
        }
      } catch (e) { /* status page is non-critical */ }
      // Refresh live telemetry on every poll, but do NOT re-fetch settings
      // here — applySettings clobbers editSettings, which would stomp on
      // the user's in-progress dropdown/field edits on the Settings page.
      // Settings are fetched explicitly on page navigation (fetchPageData's
      // 'settings' case calls fetchSettings(true)) and after an explicit
      // save (saveSettings → fetchSettings(true)).
      await Promise.all([this.fetchStatus(), this.fetchProcessStatus()]);
    },

    // --- Process lifecycle ---

    async fetchProcessStatus() {
      try {
        const data = await this.apiFetch('/api/process/status', { _silent: true });
        if (data) {
          this.processStatus = data;
          this.processConnected = true;
          this.processConsecutiveFailures = 0;
          // Detect a completed restart: PID changed while we were waiting.
          if (this.processRestartInFlight
              && this.processRestartPrevPid
              && data.pid
              && data.pid !== this.processRestartPrevPid) {
            this.processRestartInFlight = false;
            this.processRestartPrevPid = null;
            this.processActionBusy = false;
            this.processActionMessage = `Restarted (new pid ${data.pid}).`;
            this.showToast('SignalDeck restarted.', 'success');
          }
          return data;
        }
        // apiFetch returning null counts as a transient failure during a
        // restart window, but not otherwise.
        this.processConsecutiveFailures += 1;
      } catch (e) {
        this.processConsecutiveFailures += 1;
      }
      if (this.processConsecutiveFailures >= 2 && !this.processRestartInFlight) {
        this.processConnected = false;
      }
      return null;
    },

    processStateLabel() {
      if (this.processRestartInFlight) return 'Restarting…';
      if (!this.processConnected) return 'Disconnected';
      return 'Running';
    },

    processStateBadgeClass() {
      if (this.processRestartInFlight) return 'badge-orange';
      if (!this.processConnected) return 'badge-red';
      return 'badge-green';
    },

    formatUptime(seconds) {
      if (seconds == null) return '--';
      const s = Math.floor(seconds);
      const d = Math.floor(s / 86400);
      const h = Math.floor((s % 86400) / 3600);
      const m = Math.floor((s % 3600) / 60);
      const ss = s % 60;
      if (d > 0) return `${d}d ${h}h ${m}m`;
      if (h > 0) return `${h}h ${m}m`;
      if (m > 0) return `${m}m ${ss}s`;
      return `${ss}s`;
    },

    confirmProcessAction(verb) {
      const pretty = verb.charAt(0).toUpperCase() + verb.slice(1);
      if (!window.confirm(`${pretty} SignalDeck service?`)) return;
      this.processAction(verb);
    },

    async processAction(verb) {
      if (this.processActionBusy) return;
      this.processActionBusy = true;
      this.processActionMessage = `${verb === 'restart' ? 'Restarting' : verb === 'stop' ? 'Stopping' : 'Starting'}…`;
      if (verb === 'restart') {
        this.processRestartInFlight = true;
        this.processRestartPrevPid = this.processStatus.pid;
      }
      try {
        // Stop/restart may kill the response before it lands; treat a
        // network failure the same as a 202.
        const resp = await this.apiFetch(`/api/process/${verb}`, {
          method: 'POST',
          body: JSON.stringify({}),
          _silent: true,
        }).catch(() => null);
        if (verb === 'stop' && resp !== null) {
          this.processActionMessage = 'Stop requested.';
        }
      } finally {
        if (verb === 'restart') {
          // Poll until the process comes back with a new PID. Give up
          // after ~30s and show a clear message.
          const deadline = Date.now() + 30000;
          const tick = async () => {
            if (Date.now() > deadline) {
              this.processRestartInFlight = false;
              this.processActionBusy = false;
              this.processActionMessage = 'Restart timed out waiting for the service to come back.';
              return;
            }
            await this.fetchProcessStatus();
            if (this.processRestartInFlight) {
              setTimeout(tick, 1000);
            }
          };
          setTimeout(tick, 1500);
        } else if (verb === 'stop') {
          // After stop, the next poll will fail — flip to disconnected
          // without counting it as an error.
          setTimeout(() => {
            this.processConnected = false;
            this.processActionBusy = false;
          }, 1500);
        } else {
          // start: just refresh status shortly.
          setTimeout(() => {
            this.fetchProcessStatus();
            this.processActionBusy = false;
          }, 1000);
        }
      }
    },

    async fetchAnalytics() {
      const data = await this.apiFetch('/api/analytics/summary', { _silent: true });
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
      const data = await this.apiFetch('/api/logs', { _silent: true });
      if (data) this.logFiles = data;
    },

    async fetchCurrentLog() {
      const data = await this.apiFetch('/api/logs/current', { _silent: true });
      if (data) this.currentLog = data;
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
          if (resp.first_run_password) {
            this.firstRunPassword = resp.first_run_password;
            this.firstRunAcknowledged = false;
          }
          this.fetchSettings(false);
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

    async fetchSessions() {
      const data = await this.apiFetch('/api/auth/sessions');
      if (data) this.sessions = Array.isArray(data) ? data : [];
    },

    async renameSession(id, newLabel) {
      if (!newLabel) return;
      const ok = await this.apiFetch(`/api/auth/sessions/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ label: newLabel }),
      });
      if (ok) {
        this.showToast('Renamed', 'success');
        this.fetchSessions();
      }
    },

    async revokeSession(id) {
      if (!confirm('Revoke this device? It will need to sign in again.')) return;
      let resp;
      try {
        resp = await fetch(`/api/auth/sessions/${id}`, {
          method: 'DELETE',
          credentials: 'same-origin',
        });
      } catch (e) {
        this.showToast('Revoke failed — network error', 'error');
        return;
      }
      if (resp.status === 200) {
        this.showToast('Revoked', 'success');
        this.fetchSessions();
      } else if (resp.status === 401) {
        this.loginRequired = true;
      } else if (resp.status === 404) {
        // Already gone — refresh to drop the stale row
        this.showToast('Session already removed', 'info');
        this.fetchSessions();
      } else {
        this.showToast(`Revoke failed (${resp.status})`, 'error');
      }
    },

    promptRenameSession(session) {
      const newLabel = prompt('New label for this device:', session.label || '');
      if (newLabel != null && newLabel.trim()) {
        this.renameSession(session.id, newLabel.trim());
      }
    },

    async clearData(target) {
      if (!confirm(`Clear ${target}? This cannot be undone.`)) return;
      try {
        const data = await this.apiFetch(`/api/data/${target}`, { method: 'DELETE' });
        if (data) {
          if (target === 'signals') {
            this.liveSignals = [];
            this.signalEnrichment = {};
          }
          this.showToast(`${target} cleared`, 'success');
        }
      } catch (e) {
        this.showToast(`Failed to clear ${target}`, 'error');
      }
    },

    async clearLiveSignals() {
      if (!confirm('Clear signals from the live dashboard and database?')) return;
      const ok = await this.apiFetch('/api/data/signals', { method: 'DELETE' });
      if (ok) {
        this.liveSignals = [];
        this.signalEnrichment = {};
        this.showToast('Live signals cleared', 'success');
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
        frequency_hz: this.newBookmark.frequency * 1e6, // MHz to Hz
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
        if (this.liveFilterSignalClass && (s.signal_class || '') !== this.liveFilterSignalClass) return false;
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
          signal_class: sig.signal_class || enrich.signal_class || null,
          content_confidence: sig.content_confidence ?? enrich.content_confidence ?? 0,
          decoder: activity.decoder || null,
          activity_type: activity.type || null,
          activity_summary: activity.summary || null,
          rds: sig.rds || enrich.rds || null,
        };
      });
    },

    get sortedLiveSignals() {
      const key = this.liveSortKey;
      const asc = this.liveSortAsc;
      return [...this.enrichedLiveSignals].sort((a, b) => {
        let va = a[key], vb = b[key];
        if (key === 'hits') { va = a._hits || 1; vb = b._hits || 1; }
        if (key === 'last_seen') { va = a._updated || 0; vb = b._updated || 0; }
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
      this._queueSaveColumns();
    },

    _saveColsTimer: null,

    _queueSaveColumns() {
      if (this._saveColsTimer) clearTimeout(this._saveColsTimer);
      this._saveColsTimer = setTimeout(() => {
        this.apiFetch('/api/settings', {
          method: 'PUT',
          body: JSON.stringify({
            ui: { live_visible_cols: this.liveVisibleCols },
          }),
        });
      }, 500);
    },

    clearLiveFilters() {
      this.liveFilterMod = '';
      this.liveFilterProto = '';
      this.liveFilterSignalClass = '';
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

    get liveSignalClasses() {
      const classes = new Set();
      for (const s of this.liveSignals) {
        const freqKey = String(Math.round(s.frequency || 0));
        const enrich = this.signalEnrichment[freqKey] || {};
        const signalClass = s.signal_class || enrich.signal_class;
        if (signalClass) classes.add(signalClass);
      }
      return [...classes].sort();
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

    tuneAndListen(freqHz, modulation) {
      this.audioFreqMhz = freqHz / 1e6;
      this._tuneModulation = modulation || null;
      this.startAudio();
    },

    // Find the bookmark (if any) matching a given frequency within a
    // ~2.5 kHz tolerance — tight enough to keep adjacent channels
    // (12.5/25/100 kHz spacings) distinct, wide enough to absorb
    // per-sweep center drift. Returns the bookmark object or null.
    findBookmarkForFrequency(freqHz) {
      if (!freqHz || !this.bookmarks || !this.bookmarks.length) return null;
      for (const bm of this.bookmarks) {
        if (Math.abs((bm.frequency_hz || 0) - freqHz) < 2500) return bm;
      }
      return null;
    },

    // Thin wrapper kept for existing callers. New code should prefer
    // findBookmarkForFrequency so it can use the returned object.
    isBookmarked(freqHz) {
      return !!this.findBookmarkForFrequency(freqHz);
    },

    async quickBookmark(sig) {
      if (this.isBookmarked(sig.frequency)) {
        this.showToast('Already bookmarked', 'info');
        return;
      }
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

    // --- Bookmark edit/create modal methods ---

    openEditBookmark(bookmark) {
      // Clone so in-modal edits don't mutate the list until save
      this.editingBookmark = { ...bookmark };
      this.editModalMode = 'edit';
      this.editModalSignal = null;
      this.editModalError = '';
    },

    openCreateBookmarkFromSignal(sig) {
      // Dedupe — if already bookmarked, open Edit mode on the existing row
      const existing = this.findBookmarkForFrequency(sig.frequency);
      if (existing) {
        this.openEditBookmark(existing);
        return;
      }
      this.editingBookmark = {
        id: null,
        frequency_hz: sig.frequency,
        label: (sig.protocol || sig.modulation || 'Signal') + ' ' + this.formatFreq(sig.frequency),
        modulation: sig.modulation || 'FM',
        decoder: sig.protocol || null,
        priority: 3,
        camp_on_active: false,
        notes: '',
      };
      this.editModalMode = 'create';
      this.editModalSignal = sig;
      this.editModalError = '';
    },

    openNewBookmark() {
      this.editingBookmark = {
        id: null,
        frequency_hz: null,
        label: '',
        modulation: 'FM',
        decoder: null,
        priority: 3,
        camp_on_active: false,
        notes: '',
      };
      this.editModalMode = 'create';
      this.editModalSignal = null;
      this.editModalError = '';
    },

    async saveBookmarkEdit() {
      if (!this.editingBookmark) return;
      if (this.savingBookmark) return;  // prevent double-click duplicate submits
      const bm = this.editingBookmark;

      // Client-side validation
      if (!bm.label || !bm.label.trim()) {
        this.editModalError = 'Label is required';
        return;
      }
      if (this.editModalMode === 'create' && (!bm.frequency_hz || bm.frequency_hz <= 0)) {
        this.editModalError = 'Frequency is required';
        return;
      }

      const payload = {
        label: bm.label.trim(),
        modulation: bm.modulation || null,
        decoder: bm.decoder || null,
        priority: bm.priority || 3,
        camp_on_active: !!bm.camp_on_active,
        notes: bm.notes || '',
      };

      this.savingBookmark = true;
      try {
        let result;
        if (this.editModalMode === 'edit') {
          result = await this.apiFetch(`/api/bookmarks/${bm.id}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
          });
        } else {
          payload.frequency_hz = bm.frequency_hz;
          result = await this.apiFetch('/api/bookmarks', {
            method: 'POST',
            body: JSON.stringify(payload),
          });
        }

        if (result) {
          this.showToast(
            this.editModalMode === 'edit' ? 'Bookmark updated' : 'Bookmarked ' + this.formatFreq(bm.frequency_hz),
            'success',
          );
          this.editingBookmark = null;
          this.fetchBookmarks();
        }
      } finally {
        this.savingBookmark = false;
      }
    },

    cancelBookmarkEdit() {
      this.editingBookmark = null;
      this.editModalError = '';
      this.savingBookmark = false;
    },

    isGqrxBackend() {
      // Return true when gqrx is the ACTIVE audio source (playing on server speakers).
      // We read audioStatus.effective_mode, which comes from /api/status.audio and
      // respects both the configured scanner.audio_mode setting and the current
      // set of /ws/audio subscribers.
      //
      // Note: this used to read scannerStatus.backend, which returned true whenever
      // gqrx was merely CONFIGURED — even when audio_mode is pcm_stream. That caused
      // the frontend to skip PCM wiring (VU meter, volume, "Listening" badge) and
      // show a misleading "audio plays through gqrx" toast. See spec doc 2026-04-10.
      return this.audioStatus && this.audioStatus.effective_mode === 'gqrx';
    },

    startAudio() {
      if (!this.audioFreqMhz) {
        this.showToast('Enter a frequency first', 'error');
        return;
      }
      if (this.audioPlayer) {
        // Always subscribe via WebSocket — this tells the backend to tune
        this.audioPlayer.subscribe(this.audioFreqMhz * 1e6, this._tuneModulation, this.audioVolume);
        this._tuneModulation = null;
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
      if (this.audioPlayer) {
        this.audioPlayer.setVolume(this.audioVolume);
        // In gqrx mode, send volume to backend
        if (this.isGqrxBackend() && this.audioPlayer.ws && this.audioPlayer.ws.readyState === WebSocket.OPEN) {
          this.audioPlayer.ws.send(JSON.stringify({ type: 'volume', level: this.audioVolume }));
        }
      }
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
      // Deduplicate: if this exact message is already showing, skip it
      if (this.toasts.some(t => t.message === message && t.visible)) return;
      // Cap visible toasts to prevent flood
      while (this.toasts.length >= 3) {
        this.toasts.shift();
      }
      const id = ++this.toastCounter;
      this.toasts.push({ id, message, type, visible: true });
      // Errors stay 6s, everything else 3s
      const delay = type === 'error' ? 6000 : 3000;
      setTimeout(() => this.dismissToast(id), delay);
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
