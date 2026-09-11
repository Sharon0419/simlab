"""Local project persistence and validated, branched project exchanges."""
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from .schema import SCHEMA, TABLES
from .extensions import VERSION as EXTENSIONS_VERSION

FORMAT = 1
MAX_PACKAGE_BYTES = 128 * 1024 * 1024

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def new_project(name='未命名项目'):
    return {'id': str(uuid.uuid4()), 'revision': str(uuid.uuid4()), 'parent_revision': None,
            'name': name, 'created': now(), 'updated': now(), 'format': FORMAT,
            'schema_sha256': SCHEMA['source_sha256'], 'extensions_version': EXTENSIONS_VERSION, 'tables': {}, 'runs': []}

def model_hash(tables):
    raw = json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def check_structure(project):
    if project.get('extensions_version', 1) not in (1, 2, 3, 4, EXTENSIONS_VERSION):
        raise ValueError('SimLab 扩展格式版本不支持。')
    if project.get('format') != FORMAT:
        raise ValueError('项目格式版本不支持，请使用匹配的软件版本。')
    if project.get('schema_sha256') != SCHEMA['source_sha256']:
        raise ValueError('项目数据字典版本与本机软件不一致，无法无损导入。')
    if not isinstance(project.get('tables'), dict) or not isinstance(project.get('runs'), list):
        raise ValueError('项目数据结构无效。')
    for key in ('id', 'revision', 'name', 'created', 'updated'):
        if not isinstance(project.get(key), str):
            raise ValueError(f'项目缺少 {key}')
    for table, rows in project['tables'].items():
        if table not in TABLES or not isinstance(rows, list):
            raise ValueError(f'未知表或表结构错误：{table}')
        allowed = {f['id'] for f in TABLES[table]}
        for row in rows:
            if not isinstance(row, dict) or set(row) - allowed:
                raise ValueError(f'{table} 存在未知字段或无效记录')
            if any(v is not None and not isinstance(v, (str, int, float)) for v in row.values()):
                raise ValueError(f'{table} 字段值必须是文本或数字')

def _write_database(project, path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA user_version=1')
        db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('CREATE TABLE model_tables (name TEXT PRIMARY KEY, rows_json TEXT NOT NULL)')
        db.execute('CREATE TABLE runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        for key, val in project.items():
            if key not in ('tables', 'runs'):
                db.execute('INSERT INTO metadata VALUES (?,?)', (key, json.dumps(val, ensure_ascii=False, allow_nan=False)))
        for name, rows in project['tables'].items():
            db.execute('INSERT INTO model_tables VALUES (?,?)', (name, json.dumps(rows, ensure_ascii=False, allow_nan=False)))
        for run in project['runs']:
            db.execute('INSERT INTO runs VALUES (?,?)', (run['id'], json.dumps(run, ensure_ascii=False, allow_nan=False)))

def save_project(project, path, backup=True):
    check_structure(project)
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = copy.deepcopy(project)
    candidate['extensions_version'] = EXTENSIONS_VERSION
    candidate['updated'] = now()
    candidate['revision'] = str(uuid.uuid4())
    fd, tmp = tempfile.mkstemp(prefix='.save-', suffix='.sqlite', dir=path.parent)
    os.close(fd)
    try:
        _write_database(candidate, tmp)
        if backup and path.exists():
            # The GUI owns a QLockFile for the project while this executes.
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as src:
                backup_path = path.with_suffix(path.suffix + '.bak')
                with closing(sqlite3.connect(backup_path)) as dest:
                    src.backup(dest)
        os.replace(tmp, path)
        project.update(candidate)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def load_project(path):
    path = Path(path).resolve()
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError('项目超过本版支持的 128 MB 限制。')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA user_version').fetchone()[0] != FORMAT:
            raise ValueError('不支持的项目数据库版本。')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('项目数据库损坏。')
        project = {key: json.loads(val) for key, val in db.execute('SELECT key,value FROM metadata')}
        project['tables'] = {name: json.loads(rows) for name, rows in db.execute('SELECT name,rows_json FROM model_tables')}
        project['runs'] = [json.loads(row[0]) for row in db.execute('SELECT payload FROM runs ORDER BY rowid')]
    check_structure(project)
    return project

def export_package(project, destination, include_results=True):
    snapshot = copy.deepcopy(project)
    if snapshot.get('extensions_version', 1) in (1, 2, 3, 4):
        snapshot['extensions_version'] = EXTENSIONS_VERSION
    if not include_results:
        snapshot['runs'] = []
    check_structure(snapshot)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory) / 'project.sqlite'
        _write_database(snapshot, db)
        payload = db.read_bytes()
        if len(payload) > MAX_PACKAGE_BYTES:
            raise ValueError('项目超过 128 MB，请导出模型包或减少运行记录。')
        manifest = {'format': FORMAT, 'project_id': snapshot['id'], 'revision': snapshot['revision'],
                    'schema_sha256': snapshot['schema_sha256'], 'include_results': include_results,
                    'files': {'project.sqlite': hashlib.sha256(payload).hexdigest()}}
        temp_path = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
                archive.writestr('project.sqlite', payload)
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)

def import_package(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) != 2 or {x.filename for x in entries} != {'manifest.json', 'project.sqlite'}:
            raise ValueError('项目包必须仅含 manifest.json 和 project.sqlite；拒绝未知路径。')
        if sum(x.file_size for x in entries) > MAX_PACKAGE_BYTES or archive.getinfo('manifest.json').file_size > 16384:
            raise ValueError('项目包解压后过大。')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != FORMAT:
            raise ValueError('不支持的项目包版本。')
        payload = archive.read('project.sqlite')
        if hashlib.sha256(payload).hexdigest() != manifest.get('files', {}).get('project.sqlite'):
            raise ValueError('项目包校验失败：文件已被修改或损坏。')
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'project.sqlite'
            db.write_bytes(payload)
            project = load_project(db)
        if any(manifest.get(m) != project[p] for m, p in [('project_id', 'id'), ('revision', 'revision'), ('schema_sha256', 'schema_sha256')]):
            raise ValueError('项目包清单与内容不一致。')
    project['parent_revision'] = project['revision']
    project['source_project_id'] = project['id']
    project['id'], project['revision'] = str(uuid.uuid4()), str(uuid.uuid4())
    project['name'] += ' · 导入分支'
    project['updated'] = now()
    return project
