import base64
import unittest
from unittest.mock import Mock
from rmq_chat import expression, operate


class ChatQueueTests(unittest.TestCase):
    def setUp(self):
        self.state = {'id': 'a'*32, 'desiredState': 'running',
                      'connections': {'rmq-game': {'id': 'owned-game-broker'}}}
        self.engine = Mock(spec=['assert_owned', 'exec_internal'])
        self.engine.assert_owned.return_value = {'State': {'Status': 'running', 'Health': {'Status': 'healthy'}}}

    def test_queue_is_fixed_transient_bounded_and_expires_messages(self):
        code = expression('declare')
        for expected in ['dst.chat.commands', 'chat.intercept', 'long,500', 'long,300000',
                         'drop-head', 'declare(QName,false,false', 'DSTCHAT:declared']:
            self.assertIn(expected, code)

    def test_no_arbitrary_operations_or_unbounded_drains(self):
        for action, maximum in [('exec', 25), ('drain', 0), ('drain', 26), ('drain', True), ('drain', '25')]:
            with self.assertRaises(ValueError):
                operate(self.state, self.engine, action, maximum)
        self.engine.assert_owned.assert_not_called()

    def test_drain_is_at_most_once_and_preserves_unicode_and_newlines(self):
        message = 'quote " 生命\n!water'
        self.engine.exec_internal.return_value = 'MSG:'+base64.b64encode(message.encode()).decode()+'\nDSTCHAT:drained\nok\n'
        result = operate(self.state, self.engine, 'drain', 1)
        self.assertEqual(result['messages'], [message])
        self.engine.assert_owned.assert_called_once_with('owned-game-broker', 'a'*32, 'rmq-game')
        args = self.engine.exec_internal.call_args.args
        self.assertEqual(args[:3], ('owned-game-broker', 'a'*32, 'rmq-game'))
        self.assertIn('basic_get(Q,true', args[3][2])
        self.assertIn('byte_size(Body) =< 65536', args[3][2])

    def test_missing_completion_marker_never_claims_success(self):
        self.engine.exec_internal.return_value = 'ok'
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            operate(self.state, self.engine, 'declare')

    def test_stopped_or_busy_world_does_not_drain(self):
        for change in [{'desiredState': 'stopped'}, {'operation': {'phase': 'running'}}]:
            with self.assertRaises(ValueError):
                operate({**self.state, **change}, self.engine, 'drain')
        self.engine.assert_owned.assert_not_called()

    def test_stale_healthy_status_on_stopped_broker_cannot_execute(self):
        self.engine.assert_owned.return_value['State']['Status'] = 'exited'
        with self.assertRaisesRegex(ValueError, 'not ready'):
            operate(self.state, self.engine, 'declare')
        self.assertTrue(operate(self.state, self.engine, 'delete')['skipped'])
        self.engine.exec_internal.assert_not_called()

    def test_delete_can_remove_the_queue_while_world_is_stopping(self):
        self.engine.exec_internal.return_value = 'DSTCHAT:deleted\nok\n'
        self.assertFalse(operate({**self.state, 'desiredState': 'stopped'}, self.engine, 'delete')['skipped'])

    def test_foreign_broker_rejection_precedes_exec(self):
        self.engine.assert_owned.side_effect = ValueError('not owned')
        with self.assertRaisesRegex(ValueError, 'not owned'):
            operate(self.state, self.engine, 'drain')
        self.engine.exec_internal.assert_not_called()

    def test_extra_or_oversized_messages_fail_the_transport_bound(self):
        for raw in ['MSG:YQ==\nMSG:Yg==\nDSTCHAT:drained',
                    'MSG:'+base64.b64encode(b'x'*65537).decode()+'\nDSTCHAT:drained']:
            self.engine.exec_internal.return_value = raw
            with self.assertRaisesRegex(ValueError, 'transport limit'):
                operate(self.state, self.engine, 'drain', 1)


if __name__ == '__main__':
    unittest.main()
