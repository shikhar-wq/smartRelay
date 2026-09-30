import datetime
import json
import os
import threading
import time
import requests
from flask import Flask, jsonify, render_template, request, Response
from relay_class import RelayManager

"""
===============================================================================
CTFA Air Quality & Relay Controller System - Backend API
===============================================================================

ARCHITECTURE & API INTEGRATION OVERVIEW:
-------------------------------------------------------------------------------
This Flask application serves two primary roles:
  1. API & Telemetry Gateway: Provides RESTful endpoints for telemetry, manual
     control, alarms, and historical reporting.
  2. Simulation & Priority Rule Engine: Evaluates psychrometric dew point
     condensation risk and air quality purge triggers (PM2.5 > 60, CO2 > 800)
     via `RelayManager` in `relay_class.py`.

HOW TO INTEGRATE PHYSICAL SENSORS IN PRODUCTION:
-------------------------------------------------------------------------------
1. Ingestion Endpoint:
   Use `POST /api/telemetry/ingest` (documented below) to push live sensor
   readings from hardware edge devices (e.g. ESP32, Raspberry Pi, BMS gateway).
   The backend will evaluate priority rules and trigger the physical relay.

2. Polling Endpoint:
   The web dashboard polls `GET /api/telemetry` to display live conditions.

3. Database Persistence:
   The current implementation uses `telemetry_state` (in-memory) and
   `HISTORICAL_LOGS` (in-memory circular buffer). For production, swap these
   hooks with your Time-Series DB (InfluxDB, TimescaleDB, PostgreSQL).

4. Environment Variables:
   - PORT: HTTP server port (default: 5000)
   - RELAY_API_URL: Physical relay event endpoint (default: http://178.16.137.20:3101/api/events)
   - RELAY_MAC: Physical hardware MAC address (default: 004B12302844)
===============================================================================
"""

app = Flask(__name__)

# Default to Live Hardware Mode so physical signals are dispatched
DEFAULT_MAC = os.environ.get("RELAY_MAC", "004B12302844")
# PoC & Long-Run Event Actuation Endpoint
RELAY_API_URL = os.environ.get("RELAY_API_URL", "http://178.16.137.20:3101/api/events")
RELAY_EVENTS_URL = os.environ.get("RELAY_EVENTS_URL", "http://178.16.137.20:3101/api/events")

relay_manager = RelayManager(mac_address=DEFAULT_MAC, mock_mode=False)
relay_manager.relay_url = RELAY_API_URL
relay_manager.events_url = RELAY_EVENTS_URL

# In-memory telemetry state (initialized to values matching UI design)
# SENIOR NOTE: In production, back this state with Redis, PostgreSQL, or an MQTT cache.
telemetry_state = {
    "mac_address": DEFAULT_MAC,
    "indoor_pm25": 42.0,
    "outdoor_pm25": 28.0,
    "indoor_co2": 650.0,
    "outdoor_co2": 420.0,
    "indoor_temp": 24.0,
    "outdoor_temp": 28.0,
    "safety_buffer": 2.0,
    "indoor_humidity": 55.0,
    "outdoor_humidity": 45.0,
    "indoor_dew_point": 15.0,
    "outdoor_dew_point": 17.0,
    "indoor_condensation_threshold": 22.0,
    "fan_status": False,
    "mode": "Automatic",
    "last_updated": datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
    "is_connected": False,
    "system_status": "Disconnected",
    "device_online": False,
    "events_url": RELAY_EVENTS_URL,
    "state_key": "normal",
    "state_title": "Normal Air Quality - CTFA Off",
    "state_desc": "All environmental readings within acceptable thresholds",
    "decision_trace": [],
    "last_api_result": None,
    "evaluation_interval_sec": 30,
}


