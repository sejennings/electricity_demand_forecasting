from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from gridcast.eia_export import read_rows


class ExportTests(unittest.TestCase):
    def test_uses_published_utc_and_demand_not_imputed_columns(self):
        ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.xlsx'
            with ZipFile(path,'w') as bundle:
                bundle.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Published Hourly Data" r:id="rId1"/></sheets></workbook>')
                bundle.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                bundle.writestr('xl/sharedStrings.xml',f'<sst xmlns="{ns}">'+''.join(f'<si><t>{s}</t></si>' for s in ['BA','UTC time','Demand','Imputed demand','DUK'])+'</sst>')
                bundle.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="I1" t="s"><v>2</v></c><c r="L1" t="s"><v>3</v></c></row><row><c r="A2" t="s"><v>4</v></c><c r="B2"><v>45658</v></c><c r="I2"><v>100</v></c><c r="L2"><v>999</v></c></row></sheetData></worksheet>')
            dt=datetime(2025,1,1,tzinfo=timezone.utc)
            rows=read_rows(path,dt,dt)
        self.assertEqual(rows,[dict(timestamp_utc='2025-01-01T00:00:00Z',region='DUK',demand_mw=100)])
