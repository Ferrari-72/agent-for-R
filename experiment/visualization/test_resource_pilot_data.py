import unittest

from resource_pilot_data import summarize, validate


class ResourcePilotDataTests(unittest.TestCase):
    def row(self, **changes):
        row = {"case_id": "case-a", "solver": "solver-a", "repeat": 0,
               "status": "ok", "cost": 10, "peak_elements": 50,
               "algorithm_wall_seconds": 0.5, "process_wall_seconds": 0.7,
               "max_rss_kib": 1000}
        row.update(changes)
        return row

    def test_failure_is_retained_and_omitted_from_medians(self):
        rows = [self.row(), self.row(repeat=1,status="timeout",cost=None,
                                     peak_elements=None,algorithm_wall_seconds=None)]
        report = {"schema_version": 1, "rows": rows}
        validate(report)
        summary = summarize(rows)["solver-a"]
        self.assertEqual(summary["rows"],2)
        self.assertEqual(summary["successes"],1)
        self.assertEqual(summary["cost_median"],10)

    def test_resource_pilot_success_status_is_summarized(self):
        rows = [self.row(status="success")]
        validate({"schema_version": 1, "rows": rows})
        self.assertEqual(summarize(rows)["solver-a"]["successes"], 1)

    def test_reject_bool_metrics_and_duplicate_rows(self):
        with self.assertRaisesRegex(ValueError,"finite nonnegative"):
            validate({"schema_version": 1, "rows":[self.row(cost=True)]})
        with self.assertRaisesRegex(ValueError,"duplicate"):
            validate({"schema_version": 1, "rows":[self.row(),self.row()]})

    def test_success_cannot_hide_null_measurements(self):
        with self.assertRaisesRegex(ValueError,"require cost"):
            validate({"schema_version": 1, "rows":[self.row(peak_elements=None)]})


if __name__ == "__main__":
    unittest.main()