def sync_device_status_from_events():
    """
    Background worker that listens to the live hardware SSE event stream at
    http://178.16.137.20:3101/api/events and updates telemetry_state['is_connected']
    and telemetry_state['system_status'] to 'Connected' or 'Disconnected'.
    """
    while True:
        try:
            # 1. Immediate snapshot via /api/state
            state_url = RELAY_EVENTS_URL.replace("/api/events", "/api/state")
            try:
                snap_resp = requests.get(state_url, timeout=4)
                if snap_resp.ok:
                    data = snap_resp.json()
                    devices = data.get("devices", [])
                    dev = next((d for d in devices if d.get("mac") == DEFAULT_MAC), None) or (devices[0] if devices else None)
                    if dev:
                        online = bool(dev.get("online", False))
                        telemetry_state["is_connected"] = online
                        telemetry_state["system_status"] = "Connected" if online else "Disconnected"
                        telemetry_state["device_online"] = online
                        telemetry_state["device_info"] = dev
            except Exception:
                pass

            # 2. Live SSE stream from /api/events
            with requests.get(RELAY_EVENTS_URL, stream=True, timeout=30) as resp:
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data:"):
                            try:
                                payload = json.loads(decoded[5:].strip())
                                devices = payload.get("devices", [])
                                dev = next((d for d in devices if d.get("mac") == DEFAULT_MAC), None) or (devices[0] if devices else None)
                                if dev:
                                    online = bool(dev.get("online", False))
                                    telemetry_state["is_connected"] = online
                                    telemetry_state["system_status"] = "Connected" if online else "Disconnected"
                                    telemetry_state["device_online"] = online
                                    telemetry_state["device_info"] = dev
                            except Exception:
                                pass
        except Exception:
            time.sleep(3)


# Start background SSE sync thread
threading.Thread(target=sync_device_status_from_events, daemon=True).start()

PRESETS = [
    {
        "id": "purge_pm25",
        "title": "PM 2.5 Purge (CTFA ON)",
        "subtitle": "Indoor PM2.5 > 60 µg/m³ & Safe Dew Point",
        "description": "Indoor PM 2.5 (75 µg/m³) > 60 threshold with safe outdoor dew point (17.0°C < 22.0°C). Fan turns ON.",
        "indoor_temp": 24.0,
        "outdoor_temp": 28.0,
        "safety_buffer": 2.0,
        "indoor_humidity": 55.0,
        "outdoor_humidity": 45.0,
        "indoor_pm25": 75.0,
        "outdoor_pm25": 28.0,
        "indoor_co2": 650.0,
        "outdoor_co2": 420.0,
        "indoor_dew_point": 15.0,
        "outdoor_dew_point": 17.0,
    },
    {
        "id": "purge_co2",
        "title": "CO2 Purge (CTFA ON)",
        "subtitle": "Indoor CO2 > 800 PPM & Safe Dew Point",
        "description": "Indoor CO2 (920 PPM) > 800 threshold with safe outdoor dew point. Fan turns ON.",
        "indoor_temp": 24.0,
        "outdoor_temp": 27.0,
        "safety_buffer": 2.0,
        "indoor_humidity": 55.0,
        "outdoor_humidity": 40.0,
        "indoor_pm25": 35.0,
        "outdoor_pm25": 25.0,
        "indoor_co2": 920.0,
        "outdoor_co2": 420.0,
        "indoor_dew_point": 15.0,
        "outdoor_dew_point": 15.0,
    },
    {
        "id": "lockout_humidity",
        "title": "DewPoint Lockout (CTFA OFF)",
        "subtitle": "Outdoor Dew Point >= Cold Surface Threshold",
        "description": "Outdoor Dew Point (28.0°C) >= Surface Threshold (22.0°C). Condensation hazard: relay locked OFF, fan stops.",
        "indoor_temp": 24.0,
        "outdoor_temp": 32.0,
        "safety_buffer": 2.0,
        "indoor_humidity": 50.0,
        "outdoor_humidity": 80.0,
        "indoor_pm25": 95.0,
        "outdoor_pm25": 30.0,
        "indoor_co2": 950.0,
        "outdoor_co2": 430.0,
        "indoor_dew_point": 14.0,
        "outdoor_dew_point": 28.0,
    },
    {
        "id": "normal_close",
        "title": "Normal Air Quality (CTFA OFF)",
        "subtitle": "All sensors within safe thresholds",
        "description": "No alerts or purges triggered (PM2.5 <= 60, CO2 <= 800). Relay closed, fan stops.",
        "indoor_temp": 24.0,
        "outdoor_temp": 26.0,
        "safety_buffer": 2.0,
        "indoor_humidity": 55.0,
        "outdoor_humidity": 35.0,
        "indoor_pm25": 25.0,
        "outdoor_pm25": 20.0,
        "indoor_co2": 520.0,
        "outdoor_co2": 410.0,
        "indoor_dew_point": 15.0,
        "outdoor_dew_point": 13.0,
    },
]

