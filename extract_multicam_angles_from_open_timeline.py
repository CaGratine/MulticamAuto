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

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Set

OUTPUT_JSON_NAME = "multicam_extracted_config.json"
DEBUG_LOG_CACHE_SETTINGS = True


def is_writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".write_test_tmp")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return True
    except Exception:
        return False


def get_project_cache_dir(project: Any) -> Optional[str]:
    for key in ("perfCacheClipsLocation", "cacheFileLocation", "CacheFileLocation", "CacheClipLocation"):
        p = safe_call(project, "GetSetting", key)
        if isinstance(p, str) and p.strip():
            return p.strip()
    settings = safe_call(project, "GetSetting")
    if isinstance(settings, dict):
        for k, v in settings.items():
            if "cache" in str(k).lower() and isinstance(v, str) and v.strip():
                return v.strip()
    return None


def log_cache_related_project_settings(project: Any) -> None:
    settings = safe_call(project, "GetSetting")
    if not isinstance(settings, dict):
        log("[DEBUG CACHE] Project:GetSetting() indisponible ou non-dict.")
        return
    cache_items = [(str(k), v) for k, v in settings.items() if "cache" in str(k).lower()]
    if not cache_items:
        log("[DEBUG CACHE] aucune cle contenant 'cache' dans Project:GetSetting().")
        return
    log("[DEBUG CACHE] cles detectees:")
    for k, v in sorted(cache_items, key=lambda kv: kv[0].lower()):
        log(f"  - {k} = {v}")


def config_json_candidates(script_path: str, project: Any) -> List[str]:
    env_path = (os.getenv("MULTICAM_CONFIG_JSON_PATH") or "").strip()
    script_dir = os.path.dirname(os.path.abspath(script_path))
    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)
    cache_dir = get_project_cache_dir(project)
    if cache_dir:
        candidates.append(os.path.join(cache_dir, OUTPUT_JSON_NAME))
    candidates.append(os.path.join(script_dir, OUTPUT_JSON_NAME))
    candidates.append(os.path.join(tempfile.gettempdir(), OUTPUT_JSON_NAME))
    return candidates


