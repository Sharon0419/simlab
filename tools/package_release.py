"""Bundle the tested executable folder, examples and dependency licenses."""
import importlib.metadata
from pathlib import Path
import shutil
import zipfile
import sys
import argparse

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from simlab import __version__
parser=argparse.ArgumentParser()
parser.add_argument('--folder',type=Path,default=root/'dist'/'SimLab')
folder=parser.parse_args().folder.resolve()
shutil.copy2(root/'README.md', folder/'README.md')
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
for name in ['ARCHITECTURE.md', 'DIAGRAMS.md', 'V0.2.md', 'V0.3.md', 'V0.4.md', 'V0.5.md', 'V0.6.md', 'V0.7.md', 'V0.7-SPEC.md', 'V0.8.md', 'V0.8-SPEC.md', 'V0.9.md', 'V0.9.1.md', 'V0.9.2.md', 'V0.10.md', 'V0.11.md', 'METRIC_DICTIONARY.md']:
    shutil.copy2(root/'docs'/name, folder/'docs'/name)
case = root/'docs/cases/2026-09-08-aircraft-three-days/success-v0.7'
if case.exists():
    shutil.copytree(case, folder/'docs/cases/success-v0.7', dirs_exist_ok=True)
    for source in case.glob('*.simproj'):
        shutil.copy2(source, folder/'examples'/source.name)
ground_case=root/'docs/cases/2026-09-11-aircraft-ground'
if ground_case.exists():
    shutil.copytree(ground_case,folder/'docs/cases/aircraft-ground-v0.8',dirs_exist_ok=True)
    for source in ground_case.glob('*.simproj'):
        shutil.copy2(source,folder/'examples'/source.name)
for name in ('2026-09-16-m3', '2026-09-16-m3-periodic',
             '2026-09-16-lifecycle', '2026-09-16-lifecycle-periodic'):
    case = root/'docs/cases'/name
    if case.exists():
        shutil.copytree(case, folder/'docs/cases'/name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('*.sqlite', 'replay-*.json'))
        for source in case.glob('*.simproj'):
            shutil.copy2(source, folder/'examples'/f'{name}-{source.name}')
output = root/'dist'/f'SimLab-Windows-v{__version__}.zip'
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in sorted(folder.rglob('*')):
        if file.is_file():
            archive.write(file, file.relative_to(folder.parent))
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
print(f'{output}: {output.stat().st_size/1024/1024:.1f} MB; ZIP integrity passed')