# Historical logs for the Reports table
HISTORICAL_LOGS = [
    {"id": 1, "timestamp": "10:24:00 AM", "in_pm25": 42, "out_pm25": 28, "in_co2": 650, "out_co2": 420, "in_dew": 15.0, "out_dew": 17.0, "status": "OFF"},
    {"id": 2, "timestamp": "10:14:00 AM", "in_pm25": 41, "out_pm25": 29, "in_co2": 648, "out_co2": 422, "in_dew": 14.9, "out_dew": 16.9, "status": "OFF"},
    {"id": 3, "timestamp": "10:04:00 AM", "in_pm25": 43, "out_pm25": 30, "in_co2": 655, "out_co2": 421, "in_dew": 15.1, "out_dew": 17.1, "status": "OFF"},
    {"id": 4, "timestamp": "09:54:00 AM", "in_pm25": 72, "out_pm25": 27, "in_co2": 660, "out_co2": 418, "in_dew": 15.0, "out_dew": 17.2, "status": "ON"},
    {"id": 5, "timestamp": "09:44:00 AM", "in_pm25": 40, "out_pm25": 28, "in_co2": 642, "out_co2": 420, "in_dew": 14.8, "out_dew": 17.0, "status": "OFF"},
    {"id": 6, "timestamp": "09:34:00 AM", "in_pm25": 39, "out_pm25": 26, "in_co2": 630, "out_co2": 415, "in_dew": 14.7, "out_dew": 16.8, "status": "OFF"},
    {"id": 7, "timestamp": "09:24:00 AM", "in_pm25": 38, "out_pm25": 25, "in_co2": 625, "out_co2": 412, "in_dew": 14.5, "out_dew": 16.7, "status": "OFF"},
    {"id": 8, "timestamp": "09:14:00 AM", "in_pm25": 37, "out_pm25": 24, "in_co2": 610, "out_co2": 410, "in_dew": 14.4, "out_dew": 16.5, "status": "OFF"},
    {"id": 9, "timestamp": "09:04:00 AM", "in_pm25": 35, "out_pm25": 24, "in_co2": 598, "out_co2": 408, "in_dew": 14.3, "out_dew": 16.4, "status": "OFF"},
    {"id": 10, "timestamp": "08:54:00 AM", "in_pm25": 34, "out_pm25": 23, "in_co2": 590, "out_co2": 405, "in_dew": 14.2, "out_dew": 16.2, "status": "OFF"},
]

ALARMS_CONFIG = [
    {"id": 1, "name": "Indoor PM 2.5", "condition": "Above 60 µg/m³", "active": True, "type": "warning"},
    {"id": 2, "name": "Outdoor PM 2.5", "condition": "Above 150 µg/m³", "active": False, "type": "info"},
    {"id": 3, "name": "Indoor CO2", "condition": "Above 800 PPM", "active": True, "type": "danger"},
    {"id": 4, "name": "Outdoor CO2", "condition": "Above 450 PPM", "active": False, "type": "info"},
    {"id": 5, "name": "Indoor Dew Point", "condition": "Above 18.0 °C", "active": True, "type": "warning"},
]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">⚡</text></svg>'
    return Response(svg, mimetype="image/svg+xml")


@app.route("/api/telemetry", methods=["GET"])
def get_telemetry():
    """Returns the current telemetry snapshot for the dashboard."""
    return jsonify({
        "success": True,
        "telemetry": telemetry_state,
    })


