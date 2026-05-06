# Protocole A/B/C - Debug connexion Resolve

## Objectif
Isoler rapidement l'origine du probleme:
- API Resolve interne OK ou non
- import externe de `DaVinciResolveScript` OK ou crash natif
- connexion externe `scriptapp("Resolve")` OK ou non

## Test A (dans Resolve)
1. Copier `resolve_inside_menu_test.py` dans:
   - `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\`
   - ou `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`
2. Dans Resolve: `Workspace > Scripts > Utility > resolve_inside_menu_test`

Interpretation:
- Si **A FAIL**: probleme Resolve/installation/scripting interne.
- Si **A OK**: Resolve fonctionne, on teste l'externe.

## Test B (terminal externe)
```powershell
py -3.10 .\resolve_external_import_only.py
```

Interpretation:
- Si **B crash access violation**: probleme runtime natif (`fusionscript.dll` / deps C++).
- Si **B OK**: import binaire passe.

## Test C (terminal externe)
```powershell
py -3.10 .\resolve_external_connect_only.py
```

Interpretation:
- Si **C retourne None**: verifier Resolve Studio ouvert + `External scripting using = Local`.
- Si **C OK**: environnement externe valide.

## Correctifs usuels si B crash
- Reparer/installer `Microsoft Visual C++ Redistributable 2015-2022 x64`
- Reboot Windows
- Reparer Resolve Studio
- Fermer overlays/injecteurs (RTSS, overlays GPU, etc.)

