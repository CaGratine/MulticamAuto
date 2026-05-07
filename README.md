# Auto Multicam From PGM (Resolve)

Scripts pour automatiser un remontage multicam à partir d'un PGM dans DaVinci Resolve.

## Principe

- Les caméras sont lues dans une timeline multicam ouverte (`V1..V(n-1)`).
- Le `PGM` doit être sur la dernière piste vidéo (`Vn`).
- Le script d'extraction génère un JSON de config.
- Le script principal détecte les cuts du PGM, compare les angles, puis exporte :
  - une decision list (`multicam_decisions.json`)
  - un FCPXML
  - import automatique dans Resolve.

---

## Installation

## Prérequis

- DaVinci Resolve (Studio ou Free).
- Python externe accessible (utilisé par les helpers).
- OpenCV disponible pour le Python externe (`cv2`), car le matching passe par helper.

Téléchargement Python (officiel) :

- [https://www.python.org/downloads/](https://www.python.org/downloads/)

## Windows

Installation des dépendances (terminal) :

```powershell
py -m pip install --upgrade pip
py -m pip install opencv-python
```

Copier les scripts dans :

`C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Edit\`

Arborescence attendue :

- `MulticamAuto-Switch.py`
- `MulticamAuto-Extract.py`
- `MulticamAutoHelpers\MulticamAutoHelperCompare.py`
- `MulticamAutoHelpers\MulticamAutoFCPXML.py`

## macOS

Installation des dépendances (terminal) :

```bash
python3 -m pip install --upgrade pip
python3 -m pip install opencv-python
```

Copier les scripts dans :

`/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/`

Arborescence attendue :

- `MulticamAuto-Switch.py`
- `MulticamAuto-Extract.py`
- `MulticamAutoHelpers/MulticamAutoHelperCompare.py`
- `MulticamAutoHelpers/MulticamAutoFCPXML.py`

---

## Workflow Resolve (recommandé)

1. Faire la synchro multicam comme d'habitude, avec le **PGM sur la dernière piste**.
2. Ouvrir le multicam dans la timeline et copier tout le contenu.
3. Faire une nouvelle timeline, y coller tout le contenu du multicam.
4. Lancer le script `MulticamAuto-Extract.py`.
5. Sélectionner le média PGM dans le Media Pool (IN/OUT possible si besoin).
6. Lancer le script `MulticamAuto-Switch.py`.
7. Prendre un café.
8. Une timeline nommée `NomDuPGM Auto` apparaît, avec son clip multicam associé.
9. Bon remontage.

---

## Notes importantes

- Le nombre d'angles est dynamique, dérivé du JSON d'extraction.
- Le mode multi-fichiers par angle est géré (ex : caméra C coupée en plusieurs clips).
- Les scripts `extract` et `auto_switch` doivent être exécutés sur la même machine/projet pour conserver des chemins média cohérents.
