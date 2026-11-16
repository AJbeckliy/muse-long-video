"""Read-only source test; generated review files remain in the explicit test directory."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("continuity", Path(__file__).with_name("inspect_continuity.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
SOURCE = WORK = None

class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.output = Path(tempfile.mkdtemp(prefix="check-", dir=WORK))

    def test_exact_frame_and_manifest(self):
        import av
        from PIL import Image
        report = tool.extract(SOURCE, self.output, [0, 1])
        with av.open(str(SOURCE)) as media:
            frames = media.decode(video=0)
            next(frames)
            expected = next(frames).to_image()
        actual = Image.open(report["candidates"][1]["image"])
        self.assertEqual(actual.size, expected.size)
        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(report["candidates"][1]["previous_out_frame_if_selected"], 2)
        self.assertIsNone(report["selection"])

    def test_out_of_range_creates_no_files(self):
        with self.assertRaises(ValueError):
            tool.extract(SOURCE, self.output, [0, 10**9])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_output_is_preserved(self):
        report = tool.extract(SOURCE, self.output, [0])
        image = Path(report["candidates"][0]["image"])
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            tool.extract(SOURCE, self.output, [0])
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), digest)

    def test_invalid_candidate_lists(self):
        for value in ("-1", "1,1", "x", ",".join(str(i) for i in range(13))):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    tool.frame_list(value)

    def test_missing_source_creates_no_files(self):
        with self.assertRaises(ValueError):
            tool.extract(self.output/"missing.mp4", self.output/"unused", [0])
        self.assertFalse((self.output/"unused").exists())

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: test_inspect_continuity.py ABSOLUTE_VIDEO ABSOLUTE_TEST_DIRECTORY")
    SOURCE, WORK = Path(sys.argv[1]), Path(sys.argv[2])
    if not SOURCE.is_absolute() or not SOURCE.is_file() or not WORK.is_absolute():
        raise SystemExit("Provide an existing absolute video path and an absolute test directory")
    WORK.mkdir(parents=True, exist_ok=True)
    sys.argv[:] = [sys.argv[0]]
    unittest.main(verbosity=2)

