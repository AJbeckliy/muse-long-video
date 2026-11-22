"""Normalize unusual MP4 track start times on an app-owned copy before frame editing."""
from fractions import Fraction
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import av
from edit_video import find_ffmpeg


def is_mp4(path):
    """Inspect ISO BMFF boxes, without opening streams or following input references."""
    with Path(path).open("rb") as stream:
        for _ in range(16):
            header = stream.read(8)
            if len(header) != 8:
                return False
            size, kind = int.from_bytes(header[:4], "big"), header[4:]
            head = 8
            if size == 1:
                size = int.from_bytes(stream.read(8), "big")
                head = 16
            if not head <= size <= 65536 or stream.tell() > 65536:
                return False
            if kind == b"ftyp" and size >= head + 8:
                body = stream.read(size-head)
                if len(body) != size-head:
                    return False
                brands = [body[:4]] + [body[i:i+4] for i in range(8,len(body)-3,4)]
                return any(b.startswith((b"iso",b"mp4")) or b in (b"avc1",b"hvc1",b"av01",b"dash",b"M4V ",b"MSNV",b"cmfc") for b in brands)
            if kind not in (b"free",b"skip",b"wide"):
                return False
            stream.seek(size-head,1)
    return False


def normalize(path, video_start, audio_start, duration, frame_count):
    path = Path(path)
    temp = path.with_name(f"align-{uuid4().hex}.mp4")
    samples = round(duration * 48000)
    shift = round((audio_start - video_start) * 48000)
    filters = ["asetpts=PTS-STARTPTS", "aresample=48000", "aformat=channel_layouts=stereo"]
    if shift > 0:
        delay = min(shift, samples)
        filters.append(f"adelay={delay}S|{delay}S")
    elif shift < 0:
        filters.extend([f"atrim=start_sample={-shift}", "asetpts=PTS-STARTPTS"])
    filters.extend(["apad", f"atrim=end_sample={samples}", "asetpts=N/SR/TB"])
    try:
        subprocess.run([find_ffmpeg(), "-nostdin", "-n", "-v", "error", "-copyts",
                        "-itsoffset", f"{float(-video_start):.9f}", "-protocol_whitelist", "file,pipe",
                        "-f", "mov", "-enable_drefs", "0", "-i", str(path),
                        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                        "-af", ",".join(filters), "-c:a", "aac", "-b:a", "192k",
                        "-avoid_negative_ts", "disabled", "-movflags", "+faststart", str(temp)],
                       check=True, capture_output=True)
        with av.open(str(temp)) as result:
            v, a = result.streams.video[0], result.streams.audio[0]
            if v.frames != frame_count or a.duration is None or abs(a.duration*a.time_base-duration) > Fraction(1,100):
                raise ValueError("规范化后的帧数或音轨时长异常。")
            if v.start_time is None or a.start_time is None or abs(v.start_time*v.time_base) > v.time_base or abs(a.start_time*a.time_base) > Fraction(1,100):
                raise ValueError("规范化后的音画起点异常。")
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
