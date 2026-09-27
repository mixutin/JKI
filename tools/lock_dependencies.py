"""Generate a hashed runtime lock explicitly; requires uv and network access."""
from pathlib import Path
import argparse
import shutil
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', choices=['3.11', '3.12', '3.13'], default='3.12')
    args = parser.parse_args()
    uv = shutil.which('uv')
    if not uv:
        parser.error('Install uv before generating dependency locks')
    root = Path(__file__).resolve().parents[1]
    target = root / 'packaging' / f'requirements-python{args.python}.lock'
    subprocess.run([uv, 'pip', 'compile', str(root / 'pyproject.toml'), '--extra', 'audio', '--extra', 'piper',
                    '--python-version', args.python, '--generate-hashes', '--output-file', str(target)], check=True)
    print(f'Generated {target}. Install and validate it on the target platform before release.')


if __name__ == '__main__':
    main()
