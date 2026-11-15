import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import unittest
import loopback_ingress as ingress


class Firewall:
    def __init__(self):self.chains={};self.jump=[];self.writes=[]
    def __call__(self,args):
        args=args[5:];action=args[0];chain=args[1]
        result=0;output=''
        if action=='-S':
            if chain not in self.chains:result=1
            else:output='\n'.join('-A '+chain+' '+' '.join(rule) for rule in self.chains[chain])
        elif action=='-C':result=0 if args[2:] in (self.jump if chain=='PREROUTING' else self.chains.get(chain,[])) else 1
        else:
            self.writes.append(args)
            if action=='-N':self.chains[chain]=[]
            elif action=='-F':self.chains[chain]=[]
            elif action=='-X':del self.chains[chain]
            elif action=='-A':self.chains[chain].append(args[2:])
            elif action=='-I':self.jump.append(args[3:])
            elif action=='-D':self.jump.remove(args[2:])
        return subprocess.CompletedProcess(args,result,output.encode(),b'')


class LoopbackIngressTests(unittest.TestCase):
    settings={'publicIp':'8.8.4.4','target':'192.168.23.106','windowsIp':'192.168.23.23'}
    def test_translation_is_limited_to_this_windows_pc_public_ip_and_game_ports(self):
        fw=Firewall();ingress.reconcile(Path('/fixture'),self.settings,fw)
        rules=list(fw.chains.values())[0]
        self.assertEqual(len(rules),2)
        for rule in rules:
            self.assertEqual(rule[rule.index('-s')+1],'192.168.23.23/32')
            self.assertEqual(rule[rule.index('-d')+1],'8.8.4.4/32')
            self.assertEqual(rule[rule.index('--to-destination')+1],'192.168.23.106')
        self.assertEqual([rule[rule.index('--dport')+1] for rule in rules],['31982','7777:7810'])
        fw.writes=[];ingress.reconcile(Path('/fixture'),self.settings,fw)
        self.assertEqual(fw.writes,[])

    def test_cleanup_removes_only_the_installation_chain_and_jump(self):
        fw=Firewall();fw.chains['DOCKER']=[['unrelated']]
        ingress.reconcile(Path('/fixture'),self.settings,fw)
        ingress.reconcile(Path('/fixture'),None,fw)
        self.assertEqual(fw.chains,{'DOCKER':[['unrelated']]});self.assertEqual(fw.jump,[])

    def test_foreign_rule_in_owned_chain_is_never_flushed(self):
        fw=Firewall();ingress.reconcile(Path('/fixture'),self.settings,fw)
        list(fw.chains.values())[0].append(['unrelated'])
        fw.writes=[]
        with self.assertRaisesRegex(ValueError,'unrelated'):ingress.reconcile(Path('/fixture'),self.settings,fw)
        self.assertEqual(fw.writes,[])

    def test_restart_restores_translation_only_for_the_still_selected_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fw=Firewall();network={'dockerIp':'192.168.23.106','windowsIp':'192.168.23.23'}
            ingress.configure(root,self.settings,network,fw)
            fw=Firewall()
            with patch('wsl_loopback.snapshot',return_value={'target':'192.168.23.106'}):ingress.restore(root,network,Mock(),fw)
            self.assertTrue(fw.jump)
            with patch('wsl_loopback.snapshot',return_value={'target':'192.168.23.219'}):ingress.restore(root,network,Mock(),fw)
            self.assertFalse(fw.jump)


if __name__=='__main__':unittest.main()
