"""Extract exact zero-based candidate frames and a review sheet; never overwrite."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys

def frame_list(raw):
    try:
        values = [int(x.strip()) for x in raw.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("Use comma-separated integer frame indexes")
    if not values or len(values) > 12 or min(values) < 0 or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Use 1-12 unique non-negative frame indexes")
    return values

def extract(source, output, frames):
    import av
    from PIL import Image, ImageDraw
    source, output = Path(source), Path(output)
    if not source.is_absolute() or not output.is_absolute():
        raise ValueError("Use absolute source and output paths")
    source, output = source.resolve(), output.resolve()
    if not source.is_file():
        raise ValueError("Source video missing")
    names = [output / f"{source.stem}-frame-{i:06d}.png" for i in frames]
    sheet_path = output / f"{source.stem}-candidates.jpg"
    manifest = output / f"{source.stem}-candidates.json"
    for path in names + [sheet_path, manifest]:
        if path.exists():
            raise ValueError("Output exists, choose a new review directory: " + str(path))
    captured = {}
    with av.open(str(source)) as media:
        if not media.streams.video:
            raise ValueError("No video stream")
        video = media.streams.video[0]
        rate = video.average_rate
        if rate is None or rate <= 0:
            raise ValueError("Cannot determine frame rate")
        if video.frames and max(frames) >= video.frames:
            raise ValueError("Requested frame outside source")
        start_time = None
        for index, frame in enumerate(media.decode(video)):
            current = float(frame.pts * frame.time_base) if frame.pts is not None else index / float(rate)
            if start_time is None:
                start_time = current
            if index in frames:
                captured[index] = (frame.to_image(), current-start_time)
            if index >= max(frames):
                break
        if len(captured) != len(frames):
            raise ValueError("Not all requested frames could be decoded")
    # Only now create files: out-of-range requests do not leave partial images.
    output.mkdir(parents=True, exist_ok=True)
    cols = min(4, len(frames))
    rows = (len(frames)+cols-1)//cols
    sheet = Image.new("RGB", (360*cols, 680*rows), "#222222")
    draw = ImageDraw.Draw(sheet)
    records = []
    for slot, (index, path) in enumerate(zip(frames, names)):
        full, seconds = captured[index]
        full.save(path)
        thumb = full.copy()
        thumb.thumbnail((360, 640))
        x, y = slot % cols * 360, slot // cols * 680
        sheet.paste(thumb, (x+(360-thumb.width)//2, y))
        draw.text((x+6,y+648), f"frame {index} | {seconds:.3f}s", fill="white")
        records.append({"frame_index": index, "time_seconds": seconds,
                        "image": str(path), "previous_out_frame_if_selected": index+1})
    sheet.save(sheet_path, quality=92)
    report = {"source": str(source), "source_fps": str(Fraction(rate)),
              "candidates": records, "contact_sheet": str(sheet_path),
              "selection": None,
              "review_required": ["face", "clothing", "hands_and_props",
                                  "scene_anchors", "motion", "dialogue_boundary"],
              "note": "Review images manually. This tool does not select or approve continuity."}
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--frames", required=True, type=frame_list)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    try:
        print(json.dumps(extract(args.source, args.output_dir, args.frames), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

