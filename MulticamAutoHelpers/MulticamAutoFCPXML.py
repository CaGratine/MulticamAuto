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


def is_valid_tc(tc: str) -> bool:
    parts = str(tc).strip().split(":")
    if len(parts) != 4:
        return False
    try:
        _ = [int(x) for x in parts]
        return True
    except Exception:
        return False


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
    ap.add_argument(
        "--zero-based-sequence",
        action="store_true",
        default=True,
        help="Force un repere sequence a 00:00:00:00 pour eviter les ambigu�t�s tcStart Resolve",
    )
    args = ap.parse_args()
    output_basename = os.path.splitext(os.path.basename(args.output_fcpxml))[0].strip()
    effective_timeline_name = output_basename or args.timeline_name

    with open(args.decisions_json, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    fps = int(round(float(data.get("fps", 25))))
    tc_start_frames = timecode_to_frames(args.start_tc, fps)
    seq_tc_start_frames = 0 if args.zero_based_sequence else tc_start_frames
    decisions: List[Dict[str, Any]] = data.get("decisions", [])
    if not decisions:
        raise RuntimeError("Aucune decision dans le JSON.")

    src_paths: List[str] = list(data.get("manual_angle_file_paths") or [])
    src_sync_offsets: List[int] = list(data.get("manual_angle_sync_offsets") or [])
    src_match_extra_offsets: List[int] = list(data.get("manual_angle_match_extra_offsets") or [])
    src_source_starts: List[int] = list(data.get("manual_angle_source_starts") or [])
    src_start_tcs: List[str] = list(data.get("manual_angle_start_tcs") or [])
    src_source_fps: List[float] = list(data.get("manual_angle_source_fps") or [])
    angle_source_clips_map: Dict[str, List[Dict[str, Any]]] = dict(data.get("angle_source_clips_map") or {})
    pgm_path = data.get("pgm_file_path")
    pgm_start_tc = str(data.get("pgm_reference_start_tc") or "00:00:00:00")
    pgm_source_fps = float(data.get("pgm_reference_fps") or fps)
    if not src_paths or len(src_paths) < 1:
        raise RuntimeError("manual_angle_file_paths manquant dans decisions json.")
    if not pgm_path:
        raise RuntimeError("pgm_file_path manquant dans decisions json.")

    mc_start_open = int(data.get("pgm_reference_sync_offset") or 0) + int(data.get("pgm_reference_item_start_open") or 0)
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
    all_angle_paths = src_paths + [pgm_path]
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
    seq_tc_start_frames = 0 if args.zero_based_sequence else tc_start_frames

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

    asset_ids_by_path: Dict[str, str] = {}
    ordered_paths: List[str] = []
    for p in all_angle_paths:
        if p and p not in ordered_paths:
            ordered_paths.append(p)
    for rows in angle_source_clips_map.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            p = str(row.get("file_path") or "").strip()
            if p and p not in ordered_paths:
                ordered_paths.append(p)

    for i, p in enumerate(ordered_paths, start=1):
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
        asset_ids_by_path[p] = aid
        tc_meta = None
        for rows in angle_source_clips_map.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and str(row.get("file_path") or "").strip() == p:
                    tc_meta = row
                    break
            if tc_meta is not None:
                break
        if tc_meta is not None:
            start_tc_i = str(tc_meta.get("start_tc") or "00:00:00:00").strip()
            tc_fps_i = float(tc_meta.get("fps") or fps)
        else:
            base_idx = all_angle_paths.index(p) if p in all_angle_paths else -1
            start_tc_i = all_start_tcs[base_idx] if base_idx >= 0 and base_idx < len(all_start_tcs) else "00:00:00:00"
            tc_fps_i = float(all_source_fps[base_idx]) if base_idx >= 0 and base_idx < len(all_source_fps) else float(fps)
        if (not is_valid_tc(start_tc_i)) or start_tc_i == "00:00:00:00":
            base_idx = all_angle_paths.index(p) if p in all_angle_paths else -1
            if base_idx >= 0 and base_idx < len(all_start_tcs):
                base_tc = str(all_start_tcs[base_idx] or "").strip()
                if is_valid_tc(base_tc):
                    start_tc_i = base_tc
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
                # Conserve l'audio sur toutes les sources pour rester coherent
                # avec les rushes multicam (Resolve activera si piste audio presente).
                "hasAudio": "1",
                "audioSources": "1",
                "audioChannels": "2",
                "src": "file://localhost/" + p.replace("\\", "/"),
            },
        )

    multicam_display_name = effective_timeline_name
    media_id = "r_media_mc"
    media = ET.SubElement(resources, "media", {"id": media_id, "name": multicam_display_name})
    multicam = ET.SubElement(
        media,
        "multicam",
        {
            "format": "r_fmt_main",
                "tcStart": frames_to_fcptime(seq_tc_start_frames, fps),
            "tcFormat": "NDF",
        },
    )

    angle_ids: Dict[int, str] = {}
    for i, name in enumerate(angle_names, start=1):
        angle_id = str(uuid.uuid4())
        angle_ids[i] = angle_id
        mc_angle = ET.SubElement(multicam, "mc-angle", {"name": name, "angleID": angle_id})
        if i <= len(src_paths):
            rows = angle_source_clips_map.get(str(i))
            if isinstance(rows, list) and rows:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    p = str(row.get("file_path") or "").strip()
                    aid = asset_ids_by_path.get(p)
                    if not p or not aid:
                        continue
                    item_start_open = int(row.get("item_start_open") or 0)
                    item_end_open = int(row.get("item_end_open") or item_start_open)
                    source_start = int(row.get("source_start_in_file") or 0)
                    start_tc_i = str(row.get("start_tc") or "00:00:00:00").strip()
                    tc_fps_i = float(row.get("fps") or fps)
                    if (not is_valid_tc(start_tc_i)) or start_tc_i == "00:00:00:00":
                        if i - 1 < len(all_start_tcs):
                            base_tc = str(all_start_tcs[i - 1] or "").strip()
                            if is_valid_tc(base_tc):
                                start_tc_i = base_tc
                    asset_start_frames = timecode_to_frames(start_tc_i, int(round(tc_fps_i)))
                    sync = mc_start_open - item_start_open
                    clip_offset_frames = max(0, -sync)
                    clip_start_frames = asset_start_frames + source_start + max(0, sync)
                    clip_duration = max(1, item_end_open - item_start_open)
                    ET.SubElement(
                        mc_angle,
                        "asset-clip",
                        {
                            "offset": frames_to_fcptime(clip_offset_frames, fps),
                            "name": os.path.basename(p),
                            "start": frames_to_fcptime(clip_start_frames, fps),
                            "duration": frames_to_fcptime(clip_duration, fps),
                            "ref": aid,
                            "enabled": "1",
                        },
                    )
                continue
        sync = int(all_sync_offsets[i - 1]) if i - 1 < len(all_sync_offsets) else 0
        source_start = int(all_source_starts[i - 1]) if i - 1 < len(all_source_starts) else 0
        start_tc_i = all_start_tcs[i - 1] if i - 1 < len(all_start_tcs) else "00:00:00:00"
        tc_fps_i = float(all_source_fps[i - 1]) if i - 1 < len(all_source_fps) else float(fps)
        asset_start_frames = timecode_to_frames(start_tc_i, int(round(tc_fps_i)))
        clip_offset_frames = max(0, -sync)
        clip_start_frames = asset_start_frames + source_start + max(0, sync)
        p = all_angle_paths[i - 1]
        aid = asset_ids_by_path.get(p)
        if not aid:
            continue
        ET.SubElement(
            mc_angle,
            "asset-clip",
            {
                "offset": frames_to_fcptime(clip_offset_frames, fps),
                "name": os.path.basename(p),
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
    event = ET.SubElement(library, "event", {"name": f"{effective_timeline_name} (Auto)"})
    project = ET.SubElement(event, "project", {"name": effective_timeline_name})
    seq = ET.SubElement(
        project,
        "sequence",
        {
            "format": "r_fmt_main",
            "tcStart": frames_to_fcptime(seq_tc_start_frames, fps),
            "tcFormat": "NDF",
            "duration": frames_to_fcptime(total_duration, fps),
        },
    )
    spine = ET.SubElement(seq, "spine")

    # Build mc-clip segments from decisions (video cuts)
    first_multicam_media_pos: int | None = None
    for d in decisions:
        seg_start = int(d["start_frame"])
        seg_end = int(d["end_frame"])
        if seg_end <= seg_start:
            continue
        final_angle = int(d.get("final_angle") or 1)
        final_angle = max(1, min(final_angle, len(src_paths)))  # force camera, pas PGM
        rel_frames = seg_start - start_frame
        # Domaine absolu aligne sur tcStart de la sequence.
        offset_frames = seq_tc_start_frames + rel_frames
        # Reference absolue de ce segment dans le fichier PGM.
        # Si absent (anciens JSON), fallback sur un calcul relatif.
        pgm_frame_idx = int(d.get("pgm_frame_idx", pgm_source_start + rel_frames))
        pgm_source_abs = pgm_asset_start_frames + pgm_frame_idx
        # Inversion du mapping mc-angle pour retrouver la position multicam:
        # source_abs = clip_start + (mc_pos - clip_offset)
        # => mc_pos = source_abs - clip_start + clip_offset
        multicam_media_pos = pgm_source_abs - pgm_clip_start_frames + pgm_clip_offset_frames
        if first_multicam_media_pos is None:
            first_multicam_media_pos = multicam_media_pos
        dur_frames = seg_end - seg_start
        mc = ET.SubElement(
            spine,
            "mc-clip",
            {
                "offset": frames_to_fcptime(offset_frames, fps),
                "name": multicam_display_name,
                "start": frames_to_fcptime(seq_tc_start_frames + multicam_media_pos, fps),
                "duration": frames_to_fcptime(dur_frames, fps),
                "ref": media_id,
            },
        )
        ET.SubElement(mc, "mc-source", {"angleID": angle_ids[final_angle], "srcEnable": "video"})

    # Audio PGM continu via un seul mc-clip audio.
    audio_mc_start = first_multicam_media_pos if first_multicam_media_pos is not None else 0
    mc_audio = ET.SubElement(
        spine,
        "mc-clip",
        {
            "offset": frames_to_fcptime(seq_tc_start_frames, fps),
            "name": f"{multicam_display_name} Audio PGM",
            "start": frames_to_fcptime(seq_tc_start_frames + audio_mc_start, fps),
            "duration": frames_to_fcptime(total_duration, fps),
            "ref": media_id,
            "lane": "1",
        },
    )
    ET.SubElement(mc_audio, "mc-source", {"angleID": angle_ids[len(all_angle_paths)], "srcEnable": "audio"})

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

