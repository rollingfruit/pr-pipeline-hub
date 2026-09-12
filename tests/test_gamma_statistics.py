import unittest
from gamma_statistics import statistics


class StatisticsTests(unittest.TestCase):
    def test_infrastructure_failures_stay_in_denominator(self):
        result = statistics([{'first_pass': True}, {'first_pass': False, 'failure_kind': 'environment_error'}], 3, 30)
        self.assertEqual(result['first_pass_rate'], 1/3)
        self.assertEqual(result['planned'], 30)
        self.assertEqual(result['interrupted'], 1)
        self.assertEqual(result['failure_types'], {'environment_error': 1, 'interrupted': 1})

    def test_zero_execution_is_not_success(self):
        self.assertIsNone(statistics([], 0, 30)['first_pass_rate'])

    def test_running_round_is_not_an_interruption(self):
        result = statistics([], 1, 10, active=True)
        self.assertEqual(result['running'], 1)
        self.assertEqual(result['interrupted'], 0)
        self.assertEqual(result['failure_types'], {})
