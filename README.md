# radar-scout

NEXRAD Level II 3D viewer built so every displayed value traces to the source file. **Not ready for scientific use**:
see `report/validation_report.md`, `SCIENTIFIC_LIMITATIONS.md`, `docs/VALIDATION_STATUS.md`.

- `engine/` Python decode/geometry/provenance (the only place science happens) + `publish.py` (fetch and publish)
- `server/` Docker Compose for an Ubuntu/Docker host: `engine` (poll + process) and `web` (nginx: viewer + `/data`)
- `viewer/` TypeScript + CesiumJS, wrapped by Tauri 2 for Android and Windows
- `scripts/` local client builds; `.github/workflows/release.yml` builds the clients in CI

## Server (pve1)
```bash
server/deploy.sh user@pve1 /opt/radar-scout      # copies tracked files, builds, starts compose
```
Serves on port 8080 (`WEB_PORT` in `server/.env`); put your existing nginx in front if you want a hostname. LAN/Tailscale
only: there is no auth. Data: `http://pve1:8080/data/latest/thr30/viewer.json`. The Linux container has **not** been
run end to end against the live archive yet (see docs/VALIDATION_STATUS.md).

## Clients
```powershell
scripts\build-android.ps1 -Server http://pve1:8080/data   # debug-signed APK
scripts\install-android.ps1                               # adb install
scripts\build-windows.ps1 -Server http://pve1:8080/data   # optional .exe
```
CI: push a tag `v0.1.0` (or run the workflow manually) to publish the APK and `.exe` files to a GitHub release.
The server URL is also editable inside the app.

## Validation
`python validate.py --mutation` (needs `data/raw/*.gz`, pinned by SHA-256 in `fixtures/fixtures.lock.json`).
