QCompressPDF 1.6.1 improves compressed-size estimates and long Unicode filenames.

### More representative estimates

- PDFs with up to 24 pages are measured in full.
- Larger PDFs sample pages evenly across the whole document. Coverage grows with page count, up to 64 pages: for example, 24 of 100, 40 of 400, and 64 of 1000.
- Two nested samples estimate shared font/image overhead separately from per-page growth.
- The estimate shows its page coverage, runs in the background, and uses a 30-second Ghostscript budget. Preview still shows the actual size; unusual page distributions can still make a sample estimate inaccurate.

### Preserve full filenames when possible

- Removed the unconditional filename byte cap and conservative Windows path cutoff. Names are no longer truncated while typing.
- Saving/splitting tries the full name on the destination filesystem using an exclusive creation probe, immediately removed. Existing files are not modified by these probes.
- Only a filename-length error triggers shortening. The app keeps both ends with a middle ellipsis and preserves Bangla conjuncts, combining marks, emoji, the PDF extension, and generated split suffixes.
- Permission, disk-full and I/O errors are reported rather than disguised as filename problems. Overwrite confirmation applies to the final resolved name; PDF saves remain atomic.

### Updating

Close QCompressPDF and run `QCompressPDF.exe`. Windows installation remains offline and per-user with bundled Python, Qt, Ghostscript and C++ runtime DLLs. Existing Python installations are not modified. Users migrating from legacy versions are offered optional legacy removal only after successful installation; keeping the old version is the default.

The installer is unsigned; Windows SmartScreen may show an unrecognized-app warning. SHA-256 checksums and the Windows migration test report accompany this release. The bundled Ghostscript 10.08.0 corresponding source archive is also included.
