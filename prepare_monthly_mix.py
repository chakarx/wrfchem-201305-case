"""Audit downloaded MIX and save a selected native-grid month in kg/cell/month.

This is an inventory intermediate, NOT wrfchemi or ambient concentration.
python prepare_monthly_mix.py --config mix_config.json --month 2013-05
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from make_mix_wrfchemi import source_month


def prepare(config, year, month, output):
    config = Path(config).resolve()
    cfg = json.loads(config.read_text(encoding='utf-8-sig'))
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    data, report, lon0, lat0 = {}, [], None, None
    for sector, definitions in cfg['sectors'].items():
        data[sector] = {}
        for species, original in definitions['sources'].items():
            spec = original.copy()
            if 'zero_with_reason' in spec:
                continue
            path = Path(spec['file'])
            if not path.is_absolute():
                spec['file'] = str(config.parent/path)
            context = dict(inventory_year=cfg['inventory_year'],year=year,month=month,
                           month_index=month-1,sector=sector,species=species)
            lon, lat, kg, info = source_month(spec, context)
            if lon0 is not None and (not np.array_equal(lon,lon0) or not np.array_equal(lat,lat0)):
                raise ValueError('Original MIX source grids must match for this native-grid intermediate')
            lon0,lat0=lon,lat
            data[sector][species]=kg
            report.append(dict(info,sector=sector,species=species,total_kg=float(kg.sum()),
                               min_kg=float(kg.min()),max_kg=float(kg.max())))
    if lon0 is None:
        raise ValueError('No source data')
    zeros=[]
    for sector, definitions in cfg['sectors'].items():
        for species,spec in definitions['sources'].items():
            if 'zero_with_reason' in spec:
                data[sector][species]=np.zeros((len(lat0),len(lon0)))
                zeros.append(dict(sector=sector,species=species,reason=spec['zero_with_reason']))
        mass=data[sector]
        for expression,array,magnitude in [('PM10-PM25',mass['PM10']-mass['PM25'],mass['PM10']+mass['PM25']),
                                 ('PM25-BC-OC',mass['PM25']-mass['BC']-mass['OC'],mass['PM25']+mass['BC']+mass['OC'])]:
            tolerance=np.maximum(1e-7,magnitude*4*np.finfo(np.float32).eps)
            negative=array < -tolerance
            if negative.any():
                raise ValueError(f'{sector}: inconsistent {expression}, {negative.sum()} cells, min={array.min()} kg')
    output.parent.mkdir(parents=True,exist_ok=True)
    with Dataset(output,'w',format='NETCDF4') as nc:
        nc.createDimension('sector',len(data));nc.createDimension('lat',len(lat0));nc.createDimension('lon',len(lon0))
        nc.title='MIX v1.1 original monthly anthropogenic emission totals on the native grid'
        nc.inventory_year=cfg['inventory_year'];nc.inventory_month=month
        nc.intended_simulation_year=year
        nc.note='Inventory intermediate, not WRF-Chem-ready; no concentration variables. No interannual scaling.'
        nc.zero_sector_fields=json.dumps(zeros,ensure_ascii=False)
        nc.createVariable('sector',str,('sector',))[:]=np.array(list(data),dtype=object)
        for name,values,units in [('lon',lon0,'degrees_east'),('lat',lat0,'degrees_north')]:
            v=nc.createVariable(name,'f8',(name,));v[:]=values;v.units=units
        for species in next(iter(cfg['sectors'].values()))['sources']:
            v=nc.createVariable(species,'f8',('sector','lat','lon'),zlib=True,complevel=4)
            v.units='kg cell-1 month-1'
            v[:]=np.stack([values[species] for values in data.values()])
            if species=='NOx':v.mass_basis='NO2 equivalent'
    qa=output.with_suffix('.qa.json')
    qa.write_text(json.dumps(dict(inventory_year=cfg['inventory_year'],month=month,
        target_year=year,shape=[len(data),len(lat0),len(lon0)],
        pm_closure='PM10 >= PM25 and PM25 >= BC+OC checked on all native cells',
        sources=report,explicit_zero_sources=zeros),ensure_ascii=False,indent=2),encoding='utf-8')
    print(output);print(qa)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='mix_config.json')
    parser.add_argument('--month',default='2013-05')
    parser.add_argument('--output')
    args=parser.parse_args()
    date=datetime.strptime(args.month,'%Y-%m')
    cfg=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    output=args.output or f'mix_v1.1_{cfg["inventory_year"]}_{date:%m}_monthly_kg.nc'
    prepare(args.config,date.year,date.month,output)


if __name__=='__main__':
    main()
