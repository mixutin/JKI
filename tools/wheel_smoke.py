"""Install the built wheel into an isolated target and test its real entry point."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main() -> None:
    wheels = sorted(Path(sys.argv[1]).resolve().glob('jki_voice-*.whl'))
    if len(wheels) != 1:
        raise RuntimeError('Expected one JKI wheel')
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'installed'
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                        '--target', str(target), str(wheels[0])], check=True)
        env = dict(os.environ, PYTHONPATH=str(target), PYTHONNOUSERSITE='1')
        subprocess.run([sys.executable, '-m', 'jki', '--version'], cwd=directory, env=env, check=True)
        subprocess.run([sys.executable, '-m', 'jki', '--help'], cwd=directory, env=env, check=True)
        subprocess.run([sys.executable, '-c', 'from jki.engine import Engine; from jki.config import Settings; '
                        'assert Engine(Settings()).snapshot()["permission_profile"] == "restricted"'],
                       cwd=directory, env=env, check=True)


if __name__ == '__main__':
    main()
