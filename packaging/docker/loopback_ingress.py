"""Translate approved same-PC public-IP traffic into the Docker LAN listeners."""
import hashlib
import json
import subprocess
import wsl_loopback


def command(args):
    return subprocess.run(args,check=False,capture_output=True,timeout=15)


def reconcile(directory,settings,run=command):
    chain='DSTLB'+hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    owner='dst-loopback-'+chain
    def ipt(*args,check=True):
        result=run(['iptables','-w','5','-t','nat',*args])
        if check and result.returncode:raise ValueError('Docker could not configure same-PC game traffic translation.')
        return result
    existing=ipt('-S',chain,check=False)
    if existing.returncode==0:
        # Never flush a chain containing a rule not owned by this installation.
        lines=existing.stdout.decode().splitlines()
        if any(line.startswith('-A ') and owner not in line for line in lines):raise ValueError('The Docker loopback chain contains an unrelated rule; it was left unchanged.')
    jump=['PREROUTING','-m','comment','--comment',owner,'-j',chain]
    if settings is None:
        if existing.returncode:
            return
        if ipt('-C',*jump,check=False).returncode==0:ipt('-D',*jump)
        ipt('-F',chain);ipt('-X',chain)
        return
    public=wsl_loopback.public_address(settings['publicIp'])
    target=wsl_loopback.private_address(settings['target'])
    source=wsl_loopback.private_address(settings['windowsIp'])
    if not target or not source or target==source:raise ValueError('Same-PC translation requires separate Windows and Docker addresses.')
    rules=[]
    for protocol,ports in (('tcp','31982'),('udp','7777:7810')):
        rules.append(['-s',source+'/32','-d',public+'/32','-p',protocol,'--dport',ports,'-m','comment','--comment',owner,'-j','DNAT','--to-destination',target])
    if existing.returncode:ipt('-N',chain)
    matches=[ipt('-C',chain,*rule,check=False).returncode==0 for rule in rules]
    count=sum(line.startswith('-A ') for line in existing.stdout.decode().splitlines()) if existing.returncode==0 else 0
    if not all(matches) or count!=2:
        ipt('-F',chain)
        for rule in rules:ipt('-A',chain,*rule)
    if ipt('-C',*jump,check=False).returncode:ipt('-I','PREROUTING','1',*jump[1:])


def configure(directory,change,network,run=command):
    path=directory/'loopback-ingress.json'
    if change['target']==network['dockerIp'] and network['dockerIp']!=network.get('windowsIp'):
        settings={'publicIp':change['publicIp'],'target':network['dockerIp'],'windowsIp':network['windowsIp']}
        reconcile(directory,settings,run)
        from host_session import write_json
        write_json(path,settings)
    else:
        reconcile(directory,None,run);path.unlink(missing_ok=True)


def restore(directory,network,windows_script,run=command):
    path=directory/'loopback-ingress.json'
    if not path.exists():return
    settings=json.loads(path.read_text())
    actual=wsl_loopback.snapshot(windows_script,settings['publicIp'])
    if actual['target']==settings['target']==network['dockerIp']:
        configure(directory,settings,network,run)
    else:
        reconcile(directory,None,run)
