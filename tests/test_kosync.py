import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import unittest

from apple_kindle_bridge.kosync import KOSyncError, get_progress


class ProgressServiceTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.body = {'progress': '/body/DocFragment[1]/body/p/text().0', 'percentage': 0.1}
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.requests.append((self.path, self.headers.get('x-auth-user'), self.headers.get('x-auth-key'), self.headers.get('Accept')))
                self.send_response(case.status)
                if case.status == 302:
                    self.send_header('Location', '/other-service')
                self.end_headers()
                self.wfile.write(json.dumps(case.body).encode())

            def log_message(self, *args):
                pass

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_existing_kosync_request_contract_and_epub_response(self):
        result = get_progress(self.url + '/prefix', 'test-reader', '1' * 32, 'a' * 32)
        self.assertEqual(result['progress'], self.body['progress'])
        self.assertEqual(self.requests, [('/prefix/syncs/progress/' + 'a' * 32, 'test-reader', '1' * 32, 'application/vnd.koreader.v1+json')])
        self.body['progress'] = '7'  # PDF page numbers are not EPUB positions.
        with self.assertRaises(KOSyncError):
            get_progress(self.url, 'test-reader', '1' * 32, 'a' * 32)

    def test_no_redirect_or_remote_plaintext_credentials(self):
        self.status = 302
        with self.assertRaisesRegex(KOSyncError, '302'):
            get_progress(self.url, 'test-reader', '1' * 32, 'a' * 32)
        self.assertEqual(len(self.requests), 1)
        with self.assertRaisesRegex(KOSyncError, 'HTTPS'):
            get_progress('http://example.com', 'test-reader', '1' * 32, 'a' * 32)


if __name__ == '__main__':
    unittest.main()
