"""Check a frame-based POV edit plan; render only with --render. No network or overwrite."""
from __future__ import annotations
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

class PlanError(ValueError):
    pass

def number(value, label):
    if isinstance(value, bool):
        raise PlanError(label + ": boolean is not a number")
    try:
        result = Fraction(str(value))
    except (ValueError, TypeError, ZeroDivisionError):
        raise PlanError(label + ": invalid finite number")
    return result

def integer(value, label, minimum=0):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise PlanError(label + ": invalid integer")
    return value

def absolute(value, label):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise PlanError(label + ": use an absolute local path")
    return Path(value).resolve()

def key(path):
    return os.path.normcase(str(path))

def validate(plan):
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise PlanError("Expected plan version 1")
    fps = number(plan.get("fps"), "fps")
    target = number(plan.get("target_seconds"), "target_seconds")
    if fps <= 0 or target <= 0:
        raise PlanError("fps and target_seconds must be positive")
    if (target * fps).denominator != 1:
        raise PlanError("Target must lie on the output frame grid")
    width = integer(plan.get("width"), "width", 2)
    height = integer(plan.get("height"), "height", 2)
    if width % 2 or height % 2:
        raise PlanError("H.264 output dimensions must be even")
    output = absolute(plan.get("output"), "output")
    if output.suffix.lower() != ".mp4":
        raise PlanError("Output must be .mp4")
    if output.exists():
        raise PlanError("Output already exists; choose a new versioned filename")
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        raise PlanError("At least one clip is required")
    total = Fraction(0)
    seen_ids, intervals, normalized = set(), {}, []
    for i, c in enumerate(clips):
        if not isinstance(c, dict):
            raise PlanError("clip must be an object")
        label = "clip " + str(i)
        cid = c.get("id")
        if not isinstance(cid, str) or not cid or cid in seen_ids:
            raise PlanError(label + ": missing or duplicate id")
        seen_ids.add(cid)
        path = absolute(c.get("path"), label + " path")
        if key(path) == key(output):
            raise PlanError("Output cannot overwrite an input")
        rate = number(c.get("source_fps"), label + " source_fps")
        if rate <= 0:
            raise PlanError(label + ": source_fps must be positive")
        n = integer(c.get("source_frames"), label + " source_frames", 1)
        a = integer(c.get("in_frame"), label + " in_frame")
        b = integer(c.get("out_frame"), label + " out_frame", 1)
        if not a < b <= n:
            raise PlanError(label + ": empty or out-of-range source interval")
        for old_a, old_b in intervals.get(key(path), []):
            if a < old_b and old_a < b:
                raise PlanError(label + ": repeated source frames")
        intervals.setdefault(key(path), []).append((a, b))
        start, end = Fraction(a, 1)/rate, Fraction(b, 1)/rate
        duration = end-start
        if (duration*fps).denominator != 1:
            raise PlanError(label + ": trim must lie on the output frame grid")
        windows = c.get("dialogue_windows", [])
        if not isinstance(windows, list):
            raise PlanError(label + ": dialogue_windows must be a list")
        for window in windows:
            if not isinstance(window, list) or len(window) != 2:
                raise PlanError(label + ": invalid dialogue window")
            left, right = number(window[0], "speech start"), number(window[1], "speech end")
            if not start <= left < right <= end:
                raise PlanError(label + ": dialogue is clipped or outside the selected interval")
        total += duration
        normalized.append({"id": cid, "path": path, "fps": rate, "frames": n,
                           "a": a, "b": b, "start": start, "end": end,
                           "duration": duration})
    if total != target:
        raise PlanError("Selected duration " + str(total) + " differs from target " + str(target))
    return {"fps": fps, "target": target, "width": width, "height": height,
            "output": output, "clips": normalized}

def find_ffmpeg(explicit=None):
    if explicit:
        path = absolute(explicit, "--ffmpeg")
        if not path.is_file():
            raise PlanError("FFmpeg binary not found")
        return str(path)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise PlanError("FFmpeg unavailable; pass --ffmpeg or use the existing editor")

