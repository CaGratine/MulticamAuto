#!/usr/bin/env python3
"""
Helper externe pour multicam_auto_switch_segments_inside_resolve.py
Lit un payload JSON depuis stdin et renvoie:
{"best_angle": int|None, "best_score": float}
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np


def to_native_frame_idx(path: str, time_sec: float) -> Optional[int]:
    if time_sec < 0 or not os.path.isfile(path):
        return None
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            return None
        return max(0, int(round(time_sec * fps)))
    finally:
        cap.release()


def read_frame(path: str, frame_idx: int) -> Optional[Any]:
    if frame_idx < 0 or not os.path.isfile(path):
        return None
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            return None
        return frame
    finally:
        cap.release()


def hist_score(a: Any, b: Any, size: Tuple[int, int]) -> float:
    sa = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    sb = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    ha = cv2.calcHist([cv2.cvtColor(sa, cv2.COLOR_BGR2HSV)], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hb = cv2.calcHist([cv2.cvtColor(sb, cv2.COLOR_BGR2HSV)], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(ha, ha, 0, 1, cv2.NORM_MINMAX)
    cv2.normalize(hb, hb, 0, 1, cv2.NORM_MINMAX)
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))


def edge_score(a: Any, b: Any, size: Tuple[int, int]) -> float:
    sa = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    sb = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    ga = cv2.cvtColor(sa, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(sb, cv2.COLOR_BGR2GRAY)
    ea = cv2.Canny(ga, 80, 160)
    eb = cv2.Canny(gb, 80, 160)
    inter = np.logical_and(ea > 0, eb > 0).sum()
    union = np.logical_or(ea > 0, eb > 0).sum()
    if union <= 0:
        return 0.0
    return float(inter / union)


def orb_score(a: Any, b: Any, size: Tuple[int, int]) -> float:
    sa = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    sb = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    ga = cv2.cvtColor(sa, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(sb, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=250, fastThreshold=15)
    kpa, desa = orb.detectAndCompute(ga, None)
    kpb, desb = orb.detectAndCompute(gb, None)
    if desa is None or desb is None or not kpa or not kpb:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(desa, desb)
    if not matches:
        return 0.0

    # ORB distance petite = meilleure correspondance.
    good = [m for m in matches if m.distance <= 45]
    denom = max(1, min(len(kpa), len(kpb)))
    return float(len(good) / denom)


def combined_score(a: Any, b: Any, size: Tuple[int, int]) -> float:
    h = hist_score(a, b, size)             # [-1, 1]
    h_norm = max(0.0, min(1.0, (h + 1.0) / 2.0))
    e = edge_score(a, b, size)             # [0, 1]
    o = orb_score(a, b, size)              # [0, ~1]
    # Poids "leger" et robustes pour scenes multicam.
    return 0.45 * h_norm + 0.35 * e + 0.20 * min(1.0, o)


def main() -> int:
    try:
        payload: Dict[str, Any] = json.loads(sys.stdin.read())
    except Exception as exc:  # noqa: BLE001
        print(f"invalid input json: {exc!r}", file=sys.stderr)
        return 2

    pgm_path = payload.get("pgm_path", "")
    pgm_frame = int(payload.get("pgm_frame", -1))
    pgm_time_sec = payload.get("pgm_time_sec")
    size_raw = payload.get("size", [160, 90])
    size = (int(size_raw[0]), int(size_raw[1]))
    candidates = payload.get("candidates", [])

    debug: Dict[str, Any] = {"pgm_path_exists": os.path.isfile(pgm_path), "pgm_frame": pgm_frame}
    if pgm_time_sec is not None:
        pgm_idx = to_native_frame_idx(pgm_path, float(pgm_time_sec))
        if pgm_idx is not None:
            pgm_frame = pgm_idx
            debug["pgm_frame_native"] = pgm_idx
    pgm = read_frame(pgm_path, pgm_frame)
    if pgm is None:
        print(json.dumps({"best_angle": None, "best_score": -1.0, "debug": {**debug, "pgm_read_ok": False}}))
        return 0

    best_angle = None
    best_score = -1.0
    readable = 0
    details = []
    for cand in candidates:
        angle = int(cand["angle"])
        path = cand["path"]
        frame_idx = int(cand["frame"])
        time_sec = cand.get("time_sec")
        if time_sec is not None:
            native_idx = to_native_frame_idx(path, float(time_sec))
            if native_idx is not None:
                frame_idx = native_idx
        src = read_frame(path, frame_idx)
        if src is None:
            continue
        readable += 1
        score = combined_score(pgm, src, size)
        details.append({"angle": angle, "score": round(float(score), 4), "frame_idx": frame_idx})
        if score > best_score:
            best_score = score
            best_angle = angle

    print(
        json.dumps(
            {
                "best_angle": best_angle,
                "best_score": best_score,
                "debug": {
                    **debug,
                    "pgm_read_ok": True,
                    "readable_candidates": readable,
                    "candidate_count": len(candidates),
                    "candidate_scores": details,
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
