"""Bundle the tested executable folder, examples and dependency licenses."""
import importlib.metadata
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
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
output = root/'dist'/'SimLab-Windows-v0.1.0.zip'
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in sorted(folder.rglob('*')):
        if file.is_file():
            archive.write(file, file.relative_to(folder.parent))
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
print(f'{output}: {output.stat().st_size/1024/1024:.1f} MB; ZIP integrity passed')
