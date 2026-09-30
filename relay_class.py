"""
=============================================================================
CTFA RELAY CONTROLLER & HARDWARE ACTUATOR MANAGER (relay_class.py)
=============================================================================
Architecture Overview:
-----------------------------------------------------------------------------
This module is the core decision engine and physical hardware bridge.
It calculates psychrometric dew point, compares it against surface condensation
thresholds, evaluates indoor pollutant thresholds (PM2.5 and CO2), and drives
the motorized damper relay.

Hardware Driver Integration (PoC & Long-Run Event Gateway):
1. REST / HTTP Actuator Events API (Active PoC & Production):
   - Out-of-the-box, sends HTTP POST to `RELAY_API_URL` (default: `http://178.16.137.20:3101/api/events`)
     with JSON payload `{"mac": "...", "on": bool}`.
   - Designed for the PoC and retained for long-run operations as the primary event bus.
   - Fully supports redundant call suppression (skips network roundtrips if relay is already in desired state).

2. MQTT Broker Integration:
   - For deployments using an MQTT broker (e.g. Mosquitto, AWS IoT Core, EMQX, Shelly/Tasmota):
     Replace or augment `__call_device()` to publish to topic `devices/{mac}/relay/set`
     with payload `{"state": "ON"|"OFF"}`.

3. Modbus TCP / RTU or BACnet (BMS):
   - For commercial HVAC / BMS integration:
     Interface with `pymodbus` to write coil `0x0001` or BACnet IP `Binary Output` (BO-1).

4. Direct GPIO on Single Board Computers (Raspberry Pi, industrial SBCs):
   - Can drive digital pins via `gpiozero.OutputDevice` or `RPi.GPIO` directly.
=============================================================================
"""

import json
import os
import requests


