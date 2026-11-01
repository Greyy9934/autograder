import unittest
from pathlib import Path
from unittest.mock import patch

from analyzers.batch_execution import (
    run_c_batch,
    _classify_execution,
    _summarize_results,
    _adaptive_benchmark_case_order,
    _classify_benchmark_run,
)




class AdaptiveBenchmarkOrderTests(unittest.TestCase):
    def test_geometric_ladder_spans_sizes_and_preserves_every_case(self):
        cases = [
            {"input_size": size, "input": str(size)}
            for size in range(1, 41)
            for _ in range(3)
        ]

        order, ladder = _adaptive_benchmark_case_order(cases)

        self.assertEqual(len(order), len(cases))
        self.assertEqual(set(order), set(range(len(cases))))
        self.assertEqual(order[:len(ladder)], [
            next(index for index, case in enumerate(cases)
                 if case["input_size"] == size)
            for size in ladder
        ])
        self.assertEqual(ladder[0], 1)
        self.assertEqual(ladder[-1], 40)
        self.assertLessEqual(len(ladder), 16)
        self.assertGreater(ladder[-2] / ladder[1], 5)

    def test_zero_workload_size_is_supported_in_ladder(self):
        cases = [{"input_size": 0, "input": "0"}, {"input_size": 10, "input": "10"}]

        order, ladder = _adaptive_benchmark_case_order(cases)

        self.assertEqual(set(order), {0, 1})
        self.assertEqual(ladder, [0, 10])

    def test_one_size_keeps_all_cases_in_original_order(self):
        cases = [{"input_size": 7, "input": str(i)} for i in range(4)]

        order, ladder = _adaptive_benchmark_case_order(cases)

        self.assertEqual(order, [0, 1, 2, 3])
        self.assertEqual(ladder, [7])


class BatchExecutionTests(unittest.TestCase):
    @patch("analyzers.batch_execution.runner._run_bounded")
    def test_compiles_once_and_runs_each_input(self, mock_run):
        run_count = 0

        def fake_run(command, **kwargs):
            nonlocal run_count
            run_count += 1

            if "/usr/bin/gcc" in command:
                work = Path(command[command.index("--bind") + 1])
                (work / "submission").write_text("mock executable")
                return {
                    "status": "completed",
                    "exit_code": 0,
                    "seconds": 0.1,
                }

            output = "3\n" if run_count == 2 else "7\n"
            return {
                "status": "completed",
                "exit_code": 0,
                "stdout": output,
                "stderr": "",
                "seconds": 0.01,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }

        mock_run.side_effect = fake_run

        result = run_c_batch(
            "int main(void){return 0;}",
            ["1 2\n", "3 4\n"],
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["compiled_once"])
        self.assertEqual(result["executed"], 2)
        self.assertEqual(mock_run.call_count, 3)

    @patch("analyzers.batch_execution.runner._run_bounded")
    def test_compile_failure_prevents_execution(self, mock_run):
        mock_run.return_value = {
            "status": "completed",
            "exit_code": 1,
            "stderr": "compile error",
        }
        result = run_c_batch("invalid C", ["1\n"])
        self.assertEqual(result["status"], "compile_failed")
        self.assertEqual(mock_run.call_count, 1)

    def test_rejects_empty_batch(self):
        self.assertEqual(
            run_c_batch("int main(void){return 0;}", [])["status"],
            "invalid_request",
        )

    def test_rejects_invalid_input_type(self):
        self.assertEqual(
            run_c_batch("int main(void){return 0;}", [None])["status"],
            "invalid_request",
        )


    def test_execution_categories(self):
        cases = [
            ({"status": "completed", "exit_code": 0}, "program_success"),
            ({"status": "completed", "exit_code": 1}, "runtime_error"),
            ({"status": "terminated_by_signal"}, "runtime_crash"),
            ({"status": "timeout"}, "time_limit_exceeded"),
            ({"status": "output_limit"}, "output_limit_exceeded"),
            (
                {"status": "resource_limit_or_forced_kill"},
                "resource_limit_exceeded",
            ),
            ({"status": "launch_error"}, "infrastructure_error"),
            ({"status": "unexpected"}, "execution_unknown"),
        ]

        for run, expected in cases:
            with self.subTest(run=run):
                self.assertEqual(_classify_execution(run), expected)

    def test_shared_benchmark_deadline_is_not_reported_as_program_timeout(self):
        run = {"status": "timeout"}
        self.assertEqual(
            _classify_benchmark_run(run, shared_budget_limited=True),
            "benchmark_time_budget_exhausted",
        )
        self.assertEqual(
            _classify_benchmark_run(run, shared_budget_limited=False),
            "time_limit_exceeded",
        )

    def test_batch_summary_counts_each_category(self):
        results = [
            {"execution_class": "program_success"},
            {"execution_class": "program_success"},
            {"execution_class": "runtime_error"},
            {"execution_class": "time_limit_exceeded"},
            {"execution_class": "infrastructure_error"},
        ]

        summary = _summarize_results(results)

        self.assertEqual(summary["program_success"], 2)
        self.assertEqual(summary["runtime_error"], 1)
        self.assertEqual(summary["time_limit_exceeded"], 1)
        self.assertEqual(summary["infrastructure_error"], 1)
        self.assertEqual(summary["runtime_crash"], 0)

    def test_infrastructure_failure_is_not_program_success(self):
        self.assertNotEqual(
            _classify_execution({"status": "launch_error"}),
            "program_success",
        )

    def test_nonzero_exit_is_runtime_error(self):
        self.assertEqual(
            _classify_execution({
                "status": "completed",
                "exit_code": 7,
            }),
            "runtime_error",
        )


if __name__ == "__main__":
    unittest.main()