@app.route("/api/presets", methods=["GET"])
def get_presets():
    return jsonify({"presets": PRESETS})


@app.route("/api/alarms", methods=["GET", "POST"])
def alarms_endpoint():
    if request.method == "POST":
        data = request.get_json() or {}
        alarm_id = data.get("id")
        for a in ALARMS_CONFIG:
            if a["id"] == alarm_id:
                a["active"] = not a["active"]
                return jsonify({"success": True, "alarms": ALARMS_CONFIG})
        return jsonify({"success": False, "error": "Alarm not found"}), 404
    return jsonify({"success": True, "alarms": ALARMS_CONFIG})


@app.route("/api/reports", methods=["GET"])
def get_reports():
    return jsonify({"success": True, "logs": HISTORICAL_LOGS})


@app.route("/api/simulate", methods=["POST"])
def simulate():
    """
    Simulates environmental changes, executes RelayManager rules,
    dispatches live or mock signals, and synchronizes the global telemetry state.
    """
    try:
        data = request.get_json() or {}

        indoor_humidity = float(data.get("indoor_humidity", telemetry_state["indoor_humidity"]))
        outdoor_humidity = float(data.get("outdoor_humidity", telemetry_state["outdoor_humidity"]))
        indoor_pm25 = float(data.get("indoor_pm25", telemetry_state["indoor_pm25"]))
        outdoor_pm25 = float(data.get("outdoor_pm25", telemetry_state["outdoor_pm25"]))
        indoor_co2 = float(data.get("indoor_co2", telemetry_state["indoor_co2"]))
        outdoor_co2 = float(data.get("outdoor_co2", telemetry_state["outdoor_co2"]))

        indoor_temp = float(data.get("indoor_temp", telemetry_state.get("indoor_temp", 24.0)))
        outdoor_temp = float(data.get("outdoor_temp", telemetry_state.get("outdoor_temp", 32.0)))
        safety_buffer = float(data.get("safety_buffer", telemetry_state.get("safety_buffer", 2.0)))

        mac_address = str(data.get("mac_address", DEFAULT_MAC)).strip() or DEFAULT_MAC
        mock_mode = bool(data.get("mock_mode", False))
        force = bool(data.get("force", True))

        # Reconfigure manager
        relay_manager.mac_address = mac_address
        relay_manager.mock_mode = mock_mode

        eval_result = relay_manager.evaluate_and_control(
            indoor_humidity=indoor_humidity,
            outdoor_humidity=outdoor_humidity,
            indoor_pm25=indoor_pm25,
            indoor_co2=indoor_co2,
            indoor_temp=indoor_temp,
            outdoor_temp=outdoor_temp,
            safety_buffer=safety_buffer,
            mock_mode=mock_mode,
            force=force,
        )

        target_state = eval_result["target_state"]
        priority_hit = eval_result["priority_hit"]
        calc_inputs = eval_result.get("inputs", {})

        outdoor_dew_point = calc_inputs.get("outdoor_dew_point", 17.0)
        indoor_dew_point = calc_inputs.get("indoor_dew_point", 15.0)
        indoor_condensation_threshold = calc_inputs.get("indoor_condensation_threshold", 22.0)

        # Determine visual state category for UI Banner
        if priority_hit == 1:
            state_key = "lockout"
            state_title = "DewPoint Lockout - CTFA Off"
            state_desc = (
                f"Outdoor Dew Point ({outdoor_dew_point}°C) >= "
                f"Indoor Surface Threshold ({indoor_condensation_threshold}°C) [Room {indoor_temp}°C - Buffer {safety_buffer}°C]"
            )
        elif priority_hit == 2:
            if indoor_pm25 > relay_manager.PM25_THRESHOLD:
                state_key = "purge_pm25"
                state_title = "PM 2.5 Purge - CTFA ON"
                state_desc = f"Indoor PM 2.5 ({indoor_pm25} µg/m³) is higher than threshold ({relay_manager.PM25_THRESHOLD} µg/m³)"
            else:
                state_key = "purge_co2"
                state_title = "CO2 Purge - CTFA ON"
                state_desc = f"Indoor CO2 ({indoor_co2} PPM) is greater than {relay_manager.CO2_THRESHOLD} PPM"
        else:
            state_key = "normal"
            state_title = "Normal Air Quality - CTFA Off"
            state_desc = "All environmental readings within acceptable thresholds"

        # Update global telemetry store
        now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
        telemetry_state.update({
            "mac_address": mac_address,
            "indoor_humidity": indoor_humidity,
            "outdoor_humidity": outdoor_humidity,
            "indoor_pm25": indoor_pm25,
            "outdoor_pm25": outdoor_pm25,
            "indoor_co2": indoor_co2,
            "outdoor_co2": outdoor_co2,
            "indoor_temp": indoor_temp,
            "outdoor_temp": outdoor_temp,
            "safety_buffer": safety_buffer,
            "indoor_dew_point": indoor_dew_point,
            "outdoor_dew_point": outdoor_dew_point,
            "indoor_condensation_threshold": indoor_condensation_threshold,
            "fan_status": bool(target_state),
            "last_updated": now_str,
            "state_key": state_key,
            "state_title": state_title,
            "state_desc": state_desc,
            "decision_trace": eval_result.get("decision_trace", []),
            "last_api_result": eval_result.get("api_result"),
        })

        # Append to historical logs
        HISTORICAL_LOGS.insert(0, {
            "id": len(HISTORICAL_LOGS) + 1,
            "timestamp": datetime.datetime.now().strftime("%I:%M:%S %p"),
            "in_pm25": indoor_pm25,
            "out_pm25": outdoor_pm25,
            "in_co2": indoor_co2,
            "out_co2": outdoor_co2,
            "in_dew": indoor_dew_point,
            "out_dew": outdoor_dew_point,
            "status": "ON" if target_state else "OFF",
        })
        if len(HISTORICAL_LOGS) > 30:
            HISTORICAL_LOGS.pop()

        return jsonify({
            "success": True,
            "telemetry": telemetry_state,
            "eval_result": eval_result,
        })

    except (ValueError, TypeError) as err:
        return jsonify({"success": False, "error": f"Invalid parameter: {err}"}), 400
    except Exception as err:
        return jsonify({"success": False, "error": str(err)}), 500


