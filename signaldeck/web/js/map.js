/**
 * SignalDeck - Leaflet Map Integration
 *
 * Displays aircraft (ADS-B) and APRS station markers on an interactive map.
 */

class SignalMap {
  constructor(elementId) {
    this.elementId = elementId;
    this.markers = {};       // keyed by callsign/id
    this.markerGroup = null;
    this.map = null;

    this.initMap();
  }

  initMap() {
    const el = document.getElementById(this.elementId);
    if (!el || typeof L === 'undefined') return;

    // Prevent re-initialization
    if (this.map) {
      this.map.invalidateSize();
      return;
    }

    this.map = L.map(this.elementId, {
      center: [39.8, -98.5],   // US center
      zoom: 4,
      zoomControl: true,
      attributionControl: true,
    });

    // Dark-styled OpenStreetMap tiles
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(this.map);

    this.markerGroup = L.featureGroup().addTo(this.map);

    // Fix map rendering in hidden containers
    setTimeout(() => {
      if (this.map) this.map.invalidateSize();
    }, 100);
  }

  /**
   * Create an SVG aircraft icon.
   */
  aircraftIcon(heading) {
    const rotation = heading || 0;
    return L.divIcon({
      className: 'aircraft-marker',
      html: `<svg viewBox="0 0 24 24" width="24" height="24" style="transform:rotate(${rotation}deg)">
        <path d="M12 2L8 10h-5l2 3-2 3h5l4 8 4-8h5l-2-3 2-3h-5z" fill="#58a6ff" stroke="#0d1117" stroke-width="1"/>
      </svg>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
      popupAnchor: [0, -14],
    });
  }

  /**
   * Create an APRS station icon.
   */
  aprsIcon() {
    return L.divIcon({
      className: 'aprs-marker',
      html: `<svg viewBox="0 0 16 16" width="16" height="16">
        <circle cx="8" cy="8" r="6" fill="#3fb950" stroke="#0d1117" stroke-width="1.5" opacity="0.9"/>
        <circle cx="8" cy="8" r="2" fill="#0d1117"/>
      </svg>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      popupAnchor: [0, -10],
    });
  }

  /**
   * Add or update an aircraft marker.
   * @param {Object} data - { callsign, latitude, longitude, altitude, speed, heading }
   */
  addAircraft(data) {
    if (!this.map || !data.latitude || !data.longitude) return;

    const key = 'aircraft_' + (data.callsign || data.icao || `${data.latitude}_${data.longitude}`);

    const popup = `
      <div style="font-family:-apple-system,sans-serif;font-size:13px;min-width:140px;">
        <strong style="color:#58a6ff;">${data.callsign || 'Unknown'}</strong><br>
        ${data.icao ? `<span style="color:#8b949e;">ICAO: ${data.icao}</span><br>` : ''}
        ${data.altitude != null ? `Alt: ${data.altitude.toLocaleString()} ft<br>` : ''}
        ${data.speed != null ? `Speed: ${data.speed} kt<br>` : ''}
        ${data.heading != null ? `Heading: ${data.heading}&deg;<br>` : ''}
        ${data.squawk ? `Squawk: ${data.squawk}<br>` : ''}
      </div>
    `;

    if (this.markers[key]) {
      // Update existing marker
      this.markers[key].setLatLng([data.latitude, data.longitude]);
      this.markers[key].setIcon(this.aircraftIcon(data.heading));
      this.markers[key].setPopupContent(popup);
    } else {
      // Create new marker
      const marker = L.marker([data.latitude, data.longitude], {
        icon: this.aircraftIcon(data.heading),
      }).bindPopup(popup);

      marker.addTo(this.markerGroup);
      this.markers[key] = marker;
    }
  }

  /**
   * Add or update an APRS station marker.
   * @param {Object} data - { callsign, latitude, longitude, status, comment }
   */
  addAprs(data) {
    if (!this.map || !data.latitude || !data.longitude) return;

    const key = 'aprs_' + (data.callsign || `${data.latitude}_${data.longitude}`);

    const popup = `
      <div style="font-family:-apple-system,sans-serif;font-size:13px;min-width:120px;">
        <strong style="color:#3fb950;">${data.callsign || 'Unknown'}</strong><br>
        ${data.status ? `Status: ${data.status}<br>` : ''}
        ${data.comment ? `${data.comment}<br>` : ''}
        <span style="color:#8b949e;">${data.latitude.toFixed(4)}, ${data.longitude.toFixed(4)}</span>
      </div>
    `;

    if (this.markers[key]) {
      this.markers[key].setLatLng([data.latitude, data.longitude]);
      this.markers[key].setPopupContent(popup);
    } else {
      const marker = L.marker([data.latitude, data.longitude], {
        icon: this.aprsIcon(),
      }).bindPopup(popup);

      marker.addTo(this.markerGroup);
      this.markers[key] = marker;
    }
  }

  /**
   * Auto-fit map to show all markers.
   */
  fitBounds() {
    if (!this.map || !this.markerGroup) return;
    const bounds = this.markerGroup.getBounds();
    if (bounds.isValid()) {
      this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    }
  }

  /**
   * Remove all markers from the map.
   */
  clear() {
    if (this.markerGroup) {
      this.markerGroup.clearLayers();
    }
    this.markers = {};
  }
}
