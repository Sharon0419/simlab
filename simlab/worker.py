"""File-based worker protocol; no networking and no UI dependency."""
import json
import os
from pathlib import Path
import sys
import traceback
from .engine import simulate

def main(source, destination):
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    def emit(payload):
        progress_path = Path(destination).with_suffix('.progress.json')
        temp_progress = progress_path.with_suffix('.tmp')
        temp_progress.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        try:
            os.replace(temp_progress, progress_path)
        except PermissionError:
            # A Windows reader may briefly hold the old progress file open.
            # Progress is best effort; it must never abort the simulation.
            pass
        if sys.stdout is not None:
            print(json.dumps(payload, ensure_ascii=True), flush=True)
    last = -1
    def progress(fraction):
        nonlocal last
        percent = int(fraction*100)
        if percent != last:
            last = percent
            emit({'progress': percent})
    try:
        tables = json.loads(Path(source).read_text(encoding='utf-8'))
        result = simulate(tables, progress)
        temp = Path(destination).with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        os.replace(temp, destination)
        emit({'complete': True})
        return 0
    except Exception as error:
        emit({'error': str(error)})
        Path(destination).with_suffix('.error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        return 1
