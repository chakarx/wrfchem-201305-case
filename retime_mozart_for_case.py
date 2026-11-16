"""Copy a MOZART month/day/hour window onto case dates, retaining source provenance.

This changes calendar labels, not atmospheric concentrations. The result is a
time-shifted boundary experiment, not reconstructed chemistry for the target year.
Only netCDF4 and numpy are required. Input files are always opened read-only.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

FORMAT='%Y-%m-%d_%H:%M:%S'
ORIGINALS=('retime_source_date','retime_source_datesec','retime_source_time')


def times_from_date(date,seconds):
    result=[]
    for day,second in zip(date,seconds):
        if not np.isfinite(day) or int(day)!=day or not np.isfinite(second) or int(second)!=second:
            raise ValueError('date/datesec must contain finite integer values')
        if not 0<=second<86400:raise ValueError('datesec must be in [0,86400)')
        stamp=str(int(day))
        # Legacy files may describe YYMMDD, while many actually store YYYYMMDD.
        if len(stamp)<=6:
            stamp=stamp.zfill(6)
            stamp=('19' if int(stamp[:2])>=70 else '20')+stamp
        result.append(datetime.strptime(stamp,'%Y%m%d')+timedelta(seconds=int(second)))
    return result


def checked_values(variable):
    values=np.ma.asarray(variable[:])
    if np.ma.is_masked(values) or not np.isfinite(values).all():
        raise ValueError(f'{variable.name}: missing/nonfinite coordinate values')
    return np.asarray(values)


def bracket_indices(values,lower,upper,name):
    if values.ndim!=1 or len(values)<2 or not lower<upper:
        raise ValueError(f'{name}: expected a 1D coordinate and increasing bounds')
    order=np.argsort(values);sorted_values=values[order]
    if np.any(np.diff(sorted_values)<=0):raise ValueError(f'{name}: duplicate coordinate values')
    if sorted_values[0]>lower or sorted_values[-1]<upper:
        raise ValueError(f'{name}: source range {sorted_values[0]}..{sorted_values[-1]} does not cover {lower}..{upper}')
    first=max(0,np.searchsorted(sorted_values,lower,side='right')-1)
    last=min(len(values)-1,np.searchsorted(sorted_values,upper,side='left'))
    return order[first:last+1]


def source_indices(source_times,target_times,source_year=None):
    lookup={}
    for index,stamp in enumerate(source_times):lookup.setdefault(stamp,[]).append(index)
    candidates=[]
    years=[source_year] if source_year is not None else sorted({value.year for value in source_times})
    for year in years:
        try:
            wanted=[value.replace(year=year+value.year-target_times[0].year) for value in target_times]
        except ValueError:
            continue  # No implicit leap-day interpolation.
        if all(len(lookup.get(value,[]))==1 for value in wanted):
            candidates.append((year,[lookup[value][0] for value in wanted]))
    if len(candidates)!=1:
        raise ValueError(f'Expected one complete source year, found {[year for year,_ in candidates]}; '
                         'use --source-year to choose explicitly, or check missing/duplicate times')
    return candidates[0]


def copy_variable(source,destination,name=None):
    name=name or source.name
    options={}
    if '_FillValue' in source.ncattrs():options['fill_value']=source.getncattr('_FillValue')
    if source.dimensions and np.dtype(source.dtype).kind in 'iuf':
        options.update(zlib=True,complevel=2,shuffle=True)
    output=destination.createVariable(name,source.datatype,source.dimensions,**options)
    output.setncatts({key:source.getncattr(key) for key in source.ncattrs()
                     if key not in ('_FillValue','_Netcdf4Coordinates','_Netcdf4Dimid')})
    output.set_auto_maskandscale(False)
    return output


def retime(input_path,output_path,start,end,source_year=None,north=58,south=10,west=62,east=142):
    input_path,output_path=Path(input_path),Path(output_path)
    if input_path.resolve()==output_path.resolve():raise ValueError('Input and output must differ')
    temporary=output_path.with_name(output_path.name+'.partial')
    report_path=output_path.with_name(output_path.name+'.retime.json')
    for path in (output_path,temporary,report_path):
        if path.exists():raise FileExistsError(f'Refusing to overwrite {path}')
    if end<start or (end-start).total_seconds()%21600 or any(value.minute or value.second or value.hour%6 for value in (start,end)):
        raise ValueError('Use increasing dates aligned to 6-hour UTC intervals')
    targets=[start+timedelta(hours=6*index) for index in range(int((end-start).total_seconds()/21600)+1)]
    if not -90<=south<north<=90 or not 0<=west<east<=360 or east-west>180:
        raise ValueError('This script supports a non-wrapping latitude/longitude box')
    with Dataset(input_path,'r') as source:
        if source.groups:raise ValueError('Grouped NetCDF inputs are not supported')
        required={'date','datesec','time','lat','lon','lev','hyam','hybm','P0','PS'}
        if required-set(source.variables):raise ValueError(f'Missing coordinates: {required-set(source.variables)}')
        if set(ORIGINALS)&set(source.variables):raise ValueError('Input already contains retiming provenance')
        if len(source['date'].dimensions)!=1 or source['datesec'].dimensions!=source['date'].dimensions:
            raise ValueError('date/datesec must use the same single record dimension')
        time_dim=source['date'].dimensions[0]
        if source['time'].dimensions!=(time_dim,):raise ValueError('Unexpected time coordinate dimensions')
        source_times=times_from_date(checked_values(source['date']),checked_values(source['datesec']))
        year,indices=source_indices(source_times,targets,source_year)
        lat,lon=checked_values(source['lat']),checked_values(source['lon'])
        if np.any(lon<0):
            raise ValueError('Use the original 0..360 longitude coordinates; no implicit longitude conversion')
        selections={time_dim:np.array(indices),source['lat'].dimensions[0]:bracket_indices(lat,south,north,'lat'),
                    source['lon'].dimensions[0]:bracket_indices(lon,west,east,'lon')}
        selected_source=[source_times[index].strftime(FORMAT) for index in indices]
        report=dict(input=str(input_path.resolve()),source_year=year,
                    target_times=[value.strftime(FORMAT) for value in targets],source_times=selected_source,
                    requested_bounds=dict(north=north,south=south,west=west,east=east),
                    actual_bounds=dict(north=float(lat[selections[source['lat'].dimensions[0]]].max()),
                                       south=float(lat[selections[source['lat'].dimensions[0]]].min()),
                                       west=float(lon[selections[source['lon'].dimensions[0]]].min()),
                                       east=float(lon[selections[source['lon'].dimensions[0]]].max())),
                    method='same month/day/hour; concentrations unchanged; no temporal interpolation',
                    limitation='Time-shifted source chemistry is not reconstructed chemistry for the target year.')
        output_path.parent.mkdir(parents=True,exist_ok=True)
        with Dataset(temporary,'w',format='NETCDF4') as destination:
            for name,dimension in source.dimensions.items():
                length=len(selections[name]) if name in selections else len(dimension)
                destination.createDimension(name,None if dimension.isunlimited() else length)
            destination.setncatts({name:source.getncattr(name) for name in source.ncattrs()
                                  if name not in ('_NCProperties','_SuperblockVersion','_IsNetcdf4')})
            note=f'{datetime.now(timezone.utc).isoformat()}: month/day/hour retiming from source year {year} to case start {start:%Y}; source concentrations unchanged.'
            destination.history=note+'\n'+str(getattr(source,'history',''))
            destination.retime_method=report['method']
            destination.retime_limitation=report['limitation']
            destination.retime_source_year=year
            destination.retime_source_file=input_path.name
            destination.retime_original_time_variables=', '.join(ORIGINALS)
            for name,variable in source.variables.items():
                output=copy_variable(variable,destination)
                variable.set_auto_maskandscale(False)
                if time_dim in variable.dimensions:
                    axis=variable.dimensions.index(time_dim)
                    for position,index in enumerate(indices):
                        key=[selections.get(dim,slice(None)) for dim in variable.dimensions]
                        key[axis]=index
                        target=[slice(None)]*variable.ndim;target[axis]=position
                        output[tuple(target)]=variable[tuple(key)]
                else:
                    key=tuple(selections.get(dim,slice(None)) for dim in variable.dimensions)
                    output[...] = variable[key] if variable.ndim else variable[...]
            for name,original in zip(ORIGINALS,('date','datesec','time')):
                output=copy_variable(source[original],destination,name)
                output[:]=source[original][indices]
                output.retime_role='Original source timestamp; not the target case time'
            destination['date'][:]=[int(value.strftime('%Y%m%d')) for value in targets]
            destination['datesec'][:]=[value.hour*3600+value.minute*60+value.second for value in targets]
            destination['time'].units=f'hours since {start:%Y-%m-%d %H:%M:%S}'
            destination['time'].calendar='gregorian'
            destination['time'][:]=[(value-start).total_seconds()/3600 for value in targets]
            for name in ('date','datesec'):
                destination[name].long_name='Target case '+('date (YYYYMMDD)' if name=='date' else 'seconds since midnight UTC')
            print(f'Copied {len(source.variables)} original variables and {len(indices)} records from {year}',flush=True)
    with Dataset(temporary) as result:
        if times_from_date(result['date'][:],result['datesec'][:])!=targets:
            raise ValueError('Output timestamp verification failed')
        if not np.array_equal(result['retime_source_date'][:],np.array([int(value[:10].replace('-','')) for value in selected_source])):
            # Source date values in YYMMDD form are also supported; compare parsed values instead.
            originals=times_from_date(result['retime_source_date'][:],result['retime_source_datesec'][:])
            if [value.strftime(FORMAT) for value in originals]!=selected_source:
                raise ValueError('Source provenance verification failed')
    if output_path.exists():raise FileExistsError(f'Refusing to overwrite {output_path}')
    temporary.replace(output_path)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Output:',output_path)
    print('Report:',report_path)
    print('NOTE:',report['limitation'])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--start',default='2013-05-01_00:00:00');parser.add_argument('--end',default='2013-05-03_00:00:00')
    parser.add_argument('--source-year',type=int,help='Required when multiple source years cover the requested window')
    for key,value in [('north',58),('south',10),('west',62),('east',142)]:parser.add_argument('--'+key,type=float,default=value)
    args=parser.parse_args()
    retime(args.input,args.output,datetime.strptime(args.start,FORMAT),datetime.strptime(args.end,FORMAT),
           args.source_year,args.north,args.south,args.west,args.east)
