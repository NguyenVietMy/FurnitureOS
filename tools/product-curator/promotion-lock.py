"""OS byte lock held until the owning Node pipe closes; no Git operations."""
import base64,hashlib,json,os,pathlib,stat,sys

def reply(value):print(json.dumps(value),flush=True)
def main():
    path=pathlib.Path(sys.argv[1]).absolute()
    assert path.name=='.promotion.lock'
    for p in (path,*path.parents):assert not p.is_symlink() and not p.is_junction()
    fd=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(fd,'r+b',buffering=0) as file:
        assert stat.S_ISREG(os.fstat(file.fileno()).st_mode)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            print('Concurrent promotion writer is active',file=sys.stderr);return 42
        try:
            assert os.fstat(file.fileno()).st_size<=4096,'Unknown oversized lock content; preserve manually'
            file.seek(0);raw=file.read()
            reply(dict(status='LOCKED',rawBase64=base64.b64encode(raw).decode()))
            line=sys.stdin.readline()
            if not line:return 0
            command=json.loads(line);assert set(command)=={'normalizeSha256'} and command['normalizeSha256']==hashlib.sha256(raw).hexdigest()
            file.seek(0);assert file.read()==raw,'Lock content changed'
            assert os.path.samestat(os.fstat(file.fileno()),path.stat()),'Lock inode changed'
            file.seek(0);file.write(b' ');file.truncate(1);file.flush();os.fsync(file.fileno())
            reply(dict(status='HELD'))
            assert sys.stdin.readline()=='','Unexpected lock command'
        finally:
            file.seek(0)
            if os.name=='nt':msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(file.fileno(),fcntl.LOCK_UN)
    return 0
if __name__=='__main__':sys.exit(main())