def choose_writable_config_path(script_path: str, project: Any) -> Optional[str]:
    for p in config_json_candidates(script_path, project):
        parent = os.path.dirname(os.path.abspath(p)) or "."
        if is_writable_dir(parent):
            return p
    return None


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
    if DEBUG_LOG_CACHE_SETTINGS and project:
        log_cache_related_project_settings(project)
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

    v_count = to_int(safe_call(timeline, "GetTrackCount", "video"), 0)
    if v_count <= 0:
        log("FAIL: aucune piste video.")
        return 1
    # Hypothese imposee:
    # - V1..V(n-1) = caméras (angles), dans l'ordre (V1 -> angle 1, V2 -> angle 2, ...)
    # - Vn = PGM (dernier track video)
    # => on deduit le nombre d'angles uniquement via les index de pistes.
    MAX_ANGLES_TO_EXTRACT = max(0, v_count - 1)
    if MAX_ANGLES_TO_EXTRACT <= 0:
        log("FAIL: aucune piste camera (il faut au moins 2 pistes video: 1 cam + 1 PGM).")
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
    angle_source_clips_map: Dict[str, List[Dict[str, Any]]] = {}
    pgm_ref: Optional[Dict[str, Any]] = None

    # PASS 1: trouver la reference PGM (dernier track video).
    pgm_track = v_count
    items = tracks_items.get(pgm_track, [])
    if not items:
        log(f"FAIL: PGM introuvable sur le dernier track V{pgm_track}.")
        return 1
    item = choose_reference_item(items, mc_start_open)
    if item is None:
        log(f"FAIL: impossible de choisir un clip PGM représentatif sur V{pgm_track}.")
        return 1
    mp = safe_call(item, "GetMediaPoolItem")
    props = safe_call(mp, "GetClipProperty") if mp else {}
    props = props or {}
    fp = (props.get("File Path") or "").strip()
    if not fp:
        log(f"FAIL: PGM clip sans File Path sur V{pgm_track}.")
        return 1
    item_start_open = to_int(safe_call(item, "GetStart"), 0)
    source_start_in_file = to_int(safe_call(item, "GetSourceStartFrame"), 0)
    start_tc = str(
        props.get("Start TC") or props.get("Start Timecode") or "00:00:00:00"
    ).strip()
    clip_fps = infer_clip_fps(props, timeline_fps)
    pgm_ref = {
        "track_index": pgm_track,
        "file_path": fp,
        "item_start_open": item_start_open,
        "source_start_in_file": source_start_in_file,
        "start_tc": start_tc,
        "fps": clip_fps,
    }
    log(
        f"PGM REF (dernier track) on V{pgm_track}: path={fp} | "
        f"item_start_open={item_start_open} | source_start_in_file={source_start_in_file} | "
        f"fps={clip_fps}"
    )

    # Reference temporelle pour les angles camera:
    # priorite au debut reel du PGM (plus representatif de la decision list).
    ref_open = pgm_ref["item_start_open"] if pgm_ref else mc_start_open
    log(f"reference_open_for_angles={ref_open}")

    # PASS 2: extraire les angles camera en se calant sur ref_open.
    angle_tracks = list(range(1, MAX_ANGLES_TO_EXTRACT + 1))

    for t in angle_tracks:
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

        item_start_open = to_int(safe_call(item, "GetStart"), 0)
        source_start_in_file = to_int(safe_call(item, "GetSourceStartFrame"), 0)
        start_tc = str(props.get("Start TC") or props.get("Start Timecode") or "00:00:00:00").strip()
        clip_fps = infer_clip_fps(props, timeline_fps)
        sync = mc_start_open - item_start_open

        angle_idx = len(file_paths) + 1
        file_paths.append(fp)
        sync_offsets.append(sync)
        source_starts.append(source_start_in_file)
        source_start_tcs.append(start_tc)
        source_fps.append(clip_fps)

        clips_for_angle: List[Dict[str, Any]] = []
        for it in items:
            mp_it = safe_call(it, "GetMediaPoolItem")
            props_it = safe_call(mp_it, "GetClipProperty") if mp_it else {}
            props_it = props_it or {}
            fp_it = (props_it.get("File Path") or "").strip()
            if not fp_it:
                continue
            s_it = to_int(safe_call(it, "GetStart"), 0)
            e_it = to_int(safe_call(it, "GetEnd"), s_it)
            src_it = to_int(safe_call(it, "GetSourceStartFrame"), 0)
            start_tc_it = str(
                props_it.get("Start TC") or props_it.get("Start Timecode") or "00:00:00:00"
            ).strip()
            fps_it = infer_clip_fps(props_it, timeline_fps)
            if e_it <= s_it:
                continue
            clips_for_angle.append(
                {
                    "file_path": fp_it,
                    "item_start_open": int(s_it),
                    "item_end_open": int(e_it),
                    "source_start_in_file": int(src_it),
                    "start_tc": start_tc_it,
                    "fps": float(fps_it),
                }
            )
        clips_for_angle.sort(key=lambda c: int(c["item_start_open"]))
        angle_source_clips_map[str(angle_idx)] = clips_for_angle

        log(
            f"Track V{t}: file={fp} | item_start_open={item_start_open} | "
            f"source_start_in_file={source_start_in_file} | sync_offset={sync} | fps={clip_fps}"
        )

    if not file_paths:
        log("FAIL: aucun angle detecte (File Path manquant sur pistes).")
        return 1

    script_path = str(globals().get("__file__") or "extract_multicam_angles_from_open_timeline.py")
    out_json = choose_writable_config_path(script_path, project)
    if not out_json:
        log("FAIL: impossible de trouver un emplacement inscriptible pour le JSON config.")
        return 1
    payload: Dict[str, Any] = {
        "manual_angle_file_paths": file_paths,
        "manual_angle_sync_offsets": sync_offsets,
        "manual_angle_source_starts": source_starts,
        "manual_angle_start_tcs": source_start_tcs,
        "manual_angle_source_fps": source_fps,
        "angle_source_clips_map": angle_source_clips_map,
        "pgm_reference_path": pgm_ref["file_path"] if pgm_ref else None,
        "pgm_reference_item_start_open": int(pgm_ref["item_start_open"]) if pgm_ref else 0,
        "pgm_reference_source_start_in_file": int(pgm_ref["source_start_in_file"]) if pgm_ref else 0,
        "pgm_reference_start_tc": str(pgm_ref["start_tc"]) if pgm_ref else "00:00:00:00",
        "pgm_reference_sync_offset": int(mc_start_open - pgm_ref["item_start_open"]) if pgm_ref else 0,
        "pgm_reference_fps": float(pgm_ref["fps"]) if pgm_ref else float(timeline_fps),
        "generated_from_timeline": str(timeline_name),
        "generated_at_epoch": int(time.time()),
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log(f"[EXPORT JSON] {out_json}")

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
