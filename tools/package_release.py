"""Bundle the tested executable folder, examples and dependency licenses."""
import importlib.metadata
from pathlib import Path
import shutil
import zipfile
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from simlab import __version__
folder = root/'dist'/'SimLab'
for name in ['PySide6-Essentials', 'shiboken6', 'simpy', 'numpy', 'pyinstaller']:
    distribution = importlib.metadata.distribution(name)
    for file in distribution.files or []:
        if any(term in str(file).lower() for term in ('license', 'copying')) and not str(file).endswith(('.py', '.pyc')):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                destination = folder/'licenses'/name/Path(str(file))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
shutil.copy2(root/'docs'/'VERIFICATION.md', folder/'VERIFICATION.md')
(folder/'docs').mkdir(exist_ok=True)
for name in ['ARCHITECTURE.md', 'DIAGRAMS.md', 'V0.2.md', 'V0.3.md', 'V0.4.md', 'V0.5.md', 'V0.6.md']:
    shutil.copy2(root/'docs'/name, folder/'docs'/name)
output = root/'dist'/f'SimLab-Windows-v{__version__}.zip'
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in sorted(folder.rglob('*')):
        if file.is_file():
            archive.write(file, file.relative_to(folder.parent))
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
print(f'{output}: {output.stat().st_size/1024/1024:.1f} MB; ZIP integrity passed')
