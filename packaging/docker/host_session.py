"""Foreground WSL hosting session and narrowly scoped desktop integration.

No daemon or scheduled task: the installed DST shortcut owns this visible
session. Containers can request status, WSL memory settings, shortcut or shutdown.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import ipaddress
import os
import pwd
from pathlib import Path
import shlex
import signal
import socket
import struct
import subprocess
import threading
import time
import sys
import uuid

WSL='/mnt/c/Windows/System32/wsl.exe'
POWERSHELL='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
BROWSERS={'default':'System default','chrome':'Google Chrome','edge':'Microsoft Edge','firefox':'Mozilla Firefox'}

def run(args,**kwargs):
    if 'input' not in kwargs and 'stdin' not in kwargs:kwargs['stdin']=subprocess.DEVNULL
    return subprocess.run(args,check=True,capture_output=True,timeout=kwargs.pop('timeout',60),**kwargs)

def ps_literal(value):return "'"+str(value).replace("'","''")+"'"

def windows_script(script,timeout=60):
    encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return run([POWERSHELL,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],timeout=timeout).stdout.decode('utf-8',errors='replace').strip()

def write_json(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.chmod(0o600)
    if os.geteuid()==0:
        owner=path.parent.stat();os.chown(temporary,owner.st_uid,owner.st_gid,follow_symlinks=False)
    temporary.replace(path)

def running_distros():
    raw=run([WSL,'--list','--running','--quiet']).stdout
    text=raw.decode('utf-16le' if b'\x00' in raw else 'utf-8-sig')
    return [line.strip() for line in text.splitlines() if line.strip()]

class HostSession:
    def __init__(self,root):
        self.root=Path(root).resolve();self.directory=self.root/'host-session'
        self.config=json.loads((self.directory/'config.json').read_text(encoding='utf-8'))
        self.phase='ready';self.message='DST host session is running.';self.busy=False;self.lock=threading.Lock()
        self.shutdown_finished=threading.Event();self.shutdown_finished.set()
        self.open_finished=threading.Event();self.open_finished.set()
    def docker(self,*args,**kwargs):return run(['docker',*args],**kwargs).stdout.decode('utf-8').strip()
    def compose(self,*args):
        command=['compose','-p',self.config['project']]
        for path in self.config['composeFiles']:command+=['-f',path]
        update=self.root/'update.compose.json'
        if update.exists() and str(update) not in self.config['composeFiles']:command+=['-f',str(update)]
        return self.docker(*command,*args,timeout=300)
    def app_id(self):return self.compose('ps','-q','dst')
    def manager(self,action,**values):
        reply=json.loads(self.docker('exec','-i',self.app_id(),'python3','/opt/dst/packaging/docker/manager-client.py',input=json.dumps({'action':action,**values}).encode()))
        if not reply.get('ok'):raise ValueError(reply.get('error','Docker manager unavailable.'))
        return reply['data']
    def progress(self,phase,message):
        with self.lock:self.phase=phase;self.message=message
        print(message,flush=True)
    def owner_recovery(self,reader=None):
        reader=reader or input
        with self.lock:
            if self.busy:raise ValueError('Wait for the current host operation before recovering an Owner.')
            previous=(self.phase,self.message)
            self.busy=True
            self.phase='recovering-owner';self.message='Owner recovery is open in the hosting window.'
        try:
            command=['exec','-T','dst','pwsh','-NoLogo','-NoProfile','-File','/opt/dst/packaging/docker/owner-recovery.ps1']
            listed=self.compose(*command,'-Action','List')
            owners=[line.split('\t',1)[1] for line in listed.splitlines() if line.startswith(('Enabled\t','Disabled\t'))]
            if not owners:
                self.show_first_setup_link();return
            if len(owners)==1:username=owners[0]
            else:
                for number,username in enumerate(owners,1):print(f'{number}. {username}',flush=True)
                selected=reader('Owner number (Enter to cancel): ').strip()
                if not selected:return
                if not selected.isdigit() or not 1<=int(selected)<=len(owners):raise ValueError('Choose an Owner number from the list.')
                username=owners[int(selected)-1]
            print('Reset password for Owner: '+username,flush=True)
            confirmation='RESET OWNER'
            # The generated password is shown only in this local hosting window.
            print(self.compose(*command,'-Action','Reset','-Username',username,'-Confirmation',confirmation),flush=True)
        finally:
            with self.lock:
                self.busy=False;self.phase,self.message=previous
    def management_terminal(self):
        environment={**os.environ,'COMPOSE_PROJECT_NAME':self.config['project'],'COMPOSE_FILE':os.pathsep.join(self.config['composeFiles'])}
        print('Management terminal. Type exit to return to the hosting menu.',flush=True)
        subprocess.run(['bash','--noprofile','--norc','-i'],cwd=self.config['source'],env=environment,check=False)
    def browser_preference(self):
        path=self.directory/'browser.json'
        if not path.exists():return 'default'
        value=json.loads(path.read_text(encoding='utf-8')).get('browser','default')
        if value not in BROWSERS:raise ValueError('Choose a browser using option 6 in the hosting window.')
        return value
    def owner_setup_required(self):
        listed=self.compose('exec','-T','dst','pwsh','-NoLogo','-NoProfile','-File',
                            '/opt/dst/packaging/docker/owner-recovery.ps1','-Action','List')
        return not any(line.startswith(('Enabled\t','Disabled\t')) for line in listed.splitlines())
    def show_first_setup_link(self):
        from portal_urls import portal_urls
        from urllib.parse import urlsplit,urlunsplit
        local=portal_urls(self.compose('exec','-T','dst','cat','/data/state/DuneServer/last-url.txt'),[])[0]
        parsed=urlsplit(local)
        origin=urlsplit(getattr(self,'console_origin',f'http://127.0.0.1:{parsed.port}'))
        link=urlunsplit(parsed._replace(scheme=origin.scheme,netloc=origin.netloc))
        print('\nCreate your first Owner account:\n  '+link,flush=True)
        print('Open this complete link in your browser. Keep this hosting window open; your setup continues from here.',flush=True)
    def choose_browser(self,reader=None):
        reader=reader or input
        current=self.browser_preference()
        for number,(key,label) in enumerate(BROWSERS.items(),1):
            print(f'{number}  {label}'+(' (selected)' if key==current else ''),flush=True)
        choice=reader('Browser number (Enter to keep current): ').strip()
        if not choice:return
        if not choice.isdigit() or not 1<=int(choice)<=len(BROWSERS):raise ValueError('Choose a browser number from the list.')
        selected=list(BROWSERS)[int(choice)-1]
        if selected!='default':self.browser_executable(selected)
        write_json(self.directory/'browser.json',{'browser':selected})
        print(f'Browser saved: {BROWSERS[selected]}. Use option 1 to open it.',flush=True)
    def browser_executable(self,browser):
        executable,relative={'chrome':('chrome.exe',r'Google\Chrome\Application\chrome.exe'),'edge':('msedge.exe',r'Microsoft\Edge\Application\msedge.exe'),'firefox':('firefox.exe',r'Mozilla Firefox\firefox.exe')}[browser]
        script="""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$paths=@()
