# CTFA Air Quality & Relay Controller System

A production-grade environmental telemetry dashboard, priority relay controller, and simulation engine designed for indoor air quality and motorized damper ventilation management (CTFA).

Built with **Python (Flask)**, pure **HTML5/CSS3/Vanilla JavaScript**, and fully decoupled architecture supporting both **Interactive Simulation** and **Live Production Hardware Deployments**.

---

## 📋 Control Logic Priority Rules

The core business logic is implemented in [`relay_class.py`](relay_class.py) inside `RelayManager.evaluate_and_control(...)`:

| Priority | Rule Name | Condition | Relay State | Behavior & Precedence |
| :--- | :--- | :--- | :--- | :--- |
| **Priority 1 (Dominating)** | **Condensation / Dew Point Lockout** | `Outdoor Dew Point >= (Indoor Temp - Safety Buffer)` | **OFF** (`False`) | **Strict Override**: Prevents bringing outdoor moisture that would condense on cold AC vents/surfaces. Calculated as `outdoorTemp - ((100 - outdoorHumidity) / 5) >= (indoorTemp - safetyBuffer)`. Completely suppresses all ventilation purges regardless of PM2.5 or CO2 levels. |
| **Priority 2 (Purge)** | **PM2.5 / CO2 Purge** | Safe dew point **AND** (`Indoor PM2.5 > 60` **OR** `Indoor CO2 > 800`) | **ON** (`True`) | **Ventilation Purge**: Activates motorized damper / fan when either particulate pollution crosses **60 µg/m³** or CO2 crosses **800 PPM** (provided Priority 1 is satisfied). |
| **Priority 3 (Fallback)** | **Normal Air Quality** | Safe dew point **AND** both sensors within safe thresholds | **OFF** (`False`) | **Closed / Normal**: Turns off ventilation / closes damper when indoor air is within safe thresholds (`PM2.5 <= 60` and `CO2 <= 800`). |

---

## 🏗 System Architecture

```
                                  +-----------------------+
                                  |  Web Browser Client   |
                                  | (HTML / CSS / JS SPA) |
                                  +-----------+-----------+
                                              |
                   [Simulation Mode]          |          [Live Production Mode]
            POST /api/simulate (Drawer)       |          GET /api/telemetry (Polling)
                                              v
                              +-------------------------------+
                              |    Flask Application (app.py) |
                              |  - Ingest: /api/telemetry/ingest
                              |  - Telemetry State Store      |
                              +---------------+---------------+
                                              |
                                              v
                              +-------------------------------+
                              | RelayManager (relay_class.py) |
                              |  - Priority 1: Lockout Rule   |
                              |  - Priority 2: Purge Rule     |
                              |  - Priority 3: Fallback Rule  |
                              +---------------+---------------+
                                              |
                        +---------------------+---------------------+
                        |                                           |
                        v                                           v
             [Live Hardware Mode]                            [Mock Mode]
        POST $RELAY_API_URL                                In-Memory State
        {"mac": "004B12302844", "on": true/false}       Zero-Network Lag
```

---

## 👨‍💻 Senior Developer API Integration Guide

This application is architected with a **dual-mode design**:
1. **Simulation Mode (Active by Default)**: Allows interactive testing, presets, slider manipulation, and algorithm verification without requiring physical sensors or real hardware connected.
2. **Production Live Mode**: Directly connects to physical IoT sensors, building management systems (BMS), and motorized relay actuators.

### 1. Ingesting Live Sensor Data (`POST /api/telemetry/ingest`)

When deploying with physical sensors (e.g. ESP32, Raspberry Pi, LoRaWAN gateways, BACnet/Modbus gateways), configure your edge devices to send HTTP POST requests to `/api/telemetry/ingest`:

```bash
curl -X POST http://localhost:5000/api/telemetry/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "outdoor_temp": 32.0,
    "outdoor_humidity": 80.0,
    "indoor_temp": 24.0,
    "safety_buffer": 2.0,
    "indoor_pm25": 72.0,
    "indoor_co2": 650.0,
    "indoor_humidity": 55.0,
    "outdoor_pm25": 28.0,
    "outdoor_co2": 420.0,
    "mac_address": "004B12302844"
  }'
```

