import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from pr_monitor import Monitor, transition


def pr(number=102,sha='a',state='open',draft=False):
    return {'number':number,'head':{'sha':sha,'ref':'test'},'base':{'sha':'b','ref':'main'},
            'state':state,'draft':draft,'created_at':'2026-01-01T00:00:00Z','updated_at':'2026-09-10T00:00:00Z',
            'title':'test','html_url':f'https://github.com/rollingfruit/agent-governance-gw/pull/{number}'}


class MonitorTests(unittest.TestCase):
    def test_inventory_includes_history_without_building_it(self):
        with tempfile.TemporaryDirectory() as temp:
            github=Mock(side_effect=[{'id':1,'full_name':'rollingfruit/agent-governance-gw'},[[pr(),pr(99,state='closed')]]])
            send=Mock(return_value={'ok':True})
            monitor=Monitor(github,send,Path(temp)/'state.json')
            monitor.tick()
            self.assertIn('state=all',github.call_args.args[0][1])
            self.assertEqual([p['number'] for p in monitor.status()['pull_requests']],[102,99])
            self.assertFalse(any(c.args[0]=='/internal/submit' for c in send.call_args_list))

    def test_transitions(self):
        old=pr()
        self.assertIsNone(transition(None,old,'2026-09-09T00:00:00Z'))
        self.assertEqual(transition(None,old,'2026-09-09T00:00:00Z',True),'reopened')
        self.assertIsNone(transition(old,old,'2026-09-09T00:00:00Z'))
        self.assertEqual(transition(old,pr(sha='c'),'x'),'synchronize')
        self.assertEqual(transition(pr(draft=True),old,'x'),'ready_for_review')
        self.assertEqual(transition(old,pr(state='closed'),'x'),'closed')
        self.assertEqual(transition(pr(state='closed'),old,'x'),'reopened')

    def test_durable_retry_and_no_initial_enqueue(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            github=Mock(side_effect=[{'id':1,'full_name':'rollingfruit/agent-governance-gw'},[[pr()]],[[pr(sha='c')]]])
            send=Mock(return_value={'ok':True})
            monitor=Monitor(github,send,path)
            monitor.tick()
            self.assertEqual([c.args[0] for c in send.call_args_list],['/internal/monitors/governance-local-poll'])
            send.side_effect=RuntimeError('SSH offline')
            with self.assertRaises(RuntimeError):
                monitor.tick()
            delivery=copy.deepcopy(monitor.state['pending'][0])
            resumed=Monitor(Mock(return_value=[[pr(sha='c')]]),Mock(return_value={'id':'real-id'}),path)
            resumed.tick()
            self.assertEqual(resumed.send.call_args_list[0].args,('/internal/submit',delivery))
            self.assertEqual(resumed.state['pending'],[])
            resumed.tick()
            self.assertEqual(sum(c.args[0]=='/internal/submit' for c in resumed.send.call_args_list),1)

    def test_missing_from_open_list_rechecks_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            github=Mock(side_effect=[{'id':1,'full_name':'rollingfruit/agent-governance-gw'},[[pr()]],[],pr(state='closed')])
            send=Mock(return_value={'ok':True})
            monitor=Monitor(github,send,Path(temp)/'state.json')
            monitor.tick()
            monitor.tick()
            self.assertEqual(monitor.state['seen']['102']['state'],'closed')
            posted=[c.args[1] for c in send.call_args_list if c.args[0]=='/internal/submit']
            self.assertEqual(posted[0]['event']['action'],'closed')


if __name__=='__main__':
    unittest.main()
