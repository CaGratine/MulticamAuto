#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

import cv2


def frames_to_fcptime(frames: int, fps: int) -> str:
    return f"{int(frames)}/{int(fps)}s"


def timecode_to_frames(tc: str, fps: int) -> int:
    hh, mm, ss, ff = [int(x) for x in tc.split(":")]
    return ((hh * 3600) + (mm * 60) + ss) * int(fps) + ff


def probe_video(path: str, fallback_fps: int) -> Tuple[int, int, int, int]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 1920, 1080, fallback_fps, 0
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        fps = int(round(cap.get(cv2.CAP_PROP_FPS) or fallback_fps))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0:
            fps = fallback_fps
        return w, h, fps, frames
    finally:
        cap.release()


def indent(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "    "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "    "
        for e in elem:
            indent(e, level + 1)
        if not e.tail or not e.tail.strip():
            e.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def main() -> int:
    ap = argparse.ArgumentParser(description="Genere un FCPXML multicam depuis decisions JSON.")
    ap.add_argument("--decisions-json", required=True)
    ap.add_argument("--output-fcpxml", required=True)
    ap.add_argument("--timeline-name", default="Timeline Auto Multicam")
    ap.add_argument("--start-tc", default="01:00:00:00")
    ap.add_argument("--angle-names", default="A,B,C,D,E,PGM")
    ap.add_argument("--include-pgm-audio", action="store_true")
    args = ap.parse_args()

    with open(args.decisions_json, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    fps = int(round(float(data.get("fps", 25))))
    tc_start_frames = timecode_to_frames(args.start_tc, fps)
    decisions: List[Dict[str, Any]] = data.get("decisions", [])
    if not decisions:
        raise RuntimeError("Aucune decision dans le JSON.")

    src_paths: List[str] = list(data.get("manual_angle_file_paths") or [])
    src_sync_offsets: List[int] = list(data.get("manual_angle_sync_offsets") or [])
    src_match_extra_offsets: List[int] = list(data.get("manual_angle_match_extra_offsets") or [])
    src_source_starts: List[int] = list(data.get("manual_angle_source_starts") or [])
    src_start_tcs: List[str] = list(data.get("manual_angle_start_tcs") or [])
    src_source_fps: List[float] = list(data.get("manual_angle_source_fps") or [])
    pgm_path = data.get("pgm_file_path")
    pgm_start_tc = str(data.get("pgm_reference_start_tc") or "00:00:00:00")
    pgm_source_fps = float(data.get("pgm_reference_fps") or fps)
    if not src_paths or len(src_paths) < 1:
        raise RuntimeError("manual_angle_file_paths manquant dans decisions json.")
    if not pgm_path:
        raise RuntimeError("pgm_file_path manquant dans decisions json.")

    # Ajoute PGM comme dernier angle.
    all_angle_paths = src_paths + [pgm_path]
    # PGM comme angle final dans le multicam.
    pgm_sync_offset = int(data.get("pgm_reference_sync_offset") or 0)
    pgm_source_start = int(data.get("pgm_reference_source_start_in_file") or 0)
    if not src_match_extra_offsets:
        src_match_extra_offsets = [0] * len(src_paths)
    effective_src_sync_offsets: List[int] = []
    for i, s in enumerate(src_sync_offsets):
        extra = int(src_match_extra_offsets[i]) if i < len(src_match_extra_offsets) else 0
        effective_src_sync_offsets.append(int(s) + extra)

    all_sync_offsets = effective_src_sync_offsets + [pgm_sync_offset]
    all_source_starts = src_source_starts + [pgm_source_start]
    all_start_tcs = src_start_tcs + [pgm_start_tc]
    all_source_fps = src_source_fps + [pgm_source_fps]
    angle_names = [x.strip() for x in args.angle_names.split(",")]
    while len(angle_names) < len(all_angle_paths):
        angle_names.append(f"ANGLE_{len(angle_names)+1}")
    angle_names = angle_names[: len(all_angle_paths)]

    # Base timeline frames
    start_frame = min(int(d["start_frame"]) for d in decisions)
    end_frame = max(int(d["end_frame"]) for d in decisions)
    total_duration = max(1, end_frame - start_frame)

    # Probe first source for timeline format
    w0, h0, fps0, _ = probe_video(all_angle_paths[0], fps)
    if fps0 > 0:
        fps = fps0
    tc_start_frames = timecode_to_frames(args.start_tc, fps)

    root = ET.Element("fcpxml", {"version": "1.8"})
    resources = ET.SubElement(root, "resources")
    fmt_main = ET.SubElement(
        resources,
        "format",
        {
            "id": "r_fmt_main",
            "name": f"Custom_{w0}x{h0}p{fps}",
            "frameDuration": f"1/{fps}s",
            "width": str(w0),
            "height": str(h0),
        },
    )

    asset_ids: List[str] = []
    for i, p in enumerate(all_angle_paths, start=1):
        w, h, pfps, count = probe_video(p, fps)
        fmt_id = f"r_fmt_{i}"
        ET.SubElement(
            resources,
            "format",
            {
                "id": fmt_id,
                "name": f"Src_{i}_{w}x{h}p{pfps}",
                "frameDuration": f"1/{pfps}s",
                "width": str(w),
                "height": str(h),
            },
        )
        aid = f"r_asset_{i}"
        asset_ids.append(aid)
        start_tc_i = all_start_tcs[i - 1] if i - 1 < len(all_start_tcs) else "00:00:00:00"
        tc_fps_i = float(all_source_fps[i - 1]) if i - 1 < len(all_source_fps) else float(fps)
        start_frames_i = timecode_to_frames(start_tc_i, int(round(tc_fps_i)))
        ET.SubElement(
            resources,
            "asset",
            {
                "id": aid,
                "name": os.path.basename(p),
                "format": fmt_id,
                "start": frames_to_fcptime(start_frames_i, fps),
                "duration": frames_to_fcptime(count if count > 0 else total_duration + start_frame + fps * 10, fps),
                "hasVideo": "1",
                "hasAudio": "1" if i == len(all_angle_paths) else "0",
                "audioSources": "1" if i == len(all_angle_paths) else "0",
                "audioChannels": "2" if i == len(all_angle_paths) else "0",
                "src": "file://localhost/" + p.replace("\\", "/"),
            },
        )

    media_id = "r_media_mc"
    media = ET.SubElement(resources, "media", {"id": media_id, "name": "Auto Multicam"})
    multicam = ET.SubElement(
        media,
        "multicam",
        {
            "format": "r_fmt_main",
            "tcStart": frames_to_fcptime(tc_start_frames, fps),
            "tcFormat": "NDF",
        },
    )

    angle_ids: Dict[int, str] = {}
    for i, (name, aid) in enumerate(zip(angle_names, asset_ids), start=1):
        angle_id = str(uuid.uuid4())
        angle_ids[i] = angle_id
        mc_angle = ET.SubElement(multicam, "mc-angle", {"name": name, "angleID": angle_id})
        sync = int(all_sync_offsets[i - 1]) if i - 1 < len(all_sync_offsets) else 0
        source_start = int(all_source_starts[i - 1]) if i - 1 < len(all_source_starts) else 0
        start_tc_i = all_start_tcs[i - 1] if i - 1 < len(all_start_tcs) else "00:00:00:00"
        tc_fps_i = float(all_source_fps[i - 1]) if i - 1 < len(all_source_fps) else float(fps)
        asset_start_frames = timecode_to_frames(start_tc_i, int(round(tc_fps_i)))
        # Conversion du modele de sync:
        # item_start_open = mc_start_open - sync_offset
        # => dans la multicam, le clip commence a offset=max(0,-sync)
        # et son "start" dans le media source est ajuste si sync > 0.
        clip_offset_frames = max(0, -sync)
        clip_start_frames = asset_start_frames + source_start + max(0, sync)
        ET.SubElement(
            mc_angle,
            "asset-clip",
            {
                "offset": frames_to_fcptime(clip_offset_frames, fps),
                "name": os.path.basename(all_angle_paths[i - 1]),
                "start": frames_to_fcptime(clip_start_frames, fps),
                "duration": frames_to_fcptime(total_duration + start_frame, fps),
                "ref": aid,
                "enabled": "1",
            },
        )

    # Parametres de mapping du PGM dans le repere multicam (angle final).
    pgm_clip_sync = int(all_sync_offsets[-1]) if all_sync_offsets else 0
    pgm_clip_source_start = int(all_source_starts[-1]) if all_source_starts else 0
    pgm_clip_start_tc = all_start_tcs[-1] if all_start_tcs else "00:00:00:00"
    pgm_clip_tc_fps = float(all_source_fps[-1]) if all_source_fps else float(fps)
    pgm_asset_start_frames = timecode_to_frames(pgm_clip_start_tc, int(round(pgm_clip_tc_fps)))
    pgm_clip_offset_frames = max(0, -pgm_clip_sync)
    pgm_clip_start_frames = pgm_asset_start_frames + pgm_clip_source_start + max(0, pgm_clip_sync)

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": f"{args.timeline_name} (Auto)"})
    project = ET.SubElement(event, "project", {"name": args.timeline_name})
    seq = ET.SubElement(
        project,
        "sequence",
        {
            "format": "r_fmt_main",
            "tcStart": frames_to_fcptime(tc_start_frames, fps),
            "tcFormat": "NDF",
            "duration": frames_to_fcptime(total_duration, fps),
        },
    )
    spine = ET.SubElement(seq, "spine")

    # Build mc-clip segments from decisions
    for d in decisions:
        seg_start = int(d["start_frame"])
        seg_end = int(d["end_frame"])
        if seg_end <= seg_start:
            continue
        final_angle = int(d.get("final_angle") or 1)
        final_angle = max(1, min(final_angle, len(src_paths)))  # force camera, pas PGM
        rel_frames = seg_start - start_frame
        offset_frames = tc_start_frames + rel_frames
        # Reference absolue de ce segment dans le fichier PGM.
        # Si absent (anciens JSON), fallback sur un calcul relatif.
        pgm_frame_idx = int(d.get("pgm_frame_idx", pgm_source_start + rel_frames))
        pgm_source_abs = pgm_asset_start_frames + pgm_frame_idx
        # Inversion du mapping mc-angle pour retrouver la position multicam:
        # source_abs = clip_start + (mc_pos - clip_offset)
        # => mc_pos = source_abs - clip_start + clip_offset
        multicam_media_pos = pgm_source_abs - pgm_clip_start_frames + pgm_clip_offset_frames
        multicam_start_frames = tc_start_frames + multicam_media_pos
        dur_frames = seg_end - seg_start
        mc = ET.SubElement(
            spine,
            "mc-clip",
            {
                "offset": frames_to_fcptime(offset_frames, fps),
                "name": "Auto Multicam",
                "start": frames_to_fcptime(multicam_start_frames, fps),
                "duration": frames_to_fcptime(dur_frames, fps),
                "ref": media_id,
            },
        )
        ET.SubElement(mc, "mc-source", {"angleID": angle_ids[final_angle], "srcEnable": "video"})

    # Audio PGM continu optionnel (dernier asset).
    if args.include_pgm_audio:
        pgm_asset_id = asset_ids[-1]
        pgm_asset_start = timecode_to_frames(pgm_start_tc, int(round(pgm_source_fps)))
        ET.SubElement(
            spine,
            "asset-clip",
            {
                "offset": frames_to_fcptime(tc_start_frames, fps),
                "name": os.path.basename(pgm_path),
                "start": frames_to_fcptime(pgm_asset_start + pgm_source_start, fps),
                "duration": frames_to_fcptime(total_duration, fps),
                "ref": pgm_asset_id,
                "enabled": "1",
                "lane": "1",
            },
        )

    indent(root)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    xml = xml.replace('<?xml version=\'1.0\' encoding=\'utf-8\'?>', '<?xml version="1.0" encoding="UTF-8"?>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + "\n".join(xml.splitlines()[1:])

    with open(args.output_fcpxml, "w", encoding="utf-8") as f:
        f.write(xml)

    print(f"OK: {args.output_fcpxml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