#### Ingestion Behavior:
- Automatically updates in-memory telemetry state and calculation metrics (dew point, surface threshold).
- Runs the 3-priority evaluation engine (`relay_class.py`).
- Immediately sends the hardware control signal to the motorized damper relay.
- Appends to the historical reporting log for audit trails and CSV export.

---

### 2. Switching Dashboard from Simulation to Live Telemetry

To transition the frontend UI from simulator polling to live production telemetry:

1. Open [`static/js/dashboard.js`](static/js/dashboard.js).
2. Set `USE_SIMULATOR_SOURCE = false` in `INTEGRATION_CONFIG`:

```javascript
const INTEGRATION_CONFIG = {
  // Set to FALSE for production deployment with real hardware sensors
  // Set to TRUE to keep the interactive simulator active
  USE_SIMULATOR_SOURCE: false,

  // Polling interval in milliseconds for live sensor telemetry
  LIVE_POLL_INTERVAL_MS: 3000,
  
  // Custom API Base URL if backend is hosted on a separate domain or gateway
  API_BASE_URL: ""
};
```

When `USE_SIMULATOR_SOURCE` is `false`, the dashboard automatically polls `GET /api/telemetry` every 3 seconds to fetch genuine sensor readings, while still allowing manual emergency override through the fan status card.

---

### 3. Configuring Physical Relay Actuator Endpoints (PoC & Long-Run)

The relay controller communicates with the physical damper actuator over HTTP REST events (`/api/events`). Configure the target device via environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `RELAY_API_URL` | `http://178.16.137.20:3101/api/events` | Target actuator event endpoint receiving relay ON/OFF signals |
| `RELAY_MAC` | `004B12302844` | Default MAC identifier of the hardware relay |
| `RELAY_AUTH_TOKEN` | *None* | Optional Bearer authorization token sent in headers |
| `RELAY_API_KEY` | *None* | Optional API Key sent in `X-API-Key` header |
| `MOCK_MODE` | `False` | Set `True` to force mock execution without network calls |

> [!NOTE]
> For this PoC and for long-term operations, relay actuation is directly managed via `http://178.16.137.20:3101/api/events` with payload `{"mac": "004B12302844", "on": true/false}`.

#### Alternative Protocols (MQTT, Modbus, GPIO):
In [`relay_class.py`](relay_class.py), the `__call_device(payload)` method serves as the hardware dispatch adapter:
- **MQTT**: Replace `requests.post()` with `mqtt_client.publish(f"devices/{self.mac_address}/relay/set", payload)`.
- **Modbus**: Call `client.write_coil(address=0x0001, value=payload["on"], slave=1)`.
- **Direct GPIO**: Call `damper_relay.on()` / `damper_relay.off()` via `gpiozero`.

---

### 4. Setting Up Client Authentication (Frontend)

If your production gateway requires JWT or API Key authentication, configure [`static/js/api.js`](static/js/api.js):

```javascript
// Example in your application bootstrap or login routine:
api.setAuthToken("your_production_jwt_token_here");
// Or:
api.setApiKey("your_production_api_key_here");
```

All subsequent fetch calls will include `Authorization: Bearer <token>` and `X-API-Key: <key>`.

---

## 🔌 API Endpoints Reference

All API routes return and accept standard `application/json`:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the main Single Page Application dashboard |
| `GET` | `/api/telemetry` | Retrieves the latest 6-sensor snapshot, relay state, and decision trace |
| `POST` | `/api/telemetry/ingest` | **Production Ingest**: Pushes live readings from physical sensors/gateways and triggers relay |
| `POST` | `/api/simulate` | **Simulation Engine**: Evaluates scenario inputs and updates state |
| `POST` | `/api/manual` | Direct manual override command (`state: true/false`, `force: true`) |
| `GET` | `/api/presets` | Returns predefined environmental scenarios (Purge, Lockout, Normal) |
| `GET` | `/api/alarms` | Returns configurable alarm thresholds and active states |
| `POST` | `/api/alarms` | Toggles alarm alert state by `id` |
| `GET` | `/api/reports` | Returns recent historical telemetry logs (with CSV download option on UI) |
| `GET` | `/api/health` | Health check endpoint reporting device MAC, current state, and relay URL |

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.10+ installed

