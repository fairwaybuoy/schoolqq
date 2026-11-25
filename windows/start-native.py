"""Windows 原生启动器：只使用标准库引导，应用依赖隔离安装。"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def main():
    if sys.version_info < (3, 12):
        raise RuntimeError('需要 Python 3.12 或更新版本；推荐 Python 3.12 / 3.13。')
    os.chdir(ROOT)
    os.environ['PYTHONUTF8'] = '1'
    if not (ROOT / 'windows/ui/index.html').is_file():
        raise RuntimeError('缺少预构建网页，请重新下载完整项目压缩包。')
    venv = ROOT / '.venv-windows'
    python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        run(sys.executable, '-m', 'venv', venv)
    lock = ROOT / 'requirements.lock'
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    stamp = venv / 'requirements.sha256'
    if not stamp.exists() or stamp.read_text() != digest:
        print('首次启动正在安装锁定依赖，需要联网；请等待。', flush=True)
        run(python, '-m', 'pip', 'install', '--require-hashes', '-r', lock)
        stamp.write_text(digest)
    os.environ['BUNDLED_UI'] = 'true'
    if not (ROOT / '.env').exists():
        run(python, ROOT / 'scripts/bootstrap.py')
    # Tesseract 是可选的原生程序；缺少它不阻断文字和日历。
    ocr = shutil.which('tesseract')
    default_ocr = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Tesseract-OCR'
    if not ocr and (default_ocr / 'tesseract.exe').exists():
        os.environ['PATH'] = str(default_ocr) + os.pathsep + os.environ.get('PATH', '')
        ocr = str(default_ocr / 'tesseract.exe')
    if ocr:
        try:
            run(python, ROOT / 'scripts/ocr_setup.py')
        except subprocess.CalledProcessError:
            print('OCR 语言数据准备失败，文字功能可继续；图片将进入待处理。')
    else:
        print('未安装 Tesseract：文字、导入和日历可用；图片 OCR 暂不可用。')
    print('默认地址 http://127.0.0.1:8080/assistant/ （自定义端口以 .env 为准）')
    print('启动完成后在浏览器打开；登录口令见本机 .env 的 APP_TOKEN。')
    print('请保留此窗口。停止服务请按 Ctrl+C。', flush=True)
    run(python, '-m', 'app.main')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        sys.exit(1)
