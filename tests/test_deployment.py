import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.build_arrow_layer import build
from scripts.check_deployment_plan import check
from scripts.check_image_scan import platform_digest
from scripts.verify_release import verify_manifest


class DeploymentTests(unittest.TestCase):
    def test_rejects_unexpected_destruction(self):
        for resource_type,actions in [('aws_s3_bucket',['delete']),('aws_iam_role',['delete','create']),('aws_ecs_task_definition',['delete'])]:
            with self.assertRaisesRegex(ValueError,'Unexpected destruction'):
                check({'resource_changes':[{'address':'example','type':resource_type,'change':{'actions':actions}}]})
        check({'resource_changes':[{'address':'task','type':'aws_ecs_task_definition','change':{'actions':['create','delete']}}]})

    def test_selects_only_platform_image(self):
        manifest={'manifests':[{'digest':'linux','platform':{'os':'linux','architecture':'amd64'}},{'digest':'attestation','platform':{'os':'unknown','architecture':'unknown'}}]}
        self.assertEqual(platform_digest(manifest,'index'),'linux')
        self.assertEqual(platform_digest({'schemaVersion':2},'single'),'single')
        with self.assertRaises(ValueError): platform_digest({'manifests':[]},'index')

    def test_layer_bytes_ignore_source_order_and_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i,names in enumerate([['a','b'],['b','a']]):
                with zipfile.ZipFile(root/f'{i}.whl','w') as archive:
                    for name in names:
                        archive.writestr(zipfile.ZipInfo(name,(2020+i,1,1,0,0,0)),name.encode())
                build(root/f'{i}.whl',root/f'{i}.zip')
            self.assertEqual((root/'0.zip').read_bytes(),(root/'1.zip').read_bytes())

    def test_release_verifies_image_model_and_issue_timing(self):
        import csv
        from datetime import datetime,timezone,timedelta
        origin=datetime(2026,10,19,tzinfo=timezone.utc)
        rows=[dict(timestamp_utc=(origin+timedelta(hours=h)).isoformat(),issue_time_utc='2026-10-18T23:30:00Z',horizon_hours=h+1,forecast_mw=100) for h in range(24)]
        stream=io.StringIO(newline=''); writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        manifest=dict(forecast_csv=stream.getvalue(),forecast_sha256=hashlib.sha256(stream.getvalue().encode()).hexdigest(),rows=24,
            image_uri='456112636403.dkr.ecr.us-east-2.amazonaws.com/gridcast-model@sha256:test',model_sha256='model',
            issue_time_utc='2026-10-18T23:30:00Z',forecast_origin_utc=origin.isoformat())
        snapshot=dict(completed_at_utc='2026-10-18T23:29:00Z')
        self.assertEqual(len(verify_manifest(manifest,'sha256:test','model',snapshot)),24)
        with self.assertRaisesRegex(ValueError,'differs'): verify_manifest(manifest,'sha256:other','model',snapshot)
        with self.assertRaisesRegex(ValueError,'timing'): verify_manifest(manifest,'sha256:test','model',{'completed_at_utc':'2026-10-19T00:01:00Z'})
