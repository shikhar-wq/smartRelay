/**
 * ============================================================================
 * CTFA Air Quality Telemetry & Relay API Service
 * ============================================================================
 * 
 * INTEGRATION & DEPLOYMENT GUIDE:
 * ----------------------------------------------------------------------------
 * This service acts as the boundary between frontend UI and the backend/IoT layer.
 * 
 * 1. LOCAL FLASK RUNTIME:
 *    When served via Python Flask (app.py), all requests hit local endpoints:
 *    /api/telemetry, /api/simulate, /api/presets, /api/reports, /api/events.
 * 
 * 2. GITHUB PAGES (STATIC HOSTING):
 *    When hosted as a static site on GitHub Pages, built-in client fallbacks
 *    activate automatically so presets, calculations, and simulation controls
 *    continue working 100% in the user's browser without backend errors.
 * 
 * 3. REMOTE PRODUCTION BACKEND:
 *    To connect a GitHub Pages deployment to a live remote backend / gateway:
 *      window.apiService.setBaseUrl('https://api-iot.yourcompany.com');
 *      window.apiService.setAuthToken('YOUR_BEARER_TOKEN');
 * ============================================================================
 */

const DEFAULT_PRESETS = [
  {
    id: "purge_pm25",
    title: "PM 2.5 Purge (CTFA ON)",
    subtitle: "Indoor PM2.5 > 60 µg/m³ & Safe Dew Point",
    description: "Indoor PM 2.5 (75 µg/m³) > 60 threshold with safe outdoor dew point (17.0°C < 22.0°C). Fan turns ON.",
    indoor_temp: 24.0,
    outdoor_temp: 28.0,
    safety_buffer: 2.0,
    indoor_humidity: 55.0,
    outdoor_humidity: 45.0,
    indoor_pm25: 75.0,
    outdoor_pm25: 28.0,
    indoor_co2: 650.0,
    outdoor_co2: 420.0,
    indoor_dew_point: 15.0,
    outdoor_dew_point: 17.0,
  },
  {
    id: "purge_co2",
    title: "CO2 Purge (CTFA ON)",
    subtitle: "Indoor CO2 > 800 PPM & Safe Dew Point",
    description: "Indoor CO2 (920 PPM) > 800 threshold with safe outdoor dew point. Fan turns ON.",
    indoor_temp: 24.0,
    outdoor_temp: 27.0,
    safety_buffer: 2.0,
    indoor_humidity: 55.0,
    outdoor_humidity: 40.0,
    indoor_pm25: 35.0,
    outdoor_pm25: 25.0,
    indoor_co2: 920.0,
    outdoor_co2: 420.0,
    indoor_dew_point: 15.0,
    outdoor_dew_point: 15.0,
  },
  {
    id: "lockout_humidity",
    title: "DewPoint Lockout (CTFA OFF)",
    subtitle: "Outdoor Dew Point >= Cold Surface Threshold",
    description: "Outdoor Dew Point (28.0°C) >= Surface Threshold (22.0°C). Condensation hazard: relay locked OFF, fan stops.",
    indoor_temp: 24.0,
    outdoor_temp: 32.0,
    safety_buffer: 2.0,
    indoor_humidity: 50.0,
    outdoor_humidity: 80.0,
    indoor_pm25: 95.0,
    outdoor_pm25: 30.0,
    indoor_co2: 950.0,
    outdoor_co2: 430.0,
    indoor_dew_point: 14.0,
    outdoor_dew_point: 28.0,
  },
  {
    id: "normal_close",
    title: "Normal Air Quality (CTFA OFF)",
    subtitle: "All sensors within safe thresholds",
    description: "No alerts or purges triggered (PM2.5 <= 60, CO2 <= 800). Relay closed, fan stops.",
    indoor_temp: 24.0,
    outdoor_temp: 26.0,
    safety_buffer: 2.0,
    indoor_humidity: 55.0,
    outdoor_humidity: 35.0,
    indoor_pm25: 25.0,
    outdoor_pm25: 20.0,
    indoor_co2: 520.0,
    outdoor_co2: 410.0,
    indoor_dew_point: 15.0,
    outdoor_dew_point: 13.0,
  }
];

