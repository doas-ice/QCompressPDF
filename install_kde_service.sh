#!/bin/bash
set -e

# Usage:
#   bash install_kde_service.sh                # uses default repo URL
#   bash install_kde_service.sh uninstall      # uninstalls
#   bash install_kde_service.sh <repo_url>     # uses custom repo URL

APP_NAME="qcompresspdf"
SCRIPT_NAME="compress_qt.py"
REQUIREMENTS="requirements.txt"
INSTALL_BASE="$HOME/.local/share/$APP_NAME"
INSTALL_SCRIPT="$INSTALL_BASE/$SCRIPT_NAME"
INSTALL_VENV="$INSTALL_BASE/venv"
SERVICE_MENU_DIR="$HOME/.local/share/kio/servicemenus"
SERVICE_MENU_FILE="$SERVICE_MENU_DIR/qcompresspdf.desktop"
PYTHON_PATH="$(command -v python3)"
REPO_URL_DEFAULT="https://github.com/doas-ice/QCompressPDF.git"

# Uninstall option
if [ "$1" = "uninstall" ]; then
    echo "Uninstalling $APP_NAME..."
    if [ -d "$INSTALL_BASE" ]; then
        rm -rf "$INSTALL_BASE"
        echo "Removed $INSTALL_BASE."
    else
        echo "$INSTALL_BASE not found."
    fi
    if [ -f "$SERVICE_MENU_FILE" ]; then
        rm -f "$SERVICE_MENU_FILE"
        echo "Removed KDE service menu: $SERVICE_MENU_FILE."
    else
        echo "KDE service menu $SERVICE_MENU_FILE not found."
    fi
    echo "Uninstall complete."
    exit 0
fi

# Set repo URL from CLI argument if provided, else use default
if [ -n "$1" ]; then
    REPO_URL="$1"
else
    REPO_URL="$REPO_URL_DEFAULT"
fi

# 1. Check for python3
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: python3 is not installed. Please install it and rerun this script."
    exit 1
fi

# 2. Prepare install directory
mkdir -p "$INSTALL_BASE"
mkdir -p "$SERVICE_MENU_DIR"

# 3. Get latest script and requirements.txt
if [ -d .git ] || [ -f "$SCRIPT_NAME" ]; then
    # Use local copy
    cp "$SCRIPT_NAME" "$INSTALL_BASE/"
    if [ -f "$REQUIREMENTS" ]; then
        cp "$REQUIREMENTS" "$INSTALL_BASE/"
    fi
else
    # Clone repo to temp
    TMPDIR=$(mktemp -d)
    git clone "$REPO_URL" "$TMPDIR"
    cp "$TMPDIR/$SCRIPT_NAME" "$INSTALL_BASE/"
    if [ -f "$TMPDIR/$REQUIREMENTS" ]; then
        cp "$TMPDIR/$REQUIREMENTS" "$INSTALL_BASE/"
    fi
    rm -rf "$TMPDIR"
fi

# 4. Ensure script has python3 shebang
if ! head -1 "$INSTALL_SCRIPT" | grep -q "^#!"; then
    sed -i "1i #!$PYTHON_PATH" "$INSTALL_SCRIPT"
fi
chmod +x "$INSTALL_SCRIPT"

# 5. Create venv and install requirements
if [ ! -d "$INSTALL_VENV" ]; then
    "$PYTHON_PATH" -m venv "$INSTALL_VENV"
fi
source "$INSTALL_VENV/bin/activate"
pip install --upgrade pip
if [ -f "$INSTALL_BASE/$REQUIREMENTS" ]; then
    pip install -r "$INSTALL_BASE/$REQUIREMENTS"
else
    pip install PySide6 PyPDF2
fi
deactivate

# 6. Create KDE service menu
cat > "$SERVICE_MENU_FILE" <<EOF
[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=application/pdf;
Actions=compresspdf;

[Desktop Action compresspdf]
Name=Compress PDF (QCompressPDF)
Icon=application-pdf
Exec=$INSTALL_VENV/bin/python "$INSTALL_SCRIPT" "%F"
EOF

chmod +x "$SERVICE_MENU_FILE"

echo "Installed $SCRIPT_NAME to $INSTALL_BASE and created KDE service menu."
echo "You may need to restart Dolphin or your session for the menu to appear." 