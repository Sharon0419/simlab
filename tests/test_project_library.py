from simlab.project import new_project,save_project,load_project
from simlab.project_library import ProjectLibrary,copy_model


def test_library_scans_projects_and_persists_external_paths(tmp_path):
    folder=tmp_path/'app'
    p=new_project('飞机项目');p['description']='半小时保障'
    save_project(p,folder/'projects/one.sqlite')
    external=tmp_path/'external.sqlite'
    save_project(new_project('外部模型'),external)
    catalog=ProjectLibrary(folder);catalog.remember(external)
    rows=ProjectLibrary(folder).entries()
    assert {r['name'] for r in rows}=={'飞机项目','外部模型'}
    assert next(r for r in rows if r['name']=='飞机项目')['description']=='半小时保障'
    external.unlink()
    rows=catalog.entries()
    assert len(rows)==2 and any(r['error'] for r in rows)


def test_copy_preserves_source_and_uses_new_identity_without_results(tmp_path):
    p=new_project('源项目');p['runs']=[dict(id='run',status='completed')]
    p['tables']={'System':[dict(SID='PLANE')]}
    path=tmp_path/'project.sqlite';save_project(p,path)
    before=path.read_bytes()
    branch=copy_model(path)
    assert branch['id']!=p['id'] and branch['runs']==[]
    assert branch['source_project_id']==p['id'] and branch['parent_revision']==p['revision']
    branch['tables']['System'][0]['SID']='COPY'
    assert path.read_bytes()==before and load_project(path)['tables']['System'][0]['SID']=='PLANE'


def test_corrupt_project_does_not_hide_healthy_projects(tmp_path):
    folder=tmp_path/'projects';folder.mkdir()
    (folder/'broken.sqlite').write_bytes(b'not a database')
    save_project(new_project('正常项目'),folder/'valid.sqlite')
    rows=ProjectLibrary(tmp_path).entries()
    assert len(rows)==2 and sum(bool(r['error']) for r in rows)==1
