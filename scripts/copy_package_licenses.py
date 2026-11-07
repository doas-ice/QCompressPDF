"""Retain upstream package license metadata in the Windows distribution."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

output = Path(sys.argv[1])
for package in ('PySide6-Essentials', 'shiboken6', 'PyPDF2'):
    dist = distribution(package)
    target = output / package
    target.mkdir(parents=True, exist_ok=True)
    for file in dist.files or ():
        if any(word in str(file).lower() for word in ('license', 'copying', 'notice')):
            source = Path(dist.locate_file(file))
            if source.is_file():
                dest = target / str(file)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
    (target / 'METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
shutil.copyfile(Path(sys.base_prefix) / 'LICENSE.txt', output / 'Python-LICENSE.txt')