@app.route("/api/manual", methods=["POST"])
def manual_control():
    try:
        data = request.get_json() or {}
        state = bool(data.get("state", False))
        mac_address = str(data.get("mac_address", DEFAULT_MAC)).strip() or DEFAULT_MAC
        mock_mode = bool(data.get("mock_mode", False))

        relay_manager.mac_address = mac_address
        relay_manager.mock_mode = mock_mode

        res = relay_manager.turn_on(reason="Manual UI Override", mock_mode=mock_mode, force=True) if state else \
              relay_manager.turn_off(reason="Manual UI Override", mock_mode=mock_mode, force=True)

        telemetry_state["fan_status"] = state
        telemetry_state["state_title"] = f"Manual Override - CTFA {'ON' if state else 'OFF'}"
        telemetry_state["state_desc"] = f"Fan manually commanded {'ON' if state else 'OFF'} by operator"
        telemetry_state["state_key"] = "purge_pm25" if state else "normal"
        telemetry_state["last_updated"] = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
        telemetry_state["last_api_result"] = res

        return jsonify({
            "success": True,
            "telemetry": telemetry_state,
            "api_result": res,
        })
    except Exception as err:
        return jsonify({"success": False, "error": str(err)}), 500


# =============================================================================
# SENIOR INTEGRATION HOOK: DIRECT HARDWARE / BMS / IOT TELEMETRY INGESTION
# =============================================================================
@app.route("/api/telemetry/ingest", methods=["POST"])
def ingest_telemetry():
    """
    PRODUCTION SENSOR INGESTION ENDPOINT
    ---------------------------------------------------------------------------
    Use this endpoint for real hardware deployments where sensors or an IoT gateway
    (e.g., ESP32, Raspberry Pi, BMS edge device) push live sensor readings.

    Expected JSON Payload:
    {
        "outdoor_temp": 32.0,        // Celsius
        "outdoor_humidity": 80.0,    // % Relative Humidity
        "indoor_temp": 24.0,         // Celsius
        "safety_buffer": 2.0,        // Celsius (optional, default 2.0)
        "indoor_pm25": 45.0,         // µg/m³
        "indoor_co2": 650.0,         // PPM
        "indoor_humidity": 55.0,     // % Relative Humidity (optional)
        "outdoor_pm25": 28.0,        // µg/m³ (optional)
        "outdoor_co2": 420.0,        // PPM (optional)
        "mac_address": "004B12302844"// Hardware MAC (optional)
    }

    Behavior:
    1. Updates live in-memory telemetry state.
    2. Automatically evaluates priority rules (DewPoint Lockout -> Purge -> Normal).
    3. Dispatches the live physical relay control signal to the motorized damper.
    4. Appends to historical reporting logs.
    """
    try:
        data = request.get_json() or {}
        if not data:
            return jsonify({"success": False, "error": "Missing JSON request body"}), 400

        # Required physical sensor readings
        outdoor_temp = float(data.get("outdoor_temp", telemetry_state.get("outdoor_temp", 28.0)))
        outdoor_humidity = float(data.get("outdoor_humidity", telemetry_state.get("outdoor_humidity", 45.0)))
        indoor_temp = float(data.get("indoor_temp", telemetry_state.get("indoor_temp", 24.0)))
        safety_buffer = float(data.get("safety_buffer", telemetry_state.get("safety_buffer", 2.0)))

        # Optional pollutants (default to last known reading)
        indoor_pm25 = float(data.get("indoor_pm25", telemetry_state["indoor_pm25"]))
        indoor_co2 = float(data.get("indoor_co2", telemetry_state["indoor_co2"]))
        indoor_humidity = float(data.get("indoor_humidity", telemetry_state["indoor_humidity"]))
        outdoor_pm25 = float(data.get("outdoor_pm25", telemetry_state["outdoor_pm25"]))
        outdoor_co2 = float(data.get("outdoor_co2", telemetry_state["outdoor_co2"]))

        mac_address = str(data.get("mac_address", DEFAULT_MAC)).strip() or DEFAULT_MAC
        relay_manager.mac_address = mac_address
        relay_manager.mock_mode = False  # Production mode: dispatch live physical signal

        eval_result = relay_manager.evaluate_and_control(
            outdoor_temp=outdoor_temp,
            outdoor_humidity=outdoor_humidity,
            indoor_temp=indoor_temp,
            safety_buffer=safety_buffer,
            indoor_pm25=indoor_pm25,
            indoor_co2=indoor_co2,
            indoor_humidity=indoor_humidity,
            mock_mode=False,
            force=False,
        )

        target_state = eval_result["target_state"]
        priority_hit = eval_result["priority_hit"]
        calc_inputs = eval_result.get("inputs", {})

        outdoor_dew_point = calc_inputs.get("outdoor_dew_point", 17.0)
        indoor_dew_point = calc_inputs.get("indoor_dew_point", 15.0)
        indoor_condensation_threshold = calc_inputs.get("indoor_condensation_threshold", 22.0)

        if priority_hit == 1:
            state_key = "lockout"
            state_title = "DewPoint Lockout - CTFA Off"
            state_desc = (
                f"Outdoor Dew Point ({outdoor_dew_point}°C) >= "
                f"Indoor Surface Threshold ({indoor_condensation_threshold}°C)"
            )
        elif priority_hit == 2:
            if indoor_pm25 > relay_manager.PM25_THRESHOLD:
                state_key = "purge_pm25"
                state_title = "PM 2.5 Purge - CTFA ON"
                state_desc = f"Indoor PM 2.5 ({indoor_pm25} µg/m³) is higher than threshold ({relay_manager.PM25_THRESHOLD} µg/m³)"
            else:
                state_key = "purge_co2"
                state_title = "CO2 Purge - CTFA ON"
                state_desc = f"Indoor CO2 ({indoor_co2} PPM) is greater than {relay_manager.CO2_THRESHOLD} PPM"
        else:
            state_key = "normal"
            state_title = "Normal Air Quality - CTFA Off"
            state_desc = "All environmental readings within acceptable thresholds"

        now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
        telemetry_state.update({
            "mac_address": mac_address,
            "outdoor_temp": outdoor_temp,
            "outdoor_humidity": outdoor_humidity,
            "indoor_temp": indoor_temp,
            "safety_buffer": safety_buffer,
            "indoor_pm25": indoor_pm25,
            "outdoor_pm25": outdoor_pm25,
            "indoor_co2": indoor_co2,
            "outdoor_co2": outdoor_co2,
            "indoor_humidity": indoor_humidity,
            "outdoor_dew_point": outdoor_dew_point,
            "indoor_dew_point": indoor_dew_point,
            "indoor_condensation_threshold": indoor_condensation_threshold,
            "fan_status": bool(target_state),
            "last_updated": now_str,
            "state_key": state_key,
            "state_title": state_title,
            "state_desc": state_desc,
            "decision_trace": eval_result.get("decision_trace", []),
            "last_api_result": eval_result.get("api_result"),
        })

        return jsonify({
            "success": True,
            "message": "Telemetry ingested and relay evaluated successfully",
            "telemetry": telemetry_state,
            "eval_result": eval_result,
        })

    except (ValueError, TypeError) as err:
        return jsonify({"success": False, "error": f"Invalid sensor data type: {err}"}), 400
    except Exception as err:
        return jsonify({"success": False, "error": str(err)}), 500


