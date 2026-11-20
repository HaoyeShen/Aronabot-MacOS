"""One desktop process per user data directory; repeated launches reopen it."""
from __future__ import annotations
import fcntl,json,logging,socket,threading,time
from .paths import DATA,ensure_dirs

class DesktopInstance:
    def __init__(self):
        ensure_dirs();self.file=(DATA/'desktop.lock').open('a+');self.path=DATA/'ui.sock'
        self.server=None;self.stop=threading.Event()
    def acquire(self):
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            # The first instance may hold the lock before it starts listening;
            # retry briefly instead of surfacing ConnectionRefusedError.
            deadline=time.monotonic()+2.0
            while time.monotonic()<deadline:
                try:
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                        client.settimeout(.5);client.connect(str(self.path))
                        client.sendall(b'show\n')
                    break
                except OSError:
                    time.sleep(.05)
            else:
                logging.getLogger('arona').warning('已有实例占用数据目录，但未能打开窗口')
            self.file.close();return False
        self.path.unlink(missing_ok=True)
        self.server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.server.bind(str(self.path));self.path.chmod(0o600);self.server.listen(4);self.server.settimeout(.5)
        return True
    def start(self,root,show,native_control=None):
        def respond(connection,response):
            try:connection.sendall((json.dumps(response)+'\n').encode())
            except OSError:pass
            finally:
                try:connection.close()
                except OSError:pass

        def handle(connection,request):
            if request.get('command')=='native_send_text':
                # A slow native send must not block menu actions or reopening.
                def slow():
                    try:respond(connection,{'ok':True,'result':native_control(request)})
                    except Exception as exc:respond(connection,{'ok':False,'error':str(exc)})
                threading.Thread(target=slow,name='arona-native-call',daemon=True).start()
                return
            try:response={'ok':True,'result':native_control(request)}
            except Exception as exc:response={'ok':False,'error':str(exc)}
            respond(connection,response)

        def worker():
            while not self.stop.is_set():
                try:connection,_=self.server.accept()
                except socket.timeout:continue
                except OSError:break
                connection.settimeout(1)
                try:
                    data=b''
                    while len(data)<=16384:
                        chunk=connection.recv(min(4096,16385-len(data)))
                        if not chunk:break
                        data+=chunk
                        if b'\n' in data:break
                except (OSError,RuntimeError):
                    connection.close();continue
                if data.strip()==b'show':
                    try:root.after(0,show)
                    finally:connection.close()
                    continue
                if not native_control or not data or len(data)>16384:
                    connection.close();continue
                try:request=json.loads(data)
                except ValueError:
                    connection.close();continue
                if not isinstance(request,dict):
                    connection.close();continue
                handle(connection,request)
        threading.Thread(target=worker,name='arona-reopen',daemon=True).start()
    def close(self):
        self.stop.set()
        if self.server:self.server.close();self.path.unlink(missing_ok=True)
        if not self.file.closed:self.file.close()
