QCompressPDF 1.6.2 reduces estimation work and learns from completed compression of the same PDF.

### Lighter sampling

- PDFs of up to 8 pages are measured fully.
- Larger PDFs use evenly spread samples starting at 8 pages, growing with the square root of the page count to a maximum of 32: 8/50, 10/100 and 20/400 pages.
- A smaller nested sample still accounts for shared fonts and images. Estimation remains in the background with the existing Ghostscript time budget.

### Same-PDF calibration

- Retrying a previously completed DPI immediately shows its measured output size without resampling.
- Other sampled estimates use the actual/estimated size ratio from the nearest completed DPI when both measurements are available.
- Corrections apply only to the unchanged PDF in the current retry session. They are not saved across app launches or applied to other PDFs.
- Full-document measurements are not adjusted. Sampled estimates remain approximate and are capped at the original size, matching the app's no-enlargement behavior.
- No new prompts or workflow steps.

### Updating

Close QCompressPDF and run `QCompressPDF.exe`. Windows installation remains offline and per-user with bundled Python, Qt, Ghostscript and C++ runtime DLLs. Existing Python installations are not modified. Users migrating from legacy versions are offered optional legacy removal only after successful installation; keeping the old version is the default.

The installer is unsigned; Windows SmartScreen may show an unrecognized-app warning. SHA-256 checksums and the Windows migration test report accompany this release. The bundled Ghostscript 10.08.0 corresponding source archive is also included.