const DEFAULT_ALARMS = [
  { id: 1, name: "CO2 Critical Threshold", type: "Threshold Limit", trigger_val: "> 800 PPM", status: "Active", severity: "High" },
  { id: 2, name: "PM 2.5 Hazardous Inflow", type: "Threshold Limit", trigger_val: "> 60 µg/m³", status: "Active", severity: "Medium" },
  { id: 3, name: "Dew Point Condensation Risk", type: "Psychrometric Hazard", trigger_val: "Outdoor Dew >= Surface Temp", status: "Active", severity: "Critical" },
  { id: 4, name: "Gateway Network Timeout", type: "Device Connectivity", trigger_val: "No heartbeat > 60s", status: "Active", severity: "Low" },
];

const DEFAULT_REPORTS = [
  { id: 1, timestamp: "10:24:00 AM", in_pm25: 42, out_pm25: 28, in_co2: 650, out_co2: 420, in_dew: 15.0, out_dew: 17.0, status: "OFF" },
  { id: 2, timestamp: "10:14:00 AM", in_pm25: 41, out_pm25: 29, in_co2: 648, out_co2: 422, in_dew: 14.9, out_dew: 16.9, status: "OFF" },
  { id: 3, timestamp: "10:04:00 AM", in_pm25: 43, out_pm25: 30, in_co2: 655, out_co2: 421, in_dew: 15.1, out_dew: 17.1, status: "OFF" },
  { id: 4, timestamp: "09:54:00 AM", in_pm25: 72, out_pm25: 27, in_co2: 660, out_co2: 418, in_dew: 15.0, out_dew: 17.2, status: "ON" },
  { id: 5, timestamp: "09:44:00 AM", in_pm25: 40, out_pm25: 28, in_co2: 642, out_co2: 420, in_dew: 14.8, out_dew: 17.0, status: "OFF" },
  { id: 6, timestamp: "09:34:00 AM", in_pm25: 39, out_pm25: 26, in_co2: 630, out_co2: 415, in_dew: 14.7, out_dew: 16.8, status: "OFF" },
  { id: 7, timestamp: "09:24:00 AM", in_pm25: 38, out_pm25: 25, in_co2: 625, out_co2: 412, in_dew: 14.5, out_dew: 16.7, status: "OFF" },
  { id: 8, timestamp: "09:14:00 AM", in_pm25: 37, out_pm25: 24, in_co2: 610, out_co2: 410, in_dew: 14.4, out_dew: 16.5, status: "OFF" },
];

