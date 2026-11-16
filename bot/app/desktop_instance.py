"""One desktop process per user data directory; repeated launches reopen it."""
from __future__ import annotations
import fcntl,json,socket,threading
from .paths import DATA,ensure_dirs

class DesktopInstance:
    def __init__(self):
        ensure_dirs();self.file=(DATA/'desktop.lock').open('a+');self.path=DATA/'ui.sock'
        self.server=None;self.stop=threading.Event()
    def acquire(self):
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(2);client.connect(str(self.path));client.sendall(b'show\n')
            self.file.close();return False
        self.path.unlink(missing_ok=True)
        self.server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.server.bind(str(self.path));self.path.chmod(0o600);self.server.listen(4);self.server.settimeout(.5)
        return True
    def start(self,root,show,native_control=None):
        def worker():
            while not self.stop.is_set():
                try:connection,_=self.server.accept()
                except socket.timeout:continue
                except OSError:break
                with connection:
                    connection.settimeout(1)
                    try:
                        data=b''
                        while len(data)<=16384:
                            chunk=connection.recv(min(4096,16385-len(data)))
                            if not chunk:break
                            data+=chunk
                            if b'\n' in data:break
                        if data.strip()==b'show':root.after(0,show)
                        elif native_control and len(data)<=16384:
                            try:response={'ok':True,'result':native_control(json.loads(data))}
                            except Exception as exc:response={'ok':False,'error':str(exc)}
                            connection.sendall((json.dumps(response)+'\n').encode())
                    except (OSError,RuntimeError):pass
        threading.Thread(target=worker,name='arona-reopen',daemon=True).start()
    def close(self):
        self.stop.set()
        if self.server:self.server.close();self.path.unlink(missing_ok=True)
        if not self.file.closed:self.file.close()
