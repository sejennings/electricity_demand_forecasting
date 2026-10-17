import unittest
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from gridcast.analytics import SCHEMAS, upsert
from test_cloud import FakeS3


class AnalyticsTests(unittest.TestCase):
    def test_incremental_merge_preserves_history_and_replaces_revisions(self):
        s3 = FakeS3()
        schema = SCHEMAS['hourly_demand']
        upsert(s3,'bucket','key',[dict(timestamp_utc='2025-01-01T00:00:00Z',demand_mw=10),
                                 dict(timestamp_utc='2025-01-01T01:00:00Z',demand_mw=20)],schema,'timestamp_utc')
        upsert(s3,'bucket','key',[dict(timestamp_utc='2025-01-01T01:00:00Z',demand_mw=30)],schema,'timestamp_utc')
        table = pq.read_table(pa.BufferReader(s3.objects['key']))
        self.assertEqual(table['demand_mw'].to_pylist(),[10,30])
        self.assertEqual(table.schema,schema)

    def test_duplicate_or_missing_keys_rejected(self):
        row = dict(timestamp_utc='2025-01-01T00:00:00Z',demand_mw=10)
        with self.assertRaises(ValueError):
            upsert(FakeS3(),'bucket','key',[row,row],SCHEMAS['hourly_demand'],'timestamp_utc')
        with self.assertRaises(ValueError):
            upsert(FakeS3(),'bucket','key',[dict(timestamp_utc=row['timestamp_utc'])],SCHEMAS['hourly_demand'],'timestamp_utc')

    def test_concurrent_write_conflict_reloads_then_merges(self):
        class ConflictS3(FakeS3):
            conflicted = False
            def put_object(self, **kwargs):
                if not self.conflicted:
                    self.conflicted = True
                    from gridcast.analytics import normalize,parquet_bytes
                    other = normalize([dict(timestamp_utc='2025-01-01T01:00:00Z',demand_mw=20)],SCHEMAS['hourly_demand'])
                    super().put_object(Key=kwargs['Key'],Body=parquet_bytes(other,SCHEMAS['hourly_demand']))
                    raise ClientError({'Error':{'Code':'PreconditionFailed'}},'PutObject')
                return super().put_object(**kwargs)
        s3 = ConflictS3()
        result = upsert(s3,'bucket','key',[dict(timestamp_utc='2025-01-01T00:00:00Z',demand_mw=10)],
                        SCHEMAS['hourly_demand'],'timestamp_utc')
        self.assertEqual(result['rows'],2)
