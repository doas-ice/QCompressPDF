# 🚀 QCompressPDF

> **A fast, friendly, and cross-platform PDF compression tool with context menu integration!**

---

![PDF Compression Banner](https://img.shields.io/badge/PDF-Compression-blueviolet?style=for-the-badge&logo=adobeacrobatreader)

## ✨ Features
- 🗜️ **Compress PDF files** with selectable quality presets or manual settings
- ✂️ **Split compressed PDFs** into two parts
- 👀 **Preview compression results** before saving
- 🖱️ **Context menu integration** for both Windows and Linux (only KDE is currently supported)

## 🖥️ Supported Systems
- 🪟 **Windows 10/11** (with context menu integration)
- 🐧 **Linux (KDE desktop only)**

## 📋 Requirements

### 🐧 Linux Requirements
- **Python 3** (with pip)
- **KDE desktop environment**
- **Git** (for cloning the repository)

---

## 📦 Installation

### 🪟 Windows
1. **Download and run the provided `.exe` installer** from the [Releases](https://github.com/doas-ice/QCompressPDF/releases) page.
2. The installer will automatically install **Python 3.13** and **Ghostscript** if they are not already present. **Keep all default options** during installation.
3. The installation may take a few minutes — please be patient!

### 🐧 Linux (KDE only)
**Prerequisites:** Make sure you have Python 3 installed on your system.

1. Clone or download this repository.
2. Run the installer script manually:
   ```sh
   bash install_kde_service.sh
   ```
   - This will set up the script and add a KDE service menu entry for PDF files.

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