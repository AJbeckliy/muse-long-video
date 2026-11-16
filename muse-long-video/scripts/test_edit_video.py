"""Offline checks. Integration requires existing PyAV and FFmpeg. Test files are retained."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pov_edit", HERE / "edit_video.py")
edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edit)
WORK = None

class PlanChecks(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="case-", dir=WORK))
        self.plan = {"version": 1, "target_seconds": 2, "output": str(self.folder/"out.mp4"),
                     "fps": 24, "width": 64, "height": 96,
                     "clips": [
                         {"id": "one", "path": str(self.folder/"one.mp4"), "source_fps": 24,
                          "source_frames": 240, "in_frame": 0, "out_frame": 24,
                          "dialogue_windows": [[0.2, 0.8]]},
                         {"id": "two", "path": str(self.folder/"two.mp4"), "source_fps": 30,
                          "source_frames": 300, "in_frame": 30, "out_frame": 60,
                          "dialogue_windows": [[1.2, 1.8]]}]}

    def test_mixed_rates_preserve_two_seconds(self):
        p = edit.validate(self.plan)
        self.assertEqual(p["target"], 2)
        self.assertFalse(Path(self.plan["output"]).exists())

    def test_cut_dialogue_rejected(self):
        self.plan["clips"][0]["dialogue_windows"] = [[0.2, 1.1]]
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)

    def test_wrong_total_rejected(self):
        self.plan["target_seconds"] = 3
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)

    def test_source_overrun_rejected(self):
        self.plan["clips"][0]["out_frame"] = 241
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)

    def test_overlap_rejected(self):
        c = self.plan["clips"][1]
        c.update(path=self.plan["clips"][0]["path"], source_fps=24,
                 in_frame=12, out_frame=36, dialogue_windows=[])
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)

    def test_disjoint_same_source_allowed(self):
        c = self.plan["clips"][1]
        c.update(path=self.plan["clips"][0]["path"], source_fps=24,
                 in_frame=24, out_frame=48, dialogue_windows=[])
        edit.validate(self.plan)

    def test_output_cannot_be_source(self):
        self.plan["output"] = self.plan["clips"][0]["path"]
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)

    def test_existing_output_preserved(self):
        path = Path(self.plan["output"])
        path.write_bytes(b"existing user file")
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)
        self.assertEqual(path.read_bytes(), b"existing user file")

    def test_bad_numbers_rejected(self):
        for val in (True, "NaN", "Infinity", 0, -1):
            with self.subTest(value=val):
                p = copy.deepcopy(self.plan)
                p["fps"] = val
                with self.assertRaises(edit.PlanError):
                    edit.validate(p)

    def test_off_grid_rejected(self):
        self.plan["clips"][1]["out_frame"] = 59
        with self.assertRaises(edit.PlanError):
            edit.validate(self.plan)

    def test_no_speech_windows_allowed(self):
        for c in self.plan["clips"]:
            c.pop("dialogue_windows")
        edit.validate(self.plan)

    def test_missing_source_prevents_render_without_output(self):
        try:
            import av
            edit.find_ffmpeg()
        except (ImportError, edit.PlanError):
            self.skipTest("Existing render dependencies unavailable")
        with self.assertRaises(edit.PlanError):
            edit.render(self.plan)
        self.assertFalse(Path(self.plan["output"]).exists())

class RenderCheck(unittest.TestCase):
    def test_real_mixed_rate_render_and_metadata_guard(self):
        try:
            import av
            ff = edit.find_ffmpeg()
        except (ImportError, edit.PlanError):
            self.skipTest("Existing render dependencies unavailable")
        folder = Path(tempfile.mkdtemp(prefix="render-", dir=WORK))
        clips = []
        for i, rate in enumerate((24, 30)):
            src = folder / ("source-" + str(rate) + ".mp4")
            subprocess.run([ff, "-n", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=" + ("red" if i==0 else "blue") + ":s=64x96:r="+str(rate),
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                            "-t", "0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", str(src)], check=True)
            clips.append({"id": str(rate), "path": str(src), "source_fps": rate,
                          "source_frames": rate//2, "in_frame": 0,
                          "out_frame": rate//2, "dialogue_windows": []})
        plan = {"version": 1, "target_seconds": 1, "output": str(folder/"joined.mp4"),
                "fps": 24, "width": 64, "height": 96, "clips": clips}
        result = edit.render(plan, ff)
        self.assertEqual(result["frames"], 24)
        self.assertEqual(result["seconds"], 1)
        with av.open(result["output"]) as media:
            frames = list(media.decode(video=0))
            from PIL import ImageStat
            first = ImageStat.Stat(frames[0].to_image()).mean
            last = ImageStat.Stat(frames[-1].to_image()).mean
            self.assertGreater(first[0], first[2]+100)
            self.assertGreater(last[2], last[0]+100)
        bad = copy.deepcopy(plan)
        bad["output"] = str(folder/"must-not-exist.mp4")
        bad["clips"][0]["source_frames"] += 1
        with self.assertRaises(edit.PlanError):
            edit.render(bad, ff)
        self.assertFalse(Path(bad["output"]).exists())
        (folder/"plan.json").write_text(json.dumps(plan,indent=2),encoding="utf-8")

    def test_nonzero_inpoint_keeps_exact_selected_frames(self):
        try:
            import av
            ff = edit.find_ffmpeg()
        except (ImportError, edit.PlanError):
            self.skipTest("Existing render dependencies unavailable")
        folder = Path(tempfile.mkdtemp(prefix="frame-boundary-", dir=WORK))
        clips = []
        for index, (start, end) in enumerate(((0, 133), (1, 240))):
            src = folder / f"source-{index}.mp4"
            subprocess.run([ff, "-n", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x96:r=24", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=48000", "-t", "10",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            str(src)], check=True)
            clips.append({"id": str(index), "path": str(src), "source_fps": 24,
                          "source_frames": 240, "in_frame": start, "out_frame": end})
        plan = {"version": 1, "target_seconds": 15.5, "output": str(folder/"out.mp4"),
                "fps": 24, "width": 64, "height": 96, "clips": clips}
        result = edit.render(plan, ff)
        self.assertEqual(result["frames"], 372)
        with av.open(result["output"]) as media:
            self.assertEqual(sum(1 for _ in media.decode(video=0)), 372)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_edit_video.py ABSOLUTE_TEST_DIRECTORY")
    WORK = Path(sys.argv.pop())
    if not WORK.is_absolute():
        raise SystemExit("Use an absolute directory for retained test media")
    WORK.mkdir(parents=True, exist_ok=True)
    unittest.main(verbosity=2)