class RelayManager:
    CO2_THRESHOLD = 800
    PM25_THRESHOLD = 60
    DEFAULT_SAFETY_BUFFER = 2.0

    def __init__(self, mac_address="004B12302844", mock_mode=False, relay_url=None):
        self.mac_address = mac_address
        self.mock_mode = mock_mode
        self.current_state = None  # None = unknown, True = ON, False = OFF
        # Target hardware actuator endpoint:
        # Note: http://178.16.137.20:3101/api/relay receives POST control commands {"mac": "...", "on": bool}.
        # http://178.16.137.20:3101/api/events is the Server-Sent Events (SSE) live status stream.
        self.relay_url = relay_url or os.environ.get("RELAY_API_URL", "http://178.16.137.20:3101/api/relay")
        self.events_url = os.environ.get("RELAY_EVENTS_URL", "http://178.16.137.20:3101/api/events")

    @staticmethod
    def calculate_dew_point(temp_c, humidity_percent):
        """Calculates dew point using the Quick C method: temp - ((100 - humidity) / 5)"""
        return round(float(temp_c) - ((100.0 - float(humidity_percent)) / 5.0), 2)

    def evaluate_and_control(
        self,
        indoor_humidity=55.0,
        outdoor_humidity=45.0,
        indoor_pm25=42.0,
        indoor_co2=650.0,
        outdoor_temp=32.0,
        indoor_temp=24.0,
        safety_buffer=2.0,
        mock_mode=None,
        force=False,
        **kwargs,
    ):
        """
        Controls the relay based on psychrometric condensation risk and air quality priorities:

        Priority 1 (Dominating / Condensation Lockout):
            outdoorDewPoint >= indoorCondensationThreshold (indoorTemp - safetyBuffer)
                -> Relay OFF strictly (Close Damper / Lockout fresh air)

        Priority 2 (Purge Triggers):
            Safe dew point AND (Indoor PM2.5 > 60 OR Indoor CO2 > 800)
                -> Relay ON (Open Damper / PM2.5 or CO2 Purge)

        Priority 3 (Default Fallback):
            Safe dew point AND neither trigger met
                -> Relay OFF strictly (Normal Air Quality - Closed)
        """
        effective_mock = self.mock_mode if mock_mode is None else mock_mode

        # Allow kwargs override for temperatures if passed
        out_temp = float(kwargs.get("outdoor_temp", outdoor_temp))
        in_temp = float(kwargs.get("indoor_temp", indoor_temp))
        buffer_val = float(kwargs.get("safety_buffer", safety_buffer))
        out_hum = float(outdoor_humidity)
        in_hum = float(indoor_humidity)
        in_pm25 = float(indoor_pm25)
        in_co2 = float(indoor_co2)

        # 1. Calculate outdoor dew point (Quick C method)
        outdoor_dew_point = self.calculate_dew_point(out_temp, out_hum)

        # Calculate indoor dew point for telemetry
        indoor_dew_point = self.calculate_dew_point(in_temp, in_hum)

        # 2. Calculate the condensation risk threshold
        indoor_condensation_threshold = round(in_temp - buffer_val, 2)

        # 3. Priority Conditions
        is_lockout = outdoor_dew_point >= indoor_condensation_threshold
        is_pm25_high = in_pm25 > self.PM25_THRESHOLD
        is_co2_high = in_co2 > self.CO2_THRESHOLD
        is_purge = is_pm25_high or is_co2_high

        decision_trace = []
        target_state = False
        decision_reason = ""
        priority_hit = 3

        # Rule 1 Evaluation: Condensation / Dew Point Lockout
        trace_rule_1 = {
            "priority": 1,
            "name": "Condensation / Dew Point Lockout (Dominating)",
            "condition": (
                f"Outdoor Dew Point ({outdoor_dew_point}°C) >= "
                f"Indoor Threshold ({indoor_condensation_threshold}°C) [Room {in_temp}°C - Buffer {buffer_val}°C]"
            ),
            "met": bool(is_lockout),
            "status": "TRIGGERED (OVERRIDE)" if is_lockout else "PASSED",
            "action": "Relay OFF (Close Damper / Lockout)" if is_lockout else "Continue to Priority 2",
        }
        decision_trace.append(trace_rule_1)

        if is_lockout:
            priority_hit = 1
            target_state = False
            decision_reason = (
                f"DewPoint Lockout (Outdoor Dew Point {outdoor_dew_point}°C >= "
                f"Condensation Threshold {indoor_condensation_threshold}°C)"
            )

            trace_rule_2 = {
                "priority": 2,
                "name": "PM2.5 / CO2 Purge",
                "condition": f"Indoor PM2.5 ({in_pm25}) > {self.PM25_THRESHOLD} OR Indoor CO2 ({in_co2}) > {self.CO2_THRESHOLD}",
                "met": bool(is_purge),
                "status": "SUPPRESSED BY PRIORITY 1 LOCKOUT" if is_purge else "SKIPPED",
                "action": "Suppressed",
            }
            trace_rule_3 = {
                "priority": 3,
                "name": "Normal Quality Fallback",
                "condition": "No triggers met",
                "met": False,
                "status": "SKIPPED",
                "action": "Skipped",
            }
            decision_trace.extend([trace_rule_2, trace_rule_3])

        elif is_purge:
            priority_hit = 2
            target_state = True
            reasons = []
            if is_pm25_high:
                reasons.append(f"PM2.5 Purge ({in_pm25} > {self.PM25_THRESHOLD})")
            if is_co2_high:
                reasons.append(f"CO2 Purge ({in_co2} > {self.CO2_THRESHOLD})")
            decision_reason = " & ".join(reasons)

            trace_rule_2 = {
                "priority": 2,
                "name": "PM2.5 / CO2 Purge",
                "condition": f"Indoor PM2.5 ({in_pm25}) > {self.PM25_THRESHOLD} OR Indoor CO2 ({in_co2}) > {self.CO2_THRESHOLD}",
                "met": True,
                "status": "TRIGGERED",
                "action": "Relay ON (Open Damper / Fan Purge)",
            }
            trace_rule_3 = {
                "priority": 3,
                "name": "Normal Quality Fallback",
                "condition": "No triggers met",
                "met": False,
                "status": "SKIPPED",
                "action": "Skipped",
            }
            decision_trace.extend([trace_rule_2, trace_rule_3])

        else:
            priority_hit = 3
            target_state = False
            decision_reason = "Normal Air Quality - Closed (Default OFF)"

            trace_rule_2 = {
                "priority": 2,
                "name": "PM2.5 / CO2 Purge",
                "condition": f"Indoor PM2.5 ({in_pm25}) > {self.PM25_THRESHOLD} OR Indoor CO2 ({in_co2}) > {self.CO2_THRESHOLD}",
                "met": False,
                "status": "NOT MET",
                "action": "Continue to Priority 3",
            }
            trace_rule_3 = {
                "priority": 3,
                "name": "Normal Quality Fallback",
                "condition": "No triggers met",
                "met": True,
                "status": "TRIGGERED (DEFAULT)",
                "action": "Relay OFF (Damper Closed)",
            }
            decision_trace.extend([trace_rule_2, trace_rule_3])

        # Execute relay state change
        api_result = self._set_relay(
            state=target_state,
            reason=decision_reason,
            mock_mode=effective_mock,
            force=force,
        )

        return {
            "mac_address": self.mac_address,
            "mock_mode": effective_mock,
            "target_state": target_state,
            "current_state": self.current_state,
            "priority_hit": priority_hit,
            "reason": decision_reason,
            "decision_trace": decision_trace,
            "api_result": api_result,
            "inputs": {
                "outdoor_temp": out_temp,
                "outdoor_humidity": out_hum,
                "indoor_temp": in_temp,
                "safety_buffer": buffer_val,
                "indoor_pm25": in_pm25,
                "indoor_co2": in_co2,
                "indoor_humidity": in_hum,
                "outdoor_dew_point": outdoor_dew_point,
                "indoor_dew_point": indoor_dew_point,
                "indoor_condensation_threshold": indoor_condensation_threshold,
            },
        }

    def turn_on(self, reason="Manual Override", mock_mode=None, force=True):
        return self._set_relay(True, reason, mock_mode=mock_mode, force=force)

    def turn_off(self, reason="Manual Override", mock_mode=None, force=True):
        return self._set_relay(False, reason, mock_mode=mock_mode, force=force)

    def _set_relay(self, state, reason, mock_mode=None, force=False):
        """
        Change relay state, supporting live device API calls and mock mode.
        If force=False and current_state == state, skips redundant API call.
        """
        effective_mock = self.mock_mode if mock_mode is None else mock_mode

        # If relay is already in the requested state and not forced, skip network call
        if self.current_state == state and not force:
            status_msg = f"Relay already {'ON' if state else 'OFF'} -> {reason} (Network call skipped)"
            print(f"[{self.mac_address}] {status_msg}")
            return {
                "success": True,
                "changed": False,
                "api_sent": False,
                "message": status_msg,
                "mock": effective_mock,
            }

        payload = {
            "mac": self.mac_address,
            "on": state,
        }

        if effective_mock:
            self.current_state = state
            status_msg = f"[MOCK] Relay set to {'ON' if state else 'OFF'} -> {reason}"
            print(f"[{self.mac_address}] {status_msg}")
            return {
                "success": True,
                "changed": True,
                "api_sent": False,
                "message": status_msg,
                "mock": True,
            }

        # Send live command to physical relay
        response = self.__call_device(payload)

        if response and response.ok:
            self.current_state = state
            try:
                resp_json = response.json()
            except Exception:
                resp_json = {"raw": response.text}

            status_msg = f"Live Signal Sent: Relay {'ON' if state else 'OFF'} -> {reason}"
            print(f"[{self.mac_address}] {status_msg} | Response: {response.text}")
            return {
                "success": True,
                "changed": True,
                "api_sent": True,
                "message": status_msg,
                "mock": False,
                "response_json": resp_json,
                "response_text": response.text,
            }

        err_msg = f"Live Relay API call failed or timed out for {self.relay_url}"
        print(f"[{self.mac_address}] {err_msg}")
        return {
            "success": False,
            "changed": False,
            "api_sent": True,
            "message": err_msg,
            "mock": False,
        }

    def __call_device(self, payload):
        """
        HARDWARE EVENT DISPATCH ADAPTER (PoC & Production)
        -----------------------------------------------------------------------
        Dispatches relay state changes to physical hardware over HTTP REST.
        - Actuator Command Endpoint: http://178.16.137.20:3101/api/relay (POST)
        - Live Event Stream:        http://178.16.137.20:3101/api/events (GET SSE)

        If relay_url points to /api/events (the SSE listener), the adapter
        automatically routes the command payload to the actuator command endpoint.
        """
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
        }
        # Optional Bearer Token or API Key from environment
        auth_token = os.environ.get("RELAY_AUTH_TOKEN")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        api_key = os.environ.get("RELAY_API_KEY")
        if api_key:
            headers["X-API-Key"] = api_key

        target_url = self.relay_url
        if target_url and target_url.rstrip("/").endswith("/api/events"):
            target_url = target_url.replace("/api/events", "/api/relay")

        try:
            print(f"[{self.mac_address}] POST -> {target_url} with payload={payload}")
            response = requests.post(
                target_url,
                headers=headers,
                json=payload,
                timeout=8,
            )

            # Fallback check if a custom /api/events URL returned 404
            if response.status_code == 404 and "/api/events" in self.relay_url:
                fallback_url = self.relay_url.replace("/api/events", "/api/relay")
                print(f"[{self.mac_address}] Retrying command via -> {fallback_url}")
                response = requests.post(
                    fallback_url,
                    headers=headers,
                    json=payload,
                    timeout=8,
                )

            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            print(f"[{self.mac_address}] Relay API error: {exc}")
            return None


if __name__ == "__main__":
    # Test live connection
    rm = RelayManager(mac_address="004B12302844", mock_mode=False)
    print("Testing live device signal...")
    res = rm.turn_on(reason="Live Test ON")
    print("Result:", res)