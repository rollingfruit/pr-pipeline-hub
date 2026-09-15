import unittest

from e2e_execution_graph import waves


class ExecutionGraphTest(unittest.TestCase):
    def test_full_plan_has_two_lane_limit_and_exclusive_e05(self):
        plan = waves(['E01', 'E02', 'E03', 'E04', 'E05', 'E06'])
        self.assertEqual(plan, [['E01'], ['E02', 'E03'], ['E04', 'E06'], ['E05']])
        self.assertTrue(all(len(wave) <= 2 for wave in plan))

    def test_partial_selection_does_not_require_unselected_prerequisites(self):
        self.assertEqual(waves(['E02', 'E03']), [['E02', 'E03']])

    def test_rejects_more_than_two_workers(self):
        with self.assertRaises(ValueError):
            waves(['E01'], 3)


if __name__ == '__main__':
    unittest.main()
