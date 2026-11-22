import base64
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
import wsl_lan


class WslLanTests(unittest.TestCase):
    def test_mode_edit_preserves_ram_unknown_settings_and_encoding(self):
        raw=b'\xff\xfe'+('[wsl2]\r\nmemory=40GB\r\nnetworkingMode=nat\r\nkernelCommandLine=quiet\r\n[experimental]\r\nsparseVhd=true\r\n').encode('utf-16le')
        result=wsl_lan.update_config(raw,{'mode':'bridged','switch':'Orbi Switch'})
        self.assertTrue(result.startswith(b'\xff\xfe'))
        text=result[2:].decode('utf-16le')
        for expected in ['memory=40GB\r\n','networkingMode=bridged\r\n','vmSwitch=Orbi Switch\r\n','kernelCommandLine=quiet\r\n','[experimental]\r\nsparseVhd=true\r\n']:self.assertIn(expected,text)
        self.assertEqual(text.count('networkingMode='),1)
        self.assertNotIn('vmSwitch',wsl_lan.update_config(result,{'mode':'nat','switch':''})[2:].decode('utf-16le'))

    def test_rejects_invalid_static_addresses_before_any_windows_write(self):
        for address in ['8.8.4.4','127.0.0.1','169.254.1.2','192.0.2.1','192.168.23.0','192.168.23.255','bad']:
            with self.subTest(address=address),self.assertRaises(ValueError):wsl_lan.validate({'mode':'bridged','switch':'LAN','address':address,'prefix':24})
        for switch in ['','bad\nmode=other','bad#switch','*']:
            with self.subTest(switch=switch),self.assertRaises(ValueError):wsl_lan.validate({'mode':'bridged','switch':switch})

    def fixture(self,root,address='192.168.23.220',prefix=24):
        (root/'lan-settings.json').write_text(json.dumps({'mode':'bridged','switch':'LAN','address':address,'prefix':prefix}))
        def command(args):
            if args[0]=='wslinfo':return Mock(stdout=b'bridged\n')
            if args[:5]==['ip','-j','-4','route','get']:return Mock(stdout=json.dumps([{'dev':'eth0'}]).encode())
            if args[:4]==['ip','-j','-4','address']:return Mock(stdout=json.dumps([{'address':'00:15:5d:00:00:01','addr_info':[{'family':'inet','local':'192.168.23.100','prefixlen':24,'label':'eth0'}]}]).encode())
            return Mock(stdout=b'')
        return Mock(side_effect=command)

    def test_duplicate_address_never_changes_the_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);run=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'already in use'):wsl_lan.apply(root,run,Mock(return_value=True))
            self.assertFalse(any(call.args[0][:3]==['ip','address','add'] for call in run.call_args_list))
            self.assertFalse((root/'lan-address-owned.json').exists())

    def test_adds_only_a_validated_secondary_address_and_records_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);run=self.fixture(root);probe=Mock(return_value=False)
            wsl_lan.apply(root,run,probe)
            additions=[call.args[0] for call in run.call_args_list if call.args[0][:3]==['ip','address','add']]
            self.assertEqual(len(additions),1);self.assertEqual(additions[0][3],'192.168.23.220/24')
            self.assertFalse(any('default' in call.args[0] or 'del' in call.args[0] for call in run.call_args_list))
            self.assertEqual(json.loads((root/'lan-address-owned.json').read_text())['address'],'192.168.23.220')
            probe.assert_called_once()

    def test_wrong_subnet_or_prefix_is_rejected_without_probing_or_writing(self):
        for address,prefix in [('192.168.24.220',24),('192.168.23.220',16)]:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);run=self.fixture(root,address,prefix);probe=Mock()
                with self.assertRaisesRegex(ValueError,'subnet prefix'):wsl_lan.apply(root,run,probe)
                probe.assert_not_called()

    def test_dhcp_removes_only_the_current_boot_owned_alias(self):
        for owned in (True,False):
            with self.subTest(owned=owned),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);base=self.fixture(root,address='')
                label='eth0:d'+hashlib.sha256(str(root).encode()).hexdigest()[:4]
                previous={'address':'192.168.23.220','prefix':24,'interface':'eth0','label':label,'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
                (root/'lan-address-owned.json').write_text(json.dumps(previous))
                def command(args):
                    result=base(args)
                    if args[:4]==['ip','-j','-4','address']:
                        value=json.loads(result.stdout)
                        value[0]['addr_info'].append({'family':'inet','local':previous['address'],'prefixlen':24,'label':label if owned else 'eth0:manual'})
                        return Mock(stdout=json.dumps(value).encode())
                    return result
                run=Mock(side_effect=command);wsl_lan.apply(root,run,Mock())
                deletions=[call.args[0] for call in run.call_args_list if call.args[0][:3]==['ip','address','del']]
                self.assertEqual(deletions,[['ip','address','del','192.168.23.220/24','dev','eth0']] if owned else [])
                self.assertFalse((root/'lan-address-owned.json').exists())

    def test_reopening_with_the_owned_address_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=self.fixture(root)
            label='eth0:d'+hashlib.sha256(str(root).encode()).hexdigest()[:4]
            def command(args):
                result=base(args)
                if args[:4]==['ip','-j','-4','address']:
                    value=json.loads(result.stdout)
                    value[0]['addr_info'].append({'family':'inet','local':'192.168.23.220','prefixlen':24,'label':label})
                    return Mock(stdout=json.dumps(value).encode())
                return result
            run=Mock(side_effect=command);probe=Mock();wsl_lan.apply(root,run,probe)
            probe.assert_not_called()
            self.assertFalse(any(call.args[0][:2]==['ip','address'] for call in run.call_args_list))

    def test_saving_stages_configuration_and_a_windows_recovery_path_without_assigning_an_ip(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def windows(script):
                if script==wsl_lan.EXTERNAL_SWITCHES_SCRIPT:return '["LAN"]'
                if 'physicalBytes' in script:return json.dumps({'content':base64.b64encode(b'[wsl2]\nmemory=40GB\n').decode(),'physicalBytes':64*1024**3})
                if 'Recover Docker network' in script:return 'C:\\Desktop\\Recover Docker network.cmd'
                return 'saved'
            result=wsl_lan.settings(Mock(side_effect=windows),root,{'networkingMode':'nat','dockerIp':'172.25.1.2','windowsIp':'192.168.23.23'}, {'mode':'bridged','switch':'LAN','address':'192.168.23.220','prefix':24})
            self.assertTrue(result['restartRequired']);self.assertIn('Recover Docker network',result['recoveryShortcut'])
            self.assertFalse((root/'lan-address-owned.json').exists())

    def test_lists_only_usable_switch_names_and_keeps_the_saved_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            windows=Mock(return_value='["Office LAN","LAN","LAN","bad#name"]')
            result=wsl_lan.settings(windows,root,{'networkingMode':'bridged','dockerIp':'192.168.23.220'})
            self.assertEqual(result['externalSwitches'],['LAN','Office LAN'])
            self.assertEqual(result['settings']['switch'],'LAN')
            windows.assert_called_once_with(wsl_lan.EXTERNAL_SWITCHES_SCRIPT)

    def test_rejects_unverifiable_switches_before_writing_windows_or_linux_settings(self):
        for discovered in ('[]','["Office LAN"]','"invalid"',subprocess.CalledProcessError(1,'powershell')):
            with self.subTest(discovered=discovered),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                windows=Mock(side_effect=[discovered])
                with self.assertRaisesRegex(ValueError,'unavailable|could not verify'):
                    wsl_lan.settings(windows,root,{'networkingMode':'nat','dockerIp':'172.25.1.2'}, {'mode':'bridged','switch':'Ethernet'})
                windows.assert_called_once_with(wsl_lan.EXTERNAL_SWITCHES_SCRIPT)
                self.assertEqual(list(root.iterdir()),[])


if __name__=='__main__':unittest.main()
