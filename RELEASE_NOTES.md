QCompressPDF 1.6.0 improves installer isolation, upgrade safety and PDF integrity.

### Updating from older Windows releases

Run `QCompressPDF.exe` normally. The new app installs per user in `%LOCALAPPDATA%\Programs\QCompressPDF`, separate from the old `Compress PDF` installation. Python, Qt and Ghostscript are bundled; no dependency download or administrator access is needed for the new installation. Existing Python installations are not changed.

After successful validation, interactive setup offers to open the old uninstaller. Keeping the old version is the default. **The legacy uninstaller may remove everything in its old directory: move any personal files out before agreeing.** The new runtime, shortcut and context menu use separate locations and remain installed when the legacy version is removed. Removing an administrator-installed legacy version may require administrator approval. Silent installation never removes the legacy version automatically.

Setup refuses legacy directories and requires the new app to be closed before a reinstall/update. A failed bundled-runtime validation does not activate the new shortcuts or context command.

### PDF workflow

- Startup update checks run in the background.
- DPI selection shows a sample-based size estimate; preview shows the actual output size.
- Output filenames are cleaned and bounded; saves use atomic per-file replacement.
- Split limits use actual serialized PDF sizes. Numbered splitting balances both bytes and page counts while preserving page order.
- Compression validates page counts and retains the original bytes if recompression would enlarge the file.
- A nonmodal warning reports source size/page-count changes during exporting, copying or syncing. No new user inputs are required. This detects observed changes; it cannot prove an exporter or sync client will never resume later.
- Completion displays total pages.

### Linux

The KDE installer stages and tests a fresh virtual environment before switching releases, preserves the previous release on failure, and limits dependency download time. It still requires compatible system Python and Ghostscript; it is not an independently bundled Linux runtime.

### Verification and distribution

Release gates include Linux regression tests and Windows Server 2022/2025 installer tests using the published v1.5.5 installer with pre-provisioned dependencies, per-user/admin legacy migration, old-version removal, conflicting runtime environment variables, running-app protection, failed-payload validation, missing-bundled-runtime rejection and reinstall/uninstall. Hosted Windows Server checks are not a claim of testing every Windows 10/11 desktop configuration.

The installer is unsigned; Windows SmartScreen may identify it as an unrecognized application. SHA-256 checksums accompany the assets. Ghostscript 10.08.0 is bundled unmodified; its corresponding source archive is included as a release asset. Other third-party notices and source links are included in the installation.
