"""Prompt locally for a fresh EIA key; never put the value in arguments or Terraform."""
import getpass
import boto3


def main():
    key = getpass.getpass('Fresh EIA API key (hidden): ').strip()
    if not key:
        raise ValueError('No key supplied')
    client = boto3.Session(profile_name='default', region_name='us-east-2').client('secretsmanager')
    client.put_secret_value(SecretId='gridcast/eia-api-key', SecretString=key)
    print('EIA key stored. The value was not saved in project files.')


if __name__ == '__main__':
    main()
