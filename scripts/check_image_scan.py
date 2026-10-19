"""Scan the Linux image, reject critical findings, report remaining severities."""
import argparse
import json
import os
from pathlib import Path
import boto3


def platform_digest(manifest,digest):
    if 'manifests' not in manifest:
        return digest
    choices=[m['digest'] for m in manifest['manifests'] if m.get('platform',{}).get('os')=='linux' and m.get('platform',{}).get('architecture')=='amd64']
    if len(choices)!=1:
        raise ValueError('Expected exactly one Linux amd64 image')
    return choices[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--digest',required=True)
    args=parser.parse_args()
    digest=platform_digest(json.loads(args.manifest.read_text()),args.digest)
    client=boto3.Session(region_name='us-east-2').client('ecr')
    client.get_waiter('image_scan_complete').wait(repositoryName='gridcast-model',imageId={'imageDigest':digest},WaiterConfig={'Delay':5,'MaxAttempts':36})
    scan=client.describe_image_scan_findings(repositoryName='gridcast-model',imageId={'imageDigest':digest})
    if scan['imageScanStatus']['status']!='COMPLETE':
        raise ValueError('Image scan did not complete')
    counts=scan['imageScanFindings'].get('findingSeverityCounts',{})
    print('ECR scan severity counts:',json.dumps(counts,sort_keys=True))
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as stream:
            stream.write('ECR scan: '+json.dumps(counts,sort_keys=True)+'\n')
    if counts.get('CRITICAL',0):
        raise ValueError('Critical image vulnerabilities block deployment')
    if counts.get('HIGH',0):
        print('::warning::High-severity image findings remain; see deployment documentation and scan summary.')


if __name__=='__main__':
    main()