# =============================================================================
# LIVE HARDWARE EVENT STREAM PROXY & CONNECTION STATUS ENDPOINTS
# =============================================================================
@app.route("/api/events")
def stream_hardware_events():
    """
    Streams live hardware Server-Sent Events from http://178.16.137.20:3101/api/events
    to frontend clients with CORS enabled, allowing web browsers to monitor device
    Connected / Disconnected state in real time without CORS blocks.
    """
    def generate():
        current_data = {
            "mac": DEFAULT_MAC,
            "online": telemetry_state.get("is_connected", False),
            "system_status": telemetry_state.get("system_status", "Disconnected"),
            "devices": [telemetry_state.get("device_info", {"mac": DEFAULT_MAC, "online": telemetry_state.get("is_connected", False), "type": "ESP32"})]
        }
        yield f"event: state\ndata: {json.dumps(current_data)}\n\n"

        while True:
            try:
                with requests.get(RELAY_EVENTS_URL, stream=True, timeout=20) as resp:
                    for line in resp.iter_lines():
                        if line:
                            yield f"{line.decode('utf-8')}\n"
                        else:
                            yield "\n"
            except Exception:
                time.sleep(3)
                yield ": ping\n\n"

    res = Response(generate(), mimetype="text/event-stream")
    res.headers["Cache-Control"] = "no-cache"
    res.headers["X-Accel-Buffering"] = "no"
    res.headers["Access-Control-Allow-Origin"] = "*"
    return res


@app.route("/api/device/state", methods=["GET"])
def device_state():
    return jsonify({
        "success": True,
        "is_connected": telemetry_state.get("is_connected", False),
        "system_status": telemetry_state.get("system_status", "Disconnected"),
        "events_url": RELAY_EVENTS_URL,
        "device": telemetry_state.get("device_info", {}),
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "mac_address": relay_manager.mac_address,
        "current_state": relay_manager.current_state,
        "mock_mode": relay_manager.mock_mode,
        "relay_url": relay_manager.relay_url,
        "events_url": getattr(relay_manager, "events_url", "http://178.16.137.20:3101/api/events"),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    print(f"CTFA Server running on http://0.0.0.0:{port} (Relay: {relay_manager.relay_url})")
    app.run(host="0.0.0.0", port=port, debug=debug)
