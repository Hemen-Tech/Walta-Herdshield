import unittest
from datetime import date, timedelta

from backend.climate import (
    aggregate_observations,
    build_archive_params,
    compare_rainfall_to_history,
)


class ClimateDataTests(unittest.TestCase):
    def test_build_archive_params_uses_provider_daily_data_contract(self):
        params = build_archive_params(
            9.0, 38.0, date(2026, 1, 1), date(2026, 3, 31)
        )

        self.assertEqual(params["latitude"], 9.0)
        self.assertEqual(params["start_date"], "2026-01-01")
        self.assertIn("precipitation_sum", params["daily"])
        self.assertEqual(params["timezone"], "UTC")

    def test_aggregate_observations_ignores_missing_values_in_summaries(self):
        payload = {
            "daily": {
                "time": ["2026-01-01", "2026-01-02"],
                "precipitation_sum": [2.0, None],
                "temperature_2m_mean": [20.0, 22.0],
                "et0_fao_evapotranspiration": [1.0, 2.0],
            }
        }

        result = aggregate_observations(payload)

        self.assertEqual(result["summary"]["precipitation_90d_mm"], 2.0)
        self.assertEqual(result["summary"]["mean_temperature_90d_c"], 21.0)
        self.assertEqual(result["summary"]["et0_90d_mm"], 3.0)

    def test_historical_comparison_is_retrospective_and_reports_baseline(self):
        end = date(2025, 12, 31)
        start = end - timedelta(days=10 * 366 + 89)
        dates = []
        rainfall = []
        day = start
        while day <= end:
            dates.append(day.isoformat())
            rainfall.append(0.0 if day > end - timedelta(days=90) else 5.0)
            day += timedelta(days=1)

        result = compare_rainfall_to_history(
            {"daily": {"time": dates, "precipitation_sum": rainfall}}, end
        )

        self.assertEqual(result["category"], "Severe rainfall shortfall")
        self.assertEqual(result["indicator_type"], "retrospective_rainfall_comparison")
        self.assertIn("not a drought diagnosis", result["caveat"])
        self.assertEqual(result["current_rainfall_mm"], 0)


if __name__ == "__main__":
    unittest.main()
