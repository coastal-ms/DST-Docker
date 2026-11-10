"""Build a private standalone Linux installer from an explicit Git snapshot."""
import argparse,base64,hashlib,os,json
from pathlib import Path
import subprocess
import tempfile

def package(template,archive,revision,version=''):
    if not revision or any(c not in '0123456789abcdef' for c in revision) or len(revision)!=40:raise ValueError('Choose a complete Git commit ID.')
    digest=hashlib.sha256(archive).hexdigest()
    encoded=base64.encodebytes(archive).decode('ascii')
    if version and not __import__('re').fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Choose a stable Docker version.')
    payload="task_product_version='"+version+"'\ntask_package_sha='"+digest+"'\ntask_package_revision='"+revision+"'\ndst_embedded_source() {\nbase64 --decode <<'DST_BUNDLED_SOURCE'\n"+encoded+"DST_BUNDLED_SOURCE\n}\n"
    marker='# DST_EMBEDDED_SOURCE\n'
    if template.count(marker)!=1:raise ValueError('Installer template marker changed.')
    return template.replace(marker,payload).replace('\r\n','\n').encode('utf-8')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repository',type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument('--revision',default='HEAD');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    revision=subprocess.check_output(['git','rev-parse','--verify',args.revision+'^{commit}'],cwd=args.repository,text=True).strip()
    archive=subprocess.check_output(['git','archive','--format=tar.gz',revision],cwd=args.repository)
    template=subprocess.check_output(['git','show',revision+':bin/dst-install'],cwd=args.repository).decode('utf-8')
    product=json.loads(subprocess.check_output(['git','show',revision+':packaging/docker/release.json'],cwd=args.repository))
    result=package(template,archive,revision,product['version'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.dst-installer-',dir=args.output.parent)
    try:
        with os.fdopen(descriptor,'wb') as target:target.write(result);target.flush();os.fsync(target.fileno())
        os.chmod(temporary,0o755);os.replace(temporary,args.output)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    print('Built Linux shell installer for commit '+revision+' ('+str(len(result))+' bytes).')

if __name__=='__main__':main()
