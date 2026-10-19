"""Build the pinned Linux ARM64/Python 3.12 PyArrow Lambda layer on any host."""
from pathlib import Path
import subprocess
import sys
import zipfile


def main():
    root = Path('infrastructure/terraform/build')
    wheels = root / 'wheels'
    wheels.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable,'-m','pip','download','pyarrow==26.0.0',
        '--platform','manylinux_2_28_aarch64','--python-version','312','--implementation','cp',
        '--abi','cp312','--only-binary=:all:','--no-deps','--dest',str(wheels)], check=True)
    wheel = next(wheels.glob('pyarrow-26.0.0-cp312-cp312-manylinux_2_28_aarch64.whl'))
    output = root / 'pyarrow-layer.zip'
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            if not name.endswith('/'):
                info = zipfile.ZipInfo('python/' + name, date_time=(1980,1,1,0,0,0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(info, source.read(name))
    print(f'Built {output} ({output.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
