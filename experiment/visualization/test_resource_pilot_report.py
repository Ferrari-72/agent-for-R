import unittest

from resource_pilot_report import render, summarize


class ResourcePilotReportTests(unittest.TestCase):
    def test_summary_retains_failures_but_medians_use_successes(self):
        rows = [
            {"case_id": "a", "solver": "solver-a", "status": "ok", "cost": 10,
             "peak_elements": 50, "algorithm_wall_seconds": 0.5},
            {"case_id": "b", "solver": "solver-a", "status": "timeout", "cost": None,
             "peak_elements": None, "algorithm_wall_seconds": None},
        ]
        summary = summarize(rows)["solver-a"]
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["successes"], 1)
        self.assertEqual(summary["cost_median"], 10)

    def test_render_shows_failure_and_safe_labels(self):
        report = {"schema_version": 1, "run_id": "test-<run>", "image": {"id": "test"}, "rows": [
            {"case_id": "<script>alert(1)</script>", "solver": "solver & one", "repeat": 0,
             "status": "failed", "error": "kept in input", "cost": None,
             "peak_elements": None, "algorithm_wall_seconds": None,
             "process_wall_seconds": 0.1}
        ]}
        page = render(report)
        self.assertIn("0/1", page)
        self.assertIn("solver &amp; one", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("All executions", page)
        self.assertIn("prefers-color-scheme:dark", page)

    def test_resource_pilot_success_status_renders_metrics(self):
        report = {"schema_version": 1, "rows": [
            {"case_id": "a", "solver": "teacher.partition", "repeat": 0,
             "status": "success", "cost": 10, "peak_elements": 50,
             "algorithm_wall_seconds": 0.5}
        ]}
        page = render(report)
        self.assertIn("1/1", page)
        self.assertNotIn("No successful execution", page)

    def test_many_solvers_use_one_metric_color_and_direct_labels(self):
        rows = [{"case_id": "a", "solver": f"solver-{i}", "repeat": 0, "status": "ok",
                 "cost": i + 1, "peak_elements": i + 1,
                 "algorithm_wall_seconds": 0.1} for i in range(9)]
        page = render({"schema_version": 1, "rows": rows})
        self.assertIn("solver-8", page)
        self.assertIn("bars start at zero", page)
        self.assertNotIn("#eb6834", page)


if __name__ == "__main__":
    unittest.main()
