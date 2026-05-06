"""
import_fcpxml_in_resolve.py

Mini script Resolve (Workspace > Scripts) pour importer un FCPXML.
"""

from __future__ import annotations

from typing import Any


FCPXML_PATH = r"D:\Users\Emile Cervia\Documents\Boite_a_idees\PgmFromSources\Timeline_auto_multicam.fcpxml"


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        print(msg)


def get_resolve() -> Any:
    try:
        return bmd.scriptapp("Resolve")  # type: ignore[name-defined]  # noqa: F821
    except Exception:
        import DaVinciResolveScript as dvr  # type: ignore
        return dvr.scriptapp("Resolve")


def main() -> int:
    log("=== Import FCPXML in Resolve ===")
    resolve = get_resolve()
    if not resolve:
        log("FAIL: Resolve inaccessible.")
        return 1

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    if not project:
        log("FAIL: Aucun projet courant.")
        return 1

    # Methode 1: project.ImportTimelineFromFile
    import_project_fn = getattr(project, "ImportTimelineFromFile", None)
    if callable(import_project_fn):
        ok = import_project_fn(FCPXML_PATH)
        if ok:
            log(f"SUCCESS(project): Timeline importee depuis {FCPXML_PATH}")
            return 0
        log("WARN: project.ImportTimelineFromFile a retourne False.")
    else:
        log("INFO: project.ImportTimelineFromFile indisponible/non-callable.")

    # Methode 2: mediaPool.ImportTimelineFromFile
    media_pool = project.GetMediaPool()
    import_pool_fn = getattr(media_pool, "ImportTimelineFromFile", None) if media_pool else None
    if callable(import_pool_fn):
        ok = import_pool_fn(FCPXML_PATH)
        if ok:
            log(f"SUCCESS(mediaPool): Timeline importee depuis {FCPXML_PATH}")
            return 0
        log("WARN: mediaPool.ImportTimelineFromFile a retourne False.")
    else:
        log("INFO: mediaPool.ImportTimelineFromFile indisponible/non-callable.")

    log(f"FAIL: impossible d'importer la timeline depuis {FCPXML_PATH}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

