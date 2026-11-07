# Reliability and PDF workflow plan

## Invariants

- Install/update failure must leave the previous working installation usable.
- Windows must not discover, install, alter, or depend on system Python.
- Network checks must not block the GUI or prevent compression.
- Never silently overwrite input/output files or publish incomplete compression.
- Preserve every source page, page order, and vector text; DPI cannot shrink all vector content.
- Split limits apply to serialized PDFs, not sums of estimated page weights.
- Output names must be portable, bounded, and validated before writing.

## Implementation sequence

1. **Installers:** replace Windows runtime bootstrap with a CI-built, bundled application and Ghostscript; retain per-user context menus and versioned payloads. Stage a fresh Linux virtual environment, validate dependencies/Ghostscript, then switch an atomic `current` symlink. Bound network operations, lock simultaneous installs, and preserve existing installs on failure.
2. **Startup updates:** perform the release check in a background worker, compare numeric versions, and offer the platform-appropriate release page without blocking installation inside the running app.
3. **Output names:** strip invalid characters in real time, handle reserved names and Unicode length, reserve space for split suffixes, validate directories/path lengths, and publish through temporary files in the destination directory.
4. **PDF integrity and splitting:** capture a stable input snapshot; detect source changes through completion; require matching output page count. Measure serialized contiguous page ranges, honor actual size limits, explicitly reject an oversized indivisible page, and balance numbered parts by both bytes and page counts. Preserve page content rather than rasterizing text.
5. **Estimates and completion:** show a debounced background sample-based estimate beside DPI options, clearly mark its uncertainty, and include total page count in preview/completion.
6. **Verification/documentation:** focused regression tests for filename rules, source changes, shared PDF resources, uneven page sizes, update versions and GUI responsiveness; Linux install/update/failure tests with isolated fixtures; compile and smoke-test bundled Windows payload in CI. Update installation docs and record verification limits here.

## Evidence and open questions

- Windows bootstrap invokes the registered CPython installer, deletes a venv before replacement is validated, downloads without deadlines, and requires elevation for Ghostscript despite defaulting to per-user installation.
- Linux overwrites live source before pip succeeds, reuses stale virtual environments, uses caller working directory for source discovery, and omits Ghostscript validation.
- Startup performs a synchronous request with a 10-second timeout; update comparison is lexical.
- Split output ignores the chosen directory; single-page size sums double-count shared PDF objects; numbered splitting uses equal page counts.
- Source page counting and copying happen at different times without checking for active writes; successful Ghostscript exit is accepted without checking page preservation.
- User confirmed Arch Linux/KDE and Windows 10/11; numbered splits should balance both file sizes and page counts. A real failing PowerPoint PDF is still needed to confirm document-specific compression behavior.
- File stability checks cannot prove another exporter will never resume after a pause; bounded checks plus change detection prevent observed truncation without imposing a long wait on every file.

## Completion record

Implemented all six steps in the sequence above.

- Windows: removed runtime bootstrap entirely; CI builds an onedir frozen app with bundled Ghostscript. Inno installs versioned payloads and points per-user shortcuts/context menus to the installed version. No system Python discovery, Python registration, pip downloads, or elevation at install time. Legacy environments remain untouched. Added build, payload, clean-install and reinstall gates; these have **not been executed on this Linux host**.
- Linux: fresh release/venv at its final path (so venv shebangs remain valid), binary-only pinned dependencies, bounded downloads, smoke test before activation, installation lock, atomic current-link replacement, rollback on commit failure/interruption. Honors XDG_DATA_HOME, resolves local source beside the installer, and quotes the KDE launcher. Previous releases remain available for rollback; disk usage grows until uninstall/manual retirement of old releases.
- Startup: daemon network check with GUI-thread result polling and numeric version comparison. Update action opens the releases page; it no longer runs a blocking installer while the app is open.
- Output: portable Unicode-preserving filename sanitization, reserved-name/length handling, fixed PDF extension, chosen split directory, original-file protection, overwrite confirmation and atomic per-file replacement. All split destinations are chosen and all parts validated before publishing. Multi-file publication is not globally atomic; errors report any parts already saved.
- PDFs: recent-file quiet interval, EOF check, Windows writer-sharing check, stable copy and source-signature checks through save. Ghostscript output must preserve page count; a larger rewritten PDF is replaced with the validated original. Simplified pdfwrite options preserve vector text. Splitting measures serialized ranges with shared resources and balances numbered parts using both normalized byte and page-count differences.
- UX: debounced off-thread three-page sample estimate; actual preview size remains authoritative; preview and completion report total pages.

### Local proof

- 24 unittest cases cover actual Ghostscript vector-over-raster compression/text preservation, missing-page rejection, changing/incomplete inputs, shared-resource splitting, uneven byte/page balancing, cancellation, filenames, asynchronous update responsiveness, estimates/timeouts, and Linux install/update/failure/interruption/uninstall transactions.
- Linux installer transaction tests execute the real shell script with dependency installation and smoke-test executables replaced by deterministic fixtures. They do not claim an end-to-end network install or visual Dolphin validation.
- Real offscreen Qt/Ghostscript `--self-test`, Python compile checks, Bash syntax validation, and `git diff --check` pass.
- Local environment: Python 3.14, PySide6 6.12, PyPDF2 3.0.1, Ghostscript 10.08. Windows bundle pins Ghostscript 10.05.1 from the original installer source.

### Remaining external confirmation

- Run the Windows CI gates, then validate upgrading an actual legacy installation on Windows 10/11 (including multiple preinstalled Python versions). No Windows executable was built locally.
- Confirm the Dolphin context menu visually on the user's Arch/KDE session.
- Test a representative failing PowerPoint export. Synthetic vector-text-over-raster PDFs pass; no claim is made that every document-specific exporter issue is reproduced or resolved.
- Stability checks detect observed writing and later source changes, but cannot guarantee that an exporter will never resume after a long pause. Size estimates and byte/page balance are deliberately approximate.


### Follow-up: unlocked, incremental exports and slow/cloud IO

User clarified that a PDF can be readable while more pages are still arriving, whether from Note 3, a slow copy, or OneDrive. User explicitly requested **unchanged workflow and a warning on file-size/page-count changes**, not expected-page inputs or another confirmation step.

Added background observation from file selection through settings/compression/preview. Size changes are reported without requiring a valid PDF; page-count changes are compared across consistent readable revisions. Temporary missing/unreadable revisions retain the previous baseline. All IO is performed by a daemon worker, with GUI-thread polling to show one nonmodal warning per session and update it while visible. Unchanged metadata avoids repeated PDF parsing. Closing the workflow stops observation without joining potentially blocked storage IO. Existing snapshot/save integrity checks remain in place.

Added regression coverage for an unlocked writer paused longer than the snapshot quiet interval, page-count changes without size changes, temporary sync-file disappearance, no repeated reads of unchanged PDFs, nonmodal warning deduplication, and slow-IO startup/shutdown responsiveness. This detects observed changes; it cannot predict future writes after observation has ended or identify the exporter's intended final page count.

Follow-up validation: all 30 regression tests pass (including six new monitor tests); Python compilation and `git diff --check` pass. No Windows/OneDrive live environment was available for this follow-up.
