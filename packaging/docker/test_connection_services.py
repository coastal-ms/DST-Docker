from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from connection_services import ensure_tls


class ConnectionTests(unittest.TestCase):
    def test_generated_chain_passes_strict_tls_hostname_and_key_usage_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'tls'
            first=ensure_tls(root,'dst-test-rmq-game','127.0.0.1')
            second=ensure_tls(root,'dst-test-rmq-game','127.0.0.1')
            self.assertEqual(first,second)
            server=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.load_cert_chain(root/'cert.pem',root/'key.pem')
            client=ssl.create_default_context(cafile=root/'ca.pem')
            client.verify_flags|=ssl.VERIFY_X509_STRICT
            errors=[]
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0)); listener.listen(1);listener.settimeout(5)
                def serve():
                    try:
                        connection,_=listener.accept()
                        with server.wrap_socket(connection,server_side=True) as stream: stream.sendall(b'DST')
                    except Exception as error:errors.append(error)
                thread=threading.Thread(target=serve,daemon=True);thread.start()
                with client.wrap_socket(socket.socket(),server_hostname='127.0.0.1') as stream:
                    stream.settimeout(5);stream.connect(listener.getsockname())
                    self.assertEqual(stream.recv(3),b'DST')
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            self.assertEqual((root/'key.pem').stat().st_mode&0o777,0o600)
            self.assertEqual((root/'ca-key.pem').stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError):ensure_tls(root,'another-host','127.0.0.1')


if __name__=='__main__':unittest.main()
