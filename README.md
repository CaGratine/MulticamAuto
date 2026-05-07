# Auto Multicam From PGM (Resolve)

Scripts pour automatiser un remontage multicam a partir d'un PGM dans DaVinci Resolve.

## Principe

- Les cameras sont lues dans une timeline multicam ouverte (`V1..V(n-1)`).
- Le `PGM` doit etre sur la derniere piste video (`Vn`).
- Le script d'extraction genere un JSON de config.
- Le script principal detecte les cuts du PGM, compare les angles, puis exporte:
  - une decision list (`multicam_decisions.json`)
  - un FCPXML
  - import automatique dans Resolve.

---

## Installation

## Windows

Copier les scripts dans:

`C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Edit\`

Arborescence attendue:

- `multicam_auto_switch_segments_inside_resolve.py`
- `extract_multicam_angles_from_open_timeline.py`
- `helpers\cv_hist_compare_helper.py`
- `helpers\generate_multicam_fcpxml_from_decisions.py`

## macOS

Copier les scripts dans:

`/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/`

Arborescence attendue:

- `multicam_auto_switch_segments_inside_resolve.py`
- `extract_multicam_angles_from_open_timeline.py`
- `helpers/cv_hist_compare_helper.py`
- `helpers/generate_multicam_fcpxml_from_decisions.py`

## Prerequis

- DaVinci Resolve (Studio ou Free).
- Python externe accessible (utilise par les helpers).
- OpenCV disponible pour le Python externe (`cv2`), car le matching passe par helper.

---

## Workflow Resolve (recommande)

1. Faire la synchro multicam comme d'habitude, avec le **PGM sur la derniere piste**.
2. Ouvrir le multicam dans la timeline et copier tout le contenu.
3. Faire une nouvelle timeline, y coller tout le contenu du multicam.
4. Lancer le script `extract_multicam_angles_from_open_timeline.py`.
5. Selectionner le media PGM dans le Media Pool (IN/OUT possible si besoin).
6. Lancer le script `multicam_auto_switch_segments_inside_resolve.py`.
7. Prendre un cafe.
8. Une timeline nommee `NomDuPGM Auto` apparait, avec son clip multicam associe.
9. Bon remontage.

---

## Notes importantes

- Le nombre d'angles est dynamique, derive du JSON d'extraction.
- Le mode multi-fichiers par angle est gere (ex: camera C coupee en plusieurs clips).
- Les scripts `extract` et `auto_switch` doivent etre executes sur la meme machine/projet pour conserver des chemins media coherents.