def render(plan, ffmpeg=None):
    p = validate(plan)
    try:
        import av
    except ImportError:
        raise PlanError("Rendering requires existing PyAV; check-only needs standard Python")
    ff = find_ffmpeg(ffmpeg)
    for c in p["clips"]:
        if not c["path"].is_file():
            raise PlanError("Source missing: " + str(c["path"]))
        with av.open(str(c["path"])) as media:
            if not media.streams.video or not media.streams.audio:
                raise PlanError("Helper requires a video and audio track in each source")
            stream = media.streams.video[0]
            actual_rate = stream.average_rate
            if actual_rate is None or Fraction(actual_rate) != c["fps"]:
                raise PlanError("Source fps differs from plan: " + c["id"])
            if stream.width * p["height"] != stream.height * p["width"]:
                raise PlanError("Source aspect differs; choose framing in the editor first")
            actual_frames = stream.frames
            if not actual_frames:
                actual_frames = sum(1 for _ in media.decode(stream))
            if actual_frames != c["frames"]:
                raise PlanError("Source frame count differs from plan: " + c["id"])
            audio = media.streams.audio[0]
            if audio.duration is not None and audio.time_base is not None:
                audio_end = Fraction(audio.duration) * audio.time_base
                if audio_end + Fraction(1, 100) < c["end"]:
                    raise PlanError("Source audio is shorter than selected interval")
    args = [ff, "-n", "-v", "error"]
    filters, pins = [], []
    for i, c in enumerate(p["clips"]):
        args.extend(["-i", str(c["path"])])
        rate_filter = (f"fps={p['fps']},trim=end_frame={int(c['duration']*p['fps'])},"
                       "setpts=PTS-STARTPTS," if c["fps"] != p["fps"] else "")
        filters.append(
            f"[{i}:v]trim=start_frame={c['a']}:end_frame={c['b']},"
            f"setpts=PTS-STARTPTS,{rate_filter}"
            f"scale={p['width']}:{p['height']},setsar=1,format=yuv420p[v{i}]"
        )
        filters.append(
            f"[{i}:a]atrim=start={float(c['start']):.12f}:end={float(c['end']):.12f},"
            f"asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
        )
        pins.append(f"[v{i}][a{i}]")
    # Audio packet rounding must not extend each video segment by a frame.
    filters.append("".join(f"[v{i}]" for i in range(len(pins)))
                   + f"concat=n={len(pins)}:v=1:a=0,setpts=N/({p['fps']}*TB)[v]")
    filters.append("".join(f"[a{i}]" for i in range(len(pins)))
                   + f"concat=n={len(pins)}:v=0:a=1[a]")
    p["output"].parent.mkdir(parents=True, exist_ok=True)
    args.extend(["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", "-vsync", "0",
                 "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(p["output"])])
    subprocess.run(args, check=True)
    subprocess.run([ff, "-v", "error", "-xerror", "-i", str(p["output"]),
                    "-f", "null", "-"], check=True)
    with av.open(str(p["output"])) as media:
        video = media.streams.video[0]
        frames = video.frames or sum(1 for _ in media.decode(video))
        if frames != p["target"]*p["fps"]:
            raise PlanError("Rendered frame count mismatch; retain file for inspection")
        audio = media.streams.audio[0]
        if audio.duration is not None and audio.time_base is not None:
            if abs(Fraction(audio.duration)*audio.time_base-p["target"]) > Fraction(1, 20):
                raise PlanError("Rendered audio duration mismatch")
    return {"output": str(p["output"]), "seconds": float(p["target"]),
            "frames": frames, "fps": str(p["fps"]), "decode_pass": True,
            "visual_and_listening_review": "not performed by this helper"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--ffmpeg")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        if args.render:
            result = render(plan, args.ffmpeg)
        else:
            p = validate(plan)
            result = {"structure_pass": True, "seconds": float(p["target"]),
                      "clips": len(p["clips"]), "media_checked": False, "rendered": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PlanError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

