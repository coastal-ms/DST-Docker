import base64
import json
import re
import unittest
from unittest.mock import Mock
from rmq_commands import expression,publish


class RmqTests(unittest.TestCase):
    def test_existing_envelope_preserves_unicode_and_never_interpolates_player_input(self):
        field={'ServerCommand':'AddItemToInventory','PlayerId':'abc123','ItemName':'quote " 生命\nend, os:cmd("bad")','Quantity':4,'Durability':1.0}
        code=expression([field],'fixed-game-auth',200)
        self.assertNotIn(field['ItemName'],code)
        encoded=re.findall(r'base64:decode\(<<"([A-Za-z0-9+/=]+)"',code)
        self.assertEqual(len(encoded),1)
        envelope=json.loads(base64.b64decode(encoded[0]));self.assertEqual(envelope['Version'],2)
        self.assertEqual(envelope['AuthToken'],'fixed-game-auth')
        self.assertEqual(json.loads(envelope['MessageContent']),field)

    def test_unbounded_or_unsupported_commands_never_reach_the_broker(self):
        engine=Mock(spec=['assert_owned','exec_internal'])
        for fields,spacing in [([{'ServerCommand':'ShellExec','command':'bad'}],0),([{'ServerCommand':'KickPlayer'}]*129,0),([{'ServerCommand':'KickPlayer'}]*4,5000)]:
            with self.assertRaises(ValueError):publish({},engine,fields,'auth',spacing)
        engine.assert_owned.assert_not_called();engine.exec_internal.assert_not_called()

    def test_broker_confirmation_is_required_and_exec_is_scoped_to_owned_rmq(self):
        state={'id':'a'*32,'desiredState':'running','connections':{'rmq-game':{'id':'owned-broker'}}}
        engine=Mock(spec=['assert_owned','exec_internal']);engine.assert_owned.return_value={'State':{'Health':{'Status':'healthy'}}}
        engine.exec_internal.return_value='{ok,enqueued,1}\n'
        result=publish(state,engine,[{'ServerCommand':'AwardXP','XP':5}],'auth',0)
        self.assertEqual(result,{'enqueued':1})
        engine.assert_owned.assert_called_with('owned-broker','a'*32,'rmq-game')
        args=engine.exec_internal.call_args.args
        self.assertEqual(args[:3],('owned-broker','a'*32,'rmq-game'))
        self.assertEqual(args[3][:2],['/opt/rabbitmq/sbin/rabbitmqctl','eval'])
        engine.exec_internal.return_value='ok'
        with self.assertRaisesRegex(ValueError,'not confirmed'):publish(state,engine,[{'ServerCommand':'AwardXP'}],'auth',0)


if __name__=='__main__':unittest.main()
