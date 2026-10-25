"""The local page: pages render, writes need the token and a loopback Host, a logged spray is checked at once."""
import http.client
import re
import shutil
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import db, watch  # noqa: E402
from evidence import server  # noqa: E402
from tests.test_flow import DEMO, write_csv  # noqa: E402


class PageTest(unittest.TestCase):
    def setUp(self):
        quiet = unittest.mock.patch.object(server.Handler, "log_message", lambda *args: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        inbox = self.tmp / "inbox"
        inbox.mkdir()
        shutil.copy(DEMO / "labels" / "demofung-50wp.txt", inbox)
        write_csv(inbox / "blocks.csv", "block_id,name,crop,acres", "B4,Block 4,grapes,12")
        write_csv(inbox / "harvests.csv", "harvest_id,block_id,planned_date", "H4,B4,2026-10-29")
        conn = db.connect(self.tmp / "spraywatch.db")
        watch.scan(conn, inbox, watch.ModelSource(fake_replies=DEMO / "replies"))
        conn.close()
        self.cards = []

        def poster(text):
            self.cards.append(text)
            return "ts"

        self.config = server.Config(db_path=self.tmp / "spraywatch.db", queue_dir=self.tmp / "queue",
                                    inbox_dir=inbox, port=0, poster=poster,
                                    clock=lambda: datetime(2026, 10, 26, 9, 0))
        self.httpd = server.make_server(self.config)
        self.config.port = self.httpd.server_address[1]
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None, host="127.0.0.1"):
        conn = http.client.HTTPConnection("127.0.0.1", self.config.port, timeout=10)
        body = urllib.parse.urlencode(fields).encode() if fields is not None else None
        headers = {"Host": f"{host}:{self.config.port}"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        text = response.read().decode("utf-8")
        conn.close()
        return response.status, response.getheader("Location"), text

    def post(self, action, **fields):
        return self.request("POST", f"/action/{action}", {"token": self.config.token, **fields})

    def test_the_whole_page_flow(self):
        status, _, text = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("DEMOFUNG 50 WP", text)

        status, _, text = self.request("GET", "/label/1")
        self.assertIn("Confirm label", text)
        self.assertIn("<mark>L8    - Do not apply within 7 days of harvest.</mark>", text)

        status, location, _ = self.post("confirm_label", label_id="1", approver="Farm manager")
        self.assertEqual(status, 303)
        self.assertIn("done=", location)

        status, location, _ = self.post("log_spray", block_id="B4", product="Demofung 50 WP", epa_reg_no="",
                                        applied_at="2026-10-26T08:00", applicator="J. Ruiz")
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/posting/1?"), location)
        self.assertIn("1+new+alert+raised", location)
        self.assertTrue(any("harvest is set for Thursday Oct 29" in card for card in self.cards), self.cards)

        status, _, text = self.request("GET", "/posting/1")
        self.assertIn("NO ENTRE", text)
        self.assertIn("No entre hasta el lunes 26 de octubre a las 20:00", text)

        status, _, text = self.request("GET", "/alert/1")
        self.assertIn("Approve the new date: 2026-11-02", text)
        self.assertIn("Do not apply within 7 days of harvest", text)

        status, location, _ = self.post("approve_alert", alert_id="1", approver="Farm manager")
        self.assertIn("schedule-change-1.json", urllib.parse.unquote_plus(location))
        self.assertTrue((self.tmp / "queue" / "schedule-change-1.json").is_file())
        status, location, _ = self.post("approve_alert", alert_id="1", approver="Farm manager")
        self.assertIn("refused=", location)

    def test_writes_need_the_token(self):
        status, _, _ = self.request("POST", "/action/confirm_label", {"label_id": "1", "approver": "Farm manager"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/action/confirm_label",
                                    {"token": "guess", "label_id": "1", "approver": "Farm manager"})
        self.assertEqual(status, 403)

    def test_other_hosts_are_refused(self):
        for method in ("GET", "POST"):
            status, _, _ = self.request(method, "/", {"token": self.config.token} if method == "POST" else None,
                                        host="evil.example")
            self.assertEqual(status, 403)

    def test_page_text_is_escaped(self):
        status, location, _ = self.post("log_spray", block_id="B4", product="<script>x</script>", epa_reg_no="",
                                        applied_at="2026-10-26T08:00", applicator="")
        status, _, text = self.request("GET", "/")
        self.assertNotIn("<script>x", text)
        self.assertIn("&lt;script&gt;x", text)

    def test_bad_spray_is_refused_with_a_reason(self):
        status, location, _ = self.post("log_spray", block_id="B9", product="Demofung", applied_at="2026-10-26T08:00")
        self.assertIn("refused=no+such+block", location)

    def test_unknown_pages(self):
        for path in ("/alert/99", "/label/99", "/posting/99", "/nope", "/label/1/source"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        self.assertTrue(re.search(r"No open alerts", self.request("GET", "/")[2]))


if __name__ == "__main__":
    unittest.main()
