"""Export a read-only dashboard snapshot. No AWS credentials enter the browser."""
import argparse
import json
import tempfile
from pathlib import Path
import boto3
from gridcast.dashboard import build_run, export


def write_snapshot(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.snapshot-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, allow_nan=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('dashboard/snapshot.json'))
    parser.add_argument('--profile',default='default')
    parser.add_argument('--limit',type=int,default=30)
    parser.add_argument('--max-manifests',type=int,default=500)
    args=parser.parse_args()
    if not 1<=args.limit<=100: parser.error('limit must be 1–100')
    if args.max_manifests < 1: parser.error('max-manifests must be positive')
    payload=export(boto3.Session(profile_name=args.profile,region_name='us-east-2'),args.limit,args.max_manifests)
    write_snapshot(args.output,payload)
    print(f"Exported {len(payload['runs'])} forecast issues to {args.output}")


if __name__=='__main__': main()
