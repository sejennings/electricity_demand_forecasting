"""Copy dashboard assets for GitHub Pages; never copy local AWS snapshots."""
import argparse
from pathlib import Path
import shutil

SNAPSHOT_URL = 'https://gridcast-public-456112636403-us-east-2.s3.us-east-2.amazonaws.com/snapshot.json'
ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'dashboard'
    for name in ('app.js', 'style.css', 'demo.json'):
        shutil.copyfile(source / name, output / name)
    html = (source / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<html lang="en">', f'<html lang="en" data-snapshot-url="{SNAPSHOT_URL}">')
    html = html.replace('<button id="sync">', '<button id="sync" hidden>')
    html = html.replace('Reload saved view', 'Refresh data')
    html = html.replace('Read-only snapshot · no automatic AWS polling', 'AWS data updated daily · read-only dashboard')
    (output / 'index.html').write_text(html, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)


if __name__ == '__main__':
    main()