foreach($hive in @('HKCU:','HKLM:')){
 foreach($prefix in @('SOFTWARE','SOFTWARE\\WOW6432Node')){
  $key=Join-Path $hive ($prefix+'\\Microsoft\\Windows\\CurrentVersion\\App Paths\\'+EXE)
  if(Test-Path -LiteralPath $key){$paths+=(Get-Item -LiteralPath $key).GetValue('')}
 }
}
foreach($folder in @($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA)){
 if($folder){$paths+=Join-Path $folder RELATIVE}
}
foreach($path in $paths){
 if($path -and (Test-Path -LiteralPath $path -PathType Leaf)){Write-Output $path;break}
}
""".replace('EXE',ps_literal(executable)).replace('RELATIVE',ps_literal(relative))
        path=windows_script(script)
        if not path:raise ValueError(f'{BROWSERS[browser]} is not installed. Install it or choose another browser with option 6.')
        return path
    def open_browser(self):
        if self.owner_setup_required():
            # Keep the private setup token in this local window, never in the
            # permanent shortcut or a Windows process command line.
            self.show_first_setup_link();return
        browser=self.browser_preference();url=self.browser_url()
        if browser=='default':windows_script('Start-Process '+ps_literal(url))
        else:
            path=self.browser_executable(browser)
            windows_script('Start-Process -FilePath '+ps_literal(path)+' -ArgumentList '+ps_literal(subprocess.list2cmdline([url])))
    def console_menu(self,reader=None):
        reader=reader or input
        print('\nDST Docker\n  1  Open browser\n  2  Create Owner account / recover password\n  3  Open management terminal\n  4  Recreate desktop shortcut\n  5  Shut down host\n  6  Choose browser',flush=True)
        while True:
            try:
                choice=reader('Choose an option: ').strip()
                if choice=='1':
                    self.request({'action':'open','browser':True},peer_uid=os.getuid())
                    self.open_finished.wait()
                elif choice=='2':self.owner_recovery(reader)
                elif choice=='3':self.management_terminal()
                elif choice=='4':print(self.shortcut(),flush=True)
                elif choice=='6':self.choose_browser(reader)
                elif choice=='5':
                    self.request({'action':'shutdown','confirmation':'SHUT DOWN HOST'})
                    self.shutdown_finished.wait()
                    if self.phase!='failed':return
                elif choice:print('Choose a menu number. Option3 opens a command terminal.',flush=True)
            except (EOFError,OSError):return
            except (ValueError,subprocess.SubprocessError) as error:
                print(str(error) if isinstance(error,ValueError) else 'The action failed. Check the console and try again.',flush=True)
    def containers(self):
        ids=self.docker('ps','-q').split()
        return json.loads(self.docker('inspect',*ids)) if ids else []
    def select_owned(self,containers,world):
        owned=[]
        for row in containers:
            labels=row.get('Config',{}).get('Labels') or {}
            managed=labels.get('io.dst.managed')=='true'
            if labels.get('com.docker.compose.project')==self.config['project'] or (managed and (labels.get('io.dst.project')==world or labels.get('io.dst.component')=='settings')):
                owned.append(row['Id'])
            else:raise ValueError('Another Docker workload is running. Stop it before shutting down WSL from DST.')
        return owned
    def preflight(self):
        if (self.directory/'lan-settings.json').exists() and any(name!=self.config['distribution'] for name in running_distros()):
            raise ValueError('Close other running WSL distributions before restarting the Docker host network.')
        state=self.manager('status')
        if (state.get('operation') or {}).get('phase') in {'running','preparing'}:raise ValueError('Wait for the current server operation before shutting down.')
        # A host stop cannot interrupt a backup still completing after its manager operation.
        if any(b.get('phase') in {'preparing','running'} for b in state.get('backups',[])):raise ValueError('Wait for the active backup before shutting down.')
        self.select_owned(self.containers(),state.get('projectId'))
        return state
    def shortcut(self):
        source=Path(self.config['source'])
        icon=run(['wslpath','-w',str(source/'app/assets/icon.ico')]).stdout.decode().strip()
        # Windows quoting for the wsl.exe argv; no shell command is assembled.
        arguments=subprocess.list2cmdline(['-d',self.config['distribution'],'-u','root','--','python3',str(source/'packaging/docker/host_session.py'),'desktop','--root',str(self.root)])
        marker='DST Docker '+str(self.root)
        suffix=hashlib.sha256(str(self.root).encode()).hexdigest()[:8]
        script="""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$folder=Join-Path $env:LOCALAPPDATA 'DST-Docker';New-Item -ItemType Directory -Path $folder -Force|Out-Null
