from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from preview_gallery import CAPTURES, write_gallery


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
        self.assertFalse(any(tag == "img" and "src" in attrs
                             for tag, attrs in Elements(page).elements))
        self.assertEqual(["index.html"], [p.name for p in self.output.iterdir()])

    def test_actual_images_have_provenance_and_same_tab_enlargement(self):
        self.output.mkdir()
        for key in CAPTURES:
            (self.output / f"bulbs-{key}.png").write_bytes(b"actual capture supplied by caller")
        (self.output / "UniRemote-Preview.apk").write_bytes(b"test apk")
        page = self.page()
        elements = Elements(page).elements
        images = [attrs for tag, attrs in elements if tag == "img" and "src" in attrs]
        self.assertEqual(9, len(images))  # Connected is also the default connection view.
        self.assertTrue(all(image["src"].startswith("bulbs-") for image in images))
        self.assertTrue(all("?v=" in image["src"] for image in images))
        self.assertIn("Live Mac", page)
        self.assertIn("Read-only fixture", page)
        self.assertFalse(any("target" in attrs for _, attrs in elements))
        self.assertIn('id="lightbox"', page)
        self.assertIn('href="UniRemote-Preview.apk" download', page)
        self.assertIn("Old advanced setup · being removed", page)
        self.assertNotIn('<details id="advanced-details">', page)

    def test_revision_changes_only_when_inputs_change(self):
        def revision(page):
            return next(attrs["content"] for tag, attrs in Elements(page).elements
                        if tag == "meta" and attrs.get("name") == "gallery-revision")

        first = self.page()
        self.assertEqual(revision(first), revision(self.page()))
        (self.output / "bulbs-night.png").write_bytes(b"capture")
        self.assertNotEqual(revision(first), revision(self.page()))
        self.assertEqual({"index.html", "bulbs-night.png"}, {p.name for p in self.output.iterdir()})

    def test_truthful_explanations_and_refresh_state(self):
        page = self.page()
        for phrase in ("Assistant-added choice, not requested", "Six digits weren’t technically required",
                       "One manager was selected automatically", "No existing-room rename",
                       "Looks like Night · no Follow marker", "observed bulb output", "anyone on Wi-Fi",
                       "Old manager password", "v1.7: “Butler token”", "never gave you a usable way",
                       "No passwords or pairing codes. Change in progress.", ": 'modes'",
                       "sessionStorage", "saved.details", "saved.tab", "saved.y", "location.reload()",
                       "location.protocol === 'file:'", "cache: 'no-store'", "8000"):
            self.assertIn(phrase, page)

    def test_absent_apk_is_not_a_broken_download(self):
        page = self.page()
        self.assertIn("Preview APK pending", page)
        self.assertNotIn('href="UniRemote-Preview.apk"', page)


if __name__ == "__main__":
    unittest.main()
