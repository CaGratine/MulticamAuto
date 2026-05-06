"""
create_timeline_and_detect_scenecuts_from_selected_pgm.py

Script Resolve (Workspace > Scripts):
1) Lit le clip selectionne dans le Media Pool
2) Cree une timeline nommee comme le clip
3) Insere le clip en V1
4) Lance DetectSceneCuts() sur la timeline
"""

from __future__ import annotations

from typing import Any, List


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


def get_resolve() -> Any:
    try:
        return bmd.scriptapp("Resolve")  # type: ignore[name-defined]  # noqa: F821
    except Exception:
        import DaVinciResolveScript as dvr  # type: ignore

        return dvr.scriptapp("Resolve")


def pick_selected_media_pool_item(media_pool: Any) -> Any:
    # API habituelle
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


def main() -> int:
    log("=== Create timeline + scene detect from selected PGM ===")
    resolve = get_resolve()
    if not resolve:
        log("FAIL: Resolve inaccessible.")
        return 1

    pm = safe_call(resolve, "GetProjectManager")
    project = safe_call(pm, "GetCurrentProject") if pm else None
    if not project:
        log("FAIL: Aucun projet courant.")
        return 1

    media_pool = safe_call(project, "GetMediaPool")
    if not media_pool:
        log("FAIL: MediaPool inaccessible.")
        return 1

    selected_item = pick_selected_media_pool_item(media_pool)
    if not selected_item:
        log("FAIL: Aucun clip selectionne dans le Media Pool.")
        return 1

    clip_name = safe_call(selected_item, "GetName") or "PGM_Selected"
    timeline_name = unique_timeline_name(project, str(clip_name))
    timeline = safe_call(media_pool, "CreateTimelineFromClips", timeline_name, [selected_item])
    if not timeline:
        log("FAIL: CreateTimelineFromClips a echoue.")
        return 2

    # Charge la timeline nouvellement creee
    safe_call(project, "SetCurrentTimeline", timeline)
    log(f"OK: Timeline creee '{timeline_name}'")

    detect_ok = safe_call(timeline, "DetectSceneCuts")
    if detect_ok:
        log("OK: DetectSceneCuts termine.")
        return 0

    log("WARN: DetectSceneCuts a echoue ou indisponible sur cette timeline.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

