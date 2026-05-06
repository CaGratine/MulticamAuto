"""
multicam_auto_switch_segments_inside_resolve.py

Version "inside Resolve" (Workspace > Scripts), sans connexion externe.
Ce script applique des switches multicam a partir des segments PGM sur une piste.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    CV_AVAILABLE = True
except Exception:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    CV_AVAILABLE = False


# ---------------------- Configuration utilisateur -------------------------- #
PGM_TRACK = 1
MULTICAM_TRACK = 1
MAX_ANGLES = 5
SYNC_MODE = "relative"  # "relative" | "timecode"
CONFIDENCE_THRESHOLD = 0.30
# En workflow "decision list", on prefere garder le meilleur angle trouve
# meme si le score est sous le seuil, plutot que figer l'angle precedent.
USE_BEST_ANGLE_WHEN_LOW = True
APPLY_MULTICAM = False
EXPORT_DECISIONS_JSON = True
DECISIONS_JSON_NAME = "multicam_decisions.json"
AUTO_GENERATE_FCPXML = True
AUTO_IMPORT_FCPXML_IN_RESOLVE = True #False pour désactiver
AUTO_CREATE_TIMELINE_FROM_SELECTED_PGM = True
USE_EXTRACTED_CONFIG_JSON = True
EXTRACTED_CONFIG_JSON_NAME = "multicam_extracted_config.json"
REQUIRE_FRESH_EXTRACTED_CONFIG_JSON = True
EXTRACTED_CONFIG_MAX_AGE_MINUTES = 30
FCPXML_GENERATOR_SCRIPT = r"D:\Users\Emile Cervia\Documents\Boite_a_idees\PgmFromSources\generate_multicam_fcpxml_from_decisions.py"
GENERATED_FCPXML_NAME = "Timeline_auto_multicam.fcpxml"
FCPXML_TIMELINE_NAME = "Timeline Auto Multicam"
FCPXML_START_TC = "00:00:00:00"
FCPXML_AUDIO_MODE = "single-pgm-track"  # selected-angle | video-only | pgm-angle | single-pgm-track
# Recale uniquement les indices utilises pour le matching OpenCV afin
# d'eviter des frames negatives en debut de decision list.
AUTO_MATCH_CALIBRATE_TO_PGM_START = False
MIN_SEGMENT_FRAMES = 10
INITIAL_ANGLE = 1
MARKER_COLOR = "Yellow"
DOWNSCALE_SIZE = (160, 90)
DEBUG_IO = True
CALIBRATE_MANUAL_OFFSETS = False  # decale sync_offset pour empecher frame_idx negatif
# Si True, on ancre les calculs sur la reference PGM extraite du multicam ouvert.
# C'est le mode recommande quand la timeline "decision" est construite a partir du PGM.
USE_PGM_REFERENCE_ANCHOR = True
# Fallback externe si cv2/numpy indisponibles dans Python Resolve.
# Mettre le chemin Python qui a opencv-python installe (chez toi: Python 3.14).
HELPER_PYTHON = r"C:\Python314\python.exe"
# Chemin du helper (a copier aussi dans le dossier Scripts Resolve ou adapter).
HELPER_SCRIPT = r"D:\Users\Emile Cervia\Documents\Boite_a_idees\PgmFromSources\cv_hist_compare_helper.py"
# Fallback manuel si l'API n'expose pas les SourceClips multicam.
# Renseigner 5 paths (angle 1..5) si necessaire.
MANUAL_ANGLE_FILE_PATHS: List[str] = [
    r"F:\Fermactory 2026\RUSHES\JOUR_02\CAM_A\CARTE_01\XDROOT\Clip\A002C002_260425IH.MXF",
    r"F:\Fermactory 2026\RUSHES\JOUR_02\CAM_B\CARTE_01\XDROOT\Clip\B002C003_2604256E.MXF",
    r"F:\Fermactory 2026\RUSHES\JOUR_02\CAM_C\CARTE_01\XDROOT\Clip\C002C002_2604258J.MXF",
    r"F:\Fermactory 2026\RUSHES\JOUR_02\CAM_D\CARTE_01\XDROOT\Clip\D002C002_260425QY.MXF",
    r"F:\Fermactory 2026\RUSHES\JOUR_02\CAM_E\CARTE_01\XDROOT\Clip\E002C002_260425YI.MXF",
]
# Offsets sync par angle (frames), meme taille que MANUAL_ANGLE_FILE_PATHS sinon 0 par defaut.
MANUAL_ANGLE_SYNC_OFFSETS: List[int] = [-862, -50, -36, -96, -108]
# Start frame source par angle (frames). Si vide -> 0.
MANUAL_ANGLE_SOURCE_STARTS: List[int] = [0, 0, 0, 0, 0]
MANUAL_ANGLE_START_TCS: List[str] = ['18:59:48:19', '18:51:06:07', '04:08:49:03', '20:35:06:11', '20:29:02:09']
MANUAL_ANGLE_SOURCE_FPS: List[float] = [25.0, 25.0, 25.0, 25.0, 25.0]
# Reference PGM issue de extract_multicam_angles_from_open_timeline.py
PGM_REFERENCE_PATH: Optional[str] = r"F:\Fermactory 2026\RUSHES\JOUR_02\PGM\CARTE_01\Capture0001.mov"

PGM_REFERENCE_ITEM_START_OPEN: int = 90000
PGM_REFERENCE_SOURCE_START_IN_FILE: int = 0
PGM_REFERENCE_START_TC: str = "02:07:06:07"
PGM_REFERENCE_SYNC_OFFSET: int = 0
PGM_REFERENCE_FPS: float = 25.0


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


def to_int(v: Any) -> Optional[int]:
    try:
        return int(round(float(v)))
    except Exception:
        return None


def parse_fps(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def sanitize_filename(name: str) -> str:
    cleaned = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in str(name)).strip()
    return cleaned or "Timeline_auto_multicam"


def make_fcpxml_name_from_clip_name(clip_name: str) -> str:
    root, _ = os.path.splitext(str(clip_name).strip())
    stem = sanitize_filename(root or clip_name)
    return f"{stem} Auto.fcpxml"


def get_project_cache_dir(project: Any) -> Optional[str]:
    for key in ("perfCacheClipsLocation", "cacheFileLocation", "CacheFileLocation", "CacheClipLocation"):
        p = safe_call(project, "GetSetting", key) if project else None
        if isinstance(p, str) and p.strip():
            return p.strip()
    settings = safe_call(project, "GetSetting") if project else None
    if isinstance(settings, dict):
        for k, v in settings.items():
            if "cache" in str(k).lower() and isinstance(v, str) and v.strip():
                return v.strip()
    return None


def config_json_candidates(script_path: str, project: Any) -> List[str]:
    env_path = (os.getenv("MULTICAM_CONFIG_JSON_PATH") or "").strip()
    script_dir = os.path.dirname(os.path.abspath(script_path)) if script_path else os.getcwd()
    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)
    cache_dir = get_project_cache_dir(project)
    if cache_dir:
        candidates.append(os.path.join(cache_dir, EXTRACTED_CONFIG_JSON_NAME))
    candidates.append(os.path.join(script_dir, EXTRACTED_CONFIG_JSON_NAME))
    localappdata = (os.getenv("LOCALAPPDATA") or "").strip()
    if localappdata:
        candidates.append(os.path.join(localappdata, "Temp", EXTRACTED_CONFIG_JSON_NAME))
    return candidates


def timecode_to_frames(tc: str, fps: float) -> int:
    hh, mm, ss, ff = [int(p) for p in tc.split(":")]
    return int(round(((hh * 3600) + (mm * 60) + ss) * fps + ff))


def frames_to_timecode(frames: int, fps: float) -> str:
    f = max(1, int(round(fps)))
    hh = frames // (3600 * f)
    rem = frames % (3600 * f)
    mm = rem // (60 * f)
    rem %= (60 * f)
    ss = rem // f
    ff = rem % f
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def format_seconds(total_seconds: float) -> str:
    s = max(0, int(round(total_seconds)))
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def get_resolve() -> Any:
    try:
        return bmd.scriptapp("Resolve")  # type: ignore[name-defined]  # noqa: F821
    except Exception:
        import DaVinciResolveScript as dvr  # type: ignore

        return dvr.scriptapp("Resolve")


def normalize_track_items(items: Any) -> Iterable[Any]:
    if isinstance(items, dict):
        return items.values()
    if isinstance(items, list):
        return items
    return []


@dataclass
class Segment:
    index: int
    item: Any
    start: int
    end: int


@dataclass
class AngleInfo:
    angle: int
    file_path: str
    source_start: int
    sync_offset: int


def debug_methods(obj: Any, title: str) -> None:
    try:
        names = sorted(
            n
            for n in dir(obj)
            if any(k in n.lower() for k in ("source", "multi", "angle", "sync"))
        )
        log(f"{title} methods (source/multi/angle/sync):")
        for n in names:
            log(f"  - {n}")
    except Exception:
        pass


class FrameCache:
    def __init__(self) -> None:
        self.caps: Dict[str, Any] = {}

    def read(self, path: str, frame_idx: int) -> Optional[np.ndarray]:
        if frame_idx < 0 or not os.path.isfile(path):
            return None
        cap = self.caps.get(path)
        if cap is None:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return None
            self.caps[path] = cap
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            return None
        return frame

    def close(self) -> None:
        for cap in self.caps.values():
            cap.release()
        self.caps.clear()


def hist_score(a: np.ndarray, b: np.ndarray, size: Tuple[int, int]) -> float:
    sa = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    sb = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    ha = cv2.calcHist([cv2.cvtColor(sa, cv2.COLOR_BGR2HSV)], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hb = cv2.calcHist([cv2.cvtColor(sb, cv2.COLOR_BGR2HSV)], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(ha, ha, 0, 1, cv2.NORM_MINMAX)
    cv2.normalize(hb, hb, 0, 1, cv2.NORM_MINMAX)
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))


def hist_score_external(
    pgm_path: str,
    pgm_frame_idx: int,
    candidates: List[Tuple[int, str, int]],
    size: Tuple[int, int],
    timeline_fps: float,
) -> Tuple[Optional[int], float]:
    if not os.path.isfile(HELPER_SCRIPT):
        log(f"FAIL: helper introuvable: {HELPER_SCRIPT}")
        return None, -1.0
    if not os.path.isfile(HELPER_PYTHON):
        log(f"FAIL: python helper introuvable: {HELPER_PYTHON}")
        return None, -1.0

    payload = {
        "pgm_path": pgm_path,
        "pgm_frame": pgm_frame_idx,
        "pgm_time_sec": float(pgm_frame_idx) / float(timeline_fps),
        "timeline_fps": float(timeline_fps),
        "candidates": [
            {
                "angle": a,
                "path": p,
                "frame": f,
                "time_sec": float(f) / float(timeline_fps),
            }
            for (a, p, f) in candidates
        ],
        "size": [int(size[0]), int(size[1])],
    }
    try:
        run_kwargs: Dict[str, Any] = {
            "input": json.dumps(payload),
            "text": True,
            "capture_output": True,
            "check": False,
        }
        if os.name == "nt":
            # Evite l'ouverture d'une fenetre console par segment sous Windows.
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(
            [HELPER_PYTHON, HELPER_SCRIPT],
            **run_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"FAIL helper execution: {exc!r}")
        return None, -1.0

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        log(f"FAIL helper returncode={proc.returncode}: {err}")
        return None, -1.0

    try:
        out = json.loads(proc.stdout)
        angle = out.get("best_angle")
        score = float(out.get("best_score", -1.0))
        dbg = out.get("debug")
        if DEBUG_IO:
            log(
                f"[DEBUG helper] pgm_frame={pgm_frame_idx} "
                f"best_angle={angle} best_score={score:.3f}"
            )
            if dbg is not None:
                log(f"[DEBUG helper] details={dbg}")
        return (int(angle) if angle is not None else None), score
    except Exception as exc:  # noqa: BLE001
        log(f"FAIL parse helper output: {exc!r} | stdout={proc.stdout!r}")
        return None, -1.0


def run_generate_fcpxml(decisions_json: str, output_fcpxml: str, timeline_name: Optional[str] = None) -> bool:
    if not os.path.isfile(FCPXML_GENERATOR_SCRIPT):
        log(f"FAIL: generateur FCPXML introuvable: {FCPXML_GENERATOR_SCRIPT}")
        return False
    if not os.path.isfile(HELPER_PYTHON):
        log(f"FAIL: python introuvable pour generateur FCPXML: {HELPER_PYTHON}")
        return False

    effective_timeline_name = (timeline_name or "").strip() or FCPXML_TIMELINE_NAME
    cmd = [
        HELPER_PYTHON,
        FCPXML_GENERATOR_SCRIPT,
        "--decisions-json",
        decisions_json,
        "--output-fcpxml",
        output_fcpxml,
        "--timeline-name",
        effective_timeline_name,
        "--start-tc",
        FCPXML_START_TC,
        "--mc-audio-mode",
        FCPXML_AUDIO_MODE,
    ]
    kwargs: Dict[str, Any] = {"text": True, "capture_output": True, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.run(cmd, **kwargs)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        log(f"FAIL generate FCPXML rc={proc.returncode}: {err}")
        return False
    log(f"[FCPXML] genere: {output_fcpxml}")
    return True


def import_fcpxml_into_resolve(project: Any, fcpxml_path: str) -> bool:
    # Methode 1: project.ImportTimelineFromFile
    import_project_fn = getattr(project, "ImportTimelineFromFile", None)
    if callable(import_project_fn):
        ok = import_project_fn(fcpxml_path)
        if ok:
            log(f"[FCPXML] importe via project: {fcpxml_path}")
            return True
        log("[WARN] project.ImportTimelineFromFile a retourne False.")
    else:
        log("[INFO] project.ImportTimelineFromFile indisponible/non-callable.")

    # Methode 2: mediaPool.ImportTimelineFromFile
    media_pool = safe_call(project, "GetMediaPool")
    import_pool_fn = getattr(media_pool, "ImportTimelineFromFile", None) if media_pool else None
    if callable(import_pool_fn):
        ok = import_pool_fn(fcpxml_path)
        if ok:
            log(f"[FCPXML] importe via mediaPool: {fcpxml_path}")
            return True
        log("[WARN] mediaPool.ImportTimelineFromFile a retourne False.")
    else:
        log("[INFO] mediaPool.ImportTimelineFromFile indisponible/non-callable.")

    return False


def infer_source_start_frame(obj: Any, mp: Any, fps: float) -> int:
    # IMPORTANT: on veut la position dans le MEDIA SOURCE, pas la position
    # timeline du clip. GetStartFrame/GetInFrame peuvent representer la
    # timeline selon le type d'objet et faussent la reference.
    for m in ("GetSourceStartFrame",):
        v = safe_call(obj, m)
        if v is not None:
            iv = to_int(v)
            if iv is not None:
                return iv
    props = safe_call(mp, "GetClipProperty") or {}
    tc = props.get("Start TC") or props.get("Start Timecode") or ""
    return timecode_to_frames(tc, fps) if tc else 0


def infer_sync_offset_frames(source_obj: Any) -> int:
    for m in ("GetSyncOffset", "GetSyncOffsetFrames"):
        v = safe_call(source_obj, m)
        iv = to_int(v)
        if iv is not None:
            return iv
    props = safe_call(source_obj, "GetProperty") or {}
    for k in ("Sync Offset", "SyncOffset", "Sync Offset Frames"):
        if k in props:
            iv = to_int(props.get(k))
            if iv is not None:
                return iv
    return 0


def pick_selected_media_pool_item(media_pool: Any) -> Any:
    selected = safe_call(media_pool, "GetSelectedClips")
    if isinstance(selected, dict) and selected:
        return next(iter(selected.values()))
    if isinstance(selected, list) and selected:
        return selected[0]
    return None


def unique_timeline_name(project: Any, base_name: str) -> str:
    timeline_count = safe_call(project, "GetTimelineCount") or 0
    existing: List[str] = []
    for i in range(1, int(timeline_count) + 1):
        tl = safe_call(project, "GetTimelineByIndex", i)
        name = safe_call(tl, "GetName")
        if isinstance(name, str):
            existing.append(name)
    if base_name not in existing:
        return base_name
    n = 2
    while True:
        candidate = f"{base_name} ({n})"
        if candidate not in existing:
            return candidate
        n += 1


def create_timeline_and_detect_scenecuts_from_selected_pgm(project: Any) -> Tuple[Optional[Any], Optional[str]]:
    media_pool = safe_call(project, "GetMediaPool")
    if not media_pool:
        log("FAIL: MediaPool inaccessible.")
        return None, None
    selected_item = pick_selected_media_pool_item(media_pool)
    if not selected_item:
        log("FAIL: Aucun clip selectionne dans le Media Pool.")
        return None, None

    selected_name = str(safe_call(selected_item, "GetName") or "PGM_Selected")
    timeline_name = unique_timeline_name(project, selected_name)
    timeline = safe_call(media_pool, "CreateTimelineFromClips", timeline_name, [selected_item])
    if not timeline:
        log("FAIL: CreateTimelineFromClips a echoue.")
        return None, None

    safe_call(project, "SetCurrentTimeline", timeline)
    log(f"OK: Timeline creee '{timeline_name}'")
    detect_ok = safe_call(timeline, "DetectSceneCuts")
    if detect_ok:
        log("OK: DetectSceneCuts termine.")
    else:
        log("WARN: DetectSceneCuts a echoue ou indisponible sur cette timeline.")
    return timeline, selected_name


def apply_extracted_config_json(config_path: str) -> bool:
    global MANUAL_ANGLE_FILE_PATHS
    global MANUAL_ANGLE_SYNC_OFFSETS
    global MANUAL_ANGLE_SOURCE_STARTS
    global MANUAL_ANGLE_START_TCS
    global MANUAL_ANGLE_SOURCE_FPS
    global PGM_REFERENCE_PATH
    global PGM_REFERENCE_ITEM_START_OPEN
    global PGM_REFERENCE_SOURCE_START_IN_FILE
    global PGM_REFERENCE_START_TC
    global PGM_REFERENCE_SYNC_OFFSET
    global PGM_REFERENCE_FPS

    if not os.path.isfile(config_path):
        return False
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log(f"[WARN] JSON config illisible: {config_path} ({exc!r})")
        return False

    file_paths = data.get("manual_angle_file_paths")
    if isinstance(file_paths, list) and file_paths:
        MANUAL_ANGLE_FILE_PATHS = [str(x) for x in file_paths if str(x).strip()]
    sync_offsets = data.get("manual_angle_sync_offsets")
    if isinstance(sync_offsets, list):
        MANUAL_ANGLE_SYNC_OFFSETS = [to_int(x) or 0 for x in sync_offsets]
    source_starts = data.get("manual_angle_source_starts")
    if isinstance(source_starts, list):
        MANUAL_ANGLE_SOURCE_STARTS = [to_int(x) or 0 for x in source_starts]
    start_tcs = data.get("manual_angle_start_tcs")
    if isinstance(start_tcs, list):
        MANUAL_ANGLE_START_TCS = [str(x) for x in start_tcs]
    source_fps = data.get("manual_angle_source_fps")
    if isinstance(source_fps, list):
        MANUAL_ANGLE_SOURCE_FPS = [parse_fps(x) or 25.0 for x in source_fps]

    pgm_ref_path = data.get("pgm_reference_path")
    if pgm_ref_path is None or str(pgm_ref_path).strip():
        PGM_REFERENCE_PATH = str(pgm_ref_path).strip() if pgm_ref_path is not None else None
    PGM_REFERENCE_ITEM_START_OPEN = to_int(data.get("pgm_reference_item_start_open")) or 0
    PGM_REFERENCE_SOURCE_START_IN_FILE = to_int(data.get("pgm_reference_source_start_in_file")) or 0
    PGM_REFERENCE_START_TC = str(data.get("pgm_reference_start_tc") or "00:00:00:00")
    PGM_REFERENCE_SYNC_OFFSET = to_int(data.get("pgm_reference_sync_offset")) or 0
    PGM_REFERENCE_FPS = parse_fps(data.get("pgm_reference_fps")) or 25.0

    log(f"[CONFIG] JSON charge: {config_path}")
    log(f"[CONFIG] generated_from_timeline={data.get('generated_from_timeline')}")
    log(f"[CONFIG] angles charges={len(MANUAL_ANGLE_FILE_PATHS)}")
    return True


def main() -> int:
    log("=== Multicam auto switch (inside Resolve) ===")
    script_path = globals().get("__file__") or (sys.argv[0] if sys.argv else "<unknown>")
    script_dir = os.path.dirname(os.path.abspath(script_path)) if script_path != "<unknown>" else os.getcwd()
    log(f"Script file: {script_path}")
    resolve = get_resolve()
    if not resolve:
        log("FAIL: impossible d'acceder a Resolve.")
        return 1
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    if not project:
        log("FAIL: aucun projet courant.")
        return 1
    if USE_EXTRACTED_CONFIG_JSON:
        cfg_candidates = config_json_candidates(str(script_path), project)
        cfg_path = next((p for p in cfg_candidates if os.path.isfile(p)), None)
        if not cfg_path:
            msg = "[CONFIG] JSON absent (emplacements testes): " + " | ".join(cfg_candidates)
            if REQUIRE_FRESH_EXTRACTED_CONFIG_JSON:
                log(msg)
                log("FAIL: lance d'abord extract_multicam_angles_from_open_timeline.py")
                return 1
            log(f"{msg} -> fallback valeurs en dur.")
        else:
            log(f"[CONFIG] JSON trouve: {cfg_path}")
            age_seconds = max(0.0, time.time() - os.path.getmtime(cfg_path))
            max_age_seconds = max(1, int(EXTRACTED_CONFIG_MAX_AGE_MINUTES * 60))
            log(
                f"[CONFIG] age={int(age_seconds)}s "
                f"(max={max_age_seconds}s / {EXTRACTED_CONFIG_MAX_AGE_MINUTES} min)"
            )
            if age_seconds > max_age_seconds and REQUIRE_FRESH_EXTRACTED_CONFIG_JSON:
                log("FAIL: JSON config trop ancien; relance extract_multicam_angles_from_open_timeline.py")
                return 1
            if not apply_extracted_config_json(cfg_path):
                if REQUIRE_FRESH_EXTRACTED_CONFIG_JSON:
                    log("FAIL: JSON config present mais non chargeable.")
                    return 1
                log(f"[CONFIG] JSON non chargeable, fallback valeurs en dur: {cfg_path}")
    log(f"MANUAL_ANGLE_FILE_PATHS count: {len(MANUAL_ANGLE_FILE_PATHS)}")
    anchor_enabled = USE_PGM_REFERENCE_ANCHOR and (PGM_REFERENCE_ITEM_START_OPEN > 0)
    log(
        "PGM anchor: "
        f"enabled={anchor_enabled} "
        f"path_set={bool(PGM_REFERENCE_PATH)} "
        f"item_start_open={PGM_REFERENCE_ITEM_START_OPEN} "
        f"source_start_in_file={PGM_REFERENCE_SOURCE_START_IN_FILE}"
    )
    if CV_AVAILABLE:
        log("Mode comparaison: OpenCV interne Resolve")
    else:
        log("Mode comparaison: helper externe (cv2 indisponible en interne)")
    timeline = None
    selected_pgm_name_for_export: Optional[str] = None
    if project and AUTO_CREATE_TIMELINE_FROM_SELECTED_PGM:
        log("[STEP] Creation timeline + DetectSceneCuts depuis le PGM selectionne...")
        timeline, selected_pgm_name_for_export = create_timeline_and_detect_scenecuts_from_selected_pgm(project)
        if not timeline:
            return 1
    else:
        timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        log("FAIL: aucune timeline active.")
        return 1

    fps = parse_fps(safe_call(timeline, "GetSetting", "timelineFrameRate")) or 25.0
    log(f"Timeline fps={fps}")

    mc_raw = safe_call(timeline, "GetItemsInTrack", "video", MULTICAM_TRACK)
    mc_items = list(normalize_track_items(mc_raw))
    multicam = None
    # Reference de depart pour les calculs relatifs dans la timeline de matching.
    mc_start = to_int(safe_call(timeline, "GetStartFrame")) or 0
    if APPLY_MULTICAM and mc_items:
        multicam = max(
            mc_items,
            key=lambda it: (to_int(safe_call(it, "GetEnd")) or 0) - (to_int(safe_call(it, "GetStart")) or 0),
        )
        mc_start = to_int(safe_call(multicam, "GetStart")) or mc_start
        debug_methods(multicam, "TimelineItem multicam")
    else:
        log(f"[INFO] Mode PGM-only actif (pas de multicam requis sur V{MULTICAM_TRACK}).")

    pgm_raw = safe_call(timeline, "GetItemsInTrack", "video", PGM_TRACK)
    pgm_items = sorted(list(normalize_track_items(pgm_raw)), key=lambda it: to_int(safe_call(it, "GetStart")) or 0)
    segments: List[Segment] = []
    for i, it in enumerate(pgm_items, 1):
        s = to_int(safe_call(it, "GetStart"))
        e = to_int(safe_call(it, "GetEnd"))
        if s is None or e is None or e <= s:
            continue
        if (e - s) < MIN_SEGMENT_FRAMES:
            continue
        segments.append(Segment(i, it, s, e))
    if not segments:
        log(f"FAIL: aucun segment exploitable sur V{PGM_TRACK}.")
        return 1
    # Sans multicam sur la timeline, on utilise le premier segment comme ancre locale.
    if multicam is None and segments:
        mc_start = segments[0].start

    used_manual = False

    srcs = []
    if multicam is not None:
        srcs = safe_call(multicam, "GetSourceClips") or safe_call(multicam, "GetMulticamSourceClips") or []
    if isinstance(srcs, dict):
        ordered = [srcs[k] for k in sorted(srcs.keys())]
    else:
        ordered = list(srcs)

    angles: List[AngleInfo] = []
    if ordered:
        for idx, src in enumerate(ordered[:MAX_ANGLES], 1):
            mp = safe_call(src, "GetMediaPoolItem") or src
            props = safe_call(mp, "GetClipProperty") or {}
            fp = (props.get("File Path") or "").strip()
            if not fp:
                continue
            angles.append(
                AngleInfo(
                    angle=idx,
                    file_path=fp,
                    source_start=infer_source_start_frame(src, mp, fps),
                    sync_offset=infer_sync_offset_frames(src),
                )
            )
    elif MANUAL_ANGLE_FILE_PATHS:
        used_manual = True
        log("SourceClips API indisponible -> fallback MANUAL_ANGLE_FILE_PATHS.")
        for idx, fp in enumerate(MANUAL_ANGLE_FILE_PATHS[:MAX_ANGLES], 1):
            sync = MANUAL_ANGLE_SYNC_OFFSETS[idx - 1] if idx - 1 < len(MANUAL_ANGLE_SYNC_OFFSETS) else 0
            start = MANUAL_ANGLE_SOURCE_STARTS[idx - 1] if idx - 1 < len(MANUAL_ANGLE_SOURCE_STARTS) else 0
            angles.append(
                AngleInfo(
                    angle=idx,
                    file_path=fp,
                    source_start=int(start),
                    sync_offset=int(sync),
                )
            )
    else:
        log("FAIL: SourceClips multicam non exposes par l'API.")
        log("Renseigne MANUAL_ANGLE_FILE_PATHS (angle1..N) en haut du script.")
        return 1

    # Calibration de secours: si des angles donnent des frame indexes negatifs
    # (donc impossible a lire), on decale individuellement chaque angle pour
    # rendre frame_idx du 1er segment >= 0.
    if used_manual and CALIBRATE_MANUAL_OFFSETS and segments:
        rel0 = segments[0].start - mc_start
        log(f"[CALIB] rel0(first segment)={rel0}")
        for ang in angles:
            src0 = ang.source_start + rel0 + ang.sync_offset
            if src0 < 0:
                delta = -src0
                ang.sync_offset += delta
                log(
                    f"[CALIB] angle {ang.angle}: src0 was {src0}, "
                    f"delta sync_offset={delta} -> new sync_offset={ang.sync_offset}"
                )
    if not angles:
        log("FAIL: aucun angle avec File Path valide.")
        return 1

    cache = FrameCache() if CV_AVAILABLE else None
    prev_angle = INITIAL_ANGLE
    decisions: List[Dict[str, Any]] = []
    total_segments = len(segments)
    t0 = time.perf_counter()
    match_extra_offsets: Dict[int, int] = {ang.angle: 0 for ang in angles}
    if AUTO_MATCH_CALIBRATE_TO_PGM_START and segments:
        rel0 = segments[0].start - mc_start
        anchor_shift0 = (PGM_REFERENCE_ITEM_START_OPEN - mc_start) if anchor_enabled else 0
        log(f"[MATCH-CALIB] rel0={rel0} anchor_shift={anchor_shift0}")
        for ang in angles:
            src0 = ang.source_start + rel0 + anchor_shift0 + ang.sync_offset
            if src0 < 0:
                match_extra_offsets[ang.angle] = -src0
                log(
                    f"[MATCH-CALIB] angle {ang.angle}: src0={src0} -> "
                    f"extra={match_extra_offsets[ang.angle]}"
                )
    try:
        for done_idx, seg in enumerate(segments, start=1):
            seg_tc = frames_to_timecode(seg.start, fps)
            elapsed = time.perf_counter() - t0
            avg = elapsed / done_idx if done_idx > 0 else 0.0
            remaining = avg * (total_segments - done_idx)
            pct = (100.0 * done_idx / total_segments) if total_segments else 100.0
            log(
                f"[PROGRESS] {done_idx}/{total_segments} ({pct:.1f}%) "
                f"| elapsed {format_seconds(elapsed)} "
                f"| ETA {format_seconds(remaining)} "
                f"| seg {seg.index} {seg_tc}"
            )
            pgm_mp = safe_call(seg.item, "GetMediaPoolItem")
            pgm_props = safe_call(pgm_mp, "GetClipProperty") or {}
            pgm_fp = (pgm_props.get("File Path") or "").strip()
            if not pgm_fp:
                log(f"[WARN] Segment {seg.index} {seg_tc}: File Path PGM manquant.")
                continue
            if DEBUG_IO and not os.path.isfile(pgm_fp):
                log(f"[DEBUG] PGM file not found: {pgm_fp}")

            left_offset = to_int(safe_call(seg.item, "GetLeftOffset")) or 0
            pgm_src_start = infer_source_start_frame(seg.item, pgm_mp, fps)
            # IMPORTANT:
            # Dans cette timeline de cuts, left_offset correspond a la position
            # source PGM reelle du segment (ex: segment1 -> 8134).
            # Ajouter pgm_src_start ici double la reference et cree un decalage.
            pgm_frame_idx = left_offset
            rel = seg.start - mc_start

            # Ancrage PGM: rel=0 correspond au "debut de decision timeline".
            # On le mappe vers la reference PGM de la timeline multicam ouverte.
            if anchor_enabled and PGM_REFERENCE_PATH:
                pgm_fp = PGM_REFERENCE_PATH
                # On derive rel depuis la position source PGM du segment,
                # pour garder un mapping strictement base source TC/frame.
                rel = pgm_frame_idx - PGM_REFERENCE_SOURCE_START_IN_FILE
            if DEBUG_IO:
                log(
                    f"[DEBUG] Segment {seg.index} {seg_tc}: "
                    f"pgm_src_start={pgm_src_start} left_offset={left_offset} "
                    f"rel={rel} pgm_frame_idx={pgm_frame_idx}"
                )
            best_angle = None
            best_score = -1.0
            anchor_shift = PGM_REFERENCE_ITEM_START_OPEN - mc_start
            if CV_AVAILABLE:
                pgm_frame = cache.read(pgm_fp, pgm_frame_idx) if cache else None
                if pgm_frame is None:
                    log(f"[WARN] Segment {seg.index} {seg_tc}: impossible lire frame PGM.")
                    continue
                for ang in angles:
                    if SYNC_MODE == "timecode":
                        src_frame_idx = seg.start + ang.sync_offset
                    else:
                        if anchor_enabled:
                            # Decale rel pour qu'il corresponde a la meme origine que
                            # la timeline multicam ouverte (reference PGM).
                            src_frame_idx = ang.source_start + rel + anchor_shift + ang.sync_offset
                        else:
                            src_frame_idx = ang.source_start + rel + ang.sync_offset
                    src_frame_idx += match_extra_offsets.get(ang.angle, 0)
                    src_frame = cache.read(ang.file_path, src_frame_idx) if cache else None
                    if src_frame is None:
                        continue
                    score = hist_score(pgm_frame, src_frame, DOWNSCALE_SIZE)
                    if score > best_score:
                        best_score = score
                        best_angle = ang.angle
            else:
                candidates: List[Tuple[int, str, int]] = []
                for ang in angles:
                    if SYNC_MODE == "timecode":
                        src_frame_idx = seg.start + ang.sync_offset
                    else:
                        if anchor_enabled:
                            src_frame_idx = ang.source_start + rel + anchor_shift + ang.sync_offset
                        else:
                            src_frame_idx = ang.source_start + rel + ang.sync_offset
                    src_frame_idx += match_extra_offsets.get(ang.angle, 0)
                    candidates.append((ang.angle, ang.file_path, src_frame_idx))
                if DEBUG_IO:
                    for a, p, fidx in candidates:
                        log(
                            f"[DEBUG] candidate angle={a} frame={fidx} "
                            f"exists={os.path.isfile(p)} path={p}"
                        )
                best_angle, best_score = hist_score_external(
                    pgm_path=pgm_fp,
                    pgm_frame_idx=pgm_frame_idx,
                    candidates=candidates,
                    size=DOWNSCALE_SIZE,
                    timeline_fps=fps,
                )

            if best_angle is None:
                decisions.append(
                    {
                        "segment_index": seg.index,
                        "start_frame": int(seg.start),
                        "end_frame": int(seg.end),
                        "start_tc": seg_tc,
                        "pgm_frame_idx": int(pgm_frame_idx),
                        "best_angle": None,
                        "best_score": float(best_score),
                        "final_angle": int(prev_angle),
                        "reason": "no_candidate",
                    }
                )
                safe_call(
                    timeline,
                    "AddMarker",
                    seg.start,
                    MARKER_COLOR,
                    "LOW_CONF_SWITCH",
                    f"No candidate at {seg_tc}; kept angle {prev_angle}",
                    1,
                )
                log(f"[LOW] Segment {seg.index} {seg_tc}: score={best_score:.3f}, keep angle {prev_angle}")
                continue

            if best_score < CONFIDENCE_THRESHOLD:
                chosen_angle = best_angle if USE_BEST_ANGLE_WHEN_LOW else prev_angle
                safe_call(
                    timeline,
                    "AddMarker",
                    seg.start,
                    MARKER_COLOR,
                    "LOW_CONF_SWITCH",
                    f"Low confidence at {seg_tc}; best={best_angle} score={best_score:.3f}; chosen={chosen_angle}",
                    1,
                )
                log(
                    f"[LOW] Segment {seg.index} {seg_tc}: score={best_score:.3f}, "
                    f"best={best_angle}, chosen={chosen_angle}"
                )
                best_angle = chosen_angle

            final_angle = int(best_angle)
            decisions.append(
                {
                    "segment_index": seg.index,
                    "start_frame": int(seg.start),
                    "end_frame": int(seg.end),
                    "start_tc": seg_tc,
                    "pgm_frame_idx": int(pgm_frame_idx),
                    "best_angle": int(best_angle),
                    "best_score": float(best_score),
                    "final_angle": final_angle,
                    "reason": "best_or_low",
                }
            )

            if APPLY_MULTICAM:
                if multicam is None:
                    log(f"[WARN] Segment {seg.index} {seg_tc}: aucun clip multicam cible, skip SetMulticamAngle.")
                    prev_angle = final_angle
                    continue
                ok = safe_call(multicam, "SetMulticamAngle", final_angle, seg.start)
                if ok:
                    prev_angle = final_angle
                    log(f"[OK] Segment {seg.index} {seg_tc} -> angle {final_angle} score {best_score:.3f}")
                else:
                    log(f"[WARN] Segment {seg.index} {seg_tc}: SetMulticamAngle echec.")
            else:
                prev_angle = final_angle
                log(f"[DECISION] Segment {seg.index} {seg_tc} -> angle {final_angle} score {best_score:.3f}")
    finally:
        if cache:
            cache.close()

    if EXPORT_DECISIONS_JSON:
        out_json = os.path.join(script_dir, DECISIONS_JSON_NAME)
        fcpxml_name = GENERATED_FCPXML_NAME
        if selected_pgm_name_for_export:
            fcpxml_name = make_fcpxml_name_from_clip_name(selected_pgm_name_for_export)
        out_fcpxml = os.path.join(script_dir, fcpxml_name)
        match_extra_offsets_list = [int(match_extra_offsets.get(i + 1, 0)) for i in range(len(MANUAL_ANGLE_FILE_PATHS))]
        payload: Dict[str, Any] = {
            "fps": fps,
            "pgm_track": PGM_TRACK,
            "multicam_track": MULTICAM_TRACK,
            "pgm_file_path": PGM_REFERENCE_PATH or "",
            "pgm_reference_item_start_open": PGM_REFERENCE_ITEM_START_OPEN,
            "pgm_reference_source_start_in_file": PGM_REFERENCE_SOURCE_START_IN_FILE,
            "manual_angle_file_paths": MANUAL_ANGLE_FILE_PATHS,
            "manual_angle_sync_offsets": MANUAL_ANGLE_SYNC_OFFSETS,
            "manual_angle_match_extra_offsets": match_extra_offsets_list,
            "manual_angle_source_starts": MANUAL_ANGLE_SOURCE_STARTS,
            "manual_angle_start_tcs": MANUAL_ANGLE_START_TCS,
            "manual_angle_source_fps": MANUAL_ANGLE_SOURCE_FPS,
            "pgm_reference_start_tc": PGM_REFERENCE_START_TC,
            "pgm_reference_sync_offset": PGM_REFERENCE_SYNC_OFFSET,
            "pgm_reference_fps": PGM_REFERENCE_FPS,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "decisions": decisions,
        }
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log(f"[EXPORT] {len(decisions)} decisions -> {out_json}")

        if AUTO_GENERATE_FCPXML:
            timeline_name_for_import = os.path.splitext(os.path.basename(out_fcpxml))[0]
            if run_generate_fcpxml(out_json, out_fcpxml, timeline_name_for_import):
                if AUTO_IMPORT_FCPXML_IN_RESOLVE:
                    imported = import_fcpxml_into_resolve(project, out_fcpxml)
                    if not imported:
                        log(f"[WARN] Echec import FCPXML dans Resolve: {out_fcpxml}")

    log("Termine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
