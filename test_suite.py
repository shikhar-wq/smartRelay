import unittest
from unittest.mock import patch, MagicMock
from relay_class import RelayManager
from app import app, DEFAULT_MAC, relay_manager


class TestRelayManagerLogic(unittest.TestCase):
    def setUp(self):
        self.rm = RelayManager(mac_address="TEST_MAC_001", mock_mode=True)

    def test_priority_1_condensation_lockout_dominates_all(self):
        """
        Condition: Outdoor Dew Point >= Indoor Condensation Threshold (indoorTemp - safetyBuffer).
        Even if indoor PM2.5 > 60 and indoor CO2 > 800, relay MUST be strictly OFF.
        """
        # outdoorTemp=32, outdoorHum=80 -> dew point = 32 - ((100-80)/5) = 28.0°C
        # indoorTemp=24, buffer=2.0 -> threshold = 22.0°C
        # 28.0 >= 22.0 -> Lockout triggered!
        res = self.rm.evaluate_and_control(
            outdoor_temp=32.0,
            outdoor_humidity=80.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=150.0,  # High PM2.5 (> 60)
            indoor_co2=1200.0, # High CO2 (> 800)
            mock_mode=True,
        )

        self.assertFalse(res["target_state"], "Relay must be OFF when outdoor dew point >= indoor surface threshold")
        self.assertEqual(res["priority_hit"], 1, "Must hit Priority 1 (Condensation Lockout)")
        self.assertIn("DewPoint Lockout", res["reason"])
        self.assertEqual(len(res["decision_trace"]), 3)
        self.assertEqual(res["decision_trace"][0]["status"], "TRIGGERED (OVERRIDE)")
        self.assertIn("SUPPRESSED", res["decision_trace"][1]["status"])

    def test_priority_2_pm25_purge(self):
        """
        Condition: Safe dew point and Indoor PM2.5 > 60.
        Relay MUST be ON.
        """
        # outdoorTemp=25, outdoorHum=35 -> dew point = 25 - ((100-35)/5) = 12.0°C
        # indoorTemp=24, buffer=2.0 -> threshold = 22.0°C (12.0 < 22.0 -> safe!)
        res = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=65.0,  # > 60
            indoor_co2=500.0,  # Normal (<= 800)
            mock_mode=True,
        )

        self.assertTrue(res["target_state"], "Relay must be ON when PM2.5 exceeds 60 under safe dew point")
        self.assertEqual(res["priority_hit"], 2)
        self.assertIn("PM2.5 Purge", res["reason"])

    def test_priority_2_co2_purge(self):
        """
        Condition: Safe dew point and Indoor CO2 > 800.
        Relay MUST be ON.
        """
        res = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=30.0,  # Normal (<= 60)
            indoor_co2=850.0,  # > 800
            mock_mode=True,
        )

        self.assertTrue(res["target_state"], "Relay must be ON when CO2 exceeds 800 under safe dew point")
        self.assertEqual(res["priority_hit"], 2)
        self.assertIn("CO2 Purge", res["reason"])

    def test_priority_2_both_pm25_and_co2_high(self):
        """
        Condition: Safe dew point, both PM2.5 > 60 and CO2 > 800.
        Relay MUST be ON with combined purge reason.
        """
        res = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=75.0,
            indoor_co2=950.0,
            mock_mode=True,
        )

        self.assertTrue(res["target_state"])
        self.assertEqual(res["priority_hit"], 2)
        self.assertIn("PM2.5 Purge", res["reason"])
        self.assertIn("CO2 Purge", res["reason"])

    def test_priority_3_normal_air_quality_fallback(self):
        """
        Condition: Safe dew point, Indoor PM2.5 <= 60, Indoor CO2 <= 800.
        Relay MUST be strictly OFF (Normal Quality).
        """
        res = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=45.0,  # <= 60
            indoor_co2=600.0,  # <= 800
            mock_mode=True,
        )

        self.assertFalse(res["target_state"], "Relay must be OFF under normal air quality")
        self.assertEqual(res["priority_hit"], 3)
        self.assertIn("Normal Air Quality", res["reason"])

    def test_boundary_conditions(self):
        """
        Exact threshold boundaries:
        - PM2.5 exactly 60 -> NOT high (needs > 60)
        - PM2.5 = 60.1 -> High (Purge ON)
        - CO2 exactly 800 -> NOT high (needs > 800)
        - CO2 = 800.1 -> High (Purge ON)
        - Outdoor dew point == Threshold -> Lockout triggered (>= is lockout)
        - Outdoor dew point < Threshold -> Safe
        """
        # Exact thresholds with safe dew point (outdoor 25°C, 35% -> 12.0°C; threshold = 22.0°C)
        res = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=60.0,       # Exactly 60 -> not triggered
            indoor_co2=800.0,        # Exactly 800 -> not triggered
            mock_mode=True,
        )
        self.assertFalse(res["target_state"], "Thresholds at exact boundary (60, 800) should be Normal Quality (OFF)")
        self.assertEqual(res["priority_hit"], 3)

        # 60.1 PM2.5 -> Purge ON
        res_pm = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=60.1,
            indoor_co2=800.0,
            mock_mode=True,
        )
        self.assertTrue(res_pm["target_state"])
        self.assertEqual(res_pm["priority_hit"], 2)

        # 800.1 CO2 -> Purge ON
        res_co2 = self.rm.evaluate_and_control(
            outdoor_temp=25.0,
            outdoor_humidity=35.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=60.0,
            indoor_co2=800.1,
            mock_mode=True,
        )
        self.assertTrue(res_co2["target_state"])
        self.assertEqual(res_co2["priority_hit"], 2)

        # Exact dew point equality boundary:
        # outdoorTemp=26, hum=80 -> dew point = 26 - ((100-80)/5) = 22.0°C
        # indoorTemp=24, buffer=2.0 -> threshold = 22.0°C
        # 22.0 >= 22.0 -> Lockout triggered!
        res_dew_eq = self.rm.evaluate_and_control(
            outdoor_temp=26.0,
            outdoor_humidity=80.0,
            indoor_temp=24.0,
            safety_buffer=2.0,
            indoor_pm25=80.0,
            mock_mode=True,
        )
        self.assertFalse(res_dew_eq["target_state"], "Exact equality outdoorDewPoint == indoorCondensationThreshold must trigger Lockout")
        self.assertEqual(res_dew_eq["priority_hit"], 1)

    def test_manual_override_methods(self):
        res_on = self.rm.turn_on(reason="Manual ON Test", mock_mode=True)
        self.assertTrue(res_on["success"])
        self.assertTrue(self.rm.current_state)

        res_off = self.rm.turn_off(reason="Manual OFF Test", mock_mode=True)
        self.assertTrue(res_off["success"])
        self.assertFalse(self.rm.current_state)

    def test_redundant_call_suppression(self):
        """When state is unchanged and force=False, redundant network call is suppressed."""
        self.rm.current_state = True
        res = self.rm._set_relay(True, reason="Repeat Call", mock_mode=True, force=False)
        self.assertTrue(res["success"])
        self.assertFalse(res["changed"])
        self.assertFalse(res["api_sent"])


