import sys
import threading
import unittest
from pathlib import Path


LIB_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB_DIR))

import ssh_sync  # noqa: E402


class Control:
    def __init__(self):
        self.cancelled = threading.Event()


def values(count):
    import sys

    print("stdout text")
    print("stderr text", file=sys.stderr)
    for value in range(count):
        yield {"value": value, "bytes": bytes([value])}
    return "finished"


def slow_values():
    import time

    yield "first"
    time.sleep(60)


class IteratorWorkerTest(unittest.TestCase):
    def request(self, function, *args, timeout=5):
        return {
            "request_id": "test",
            "function": ssh_sync._function_spec(function),
            "args": args,
            "kwargs": {},
            "timeout": timeout,
            "max_frame": ssh_sync._DEFAULT_MAX_FRAME,
        }

    def run_iterator(self, request, control=None):
        if control is None:
            control = Control()
        worker = [sys.executable, ssh_sync.__file__, "_remote_iterator"]
        return ssh_sync._run_iterator(request, worker, control)

    def test_yields_values_and_captures_output(self):
        responses = list(self.run_iterator(self.request(values, 3)))

        self.assertEqual(
            [response["value"] for response in responses[:-1]],
            [
                {"value": 0, "bytes": b"\0"},
                {"value": 1, "bytes": b"\1"},
                {"value": 2, "bytes": b"\2"},
            ],
        )
        self.assertEqual(responses[-1]["stream_event"], "end")
        self.assertTrue(responses[-1]["ok"])
        self.assertEqual(responses[-1]["value"], "finished")
        self.assertEqual(responses[-1]["stdout"], b"stdout text\n")
        self.assertEqual(responses[-1]["stderr"], b"stderr text\n")

    def test_cancel_terminates_worker(self):
        control = Control()
        responses = self.run_iterator(self.request(slow_values), control)

        self.assertEqual(next(responses)["value"], "first")
        control.cancelled.set()
        final = next(responses)
        self.assertEqual(final["stream_event"], "end")
        self.assertTrue(final["cancelled"])
        with self.assertRaises(StopIteration):
            next(responses)


if __name__ == "__main__":
    unittest.main()