### 2. Setup Virtual Environment & Install Dependencies
```bash
python -m venv venv
.\venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On Linux/macOS

pip install -r requirements.txt
```

### 3. Run the Server
```bash
python app.py
```
Open `http://localhost:5000` in your web browser.

---

## 🧪 Automated Testing

A dedicated test suite is included in [`test_suite.py`](test_suite.py) testing all priority rules, edge cases, boundaries, state caching, live ingestion, and API endpoints.

To run tests:
```bash
python -m unittest test_suite.py -v
```

Expected output:
```
test_api_alarms (test_suite.TestFlaskAPIs.test_api_alarms) ... ok
test_api_health (test_suite.TestFlaskAPIs.test_api_health) ... ok
test_api_manual_override (test_suite.TestFlaskAPIs.test_api_manual_override) ... ok
test_api_presets (test_suite.TestFlaskAPIs.test_api_presets) ... ok
test_api_reports (test_suite.TestFlaskAPIs.test_api_reports) ... ok
test_api_simulate_lockout (test_suite.TestFlaskAPIs.test_api_simulate_lockout) ... ok
test_api_simulate_purge (test_suite.TestFlaskAPIs.test_api_simulate_purge) ... ok
test_api_telemetry (test_suite.TestFlaskAPIs.test_api_telemetry) ... ok
test_api_telemetry_ingest (test_suite.TestFlaskAPIs.test_api_telemetry_ingest) ... ok
test_index_page (test_suite.TestFlaskAPIs.test_index_page) ... ok
test_boundary_conditions (test_suite.TestRelayManagerLogic.test_boundary_conditions) ... ok
test_manual_override_methods (test_suite.TestRelayManagerLogic.test_manual_override_methods) ... ok
test_priority_1_condensation_lockout_dominates_all (test_suite.TestRelayManagerLogic.test_priority_1_condensation_lockout_dominates_all) ... ok
test_priority_2_both_pm25_and_co2_high (test_suite.TestRelayManagerLogic.test_priority_2_both_pm25_and_co2_high) ... ok
test_priority_2_co2_purge (test_suite.TestRelayManagerLogic.test_priority_2_co2_purge) ... ok
test_priority_2_pm25_purge (test_suite.TestRelayManagerLogic.test_priority_2_pm25_purge) ... ok
test_priority_3_normal_air_quality_fallback (test_suite.TestRelayManagerLogic.test_priority_3_normal_air_quality_fallback) ... ok
test_redundant_call_suppression (test_suite.TestRelayManagerLogic.test_redundant_call_suppression) ... ok

----------------------------------------------------------------------
Ran 18 tests in 0.063s

OK
```

---

## 💻 Frontend UI Details

- **Responsive Design**: Adapts cleanly from full desktop screens down to mobile viewports with an off-canvas drawer navigation.
- **Fixed-Axis Rotating Fan**: Orthogonal 4-blade SVG fan with CSS rotation centered on `50% 50%` (`will-change: transform`) that spins when the relay is ON and stops cleanly when the relay is OFF.
- **5 Complete Views**:
  1. **Dashboard**: Live CTFA State banner, 6 sensor cards, fan status controller card.
  2. **Trends**: Multi-metric smooth SVG curves for hourly, daily, and monthly telemetry.
  3. **Alarms**: Alert notifications and configurable threshold toggles.
  4. **Reports**: Historical log table with live pagination and CSV export.
  5. **Settings**: Alert preferences, user profile, and theme options.
- **Slide-Over Simulator Drawer**: Access via `🧪 Simulator Controls` in the sidebar or header to test live sensor adjustments, presets, and observe instant UI & hardware reaction.
