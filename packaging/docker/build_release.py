"""Build the separate DST Docker release assets without publishing."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def git_bytes(repository,revision,path):
    return subprocess.check_output(['git','show',revision+':'+path],cwd=repository)

def build(repository,revision,output):
    revision=subprocess.check_output(['git','rev-parse','--verify',revision+'^{commit}'],cwd=repository,text=True).strip()
    product=json.loads(git_bytes(repository,revision,'packaging/docker/release.json'))
    if product.get('name')!='DST Docker' or product.get('repository')!='coastal-ms/DST-Docker' or not re.fullmatch(r'\d+\.\d+\.\d+',product.get('version','')) or product.get('tag')!='v'+product['version']:
        raise ValueError('Choose a consistent independent Docker release identity.')
    if product.get('installer')!='dst-docker-install.sh' or product.get('checksums')!='SHA256SUMS':raise ValueError('Unexpected release asset names.')
    web=json.loads(git_bytes(repository,revision,'webui/package.json'))
    if web['version']!=product['version']:raise ValueError('Docker frontend version differs from the release identity.')
    changelog=git_bytes(repository,revision,'CHANGELOG.md').decode('utf-8')
    heading='## ['+product['version']+']'
    if heading not in changelog:raise ValueError('Release notes are missing.')
    notes=changelog.split(heading,1)[1].split('\n## ',1)[0].strip()+'\n'
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,str(Path(__file__).with_name('build_installer.py')),'--repository',str(repository),'--revision',revision,'--output',str(output/product['installer'])],check=True)
    payload=(output/product['installer']).read_bytes();digest=hashlib.sha256(payload).hexdigest()
    (output/product['checksums']).write_text(digest+'  '+product['installer']+'\n',encoding='utf-8',newline='\n')
    (output/'RELEASE-NOTES.md').write_text(notes,encoding='utf-8',newline='\n')
    base='https://github.com/'+product['repository']+'/releases/download/'+product['tag']
    manifest={**product,'sourceCommit':revision,'installerBytes':len(payload),'installerSha256':digest,'installerUrl':base+'/'+product['installer'],'checksumUrl':base+'/'+product['checksums']}
    (output/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    command='curl -fsSL '+manifest['installerUrl']+' | bash\n'
    (output/'install-command.txt').write_text(command,encoding='utf-8',newline='\n')
    return manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repository',type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument('--revision',default='HEAD');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(build(args.repository,args.revision,args.output),indent=2))

if __name__=='__main__':main()
