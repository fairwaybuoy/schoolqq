import hashlib
import importlib.util
from pathlib import Path


def test_native_setup_preserves_config_and_reuses_dependencies(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('native', Path(__file__).parents[1] / 'windows/start-native.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PATH', '')
    monkeypatch.delenv('BUNDLED_UI', raising=False)
    monkeypatch.setenv('ProgramFiles', str(tmp_path / 'missing'))
    (tmp_path / 'requirements.lock').write_text('locked')
    (tmp_path / '.env').write_text('existing user configuration')
    (tmp_path / 'windows/ui').mkdir(parents=True)
    (tmp_path / 'windows/ui/index.html').write_text('compiled UI')
    calls = []
    def fake_run(*args):
        calls.append(tuple(str(x) for x in args))
        if 'venv' in args:
            python = tmp_path / '.venv-windows' / ('Scripts/python.exe' if native.os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True)
            python.touch()
    monkeypatch.setattr(native, 'run', fake_run)
    native.main()
    assert any('--require-hashes' in c for c in calls)
    assert native.os.environ['BUNDLED_UI'] == 'true'
    assert not (tmp_path / 'web/dist').exists()
    assert not any(any(arg.endswith('bootstrap.py') for arg in command) for command in calls)
    assert (tmp_path / '.env').read_text() == 'existing user configuration'
    calls.clear()
    native.main()
    assert not any('install' in c for c in calls)
    assert calls[-1][-2:] == ('-m', 'app.main')
    (tmp_path / 'requirements.lock').write_text('updated')
    calls.clear()
    native.main()
    assert any('--require-hashes' in c for c in calls)
