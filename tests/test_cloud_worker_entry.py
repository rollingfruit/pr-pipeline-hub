import unittest
from pathlib import Path


class CloudWorkerEntryTest(unittest.TestCase):
    def test_worker_starts_control_queue_consumer(self):
        source = Path(__file__).parents[1].joinpath('cloud_entry.py').read_text()
        self.assertIn('target=work', source)
        self.assertIn("name='control-queue-worker'", source)


if __name__ == '__main__':
    unittest.main()
