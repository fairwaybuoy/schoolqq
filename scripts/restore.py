"""离线恢复备份：停止服务后运行。先验证，再归档原数据；拒绝路径穿越。"""
import argparse,shutil,sqlite3,tempfile,zipfile
from datetime import datetime
from pathlib import Path

def restore(archive,data_dir):
    dest=Path(data_dir).resolve()
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        folder=Path(tmp)
        with zipfile.ZipFile(archive) as z:
            if sum(x.file_size for x in z.infolist())>512*1024*1024:raise ValueError('备份超过 512MB')
            names=z.namelist()
            if len(names)!=len(set(names)):raise ValueError('重复归档路径')
            if 'schedule.sqlite3'not in names:raise ValueError('缺少数据库')
            for item in z.infolist():
                p=Path(item.filename)
                if p.is_absolute() or '..' in p.parts or (item.filename!='schedule.sqlite3' and not (len(p.parts)==2 and p.parts[0]=='images' and p.suffix=='.png')):raise ValueError('非法归档路径')
                if (item.external_attr>>16)&0o170000==0o120000:raise ValueError('拒绝符号链接')
            z.extractall(folder)
        c=sqlite3.connect(folder/'schedule.sqlite3')
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库损坏')
        if c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]!=1:raise ValueError('不支持的 schema')
        c.close()
        if dest.exists():
            backup=dest.with_name(dest.name+'.before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            shutil.copytree(dest,backup)
            shutil.rmtree(dest)
        shutil.copytree(folder,dest)
    print('已恢复；恢复前数据已另行归档。请重新启动服务并核对。')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('--data-dir',required=True);a=p.parse_args();restore(a.archive,a.data_dir)
