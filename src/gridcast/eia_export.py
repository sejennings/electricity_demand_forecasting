"""Read EIA's published hourly export without using its imputed/adjusted columns."""
from datetime import datetime,timedelta,timezone
import posixpath
import shutil
from urllib.request import urlopen
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from gridcast.ingestion import number,timestamp

URL='https://www.eia.gov/electricity/gridmonitor/knownissues/xls/DUK.xlsx'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def download(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with urlopen(URL,timeout=60) as response,path.open('wb') as output:
        shutil.copyfileobj(response,output)


def read_rows(path,start,end):
    rows=[]
    with ZipFile(path) as bundle:
        workbook=ET.fromstring(bundle.read('xl/workbook.xml'))
        props=workbook.find('m:workbookPr',NS)
        if props is not None and props.attrib.get('date1904') in ('1','true'):
            raise ValueError('Unexpected EIA workbook date epoch')
        sheet=next(s for s in workbook.findall('m:sheets/m:sheet',NS) if s.attrib['name']=='Published Hourly Data')
        rid=sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
        rel=next(r for r in ET.fromstring(bundle.read('xl/_rels/workbook.xml.rels')) if r.attrib['Id']==rid)
        target=rel.attrib['Target']
        member=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
        strings=[''.join(si.itertext()) for si in ET.fromstring(bundle.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        headers=None
        with bundle.open(member) as stream:
            for _,row in ET.iterparse(stream,events=['end']):
                if row.tag!='{'+NS['m']+'}row': continue
                cells={}
                for cell in row:
                    column=cell.attrib.get('r','').rstrip('0123456789')
                    if headers and column not in headers.values(): continue
                    value=cell.find('m:v',NS)
                    if value is not None:
                        cells[column]=strings[int(value.text)] if cell.attrib.get('t')=='s' else value.text
                if headers is None:
                    headers={label:column for column,label in cells.items() if label in ('BA','UTC time','Demand')}
                    if set(headers)!= {'BA','UTC time','Demand'}:
                        raise ValueError('Unexpected EIA published-hourly export headers')
                elif cells.get(headers['UTC time']):
                    serial=float(cells[headers['UTC time']])
                    hour=round(serial*24)
                    if abs(serial*24-hour)>0.0001:
                        raise ValueError('Export timestamp is not a whole UTC hour')
                    dt=datetime(1899,12,30,tzinfo=timezone.utc)+timedelta(hours=hour)
                    if start<=dt<=end:
                        if cells.get(headers['BA'])!='DUK': raise ValueError('Unexpected export region')
                        rows.append(dict(timestamp_utc=timestamp(dt),region='DUK',
                                         demand_mw=number(cells.get(headers['Demand']))))
                row.clear()
    return rows
