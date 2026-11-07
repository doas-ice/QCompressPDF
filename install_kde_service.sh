#!/bin/bash
set -euo pipefail

APP_NAME=qcompresspdf
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_BASE="$DATA_HOME/$APP_NAME"
SERVICE_MENU_DIR="$DATA_HOME/kio/servicemenus"
SERVICE_MENU_FILE="$SERVICE_MENU_DIR/qcompresspdf.desktop"
REPO_URL_DEFAULT=https://github.com/doas-ice/QCompressPDF.git

# flock is supplied by util-linux on Arch. Lock outside the install directory so
# removing an installation cannot allow a second installer to enter mid-operation.
mkdir -p "$DATA_HOME"
exec 9>"$DATA_HOME/.qcompresspdf-install.lock"
flock -n 9 || { echo 'Another QCompressPDF installer is running.' >&2; exit 1; }
if [[ ${1:-} == uninstall ]]; then
    rm -f -- "$SERVICE_MENU_FILE"
    rm -rf -- "$INSTALL_BASE"
    echo 'QCompressPDF uninstalled.'
    exit 0
fi

for tool in python3 gs timeout; do
    command -v "$tool" >/dev/null || {
        echo "Missing $tool. On Arch: sudo pacman -S python ghostscript coreutils" >&2
        exit 1
    }
done
python3 -c 'import sys, venv; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
timeout 10 gs --version >/dev/null
mkdir -p "$INSTALL_BASE/releases" "$SERVICE_MENU_DIR"
release=$(mktemp -d "$INSTALL_BASE/releases/release.XXXXXXXX")
source_tmp=''
menu_tmp=''
menu_backup=''
previous=''
link_tmp="$INSTALL_BASE/.current.$$"
committed=false
cleanup() {
    [[ -z "$source_tmp" ]] || rm -rf -- "$source_tmp"
    [[ -z "$menu_tmp" ]] || rm -f -- "$menu_tmp"
    rm -f -- "$link_tmp"
    if [[ "$committed" == false ]]; then
        # Restore the pointer even if interrupted between the two renames.
        if [[ $(readlink "$INSTALL_BASE/current" || true) == "releases/$(basename "$release")" ]]; then
            if [[ -n "$previous" ]]; then
                ln -s "$previous" "$link_tmp"
                mv -Tf -- "$link_tmp" "$INSTALL_BASE/current"
            else
                rm -f -- "$INSTALL_BASE/current"
            fi
            if [[ -n "$menu_backup" ]]; then
                mv -f -- "$menu_backup" "$SERVICE_MENU_FILE"
            else
                rm -f -- "$SERVICE_MENU_FILE"
            fi
        fi
        rm -rf -- "$release"
    fi
    [[ -z "$menu_backup" ]] || rm -f -- "$menu_backup"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Resolve beside this script, never from an arbitrary caller working directory.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-/dev/stdin}")" && pwd)
if [[ $# == 0 && -f "$script_dir/compress_qt.py" && -f "$script_dir/requirements.txt" ]]; then
    source_dir=$script_dir
else
    command -v git >/dev/null || { echo 'Git is required for remote installation.' >&2; exit 1; }
    source_tmp=$(mktemp -d)
    GIT_TERMINAL_PROMPT=0 timeout 120 git -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=30 clone --depth 1 -- "${1:-$REPO_URL_DEFAULT}" "$source_tmp"
    source_dir=$source_tmp
fi
cp -- "$source_dir/compress_qt.py" "$source_dir/pdf_core.py" "$source_dir/runtime_environment.py" "$source_dir/requirements.txt" "$release/"
python3 -m venv "$release/venv"
timeout 240 "$release/venv/bin/python" -m pip --isolated install --only-binary=:all: --disable-pip-version-check --timeout 15 --retries 1 -r "$release/requirements.txt"
QT_QPA_PLATFORM=offscreen timeout 20 "$release/venv/bin/python" "$release/compress_qt.py" --self-test

# All generation and validation happens before the current release is switched.
# Desktop Exec needs both shell-independent quoting and literal-percent escaping.
exec_path=${INSTALL_BASE//\\/\\\\}
exec_path=${exec_path//\"/\\\"}
exec_path=${exec_path//\`/\\\`}
exec_path=${exec_path//\$/\\\$}
exec_path=${exec_path//%/%%}
menu_tmp=$(mktemp "$SERVICE_MENU_DIR/.qcompresspdf.XXXXXXXX")
cat > "$menu_tmp" <<MENU
[Desktop Entry]
Type=Service
MimeType=application/pdf;
Actions=compresspdf;

[Desktop Action compresspdf]
Name=Compress PDF (QCompressPDF)
Icon=application-pdf
Exec="$exec_path/current/venv/bin/python" "$exec_path/current/compress_qt.py" %f
MENU
chmod +x "$menu_tmp"
# Menu replacement can fail without affecting the previous release. The new
# launcher remains compatible with all releases using the current link.
# On first migration, create the link before replacing the legacy menu.
ln -s "releases/$(basename "$release")" "$link_tmp"
previous=$(readlink "$INSTALL_BASE/current" || true)
if [[ -f "$SERVICE_MENU_FILE" ]]; then
    menu_backup=$(mktemp "$SERVICE_MENU_DIR/.qcompresspdf-backup.XXXXXXXX")
    cp -- "$SERVICE_MENU_FILE" "$menu_backup"
fi
mv -Tf -- "$link_tmp" "$INSTALL_BASE/current"
if ! mv -f -- "$menu_tmp" "$SERVICE_MENU_FILE"; then
    if [[ -n "$previous" ]]; then
        ln -s "$previous" "$link_tmp"
        mv -Tf -- "$link_tmp" "$INSTALL_BASE/current"
    else
        rm -f -- "$INSTALL_BASE/current"
    fi
    exit 1
fi
committed=true
echo 'QCompressPDF installed. Previous releases are retained for rollback.'
echo 'If needed, restart Dolphin to refresh its service menu.'
