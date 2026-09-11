import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('receipts', Path(__file__).with_name('daemon-receipts.py'))
receipts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipts)


class ReceiptsTest(unittest.TestCase):
    def test_pre_spawn_failure_and_redaction(self):
        line = (f'time=now msg="task failed" task_id=probe agent_id={receipts.AGENT} '
                f'workspace_id={receipts.WORKSPACE} error="im_task_prompt is empty" token=SECRET')
        result = receipts.inspect([line], 'probe')
        self.assertEqual(result['execution'], 'failed')
        self.assertEqual(result['events'][0]['error_code'], 'empty_im_task_prompt')
        self.assertNotIn('SECRET', str(result))
        self.assertEqual(receipts.inspect([line], 'other')['execution'], 'unknown')
        self.assertEqual(receipts.inspect([line.replace(receipts.AGENT, 'other')], 'probe')['execution'], 'unknown')

    def test_completion_is_not_group_delivery(self):
        line = (f'msg="task completed" task_id=probe agent_id={receipts.AGENT} '
                f'workspace_id={receipts.WORKSPACE}')
        result = receipts.inspect([line], 'probe')
        self.assertEqual(result['final_group_reply'], 'not_verified')


if __name__ == '__main__':
    unittest.main()
