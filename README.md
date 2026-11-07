# 🚀 QCompressPDF

> **A fast, friendly, and cross-platform PDF compression tool with context menu integration!**

---

![PDF Compression Banner](https://img.shields.io/badge/PDF-Compression-blueviolet?style=for-the-badge&logo=adobeacrobatreader)

## ✨ Features
- 🗜️ **Compress PDF files** with selectable quality presets or manual settings
- ✂️ **Split PDFs** by measured file size or a chosen number of parts, balancing size and page counts
- 👀 **Preview compression results** before saving
- 🖱️ **Context menu integration** for both Windows and Linux (only KDE is currently supported)

## 🖥️ Supported Systems
- 🪟 **Windows 10/11** (with context menu integration)
- 🐧 **Linux (KDE desktop only)**

## 📋 Requirements

### 🐧 Linux Requirements
- **Python 3.10+** with venv/pip, plus **Ghostscript**
- **KDE desktop environment**
- **Git** (for cloning the repository)

---

## 📦 Installation

### 🪟 Windows
1. **Download and run the provided `.exe` installer** from the [Releases](https://github.com/doas-ice/QCompressPDF/releases) page.
2. The installer bundles its own Python runtime, Qt and Ghostscript. It requires **no system Python, dependency downloads, or administrator privileges**. Existing Python versions are left alone.
3. To update, close QCompressPDF and run the new installer. The bundled app installs in `%LOCALAPPDATA%\Programs\QCompressPDF`, separate from old `Compress PDF` installations. After validation, setup optionally opens the old uninstaller; keeping it is the default. Move personal files out of the old directory before uninstalling it, because the legacy uninstaller can delete that whole directory. Existing Python installations are not changed.

Windows installers are x64 builds for Windows 10/11. The old context-menu command is hidden per user while the new version is installed. Removing an administrator-installed legacy version may require administrator approval. Bundled third-party licenses and source links are listed in `THIRD-PARTY-NOTICES.txt`.

### 🐧 Linux (KDE only)
**Arch Linux / KDE prerequisites:**

```sh
sudo pacman -S python ghostscript git
```

The installer creates an isolated virtual environment; it never installs packages into system Python. Dependencies are pinned and installed from wheels. Unsupported Python versions fail before changing the active installation.

1. Clone or download this repository.
2. Run the installer script manually:
   ```sh
   bash install_kde_service.sh
   ```
   - This creates a versioned release and adds a KDE service menu entry. Run the same command from an updated checkout to update.
   - Run `bash install_kde_service.sh https://github.com/doas-ice/QCompressPDF.git` to explicitly fetch the latest repository version.
   - Dependency downloads have a four-minute overall deadline; repository fetching has a two-minute deadline. A failed update leaves the previous release active.
   - Releases live in `${XDG_DATA_HOME:-~/.local/share}/qcompresspdf/releases`; `current` selects the active release. Older releases are retained for rollback and are removed on uninstall.
   - Uninstall with `bash install_kde_service.sh uninstall`.

**OR**

- You can use this one-liner (be sure to review the script before running!):

  ⚠️ **WARNING:** ⚠️
  
  **Piping scripts from the internet directly to `bash` can be dangerous!**
  Always review the script at [install_kde_service.sh](https://github.com/doas-ice/QCompressPDF/blob/main/install_kde_service.sh) before running. Only use this method if you trust the source.

  ```sh
  curl -fsSL https://raw.githubusercontent.com/doas-ice/QCompressPDF/main/install_kde_service.sh | bash
  ```

---

## 🧑‍💻 Usage

### 🪟 Windows
- Right-click any PDF file.
- Select **"Compress PDF"** from the context menu.
- *(Windows 11 users:)* Click **"Show more options"** first, then choose **"Compress PDF"**.

### 🐧 Linux (KDE)
- Right-click any PDF file.
- Select **"Compress PDF (QCompressPDF)"** from the context menu.

---

## 📜 License
MIT

## Compression behavior

- Startup checks for releases in the background. “Open Releases” works on both platforms; compression can continue while an update is available.
- DPI options show a debounced estimate from up to three sampled pages. Mixed documents and shared resources can make the estimate inaccurate; the preview shows the actual result.
- Vector text stays selectable. Lower DPI mainly reduces raster images; vector-heavy or already optimized files may not shrink. If rewriting would enlarge the PDF, the original bytes are retained.
- Invalid filename characters are stripped immediately, reserved Windows names are adjusted, and long names are shortened while retaining Unicode. The PDF extension is fixed. Split outputs use the selected directory.
- Size-based splitting measures actual serialized PDFs. A single page larger than the limit cannot be split without changing its content: choose lower DPI or raise the limit. Numbered splitting balances both bytes and page counts, but cannot make them equal for every document while retaining page order.
- A background monitor warns once when the selected source PDF changes size or page count, including unlocked exports, slow copies and cloud sync. It stays active through settings, compression and preview; it does not add inputs or confirmation steps. PDF page counts are reread only when file metadata changes (or a previous read was incomplete), and all monitoring IO runs off the UI thread. A quiet file is not proof that an export or sync has finished.
- Input stability checks run in the worker: approximately 0.1 seconds for older completed files and 0.75 seconds for recent exports, retrying for up to five seconds. Changes during compression or before saving are rejected, and output page count must match the snapshot. No finite check can guarantee that another program will not resume writing later; finish exporting before compressing whenever possible.
- Saves use a temporary destination file followed by an atomic replacement. Existing files require overwrite confirmation. Original input files are protected from overwrite.

## Verification

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen .venv/bin/python compress_qt.py --self-test
```

The Windows workflow builds the bundled app and installer, smoke-tests installation/reinstallation, and tests the installed payload with system Python absent from PATH. See [PLAN.md](PLAN.md) for implementation status and remaining platform/document checks.
