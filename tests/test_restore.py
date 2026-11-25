import io,zipfile,sqlite3
import pytest
from app.store import Store
from scripts.restore import restore

def test_backup_restore_and_path_rejection(tmp_path):
    src=tmp_path/'src';db=Store(src);db.runtime('test','retained');out=tmp_path/'snapshot.sqlite3';db.backup(out)
    archive=tmp_path/'backup.zip'
    with zipfile.ZipFile(archive,'w') as z:z.write(out,'schedule.sqlite3')
    dest=tmp_path/'dest';restore(archive,dest);c=sqlite3.connect(dest/'schedule.sqlite3');assert c.execute("SELECT value FROM runtime WHERE key='test'").fetchone()[0]=='retained';c.close()
    (dest/'keep.txt').write_text('old file');restore(archive,dest);assert list(tmp_path.glob('dest.before-restore-*'))[0].joinpath('keep.txt').read_text()=='old file'
    evil=tmp_path/'evil.zip'
    with zipfile.ZipFile(evil,'w') as z:z.write(out,'schedule.sqlite3');z.writestr('../escape','bad')
    with pytest.raises(ValueError):restore(evil,dest)
    assert not (tmp_path/'escape').exists()
