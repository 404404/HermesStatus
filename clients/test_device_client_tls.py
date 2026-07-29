import json
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from device_client_transport import (  # noqa: E402
    DeviceHTTPSClient,
    DeviceTransportError,
)
from multi_device_contracts import (  # noqa: E402
    ClientContractError,
    ClientV2Config,
    build_envelope,
)


TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def valid_stats():
    return {
        "cpu": 42,
        "extension_version": "1.0-draft",
        "hardware": {},
        "docker": {},
        "hermes": {},
        "lucky": {},
    }


class SyntheticHandler(BaseHTTPRequestHandler):
    response_status = 202
    response_body = json.dumps(
        {
            "accepted": True,
            "server_time": "2026-07-01T12:00:00Z",
            "config_generation": "g-local",
            "monitors": [],
        }
    ).encode()
    response_headers = {"Content-Type": "application/json"}
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append((self.path, dict(self.headers), body))
        self.send_response(type(self).response_status)
        for key, value in type(self).response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(type(self).response_body)))
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, _format, *_arguments):
        return


class LocalServer:
    def __init__(self, handler, cert=None, key=None):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        if cert is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert), str(key))
            self.server.socket = context.wrap_socket(
                self.server.socket,
                server_side=True,
            )
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class DeviceClientLocalTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.ca_cert, cls.ca_key = cls.generate_ca("trusted")
        cls.other_ca_cert, cls.other_ca_key = cls.generate_ca("untrusted")
        cls.valid_cert, cls.valid_key = cls.generate_server_certificate(
            "valid",
            cls.ca_cert,
            cls.ca_key,
            "DNS:localhost,IP:127.0.0.1",
            2,
        )
        cls.mismatch_cert, cls.mismatch_key = cls.generate_server_certificate(
            "mismatch",
            cls.ca_cert,
            cls.ca_key,
            "DNS:wronghost.example.invalid",
            2,
        )
        cls.expired_cert, cls.expired_key = cls.generate_server_certificate(
            "expired",
            cls.ca_cert,
            cls.ca_key,
            "DNS:localhost,IP:127.0.0.1",
            0,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def openssl(cls, *arguments):
        subprocess.run(
            ["openssl", *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def generate_ca(cls, name):
        key = cls.root / f"{name}-ca.key"
        cert = cls.root / f"{name}-ca.crt"
        cls.openssl(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-days",
            "2",
            "-subj",
            f"/CN={name} synthetic CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        )
        return cert, key

    @classmethod
    def generate_server_certificate(cls, name, ca_cert, ca_key, san, days):
        key = cls.root / f"{name}.key"
        request = cls.root / f"{name}.csr"
        cert = cls.root / f"{name}.crt"
        extensions = cls.root / f"{name}.ext"
        extensions.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectKeyIdentifier=hash\n"
            "authorityKeyIdentifier=keyid,issuer\n"
            f"subjectAltName={san}\n",
            encoding="ascii",
        )
        cls.openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(key),
            "-out",
            str(request),
        )
        cls.openssl(
            "x509",
            "-req",
            "-sha256",
            "-days",
            str(days),
            "-in",
            str(request),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-extfile",
            str(extensions),
            "-out",
            str(cert),
        )
        return cert, key

    def setUp(self):
        self.case_directory = tempfile.TemporaryDirectory()
        self.case_root = Path(self.case_directory.name)
        self.token_path = self.case_root / "token"
        self.token_path.write_text(TOKEN, encoding="utf-8")
        self.token_path.chmod(0o600)
        SyntheticHandler.requests = []
        SyntheticHandler.response_status = 202
        SyntheticHandler.response_headers = {"Content-Type": "application/json"}
        SyntheticHandler.response_body = json.dumps(
            {
                "accepted": True,
                "server_time": "2026-07-01T12:00:00Z",
                "config_generation": "g-local",
                "monitors": [],
            }
        ).encode()

    def tearDown(self):
        self.case_directory.cleanup()

    def config(self, port, ca_file, *, scheme="https", loopback=False):
        return ClientV2Config(
            server_url=f"{scheme}://localhost:{port}",
            device_id="device-alpha",
            device_name=None,
            device_fqdn=None,
            token_file=str(self.token_path),
            ca_file=None if ca_file is None else str(ca_file),
            verify_tls=scheme == "https",
            connect_timeout_seconds=3,
            read_timeout_seconds=3,
            collection_interval_seconds=60,
            loopback_test_profile=loopback,
        )

    def envelope(self, config):
        return build_envelope(
            config,
            collected_at="2026-07-01T12:00:00Z",
            stats=valid_stats(),
        )

    def test_verified_local_tls_custom_ca_and_fixed_request(self):
        server = LocalServer(
            SyntheticHandler,
            self.valid_cert,
            self.valid_key,
        )
        self.addCleanup(server.close)
        config = self.config(server.port, self.ca_cert)
        response = DeviceHTTPSClient(config).send(self.envelope(config))
        self.assertTrue(response["accepted"])
        self.assertEqual(len(SyntheticHandler.requests), 1)
        path, headers, body = SyntheticHandler.requests[0]
        self.assertEqual(path, "/api/v2/device-updates")
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(headers["X-HermesStatus-Device-ID"], "device-alpha")
        self.assertNotIn(TOKEN, body.decode())

    def test_synthetic_chain_passes_strict_openssl_validation(self):
        subprocess.run(
            [
                "openssl",
                "verify",
                "-x509_strict",
                "-CAfile",
                str(self.ca_cert),
                str(self.valid_cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_bad_ca_san_mismatch_and_expired_certificate_fail_closed(self):
        cases = [
            ("bad-ca", self.valid_cert, self.valid_key, self.other_ca_cert),
            (
                "san-mismatch",
                self.mismatch_cert,
                self.mismatch_key,
                self.ca_cert,
            ),
            ("expired", self.expired_cert, self.expired_key, self.ca_cert),
        ]
        for name, cert, key, ca_file in cases:
            with self.subTest(name=name):
                server = LocalServer(SyntheticHandler, cert, key)
                try:
                    config = self.config(server.port, ca_file)
                    with self.assertRaisesRegex(
                        DeviceTransportError,
                        "tls_verification_failed",
                    ):
                        DeviceHTTPSClient(config).send(self.envelope(config))
                finally:
                    server.close()

    def test_custom_ca_symlink_is_rejected_before_network(self):
        link = self.case_root / "ca-link.pem"
        link.symlink_to(self.ca_cert)
        config = self.config(443, link)
        with self.assertRaises(ClientContractError):
            DeviceHTTPSClient(config)

    def test_explicit_loopback_http_profile_and_redirect_rejection(self):
        plain_server = LocalServer(SyntheticHandler)
        self.addCleanup(plain_server.close)
        config = self.config(
            plain_server.port,
            None,
            scheme="http",
            loopback=True,
        )
        self.assertTrue(DeviceHTTPSClient(config).send(self.envelope(config))["accepted"])

        SyntheticHandler.response_status = 302
        SyntheticHandler.response_headers = {
            "Content-Type": "application/json",
            "Location": "https://other.example.invalid/api/v2/device-updates",
        }
        redirect_server = LocalServer(
            SyntheticHandler,
            self.valid_cert,
            self.valid_key,
        )
        self.addCleanup(redirect_server.close)
        redirect_config = self.config(redirect_server.port, self.ca_cert)
        with self.assertRaisesRegex(DeviceTransportError, "redirect_rejected"):
            DeviceHTTPSClient(redirect_config).send(
                self.envelope(redirect_config)
            )

    def test_insecure_production_profiles_are_rejected_before_network(self):
        non_loopback_http = ClientV2Config(
            server_url="http://192.0.2.10:8080",
            device_id="device-alpha",
            device_name=None,
            device_fqdn=None,
            token_file=str(self.token_path),
            verify_tls=False,
            loopback_test_profile=True,
        )
        with self.assertRaises(ClientContractError):
            DeviceHTTPSClient(non_loopback_http)

        verify_disabled = ClientV2Config(
            server_url="https://localhost:443",
            device_id="device-alpha",
            device_name=None,
            device_fqdn=None,
            token_file=str(self.token_path),
            verify_tls=False,
        )
        with self.assertRaises(ClientContractError):
            DeviceHTTPSClient(verify_disabled)


if __name__ == "__main__":
    unittest.main()
