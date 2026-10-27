import subprocess
import time
import unittest

from app.runner import run_c_program


class RunnerTests(unittest.TestCase):
    def test_successful_program(self):
        result = run_c_program(
            '#include <stdio.h>\nint main(void){int n; if(scanf("%d",&n)!=1)return 1; printf("%d\\n",n*2); return 0;}',
            "21\n",
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["stdout"], "42\n")

    def test_compile_error(self):
        result = run_c_program("int main( {")
        self.assertEqual(result["status"], "compile_error")

    def test_runtime_failure(self):
        result = run_c_program("int main(void){return 7;}")
        self.assertEqual(result["status"], "terminated_by_signal" if result.get("exit_code", 0) < 0 else "completed")
        self.assertEqual(result["exit_code"], 7)

    def test_timeout(self):
        result = run_c_program("int main(void){for(;;){} return 0;}")
        self.assertEqual(result["status"], "timeout")

    def test_empty_source_rejected(self):
        result = run_c_program("")
        self.assertEqual(result["status"], "invalid_request")

    def test_source_size_rejected(self):
        result = run_c_program(" " * (256 * 1024 + 1))
        self.assertEqual(result["status"], "invalid_request")

    def test_output_is_bounded(self):
        result = run_c_program(
            '#include <stdio.h>\nint main(void){for(;;)puts("012345678901234567890123456789");}'
        )
        self.assertEqual(result["status"], "output_limit")
        self.assertTrue(result["stdout_truncated"])
        self.assertLessEqual(len(result["stdout"].encode()), 1024 * 1024)

    def test_timeout_kills_child_processes(self):
        source = r"""
#include <unistd.h>
int main(void) {
    if (fork() == 0) {
        for (;;) pause();
    }
    for (;;) pause();
}
"""
        result = run_c_program(source)
        self.assertEqual(result["status"], "timeout")
        time.sleep(0.3)
        ps = subprocess.run(
            ["ps", "-eo", "args"],
            capture_output=True, text=True, check=True
        )
        leftovers = [
            line for line in ps.stdout.splitlines()
            if "/work/submission" in line
        ]
        self.assertFalse(leftovers, f"Possible leftover processes: {leftovers}")


if __name__ == "__main__":
    unittest.main()
