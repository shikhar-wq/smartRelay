import json
import requests


class RelayManager:
    """
    Standalone Relay Controller for CTFA Air Quality & Motorized Damper.
    Controls physical relay via HTTP REST using psychrometric condensation risk
    and air quality priority rules.
    """
    CO2_THRESHOLD = 800       # PPM: Ventilation purge triggered above this
    PM25_THRESHOLD = 60       # µg/m³: Ventilation purge triggered above this
    DEFAULT_SAFETY_BUFFER = 2.0  # °C: Accounts for cold AC vents/surfaces

    def __init__(self, mac_address="004B12302844", relay_url=None):
        self.mac_address = mac_address
        self.current_state = None  # None = unknown, True = ON, False = OFF

        # Actuator Command Endpoint (POST /api/relay)
        # Note: http://178.16.137.20:3101/api/events is the SSE stream; POST goes to /api/relay
        self.relay_url = relay_url or "http://178.16.137.20:3101/api/relay"

    @staticmethod
    def calculate_dew_point(temp_c, humidity_percent):
        """
        Calculates dew point using the Quick C method:
        DewPoint = Temp - ((100 - Humidity) / 5)
        """
        return round(float(temp_c) - ((100.0 - float(humidity_percent)) / 5.0), 2)

    def evaluate_and_control(
        self,
        outdoor_temp=32.0,
        outdoor_humidity=45.0,
        indoor_temp=24.0,
        safety_buffer=2.0,
        indoor_pm25=42.0,
        indoor_co2=650.0,
        **kwargs,
    ):
        """
        Controls the relay based on psychrometric dew point and air quality priority rules:

        Priority 1 (Dominating / Condensation Lockout):
            Outdoor Dew Point >= (Indoor Temp - Safety Buffer)
                -> Relay OFF strictly (Lockout fresh air / close damper to prevent condensation)

        Priority 2 (Purge Triggers):
            Safe Dew Point AND (Indoor PM2.5 > 60 OR Indoor CO2 > 800)
                -> Relay ON (Open Damper / Exhaust pollutants)

        Priority 3 (Default Fallback):
            Safe Dew Point AND Indoor air within safe limits
                -> Relay OFF strictly (Normal Air Quality - Closed)
        """
        out_temp = float(kwargs.get("outdoor_temp", outdoor_temp))
        out_hum = float(kwargs.get("outdoor_humidity", outdoor_humidity))
        in_temp = float(kwargs.get("indoor_temp", indoor_temp))
        buffer_val = float(kwargs.get("safety_buffer", safety_buffer))
        in_pm25 = float(kwargs.get("indoor_pm25", indoor_pm25))
        in_co2 = float(kwargs.get("indoor_co2", indoor_co2))

        # 1. Calculate outdoor dew point (Quick C formula)
        outdoor_dew_point = self.calculate_dew_point(out_temp, out_hum)

        # 2. Calculate indoor cold surface condensation threshold
        indoor_condensation_threshold = round(in_temp - buffer_val, 2)

        # ---------------------------------------------------------------------
        # Priority 1: Condensation / Dew Point Lockout (Strict Override)
        # ---------------------------------------------------------------------
        if outdoor_dew_point >= indoor_condensation_threshold:
            self._set_relay(
                state=False,
                reason=(
                    f"DewPoint Lockout (Outdoor Dew Point {outdoor_dew_point}°C >= "
                    f"Condensation Threshold {indoor_condensation_threshold}°C "
                    f"[Room {in_temp}°C - Buffer {buffer_val}°C])"
                )
            )
            return

        # ---------------------------------------------------------------------
        # Priority 2: Indoor Air Quality Purge (PM2.5 > 60 or CO2 > 800)
        # ---------------------------------------------------------------------
        is_pm25_high = in_pm25 > self.PM25_THRESHOLD
        is_co2_high = in_co2 > self.CO2_THRESHOLD

        if is_pm25_high or is_co2_high:
            reasons = []
            if is_pm25_high:
                reasons.append(f"PM2.5 Purge ({in_pm25} > {self.PM25_THRESHOLD})")
            if is_co2_high:
                reasons.append(f"CO2 Purge ({in_co2} > {self.CO2_THRESHOLD})")

            self._set_relay(
                state=True,
                reason=" & ".join(reasons)
            )
            return

        # ---------------------------------------------------------------------
        # Priority 3: Default Fallback - Normal Air Quality (Closed)
        # ---------------------------------------------------------------------
        self._set_relay(
            state=False,
            reason="Normal Air Quality - Closed (Default OFF)"
        )

    def turn_on(self, reason="Manual"):
        self._set_relay(True, reason)

    def turn_off(self, reason="Manual"):
        self._set_relay(False, reason)

    def _set_relay(self, state, reason):
        """
        Changes relay state only when necessary (suppresses redundant network calls).
        """
        if self.current_state == state:
            print(
                f"[{self.mac_address}] "
                f"Relay already {'ON' if state else 'OFF'} "
                f"-> {reason} (Network call skipped)"
            )
            return

        payload = {
            "mac": self.mac_address,
            "on": state
        }

        response = self.__call_device(payload)

        if response and response.ok:
            self.current_state = state
            print(
                f"[{self.mac_address}] "
                f"Relay {'ON' if state else 'OFF'} "
                f"-> {reason}"
            )

    def __call_device(self, payload):
        """
        Sends HTTP POST command to physical relay gateway.
        Automatically routes commands to /api/relay if /api/events was provided.
        """
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
        }

        target_url = self.relay_url
        if target_url and target_url.rstrip("/").endswith("/api/events"):
            target_url = target_url.replace("/api/events", "/api/relay")

        try:
            response = requests.post(
                target_url,
                headers=headers,
                json=payload,
                timeout=10,
            )

            # Fallback if a custom URL returned 404
            if response.status_code == 404 and "/api/events" in self.relay_url:
                fallback_url = self.relay_url.replace("/api/events", "/api/relay")
                response = requests.post(
                    fallback_url,
                    headers=headers,
                    json=payload,
                    timeout=10,
                )

            response.raise_for_status()

            print(
                f"[{self.mac_address}] "
                f"Relay API response: {response.text.strip()}"
            )
            return response

        except requests.RequestException as exc:
            print(
                f"[{self.mac_address}] "
                f"Relay API error: {exc}"
            )
            return None


