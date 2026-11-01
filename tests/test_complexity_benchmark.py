import unittest
from unittest.mock import patch

from analyzers.complexity_benchmark import benchmark_complexity


def successful_run(seconds):
    return {
        "execution_class": "program_success",
        "exit_code": 0,
        "run_seconds": seconds,
    }


class ComplexityBenchmarkTests(unittest.TestCase):
    def test_invalid_request_is_rejected(self):
        result = benchmark_complexity(
            "int main(void) { return 0; }",
            [{"input_size": 10, "input": "10\n"}],
            repetitions=0,
        )
        self.assertEqual(result["status"], "invalid_request")

    def test_rejects_duplicate_input_sizes(self):
        result = benchmark_complexity(
            "int main(void) { return 0; }",
            [
                {"input_size": 10, "input": "10\n"},
                {"input_size": 10, "input": "10  \n"},
            ],
        )
        self.assertEqual(result["status"], "invalid_request")

    @patch("analyzers.complexity_benchmark.run_c_batch")
    def test_aggregates_median_and_builds_graph_data(self, mock_batch):
        mock_batch.return_value = {
            "status": "completed",
            "compiled_once": True,
            "compile_seconds": 0.12,
            "results": [
                successful_run(0.03),
                successful_run(0.01),
                successful_run(0.02),
                successful_run(0.08),
                successful_run(0.10),
                successful_run(0.09),
            ],
        }

        result = benchmark_complexity(
            "int main(void) { return 0; }",
            [
                {"input_size": 100, "input": "100\n"},
                {"input_size": 200, "input": "200\n"},
            ],
            repetitions=3,
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["compiled_once"])
        self.assertEqual(result["results"][0]["median_runtime_seconds"], 0.02)
        self.assertEqual(result["results"][1]["median_runtime_seconds"], 0.09)
        self.assertEqual(len(result["chart_data"]), 2)
        self.assertEqual(result["growth_observations"][0]["input_size_ratio"], 2)
        self.assertEqual(mock_batch.call_count, 1)
        self.assertEqual(len(mock_batch.call_args.args[1]), 6)

    @patch("analyzers.complexity_benchmark.run_c_batch")
    def test_failed_runs_are_not_included_in_timing_statistics(self, mock_batch):
        mock_batch.return_value = {
            "status": "completed_with_execution_issues",
            "compiled_once": True,
            "results": [
                successful_run(0.02),
                {
                    "execution_class": "time_limit_exceeded",
                    "exit_code": None,
                    "run_seconds": 2.0,
                },
                successful_run(0.04),
            ],
        }

        result = benchmark_complexity(
            "int main(void) { return 0; }",
            [{"input_size": 10, "input": "10\n"}],
            repetitions=3,
        )

        item = result["results"][0]
        self.assertEqual(result["status"], "completed_with_execution_issues")
        self.assertEqual(item["successful_runs"], 2)
        self.assertEqual(item["failed_runs"], 1)
        self.assertEqual(item["median_runtime_seconds"], 0.03)
        self.assertEqual(item["runs"][1]["included_in_timing"], False)

    @patch("analyzers.complexity_benchmark.run_c_batch")
    def test_compile_failure_produces_no_graph_data(self, mock_batch):
        mock_batch.return_value = {
            "status": "compile_failed",
            "compile_status": "compile_error",
            "results": [],
        }

        result = benchmark_complexity(
            "invalid C",
            [{"input_size": 10, "input": "10\n"}],
        )

        self.assertEqual(result["status"], "compile_failed")
        self.assertEqual(result["chart_data"], [])
        self.assertEqual(result["growth_observations"], [])

    @patch("analyzers.complexity_benchmark.run_c_batch")
    def test_report_disclaims_asymptotic_proof(self, mock_batch):
        mock_batch.return_value = {
            "status": "completed",
            "compiled_once": True,
            "results": [successful_run(0.01)],
        }

        result = benchmark_complexity(
            "int main(void) { return 0; }",
            [{"input_size": 10, "input": "10\n"}],
            repetitions=1,
        )

        self.assertIn("do not prove Big-O", result["interpretation"])
        self.assertIn("startup overhead", result["measurement_scope"])


if __name__ == "__main__":
    unittest.main()
