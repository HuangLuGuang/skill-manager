import unittest
from run_stability_test import check_summary, cpu_seconds, resource_report


class StabilityReportTests(unittest.TestCase):
    def test_cpu_time_formats(self):
        self.assertAlmostEqual(cpu_seconds("12:34.56"), 754.56)
        self.assertEqual(cpu_seconds("1-02:03:04"), 93784)

    def test_resource_metrics_use_elapsed_time_and_plateau(self):
        samples = [{"elapsed_s": n * 60, "rss_kib": 32768 + n * 1024,
                    "cpu_seconds": n * 0.6} for n in range(10)]
        report = resource_report(samples)
        self.assertAlmostEqual(report["cpu_percent_one_core"], 1.0)
        self.assertEqual(report["peak_rss_mib"], 41)
        self.assertEqual(report["rss_growth_mib"], 7)

    def test_missing_samples_cannot_pass(self):
        self.assertFalse(resource_report([])["sufficient_samples"])

    def test_missing_log_tail_cannot_pass(self):
        summary = {key: "0" for key in ("gaps", "overflow", "event_discarded",
                   "event_remaining", "log_unconfirmed", "log_dropped",
                   "log_errors", "log_remaining")}
        summary.update(monitor_session="s", coverage="complete", log_shutdown_timeout="false",
                       received="10", enqueued="10", processed="10", log_enqueued="11", log_written="11")
        events = {"sessions": ["s"], "events": 10}
        self.assertEqual([], check_summary(summary, events))
        events["events"] = 9
        self.assertIn("counter_log_written", check_summary(summary, events))


if __name__ == "__main__":
    unittest.main()