class TestFlaskAPIs(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        relay_manager.current_state = None

    def test_index_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("CTFA", html)
        self.assertIn("Current CTFA State", html)
        self.assertIn("fan-status-icon", html)
        self.assertIn("simulator-drawer", html)
        self.assertNotIn("Simulator Telemetry Input:", html)

    def test_api_telemetry(self):
        resp = self.client.get("/api/telemetry")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        t = data["telemetry"]
        for key in ["indoor_pm25", "outdoor_pm25", "indoor_co2", "outdoor_co2", "indoor_temp", "outdoor_temp", "indoor_humidity", "outdoor_humidity", "fan_status"]:
            self.assertIn(key, t)

    def test_api_presets(self):
        resp = self.client.get("/api/presets")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        presets = data["presets"]
        self.assertGreaterEqual(len(presets), 4)
        preset_ids = [p["id"] for p in presets]
        self.assertIn("purge_pm25", preset_ids)
        self.assertIn("purge_co2", preset_ids)
        self.assertIn("lockout_humidity", preset_ids)
        self.assertIn("normal_close", preset_ids)

    def test_api_simulate_lockout(self):
        # High outdoor dew point: 32°C, 80% hum -> dew point = 28.0°C >= 22.0°C
        payload = {
            "outdoor_temp": 32.0,
            "outdoor_humidity": 80.0,
            "indoor_temp": 24.0,
            "safety_buffer": 2.0,
            "indoor_pm25": 140.0,
            "indoor_co2": 950.0,
            "mock_mode": True,
        }
        resp = self.client.post("/api/simulate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["telemetry"]["fan_status"])
        self.assertEqual(data["telemetry"]["state_key"], "lockout")

    def test_api_simulate_purge(self):
        # Safe dew point: 25°C, 35% hum -> dew point = 12.0°C < 22.0°C
        payload = {
            "outdoor_temp": 25.0,
            "outdoor_humidity": 35.0,
            "indoor_temp": 24.0,
            "safety_buffer": 2.0,
            "indoor_pm25": 65.0,  # > 60
            "indoor_co2": 500.0,
            "mock_mode": True,
        }
        resp = self.client.post("/api/simulate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["telemetry"]["fan_status"])
        self.assertEqual(data["telemetry"]["state_key"], "purge_pm25")

    def test_api_manual_override(self):
        resp = self.client.post("/api/manual", json={"state": True, "mock_mode": True})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["telemetry"]["fan_status"])

        resp_off = self.client.post("/api/manual", json={"state": False, "mock_mode": True})
        self.assertEqual(resp_off.status_code, 200)
        data_off = resp_off.get_json()
        self.assertTrue(data_off["success"])
        self.assertFalse(data_off["telemetry"]["fan_status"])

    def test_api_alarms(self):
        resp = self.client.get("/api/alarms")
        self.assertEqual(resp.status_code, 200)
        alarms = resp.get_json()["alarms"]
        self.assertGreater(len(alarms), 0)

        # Toggle alarm 1
        initial_active = alarms[0]["active"]
        resp_post = self.client.post("/api/alarms", json={"id": alarms[0]["id"]})
        self.assertEqual(resp_post.status_code, 200)
        updated_active = resp_post.get_json()["alarms"][0]["active"]
        self.assertEqual(updated_active, not initial_active)

    def test_api_reports(self):
        resp = self.client.get("/api/reports")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["logs"], list)

    def test_api_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["relay_url"], "http://178.16.137.20:3101/api/events")

    @patch("requests.post")
    def test_api_telemetry_ingest(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.text = '{"status": "ok"}'
        mock_post.return_value = mock_resp

        # Test live ingest payload with safe dew point and high PM2.5 (>60)
        payload = {
            "outdoor_temp": 25.0,
            "outdoor_humidity": 35.0,
            "indoor_temp": 24.0,
            "safety_buffer": 2.0,
            "indoor_pm25": 72.0,
            "indoor_co2": 550.0,
            "indoor_humidity": 50.0,
            "outdoor_pm25": 20.0,
            "outdoor_co2": 410.0,
            "mac_address": "004B12302844",
        }
        resp = self.client.post("/api/telemetry/ingest", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["telemetry"]["fan_status"])
        self.assertEqual(data["telemetry"]["state_key"], "purge_pm25")
        self.assertEqual(data["telemetry"]["indoor_pm25"], 72.0)
        # Verify the hardware actuator call targeted /api/relay
        self.assertTrue(mock_post.called)
        called_url = mock_post.call_args[0][0]
        self.assertEqual(called_url, "http://178.16.137.20:3101/api/relay")

    def test_api_device_state(self):
        resp = self.client.get("/api/device/state")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("is_connected", data)
        self.assertIn(data["system_status"], ["Connected", "Disconnected"])
        self.assertEqual(data["events_url"], "http://178.16.137.20:3101/api/events")


if __name__ == "__main__":
    unittest.main()