$icon=Join-Path $folder 'dst.ico';Copy-Item -LiteralPath SOURCEICON -Destination $icon -Force
$path=Join-Path ([Environment]::GetFolderPath('Desktop')) 'DST Docker.lnk'
$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut($path)
if((Test-Path -LiteralPath $path) -and $link.Description -cne MARKER){
 $path=Join-Path ([Environment]::GetFolderPath('Desktop')) ALTERNATENAME
 $link=$shell.CreateShortcut($path)
 if((Test-Path -LiteralPath $path) -and $link.Description -cne MARKER){throw 'A different DST Docker shortcut already exists at this installation path.'}
}
$link.TargetPath=Join-Path $env:WINDIR 'System32\\wsl.exe'
$link.Arguments=ARGUMENTS
$link.Description=MARKER
$link.IconLocation=$icon
$link.WorkingDirectory=$env:USERPROFILE
$link.Save()
Write-Output $path
""".replace('SOURCEICON',ps_literal(icon)).replace('MARKER',ps_literal(marker)).replace('ARGUMENTS',ps_literal(arguments)).replace('ALTERNATENAME',ps_literal('DST Docker ('+suffix+').lnk'))
        return windows_script(script)
    def shutdown(self,state):
        try:
            time.sleep(.5)
            resume_path=self.directory/'resume.json'
            previous=json.loads(resume_path.read_text()) if resume_path.exists() else {}
            write_json(resume_path,{'world':state.get('projectId'),'resume':state.get('desiredState')=='running' or (previous.get('world')==state.get('projectId') and previous.get('resume',False))})
            self.progress('stopping-battlegroup','Stopping battlegroup and waiting for game processes to exit...')
            result=self.manager('services.stop');operation=result.get('operation',{}).get('id')
            resume=json.loads(resume_path.read_text());resume['stopOperation']=operation;write_json(resume_path,resume)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                current=self.manager('status');op=current.get('operation') or {}
                if op.get('id')!=operation:raise ValueError('The shutdown operation changed; WSL remains running.')
                if op.get('phase') in {'failed','interrupted'}:raise ValueError('Battlegroup stop failed; WSL remains running.')
                if op.get('phase')=='completed':break
                time.sleep(2)
            else:raise ValueError('Battlegroup stop is still pending; WSL remains running.')
            if any(s.get('state') in {'running','restarting'} for s in current.get('services',[]) if s.get('component','').startswith('game-')):
                raise ValueError('A map is still running; WSL remains running.')
            owned=self.select_owned(self.containers(),current.get('projectId'))
            self.progress('stopping-containers','Battlegroup stopped. Stopping DST containers cleanly; this page will disconnect...')
            time.sleep(3)
            if owned:self.docker('stop','--time','120',*owned,timeout=240)
            if self.containers():raise ValueError('A Docker workload is still running; WSL remains running. Use the DST icon to reopen the console.')
            self.progress('shutting-down-wsl','DST containers stopped. Stopping the DST WSL distribution. Use the DST Docker icon to start again.')
            # All owned containers are stopped before the host-level request.
            network_restart=(self.directory/'lan-settings.json').exists()
            if network_restart and any(name!=self.config['distribution'] for name in running_distros()):
                raise ValueError('Another WSL distribution started. Close it before restarting the Docker host network; WSL remains running.')
            command=[WSL,'--shutdown'] if network_restart else [WSL,'--terminate',self.config['distribution']]
            run(command,timeout=60)
        except Exception as error:
            self.progress('failed',str(error) if isinstance(error,ValueError) else 'Host shutdown failed. WSL was not deliberately shut down; inspect this DST console.')
        finally:
            with self.lock:self.busy=False
            self.shutdown_finished.set()
    def request(self,request,peer_uid=None):
        action=request.get('action')
        if action=='open':
            # Only the local desktop launcher can reopen this foreground host.
            # The unprivileged console container cannot invoke this operation.
            if peer_uid not in {0,os.getuid()}:raise ValueError('Use the installed desktop icon to reopen DST.')
            if type(request.get('browser')) is not bool:raise ValueError('Choose whether to open the browser.')
            with self.lock:
                if self.busy:raise ValueError('A host operation is still running. Check the existing DST window.')
                self.busy=True
            self.open_finished.clear()
            threading.Thread(target=self.recover_console,args=(request['browser'],),daemon=True).start()
            return {'accepted':True}
        if action=='status':
            with self.lock:return {'available':True,'platform':'wsl','phase':self.phase,'message':self.message,'busy':self.busy,'localMenuAvailable':bool(getattr(self,'menu_thread',None) and self.menu_thread.is_alive())}
        if action=='network.get':return self.network_info(request.get('publicIp'))
        if action=='loopback.get':
            import wsl_loopback
            result=wsl_loopback.snapshot(windows_script,request.get('publicIp'))
            operation=wsl_loopback.operation(self.directory)
            if operation and operation.get('publicIp')==result['publicIp']:result['operation']=operation
            return result
        if action=='loopback.set':
            import wsl_loopback
            change=wsl_loopback.validate(request)
            with self.lock:
                if self.busy:raise ValueError('Wait for the current host operation to finish.')
                current=wsl_loopback.snapshot(windows_script,change['publicIp'])
                if current.get('multiple') or current.get('target')!=change['expectedTarget']:raise ValueError('The loopback route changed. Refresh and review it before applying.')
                if current.get('target')==change['target']:return current
                if change['target'] in current.get('windowsAddresses',[]):
                    raise ValueError('The loopback target is an address on this Windows PC. Use router NAT loopback or a separate server address.')
                operation={'id':uuid.uuid4().hex,'phase':'running',**change}
                write_json(self.directory/'loopback-operation.json',operation)
                self.busy=True
                self.phase='applying-loopback';self.message='Approve the Windows permission prompt to change the same-PC loopback target.'
            threading.Thread(target=self.change_loopback,args=(change,operation),daemon=True).start()
            return {**current,'operation':operation}
        if action in {'network.settings.get','network.settings.set','network.settings.set-bridged'}:
            import wsl_lan
            with self.lock:
                if self.busy:raise ValueError('Wait for the current host operation to finish.')
                return wsl_lan.settings(windows_script,self.directory,self.network_info(),request.get('settings') if action!='network.settings.get' else None)
        if action in {'memory.get','memory.set'}:
            import wsl_memory
            if action=='memory.set' and 'memoryGiB' not in request:raise ValueError('Choose a RAM limit or the WSL default.')
            current=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))*1024
            boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            with self.lock:
                return wsl_memory.settings(windows_script,self.directory,current,boot_id,request.get('memoryGiB') if action=='memory.set' else wsl_memory.READ)
        if action=='shortcut':
            with self.lock:
                if self.busy:raise ValueError('Wait for host shutdown before recreating a shortcut.')
            return {'path':self.shortcut()}
        if action=='shutdown':
            if request.get('confirmation')!='SHUT DOWN HOST':raise ValueError('Confirm the host shutdown.')
            with self.lock:
                if self.busy:raise ValueError('Host shutdown is already in progress.')
                self.busy=True
            try:state=self.preflight()
            except Exception:
                with self.lock:self.busy=False
                raise
            self.shutdown_finished.clear()
            threading.Thread(target=self.shutdown,args=(state,),daemon=True).start()
            return {'accepted':True}
        raise ValueError('Choose a supported host action.')
    def change_loopback(self,change,operation):
        import wsl_loopback
        import loopback_ingress
        path=self.directory/'loopback-ingress.json'
        previous=json.loads(path.read_text()) if path.exists() else None
        prepared=False
        try:
            network=self.network_info()
            if change['target']==network['dockerIp']:
                loopback_ingress.configure(self.directory,change,network)
                prepared=True
            wsl_loopback.apply(lambda script:windows_script(script,timeout=180),change)
            current=wsl_loopback.snapshot(windows_script,change['publicIp'])
            if current.get('target')!=change['target']:raise ValueError('Windows did not confirm the new loopback target.')
            loopback_ingress.configure(self.directory,change,network)
            operation['phase']='completed'
        except Exception as error:
            if prepared:
                try:
                    current=wsl_loopback.snapshot(windows_script,change['publicIp'])
                    if current.get('target')!=change['target']:
                        loopback_ingress.reconcile(self.directory,previous)
                        if previous:write_json(path,previous)
                        else:path.unlink(missing_ok=True)
                except Exception:pass
            operation['phase']='failed'
            operation['error']=str(error) if isinstance(error,ValueError) else 'Windows could not apply the loopback route. Check the Windows permission prompt, then refresh the current target.'
        finally:
            write_json(self.directory/'loopback-operation.json',operation)
            with self.lock:
                self.busy=False;self.phase='ready';self.message='DST host session is running.'
    def start(self,open_browser=True):
        # This foreground process, rather than a systemd service, owns WSL lifetime.
        self.session_lock=(self.directory/'session.lock').open('a')
        try:fcntl.flock(self.session_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.session_lock.close()
            self.reopen_existing(open_browser)
            return
        self.start_console(open_browser)
        self.serve()
    def reopen_existing(self,open_browser):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(15)
            try:
                connection.connect(str(self.directory/'host.sock'))
                connection.sendall(json.dumps({'action':'open','browser':open_browser}).encode()+b'\n')
                with connection.makefile('rb') as stream:raw=stream.readline(65537)
                if len(raw)>65536:raise ValueError('Host response is too large.')
                result=json.loads(raw)
            except (OSError,json.JSONDecodeError):raise ValueError('The existing DST window is not responding. Check that window before starting again.')
            if not result.get('ok'):raise ValueError(result.get('error','DST could not reopen the console.'))
        print('Reopening DST in its existing hosting window.',flush=True)
    def recover_console(self,open_browser):
        try:
            self.progress('starting','Reopening the DST console...')
            self.start_console(open_browser)
            with self.lock:
                if self.phase=='starting':
                    self.phase='ready';self.message='DST console is available. Keep this hosting window open.'
            print(self.message,flush=True)
        except Exception as error:
            self.progress('failed',str(error) if isinstance(error,ValueError) else 'The console could not reopen. Check Docker access in this DST window and retry the desktop icon.')
        finally:
            with self.lock:self.busy=False
            self.open_finished.set()
    def prepare_backup_mirror(self):
        import mirror_config
        # Preserve an existing custom mount, including folders configured by
        # the command-line launcher. Never silently replace a user's target.
        effective=json.loads(self.compose('config','--format','json'))
        volumes=effective.get('services',{}).get('manager',{}).get('volumes',[])
        if any(row.get('target')=='/mirror' for row in volumes):return
        override=self.root/'mirror.compose.json'
        account=pwd.getpwuid(self.root.stat().st_uid)
        if override.exists():
            folder=json.loads(override.read_text(encoding='utf-8'))['x-dst-backup-mirror-folder']
        else:
            folder=os.environ.get('DST_BACKUP_MIRROR_DIR') or str(Path(account.pw_dir)/'.local/state/dst-docker/backups'/self.config['project'])
        mirror_config.prepare(self.config['project'],folder,override,self.config['distribution'],owner=(account.pw_uid,account.pw_gid))
        self.config['composeFiles']=list(dict.fromkeys([*self.config['composeFiles'],str(override)]))
        config_path=self.directory/'config.json';previous=config_path.stat()
        write_json(config_path,self.config)
        os.chown(config_path,previous.st_uid,previous.st_gid)
    def start_console(self,open_browser):
        # Installer upgrades can replace the active release while this window
        # remains open. Reopen the saved current installation, not an old release.
        self.config=json.loads((self.directory/'config.json').read_text(encoding='utf-8'))
        self.network_error=None
        self.network_pending=False
        if (self.directory/'lan-settings.json').exists():
            import wsl_lan
            try:
                wsl_lan.apply(self.directory,run)
                desired=json.loads((self.directory/'lan-settings.json').read_text())
                actual=run(['wslinfo','--networking-mode']).stdout.decode().strip().lower()
                self.network_pending=desired['mode']!=actual
                write_json(self.directory/'lan-settings-status.json',{})
            except (ValueError,OSError,subprocess.SubprocessError) as error:
                self.network_error=str(error)
                write_json(self.directory/'lan-settings-status.json',{'error':self.network_error})
        # HTTPS can be enabled or disabled after this hosting window opened.
        # Follow the active override, including a return to the HTTP listener.
        tls=self.root/'https.compose.json';host=self.root/'host.compose.json'
        files=[file for file in self.config['composeFiles'] if file not in {str(tls),str(host)}]
        if tls.exists():files.append(str(tls))
        if host.exists():files.append(str(host))
        self.config['composeFiles']=files
        self.prepare_backup_mirror()
        self.compose('up','-d','--no-build')
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            try:
                url=self.docker('exec',self.app_id(),'cat','/data/state/DuneServer/last-url.txt')
                inspected=json.loads(self.docker('inspect',self.app_id()))[0]
                if inspected['State'].get('Health',{}).get('Status')=='healthy':break
            except (subprocess.SubprocessError,ValueError,KeyError):pass
            time.sleep(2)
        else:raise ValueError('DST console did not become healthy. Check Docker logs; no world was reset.')
        # Never put the one-time setup token in a shortcut or Windows command line.
        from urllib.parse import urlsplit
        parts=urlsplit(url)
        addresses=run(['hostname','-I']).stdout.decode().split()
        address=next((str(ipaddress.ip_address(value)) for value in addresses if ':' not in value and not ipaddress.ip_address(value).is_loopback),'127.0.0.1')
        origin=f'http://{address}:{parts.port or 8088}'
        for file in self.config['composeFiles']:
            if file.endswith('.json'):
                value=json.loads(Path(file).read_text(encoding='utf-8'))
                if value.get('x-dst-https-origin'):origin=value['x-dst-https-origin']
        if origin.startswith('http://'):
            loopback=f'http://127.0.0.1:{parts.port or 8088}'
            if self.windows_console_reachable(loopback):origin=loopback
            elif not self.windows_console_reachable(origin):
                raise ValueError('DST is running inside WSL, but Windows cannot reach its console. Check the Windows network/firewall settings and retry Open browser.')
        self.console_origin=origin
        try:
            network=self.network_info()
            import loopback_ingress
            loopback_ingress.restore(self.directory,network,windows_script)
        except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
            print('Same-PC network check: '+str(error),flush=True)
        if (self.directory/'lan-settings.json').exists() and not self.network_error:
            self.reconcile_private_address()
        if (self.directory/'resume.json').exists() and not self.network_error and not self.network_pending:
            resume=json.loads((self.directory/'resume.json').read_text())
            state=self.manager('status')
            same_stop=not resume.get('stopOperation') or state.get('operation',{}).get('id')==resume['stopOperation']
            if resume.get('resume') and state.get('projectId')==resume.get('world') and state.get('desiredState')=='stopped' and same_stop:
                started=self.manager('services.start')
                resume['startOperation']=started.get('operation',{}).get('id')
                write_json(self.directory/'resume.json',resume)
            elif state.get('operation',{}).get('id')!=resume.get('startOperation'):
                # A deliberate later world action supersedes the host resume intent.
                (self.directory/'resume.json').unlink()
            if (self.directory/'resume.json').exists():
                if not getattr(self,'resume_worker',None) or not self.resume_worker.is_alive():
                    self.resume_worker=threading.Thread(target=self.finish_resume,daemon=True)
                    self.resume_worker.start()
        if open_browser:self.open_browser()
    def reconcile_private_address(self):
        state=self.manager('status');profile=state.get('profile') or {}
        try:private=ipaddress.ip_address(profile.get('address','')).is_private
        except ValueError:return
        network=self.network_info()
        desired=json.loads((self.directory/'lan-settings.json').read_text())
        if network['networkingMode']!=desired['mode']:return
        address=network['dockerIp']
        if not private or profile.get('address')==address:return
        result=self.manager('network.set',mode='private',address=address,expectedAddress=profile['address'])
        operation=result.get('operation',{}).get('id');deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            current=self.manager('status');op=current.get('operation') or {}
            if op.get('id')!=operation:raise ValueError('The address operation changed during host startup.')
            if op.get('phase')=='completed':
                path=self.directory/'resume.json'
                if path.exists():
                    resume=json.loads(path.read_text());resume['stopOperation']=operation;write_json(path,resume)
                return
            if op.get('phase') in {'failed','interrupted'}:raise ValueError(op.get('error','Docker address update failed.'))
            time.sleep(1)
        raise ValueError('The Docker address update is still running. Review its status before starting maps.')
    def network_info(self,public_ip=None):
        import wsl_network
        value=wsl_network.snapshot(windows_script,run,public_ip)
        saved=self.directory/'lan-settings.json'
        if value['networkingMode']=='bridged' and saved.exists():
            desired=json.loads(saved.read_text()).get('address')
            addresses=json.loads(run(['ip','-j','-4','address']).stdout)
            if desired and any(row.get('local')==desired for iface in addresses for row in iface.get('addr_info',[])):
                value['dockerIp']=desired;value['routerForwardIp']=desired
        write_json(self.directory/'network-info.json',value)
        (self.directory/'network-info.json').chmod(0o644)
        return value
    def windows_console_reachable(self,origin):
        # Probe from the browser's Windows host. Linux health alone cannot
        # detect a blocked WSL interface or disabled localhost forwarding.
        script=("$ErrorActionPreference='Stop';$response=$null;try {"
                "$request=[Net.HttpWebRequest]::Create("+ps_literal(origin+'/')+");"
                "$request.Proxy=$null;$request.Timeout=3000;$request.ReadWriteTimeout=3000;"
                "$request.AllowAutoRedirect=$false;$response=$request.GetResponse();"
                "if([int]$response.StatusCode -eq 200 -and $response.ContentType -like 'text/html*'){'ready'}else{'unavailable'}"
                "} catch {'unavailable'} finally {if($response){$response.Dispose()}}")
        try:return windows_script(script)=='ready'
        except subprocess.SubprocessError:return False
    def browser_url(self):
        origin=getattr(self,'console_origin',None)
        if not origin:raise ValueError('The console address is not ready.')
        # A permanent redirect from earlier optional HTTPS must not override
        # the current HTTP transport when a browser reuses its cached root URL.
        return origin+'/?_dst_launch='+uuid.uuid4().hex
    def finish_resume(self):
        path=self.directory/'resume.json'
        try:
            resume=json.loads(path.read_text());deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                state=self.manager('status');operation=state.get('operation') or {}
                if operation.get('id')!=resume.get('startOperation'):
                    raise ValueError('World startup changed. Review the server operation in DST; restart intent was retained.')
                if operation.get('phase') in {'failed','interrupted'}:
                    raise ValueError('World startup failed. Review the server operation in DST; restart intent was retained.')
                if operation.get('phase')=='completed' and state.get('desiredState')=='running':
                    path.unlink(missing_ok=True);return
                time.sleep(2)
            raise ValueError('World startup is still pending. Check Server Overview; restart intent was retained.')
        except Exception as error:
            self.progress('failed',str(error) if isinstance(error,ValueError) else 'World startup could not be checked. Restart intent was retained; inspect DST before retrying.')
    def serve(self):
        sockpath=self.directory/'host.sock'
        with (self.directory/'session.lock').open('a') as lockfile:
            if not hasattr(self,'session_lock'):
                try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError('DST host session is already open. Use the existing DST window.')
            sockpath.unlink(missing_ok=True)
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(sockpath));sockpath.chmod(0o666);server.listen(5)
                print('DST Docker is running. Keep this window open.',flush=True)
                if sys.stdin.isatty():
                    signal.signal(signal.SIGINT,lambda *_:print('\nHosting continues. Use option5 to shut down safely.',flush=True))
                    self.menu_thread=threading.Thread(target=self.console_menu,daemon=True)
                    self.menu_thread.start()
                while True:
                    connection,_=server.accept()
                    with connection:
                        connection.settimeout(5)
                        try:
                            with connection.makefile('rb') as stream:raw=stream.readline(4097)
                            if len(raw)>4096:raise ValueError('Host request is too large.')
                            _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                            response={'ok':True,'data':self.request(json.loads(raw),peer_uid=uid)}
                        except Exception as error:response={'ok':False,'error':str(error) if isinstance(error,ValueError) else 'Host action unavailable. Check the DST host window.'}
                        try:connection.sendall(json.dumps(response).encode()+b'\n')
                        except OSError:
                            # Closing a browser/client must not end the foreground
                            # process that keeps the WSL server alive.
                            pass

def prepare_binding(root):
    if not os.environ.get('WSL_DISTRO_NAME') or not Path(WSL).exists():raise ValueError('Desktop hosting is available in Windows WSL.')
    root=Path(root).resolve();directory=root/'host-session'
    if directory.is_symlink():raise ValueError('The host directory must not be a symbolic link.')
    directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o755)
    if os.geteuid()==0:
        owner=root.stat();os.chown(directory,owner.st_uid,owner.st_gid,follow_symlinks=False)
    override=root/'host.compose.json'
    # The parent install directory is private. Only this socket directory is exposed.
    value={'services':{'dst':{'environment':{'DST_HOST_PLATFORM':'wsl'},'volumes':[{'type':'bind','source':str(directory),'target':'/host-control','read_only':True}]}}}
    write_json(override,value)
    # Public platform metadata only; no launcher paths, tokens or account data.
    marker=directory/'platform.json'
    write_json(marker,{'platform':'wsl','distribution':os.environ['WSL_DISTRO_NAME']})
    marker.chmod(0o644)
    return root,directory,override

def prepare(root,source,project,files):
    root,directory,override=prepare_binding(root)
    config={'distribution':os.environ['WSL_DISTRO_NAME'],'source':str(Path(source).resolve()),'project':project,'composeFiles':list(dict.fromkeys([*files,str(override)]))}
    write_json(directory/'config.json',config)
    return HostSession(root)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['bind','prepare','desktop','shortcut']);parser.add_argument('--root',required=True);parser.add_argument('--source');parser.add_argument('--project');parser.add_argument('--compose-file',action='append',default=[]);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    try:
        if args.action=='bind':prepare_binding(args.root);return
        host=prepare(args.root,args.source,args.project,args.compose_file) if args.action=='prepare' else HostSession(args.root)
        if args.action in {'prepare','shortcut'}:print(host.shortcut())
        else:host.start(open_browser=not args.no_browser)
    except (ValueError,subprocess.SubprocessError,OSError) as error:
        print('DST host: '+(str(error) if isinstance(error,ValueError) else 'Host integration could not complete. Check WSL and Docker access.'),flush=True);raise SystemExit(1)

if __name__=='__main__':main()
