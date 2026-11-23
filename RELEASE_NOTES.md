QCompressPDF 1.6.3 restores in-app Windows updates and adds a preview for shortening long output filenames.

- The update prompt opens over compression settings. On Windows, Download & Install shows progress and verifies the installer checksum before opening setup. Select View Release to open the release page on either platform.
- If the destination rejects a long filename, choose which end to emphasize and preview the shortened name before saving. The middle ellipsis preserves Unicode characters and split part suffixes.
- When Windows reports that a long path cannot be found, the app checks whether a short filename works in the same directory before offering clipping.

### Updating

Close QCompressPDF and run `QCompressPDF.exe`. Windows installation remains offline and per-user with bundled Python, Qt, Ghostscript and C++ runtime DLLs. Existing Python installations are not modified. Users migrating from legacy versions are offered optional legacy removal only after successful installation; keeping the old version is the default.

The installer is unsigned; Windows SmartScreen may show an unrecognized-app warning. SHA-256 checksums and the Windows migration test report accompany this release. The bundled Ghostscript 10.08.0 corresponding source archive is also included.