if __name__ == "__main__":
    # Test instance targeting the physical relay
    relay_manager = RelayManager("004B12302844")

    # Example 1: Condensation / Dew Point Lockout -> Relay OFF
    # Outdoor 32°C, 80% Humidity -> Dew Point = 32 - ((100 - 80) / 5) = 28.0°C
    # Indoor 24°C, 2.0°C Buffer -> Surface Threshold = 22.0°C
    # 28.0°C >= 22.0°C -> Lockout triggers, suppressing high PM2.5/CO2
    print("--- Test 1: High Outdoor Dew Point (Condensation Lockout) ---")
    relay_manager.evaluate_and_control(
        outdoor_temp=32.0,
        outdoor_humidity=80.0,
        indoor_temp=24.0,
        safety_buffer=2.0,
        indoor_pm25=120.0,  # High PM2.5 is dominated by condensation lockout
        indoor_co2=900.0,   # High CO2 is dominated by condensation lockout
    )

    # Example 2: Indoor Pollution Purge -> Relay ON
    # Outdoor 25°C, 35% Humidity -> Dew Point = 12.0°C < 22.0°C (Safe)
    # Indoor PM2.5 = 75.0 (> 60) -> Purge triggers
    print("\n--- Test 2: Safe Dew Point & High PM2.5 Purge (> 60) ---")
    relay_manager.evaluate_and_control(
        outdoor_temp=25.0,
        outdoor_humidity=35.0,
        indoor_temp=24.0,
        safety_buffer=2.0,
        indoor_pm25=75.0,
        indoor_co2=600.0,
    )

    # Example 3: Normal Conditions -> Always Close / Relay OFF
    # Safe Dew Point, PM2.5 30 <= 60, CO2 550 <= 800
    print("\n--- Test 3: Normal Conditions (Fallback Closed) ---")
    relay_manager.evaluate_and_control(
        outdoor_temp=25.0,
        outdoor_humidity=35.0,
        indoor_temp=24.0,
        safety_buffer=2.0,
        indoor_pm25=30.0,
        indoor_co2=550.0,
    )
