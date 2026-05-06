"""
extract_multicam_angles_from_open_timeline.py

A lancer depuis Resolve APRES "Open in Timeline" du multicam.
Le script lit les pistes video de la timeline multicam ouverte et affiche
des blocs prets a coller dans multicam_auto_switch_segments_inside_resolve.py:
  - MANUAL_ANGLE_FILE_PATHS
  - MANUAL_ANGLE_SYNC_OFFSETS
  - MANUAL_ANGLE_SOURCE_STARTS
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        print(msg)


def safe_call(obj: Any, method: str, *args: Any) -> Any:
    if obj is None:
        return None
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def to_int(v: Any, default: int = 0) -> int:
    try:
        return int(round(float(v)))
    except Exception:
        return default


def parse_fps_value(v: Any, default: float = 25.0) -> float:
    if v is None:
        return default
    s = str(v).strip().replace(",", ".")
    if not s:
        return default
    token = s.split()[0]
    try:
        fps = float(token)
        return fps if fps > 0 else default
    except Exception:
        return default


def infer_clip_fps(props: Dict[str, Any], timeline_fps: float) -> float:
    for key in ("FPS", "Frame Rate", "Video Frame Rate", "Video FPS"):
        if key in props:
            return parse_fps_value(props.get(key), timeline_fps)
    return timeline_fps


def choose_reference_item(items: List[Any], mc_start_open: int) -> Optional[Any]:
    """Choisit l'item representatif de la piste au debut multicam.

    Priorite:
    1) un item qui couvre mc_start_open
    2) sinon l'item dont le start est le plus proche de mc_start_open
    """
    if not items:
        return None

    enriched = []
    for it in items:
        s = to_int(safe_call(it, "GetStart"), 0)
        e = to_int(safe_call(it, "GetEnd"), s)
        enriched.append((it, s, e))

    covering = [x for x in enriched if x[1] <= mc_start_open < x[2]]
    if covering:
        # Si plusieurs, prendre celui qui commence le plus proche avant le start multicam.
        covering.sort(key=lambda x: mc_start_open - x[1])
        return covering[0][0]

    # Fallback: item au start le plus proche
    enriched.sort(key=lambda x: abs(x[1] - mc_start_open))
    return enriched[0][0]


def get_resolve() -> Any:
    try:
        return bmd.scriptapp("Resolve")  # type: ignore[name-defined]  # noqa: F821
    except Exception:
        import DaVinciResolveScript as dvr  # type: ignore

        return dvr.scriptapp("Resolve")


def main() -> int:
    log("=== Extract angles from OPEN multicam timeline ===")
    resolve = get_resolve()
    if not resolve:
        log("FAIL: Resolve inaccessible.")
        return 1

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        log("FAIL: aucune timeline active.")
        return 1

    timeline_name = safe_call(timeline, "GetName") or "<unknown>"
    log(f"Timeline active: {timeline_name}")
    timeline_fps = parse_fps_value(safe_call(timeline, "GetSetting", "timelineFrameRate"), 25.0)
    log(f"timeline_fps={timeline_fps}")

    # Coordonnees de reference de cette timeline "ouverte".
    mc_start_open = to_int(safe_call(timeline, "GetStartFrame"), 0)
    log(f"mc_start_open={mc_start_open}")

    # Filtre: typiquement les angles sont en MXF, le PGM en MP4/MOV.
    KEEP_EXTS: Set[str] = {".mxf"}
    MAX_ANGLES_TO_EXTRACT = 5
    v_count = to_int(safe_call(timeline, "GetTrackCount", "video"), 0)
    if v_count <= 0:
        log("FAIL: aucune piste video.")
        return 1

    # Cache des items par piste pour faire une extraction en 2 passes.
    tracks_items: Dict[int, List[Any]] = {}
    for t in range(1, v_count + 1):
        items = safe_call(timeline, "GetItemListInTrack", "video", t) or []
        tracks_items[t] = list(items)

    file_paths: List[str] = []
    sync_offsets: List[int] = []
    source_starts: List[int] = []
    source_start_tcs: List[str] = []
    source_fps: List[float] = []
    pgm_ref: Optional[Dict[str, Any]] = None

    # PASS 1: trouver la reference PGM.
    for t in range(1, v_count + 1):
        items = tracks_items.get(t, [])
        if not items:
            continue
        item = choose_reference_item(items, mc_start_open)
        if item is None:
            continue
        mp = safe_call(item, "GetMediaPoolItem")
        props = safe_call(mp, "GetClipProperty") if mp else {}
        props = props or {}
        fp = (props.get("File Path") or "").strip()
        if not fp:
            continue
        ext = os.path.splitext(fp)[1].lower()
        if "pgm" not in fp.lower() and ext not in {".mp4", ".mov", ".mkv"}:
            continue
        item_start_open = to_int(safe_call(item, "GetStart"), 0)
        source_start_in_file = to_int(safe_call(item, "GetSourceStartFrame"), 0)
        start_tc = str(props.get("Start TC") or props.get("Start Timecode") or "00:00:00:00").strip()
        clip_fps = infer_clip_fps(props, timeline_fps)
        pgm_ref = {
            "track_index": t,
            "file_path": fp,
            "item_start_open": item_start_open,
            "source_start_in_file": source_start_in_file,
            "start_tc": start_tc,
            "fps": clip_fps,
        }
        log(
            f"PGM REF on V{t}: path={fp} | item_start_open={item_start_open} | "
            f"source_start_in_file={source_start_in_file} | fps={clip_fps}"
        )
        break

    # Reference temporelle pour les angles camera:
    # priorite au debut reel du PGM (plus representatif de la decision list).
    ref_open = pgm_ref["item_start_open"] if pgm_ref else mc_start_open
    log(f"reference_open_for_angles={ref_open}")

    # PASS 2: extraire les angles camera en se calant sur ref_open.
    for t in range(1, v_count + 1):
        items = tracks_items.get(t, [])
        if not items:
            continue
        item = choose_reference_item(items, ref_open)
        if item is None:
            continue
        mp = safe_call(item, "GetMediaPoolItem")
        props = safe_call(mp, "GetClipProperty") if mp else {}
        props = props or {}
        fp = (props.get("File Path") or "").strip()
        if not fp:
            continue

        ext = os.path.splitext(fp)[1].lower()
        if KEEP_EXTS and ext not in KEEP_EXTS:
            log(f"Skip track V{t}: ext={ext} path={fp}")
            continue

        item_start_open = to_int(safe_call(item, "GetStart"), 0)
        source_start_in_file = to_int(safe_call(item, "GetSourceStartFrame"), 0)
        start_tc = str(props.get("Start TC") or props.get("Start Timecode") or "00:00:00:00").strip()
        clip_fps = infer_clip_fps(props, timeline_fps)
        sync = mc_start_open - item_start_open

        if len(file_paths) < MAX_ANGLES_TO_EXTRACT:
            file_paths.append(fp)
            sync_offsets.append(sync)
            source_starts.append(source_start_in_file)
            source_start_tcs.append(start_tc)
            source_fps.append(clip_fps)

            log(
                f"Track V{t}: file={fp} | item_start_open={item_start_open} | "
                f"source_start_in_file={source_start_in_file} | sync_offset={sync} | fps={clip_fps}"
            )
        else:
            log(
                f"Skip extra camera track V{t} (already {MAX_ANGLES_TO_EXTRACT} angles): {fp}"
            )

    if not file_paths:
        log("FAIL: aucun angle detecte (File Path manquant sur pistes).")
        return 1

    log("\n--- A copier dans multicam_auto_switch_segments_inside_resolve.py ---")
    log("MANUAL_ANGLE_FILE_PATHS = [")
    for p in file_paths:
        log(f"    r\"{p}\",")
    log("]")

    log(f"MANUAL_ANGLE_SYNC_OFFSETS = {sync_offsets}")
    log(f"MANUAL_ANGLE_SOURCE_STARTS = {source_starts}")
    log(f"MANUAL_ANGLE_START_TCS = {source_start_tcs}")
    log(f"MANUAL_ANGLE_SOURCE_FPS = {source_fps}")
    if pgm_ref:
        log(f"PGM_REFERENCE_PATH = r\"{pgm_ref['file_path']}\"")
        log(f"PGM_REFERENCE_ITEM_START_OPEN = {pgm_ref['item_start_open']}")
        log(f"PGM_REFERENCE_SOURCE_START_IN_FILE = {pgm_ref['source_start_in_file']}")
        log(f"PGM_REFERENCE_START_TC = \"{pgm_ref['start_tc']}\"")
        log(f"PGM_REFERENCE_SYNC_OFFSET = {mc_start_open - pgm_ref['item_start_open']}")
        log(f"PGM_REFERENCE_FPS = {pgm_ref['fps']}")
    else:
        log("PGM_REFERENCE_PATH = None  # non detecte automatiquement")
    log("SUCCESS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
