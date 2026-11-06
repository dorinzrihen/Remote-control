from html.parser import HTMLParser
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen
import json

from preview_gallery import CAPTURES, write_gallery
from gallery_server import create_server


class Elements(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.elements = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class PreviewGalleryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "live"

    def page(self):
        write_gallery(self.output)
        return (self.output / "index.html").read_text()

    def test_missing_captures_are_not_mockups(self):
        page = self.page()
        self.assertIn("Awaiting actual capture", page)
        self.assertFalse(any(tag == "img" and "src" in attrs for tag, attrs in Elements(page).elements))
        self.assertEqual(["index.html"], [p.name for p in self.output.iterdir()])

    def test_actual_images_are_visible_screenshots_first(self):
        self.output.mkdir()
        for key in CAPTURES:
            (self.output / f"bulbs-{key}.png").write_bytes(b"caller supplies actual capture")
        page = self.page()
        elements = Elements(page).elements
        images = [a for tag, a in elements if tag == "img" and "src" in a]
        self.assertEqual(8, len(images))
        self.assertEqual(["bulbs-regular.png", "bulbs-night.png", "bulbs-follow.png"],
                         [a["src"].split("?")[0] for a in images[:3]])
        self.assertFalse(any("hidden" in a or "target" in a for _, a in elements))
        self.assertIn("Live Mac", page)
        self.assertIn("Read-only sample", page)
        self.assertNotIn("Awaiting actual capture", page)
        self.assertIn('<title>Bulbs — screenshots</title>', page)

    def test_no_flickering_reload_or_tabs(self):
        page = self.page()
        for forbidden in ("location.reload", "http-equiv", "data-tab", "UniRemote Preview"):
            self.assertNotIn(forbidden, page)
        self.assertIn("sessionStorage", page)
        self.assertIn("data-enlarge", page)
        self.assertIn("/__gallery_manifest", page)
        self.assertIn("replacement.replaceWith(existing)", page)

    def test_truthful_notes_below_screenshots(self):
        page = self.page()
        for phrase in ("LIMITATION · no Follow marker", "observed bulb output", "No existing-room rename",
                       "Working now:", "anyone on Wi-Fi", "Fresh emulator connected without entering any fields",
                       "Assistant-added choice, not requested", "v1.7: “Butler token”"):
            self.assertIn(phrase, page)
        self.assertLess(page.index('id="modes"'), page.index('id="old-code"'))
        self.assertNotIn("being removed", page)
        self.assertNotIn("in progress", page)
        self.assertEqual("Live Mac", CAPTURES["advanced"][1])

    def test_no_broken_apk_link(self):
        self.assertNotIn('href="UniRemote-Preview.apk"', self.page())
        (self.output / "UniRemote-Preview.apk").write_bytes(b"test apk")
        self.assertIn('href="UniRemote-Preview.apk" download', self.page())

    def test_local_manifest_tracks_html_and_images(self):
        self.page()
        server = create_server(self.output)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.assertEqual('127.0.0.1', server.server_address[0])
        url = f'http://127.0.0.1:{server.server_port}/__gallery_manifest'
        with urlopen(url) as response:
            before = json.load(response)
            self.assertEqual('no-store', response.headers['Cache-Control'])
        (self.output / 'bulbs-night.png').write_bytes(b'changed')
        with urlopen(url) as response:
            after = json.load(response)
        self.assertNotEqual(before['files'], after['files'])
        self.assertEqual(before['html'], after['html'])
        (self.output / 'index.html').write_text('<html>changed source</html>')
        with urlopen(url) as response:
            self.assertNotEqual(after['html'], json.load(response)['html'])


if __name__ == "__main__":
    unittest.main()
