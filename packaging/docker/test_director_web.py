import unittest
from unittest.mock import Mock
from engine import Engine
from director_web import endpoint


class DirectorWebTests(unittest.TestCase):
    def setUp(self):
        self.state={'id':'a'*32,'services':{'director':{'id':'owned-director'}},'worldPlan':{'ports':{'director':29777}}}
        self.engine=Mock(spec=Engine)
        self.engine.assert_owned.return_value={'State':{'Status':'running'},'HostConfig':{'PortBindings':{'11717/tcp':[{'HostIp':'127.0.0.1','HostPort':'29777'}]}}}

    def test_only_the_owned_exact_loopback_binding_is_published(self):
        self.assertEqual(endpoint(self.state,self.engine),{'available':True,'port':29777})
        self.engine.assert_owned.assert_called_once_with('owned-director','a'*32,'director')
        self.engine.lifecycle.assert_not_called()

    def test_foreign_binding_or_public_listener_is_not_a_proxy_target(self):
        for ip,port in [('0.0.0.0','29777'),('127.0.0.1','8088')]:
            self.engine.assert_owned.return_value['HostConfig']['PortBindings']['11717/tcp']=[{'HostIp':ip,'HostPort':port}]
            with self.assertRaisesRegex(ValueError,'owned loopback'):endpoint(self.state,self.engine)

    def test_stopped_director_is_not_started_by_a_page_read(self):
        self.engine.assert_owned.return_value['State']['Status']='exited'
        self.assertEqual(endpoint(self.state,self.engine),{'available':False,'port':29777})
        self.engine.lifecycle.assert_not_called()


if __name__=='__main__':unittest.main()
