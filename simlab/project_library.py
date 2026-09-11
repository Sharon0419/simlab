"""Read project summaries without loading simulation results into the UI."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing
from .project import new_project, load_project, MAX_PACKAGE_BYTES


class ProjectLibrary:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.index=self.directory/'project-library.json'
        self.cache={}

    def paths(self):
        paths=set((self.directory/'projects').glob('*.sqlite'))
        if self.index.exists():
            paths.update(Path(p) for p in json.loads(self.index.read_text(encoding='utf-8')))
        return sorted({p.resolve() for p in paths},key=str)

    def remember(self,path):
        paths=self.paths()
        path=Path(path).resolve()
        if path not in paths:paths.append(path)
        self.directory.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(dir=self.directory,prefix='.library-',suffix='.json')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as file:json.dump([str(p) for p in paths],file,ensure_ascii=False)
            os.replace(temp,self.index)
        finally:
            if os.path.exists(temp):os.unlink(temp)

    def entries(self):
        rows=[]
        for path in self.paths():
            try:
                stat=path.stat()
                stamp=(stat.st_mtime_ns,stat.st_size)
                if stat.st_size>MAX_PACKAGE_BYTES:raise ValueError('项目超过128 MB')
                if path in self.cache and self.cache[path][0]==stamp:
                    rows.append(self.cache[path][1]);continue
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('PRAGMA trusted_schema=OFF')
                    meta={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
                    # JSON is parsed by SQLite; full Monte Carlo payloads never enter the widget.
                    last=db.execute("SELECT json_extract(payload,'$.started'), json_extract(payload,'$.result.engine'), json_extract(payload,'$.status') FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
                    model={k:json.loads(v) for k,v in db.execute("SELECT name,rows_json FROM model_tables WHERE name IN ('SystemDeployment','OperationProfile')")}
                qty=sum(float(r.get('QTYPS',0) or 0) for r in model.get('SystemDeployment',[]))
                info=meta.get('description') or f'{qty:g}台装备 · {len(model.get("OperationProfile",[]))}个计划窗口'
                row=dict(path=str(path),name=meta['name'],description=info,updated=meta.get('updated',''),
                         last_run=last[0] if last else '',engine=last[1] if last else '',status=last[2] if last else '未运行',error='')
                self.cache[path]=(stamp,row)
            except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
                row=dict(path=str(path),name=path.stem,description='项目暂不可读取',updated='',last_run='',engine='',status='不可读',error=str(error))
            rows.append(row)
        return sorted(rows,key=lambda r:r['updated'],reverse=True)


def copy_model(path,name=None):
    source=load_project(path)
    project=new_project(name or source['name']+' · 新方案')
    project['tables']=copy.deepcopy(source['tables'])
    project['description']=source.get('description','')
    project['source_project_id']=source['id']
    project['parent_revision']=source['revision']
    return project
