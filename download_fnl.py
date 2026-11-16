"""Download original NCAR/NCEP 1-degree, 6-hour FNL GRIB2 for namelist.wps dates.

python download_fnl.py --namelist namelist.wps --output ../fnl_20130501_20130503
Uses only the Python standard library. No GDEX account or conversion service needed.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

BASE = 'https://data.gdex.ucar.edu/d083002/grib2'
DATE_FORMAT = '%Y-%m-%d_%H:%M:%S'


def case_dates(path):
    text=Path(path).read_text(encoding='utf-8-sig')
    text='\n'.join(line.split('!')[0] for line in text.splitlines())
    def dates(key):
        found=re.search(r'\b'+key+r'\s*=\s*((?:[\s,]*[\'\"][0-9_:\-]+[\'\"])+)',text,re.I)
        if not found:raise ValueError(f'Missing {key} in {path}')
        values=re.findall(r'[\'\"]([0-9_:\-]+)[\'\"]',found[1])
        if len(set(values))!=1:raise ValueError(f'Domains have different {key}: {values}')
        return datetime.strptime(values[0],DATE_FORMAT)
    interval=re.search(r'\binterval_seconds\s*=\s*(\d+)',text,re.I)
    if not interval or int(interval[1])!=21600:
        raise ValueError('This FNL dataset is 6-hourly: interval_seconds must be 21600')
    start,end=dates('start_date'),dates('end_date')
    if start>end or any(t.hour%6 or t.minute or t.second for t in [start,end]):
        raise ValueError('Use an increasing interval aligned to 00/06/12/18 UTC')
    return start,end


def audit_grib2(path,expected):
    """Check every GRIB message boundary, sections, time, grid and core level metadata.

    This verifies framing and header metadata, not decompression of packed grid values.
    """
    data=Path(path).read_bytes()
    offset=0;messages=0;fields=0;grids=set();references=Counter();templates=Counter()
    pressure_levels={n:set() for n in ['temperature','relative_humidity','u_wind','v_wind','height']}
    # WMO GRIB2 discipline/category/parameter identifiers.
    parameter_names={(0,0,0):'temperature',(0,1,1):'relative_humidity',
                     (0,2,2):'u_wind',(0,2,3):'v_wind',(0,3,5):'height'}
    while offset<len(data):
        if data[offset:offset+4]!=b'GRIB' or len(data)-offset<20 or data[offset+7]!=2:
            raise ValueError(f'{path}: invalid GRIB2 header at {offset}')
        size=int.from_bytes(data[offset+8:offset+16],'big')
        stop=offset+size
        if size<20 or stop>len(data) or data[stop-4:stop]!=b'7777':
            raise ValueError(f'{path}: incomplete GRIB2 message at {offset}')
        cursor=offset+16;sections=[];reference=None;grid=None;discipline=data[offset+6]
        while cursor<stop-4:
            length=int.from_bytes(data[cursor:cursor+4],'big')
            if length<5 or cursor+length>stop-4:
                raise ValueError(f'{path}: invalid section length at {cursor}')
            section=data[cursor:cursor+length];number=section[4];sections.append(number)
            if number==1:
                if length<21:raise ValueError('Short identification section')
                reference=datetime(int.from_bytes(section[12:14],'big'),*section[14:19])
                references[reference.strftime(DATE_FORMAT)]+=1
            if number==3:
                template=int.from_bytes(section[12:14],'big')
                if template!=0 or length<72:raise ValueError(f'Expected regular lon/lat grid, template={template}')
                grid=(int.from_bytes(section[30:34],'big'),int.from_bytes(section[34:38],'big'))
                grids.add(grid)
                if grid!=(360,181):raise ValueError(f'Expected 1-degree global grid; found {grid}')
            if number==4:
                if reference is None or grid is None:raise ValueError('Product before identification/grid')
                template=int.from_bytes(section[7:9],'big');templates[template]+=1;fields+=1
                if template==0 and length>=34:
                    parameter=parameter_names.get((discipline,section[9],section[10]))
                    forecast=int.from_bytes(section[18:22],'big')
                    if parameter and section[22]==100 and forecast==0 and reference==expected:
                        scale=section[23]
                        if scale&128:scale=-(scale&127)
                        pressure_pa=int.from_bytes(section[24:28],'big')*10.0**(-scale)
                        pressure_levels[parameter].add(pressure_pa/100)
            cursor+=length
        if cursor!=stop-4 or not all(n in sections for n in [1,3,4,5,6,7]):
            raise ValueError(f'{path}: missing GRIB2 sections')
        messages+=1;offset=stop
    if not messages or not fields:raise ValueError(f'{path}: empty GRIB file')
    if expected.strftime(DATE_FORMAT) not in references:raise ValueError(f'{path}: wrong reference time')
    for name,levels in pressure_levels.items():
        if len(levels)<20:raise ValueError(f'{path}: missing analysis {name} pressure levels: {sorted(levels)}')
    return dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),grib_edition=2,
                messages=messages,fields=fields,grid_sizes=[list(g) for g in sorted(grids)],
                reference_times=dict(references),product_templates=dict(templates),
                analysis_pressure_levels_hpa={k:sorted(v,reverse=True) for k,v in pressure_levels.items()},
                verification='All message/section lengths and 7777 trailers; grid/time and core pressure-level metadata. Packed values not decoded.')


def fetch(timestamp,output):
    name=f'fnl_{timestamp:%Y%m%d_%H}_00.grib2'
    url=f'{BASE}/{timestamp:%Y}/{timestamp:%Y.%m}/{name}'
    target=output/name
    if not target.exists():
        temporary=target.with_suffix('.grib2.part')
        for attempt in range(3):
            try:
                request=urllib.request.Request(url,headers={'User-Agent':'WRF-case-FNL-downloader/1.0'})
                with urllib.request.urlopen(request,timeout=60) as response,temporary.open('wb') as handle:
                    expected_bytes=response.headers.get('Content-Length')
                    downloaded=0
                    while block:=response.read(1024*1024):
                        handle.write(block);downloaded+=len(block)
                if expected_bytes and downloaded!=int(expected_bytes):
                    raise ValueError(f'Truncated download: {downloaded}/{expected_bytes}')
                audit=audit_grib2(temporary,timestamp)
                temporary.replace(target)
                break
            except Exception:
                temporary.unlink(missing_ok=True)
                if attempt==2:raise
                time.sleep(2*(attempt+1))
    else:
        audit=audit_grib2(target,timestamp)
    print(f'{name}: {audit["bytes"]:,} bytes, {audit["fields"]} fields, PASS',flush=True)
    return dict(file=name,url=url,analysis_time_utc=timestamp.strftime(DATE_FORMAT),**audit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namelist',default=str(Path(__file__).with_name('namelist.wps')))
    parser.add_argument('--output',default=str(Path(__file__).parent.parent/'fnl_20130501_20130503'))
    args=parser.parse_args()
    start,end=case_dates(args.namelist)
    timestamps=[start+timedelta(hours=6*i) for i in range(int((end-start).total_seconds()/21600)+1)]
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    print(f'{start} to {end} UTC inclusive: {len(timestamps)} files',flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda t:fetch(t,output),timestamps))
    manifest=dict(dataset='NCEP FNL Operational Model Global Tropospheric Analyses',
                  dataset_id='d083002 (formerly ds083.2)',doi='10.5065/D6M043C6',
                  source_page='https://gdex.ucar.edu/datasets/d083002/',
                  download_time_utc=datetime.now(timezone.utc).isoformat(),
                  interval_seconds=21600,start_utc=start.strftime(DATE_FORMAT),end_utc=end.strftime(DATE_FORMAT),
                  total_files=len(results),total_bytes=sum(r['bytes'] for r in results),files=results)
    (output/'download_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'download_urls.txt').write_text('\n'.join(r['url'] for r in results)+'\n',encoding='utf-8')
    print(f'Complete: {len(results)} files, {manifest["total_bytes"]:,} bytes; {output}',flush=True)


if __name__=='__main__':main()
