import unittest
from unittest.mock import patch
import gamma_cleanup


class CleanupTests(unittest.TestCase):
    root = '/var/lib/pr-gamma-executor/diagnostics/gamma-check-test'

    def test_permission_failure_still_stops_owned_local_processes(self):
        with patch.object(gamma_cleanup, '_cleanup', side_effect=PermissionError('denied')), \
                patch.object(gamma_cleanup, 'stop_owned_processes', return_value=[]) as stop:
            result = gamma_cleanup.cleanup(self.root, {}, None)
        stop.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['active_residuals'])

    def test_process_inventory_error_cannot_be_reported_as_zero_residuals(self):
        initial = {'status': 'passed', 'errors': [], 'active_residuals': []}
        with patch.object(gamma_cleanup, '_cleanup', return_value=initial), \
                patch.object(gamma_cleanup, 'stop_owned_processes', side_effect=OSError('unknown')):
            result = gamma_cleanup.cleanup(self.root, {}, None)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['active_residuals'], [{'kind': 'process_inventory_unverified'}])

    def test_foreign_directory_is_never_cleaned(self):
        with patch.object(gamma_cleanup, 'stop_owned_processes') as stop:
            with self.assertRaises(RuntimeError):
                gamma_cleanup.cleanup('/tmp/gamma-check-test', {}, None)
        stop.assert_not_called()
