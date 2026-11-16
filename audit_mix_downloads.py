"""Audit every downloaded original NetCDF for the selected calendar month."""
import argparse
import json
from pathlib import Path
import numpy as np
from netCDF4 import Dataset


def audit(root,month):
    root=Path(root).resolve()
    manifest=json.loads((root/'download_manifest.json').read_text(encoding='utf-8'))
    records=[]
    for bundle in manifest['files']:
        for name in bundle['extracted']:
            # Remains portable after moving the dataset to the server.
            path=root/str(manifest['base_year'])/Path(name.replace('\\','/')).name
            with Dataset(path) as nc:
                assert len(nc.dimensions['time'])==12,path
                assert float(nc['time'][month-1])==month,path
                for name,var in nc.variables.items():
                    if name in ('lon','lat','time'):continue
                    values=np.ma.asarray(var[month-1],dtype='f8')
                    finite=np.asarray(np.ma.filled(values,np.nan))
                    if not np.isfinite(finite).all() or np.min(finite)<0:
                        raise ValueError(f'{path}:{name}: negative or missing values')
                    units=getattr(var,'units',getattr(var,'Unit','')).strip()
                    if units not in ('Mg/month','Mmol/month'):
                        raise ValueError(f'{path}:{name}: unexpected original unit {units!r}')
                    records.append(dict(file=path.name,variable=name,units=units,
                                        min=float(finite.min()),max=float(finite.max()),
                                        sum_original_units=float(finite.sum())))
    report=dict(base_year=manifest['base_year'],month=month,
                original_netcdf_files=sum(len(f['extracted']) for f in manifest['files']),
                fields=len(records),status='PASS: 12-month axis; selected month finite and nonnegative; declared units verified',
                note='This checks original fields, not cross-mechanism VOC speciation.',records=records)
    output=root/f'audit_{manifest["base_year"]}_{month:02d}.json'
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print({k:v for k,v in report.items() if k!='records'});print(output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='../raw_mix_v1.1');p.add_argument('--month',type=int,choices=range(1,13),default=5)
    a=p.parse_args();audit(a.root,a.month)