class CTFAApiService {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.authToken = null;
    this.apiKey = null;
  }

  setBaseUrl(url) {
    this.baseUrl = (url || '').replace(/\/+$/, '');
  }

  setAuthToken(token) {
    this.authToken = token;
  }

  setApiKey(key) {
    this.apiKey = key;
  }

  _getHeaders(contentType = 'application/json') {
    const headers = {};
    if (contentType) headers['Content-Type'] = contentType;
    if (this.authToken) headers['Authorization'] = `Bearer ${this.authToken}`;
    if (this.apiKey) headers['X-API-Key'] = this.apiKey;
    return headers;
  }

  async fetchTelemetry() {
    try {
      const res = await fetch(`${this.baseUrl}/api/telemetry`, {
        headers: this._getHeaders(null),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      return json.telemetry;
    } catch (err) {
      console.warn('[CTFA API] Failed to fetch telemetry from server:', err.message);
      return null;
    }
  }

  async simulate(payload) {
    try {
      const res = await fetch(`${this.baseUrl}/api/simulate`, {
        method: 'POST',
        headers: this._getHeaders('application/json'),
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      // Local fallback calculation for static hosting (GitHub Pages)
      console.info('[CTFA API] Calculating simulation locally in browser (static mode)');
      return {
        success: true,
        simulated_offline: true,
        telemetry: this._calculateLocalTelemetry(payload)
      };
    }
  }

  async manualOverride(state, macAddress = '004B12302844', mockMode = false) {
    try {
      const res = await fetch(`${this.baseUrl}/api/manual`, {
        method: 'POST',
        headers: this._getHeaders('application/json'),
        body: JSON.stringify({ state, mac_address: macAddress, mock_mode: mockMode })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      return {
        success: true,
        message: `Simulated manual ${state ? 'ON' : 'OFF'} in offline/static mode`,
        telemetry: { fan_status: state, last_updated: new Date().toLocaleTimeString() }
      };
    }
  }

  async fetchPresets() {
    try {
      const res = await fetch(`${this.baseUrl}/api/presets`, {
        headers: this._getHeaders(null),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      return json.presets || DEFAULT_PRESETS;
    } catch (err) {
      console.info('[CTFA API] Using client scenario presets (static mode)');
      return DEFAULT_PRESETS;
    }
  }

  async fetchAlarms() {
    try {
      const res = await fetch(`${this.baseUrl}/api/alarms`, {
        headers: this._getHeaders(null),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      return json.alarms || DEFAULT_ALARMS;
    } catch (err) {
      return DEFAULT_ALARMS;
    }
  }

  async toggleAlarm(id) {
    try {
      const res = await fetch(`${this.baseUrl}/api/alarms`, {
        method: 'POST',
        headers: this._getHeaders('application/json'),
        body: JSON.stringify({ id })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      return { success: true, id };
    }
  }

  async fetchReports() {
    try {
      const res = await fetch(`${this.baseUrl}/api/reports`, {
        headers: this._getHeaders(null),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      return json.logs || DEFAULT_REPORTS;
    } catch (err) {
      return DEFAULT_REPORTS;
    }
  }

  _calculateLocalTelemetry(payload) {
    const outdoorTemp = Number(payload.outdoor_temp ?? 28.0);
    const outdoorHum = Number(payload.outdoor_humidity ?? 45.0);
    const indoorTemp = Number(payload.indoor_temp ?? 24.0);
    const indoorHum = Number(payload.indoor_humidity ?? 55.0);
    const safetyBuffer = Number(payload.safety_buffer ?? 2.0);
    const indoorPm25 = Number(payload.indoor_pm25 ?? 42.0);
    const outdoorPm25 = Number(payload.outdoor_pm25 ?? 28.0);
    const indoorCo2 = Number(payload.indoor_co2 ?? 650.0);
    const outdoorCo2 = Number(payload.outdoor_co2 ?? 420.0);

    const outdoorDew = outdoorTemp - ((100.0 - outdoorHum) / 5.0);
    const indoorDew = indoorTemp - ((100.0 - indoorHum) / 5.0);
    const threshold = indoorTemp - safetyBuffer;

    let fanStatus = false;
    let stateKey = 'normal';
    let stateTitle = 'Normal Air Quality - CTFA Off';
    let stateDesc = 'All environmental readings within acceptable thresholds';

    if (outdoorDew >= threshold) {
      fanStatus = false;
      stateKey = 'lockout';
      stateTitle = 'DewPoint Lockout - CTFA Off';
      stateDesc = `Outdoor Dew Point (${outdoorDew.toFixed(1)}°C) >= Cold Surface Threshold (${threshold.toFixed(1)}°C)`;
    } else if (indoorPm25 > 60 || indoorCo2 > 800) {
      fanStatus = true;
      if (indoorPm25 > 60) {
        stateKey = 'purge_pm25';
        stateTitle = 'PM 2.5 Purge - CTFA ON';
        stateDesc = `Indoor PM 2.5 (${indoorPm25} µg/m³) is higher than 60 µg/m³ threshold`;
      } else {
        stateKey = 'purge_co2';
        stateTitle = 'CO2 Purge - CTFA ON';
        stateDesc = `Indoor CO2 (${indoorCo2} PPM) is greater than 800 PPM threshold`;
      }
    }

    return {
      indoor_pm25: indoorPm25,
      outdoor_pm25: outdoorPm25,
      indoor_co2: indoorCo2,
      outdoor_co2: outdoorCo2,
      indoor_temp: indoorTemp,
      outdoor_temp: outdoorTemp,
      indoor_humidity: indoorHum,
      outdoor_humidity: outdoorHum,
      safety_buffer: safetyBuffer,
      indoor_dew_point: indoorDew,
      outdoor_dew_point: outdoorDew,
      indoor_condensation_threshold: threshold,
      fan_status: fanStatus,
      state_key: stateKey,
      state_title: stateTitle,
      state_desc: stateDesc,
      last_updated: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      system_status: 'Disconnected',
      is_connected: false
    };
  }
}

// Global API service singleton available to dashboard controllers
window.apiService = new CTFAApiService();
