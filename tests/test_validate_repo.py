"""The repo gate keeps label files and images out of git, except the page's screenshots."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import validate_repo  # noqa: E402


def banned(*paths):
    errors = []
    validate_repo.check_banned_files(errors, list(paths))
    return errors


class BannedFilesTest(unittest.TestCase):
    def test_page_screenshots_are_allowed(self):
        self.assertEqual(banned("docs/screenshots/01-today.png", "docs/screenshots/03-Label.PNG"), [])

    def test_other_images_and_label_files_stay_out(self):
        for path in ("docs/screenshots/label.jpg", "docs/screenshots/old/today.png", "docs/today.png",
                     "demo/captan-80-df.png", "docs/screenshots/captan-80-df.pdf", "state/spraywatch.db"):
            with self.subTest(path=path):
                self.assertEqual(len(banned(path)), 1)

    def test_environment_files_stay_out(self):
        self.assertEqual(len(banned(".env", "docs/screenshots/.env.local")), 2)
        self.assertEqual(banned(".env.example"), [])


if __name__ == "__main__":
    unittest.main()
