"""Verify a trusted content-addressed model without deserializing it."""
import argparse
import hashlib
import re
import boto3


def verify(s3,bucket,sha256):
    if not re.fullmatch('[0-9a-f]{64}',sha256):
        raise ValueError('Invalid model SHA-256')
    digest=hashlib.sha256()
    with s3.get_object(Bucket=bucket,Key=f'models/weather/{sha256}.joblib')['Body'] as stream:
        for block in stream.iter_chunks(chunk_size=1024*1024):
            digest.update(block)
    if digest.hexdigest()!=sha256:
        raise ValueError('Published model hash mismatch')
    print('Published model SHA-256 verified')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha256',required=True)
    args=parser.parse_args()
    verify(boto3.Session(region_name='us-east-2').client('s3'),'gridcast-lake-456112636403-us-east-2',args.sha256)


if __name__=='__main__':
    main()
