"""Read real met_em dimensions and generate bootstrap + ARI-pair namelists.

python prepare_runtime_namelists.py --met-dir /path/to/WPS_case --output-dir /path/to/prepared
Writes new files only; leaves the supplied templates unchanged.
Requires netCDF4; f90nml is not needed. Reads the simple integer/string
assignments used by this case, rather than implementing all Fortran namelist syntax.
"""
import argparse
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from netCDF4 import Dataset


_QUOTED_OR_COMMENT = re.compile(r"'[^']*(?:''[^']*)*'|\"[^\"]*(?:\"\"[^\"]*)*\"|![^\r\n]*")


def _clean(text, mask_strings=False):
    """Keep character offsets while hiding comments and, optionally, strings."""
    def hide(match):
        value=match.group()
        if mask_strings or value.startswith('!'):
            return ''.join('\n' if char=='\n' else ' ' for char in value)
        return value
    return _QUOTED_OR_COMMENT.sub(hide,text)


def _value_span(text,section,key):
    masked=_clean(text,mask_strings=True)
    groups=list(re.finditer(r'(?im)^[ \t]*&'+re.escape(section)+r'\b',masked))
    if len(groups)!=1:raise ValueError(f'Expected one &{section} group')
    start=groups[0].end()
    end=re.search(r'/|(?im:^[ \t]*&end\b)',masked[start:])
    if end is None:raise ValueError(f'Missing terminator for &{section}')
    stop=start+end.start()
    if re.search(r'(?m)^[ \t]*&',masked[start:stop]):
        raise ValueError(f'Missing terminator for &{section}')
    assignments=list(re.finditer(r'(?i)\b([a-z]\w*)\s*(\([^)]*\))?\s*=',masked[start:stop]))
    matches=[i for i,m in enumerate(assignments) if m.group(1).lower()==key.lower()]
    if len(matches)!=1:raise ValueError(f'Expected one {key} assignment in &{section}')
    index=matches[0];match=assignments[index]
    if match.group(2):raise ValueError(f'Indexed assignment unsupported for {section}.{key}')
    return start+match.end(),start+assignments[index+1].start() if index+1<len(assignments) else stop


def read_values(text,section,key):
    first,last=_value_span(text,section,key)
    raw=_clean(text[first:last]).strip().rstrip(',').strip()
    # Only the integer arrays and quoted dates needed by this script are parsed.
    values=[]
    for token in re.findall(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[^,]+",raw):
        token=token.strip()
        if token[:1] in ("'",'"') and token[-1:]==token[0]:
            values.append(token[1:-1].replace(token[0]*2,token[0]))
        elif re.fullmatch(r'[+-]?\d+',token):values.append(int(token))
        else:raise ValueError(f'Unsupported value in {section}.{key}: {token!r}')
    if not values:raise ValueError(f'Empty {section}.{key}')
    return values


def set_integers(text,section,key,values):
    """Replace this assignment only, preserving surrounding text and trailing comments."""
    if not all(isinstance(value,int) for value in read_values(text,section,key)):
        raise ValueError(f'Expected integers for {section}.{key}')
    first,last=_value_span(text,section,key)
    clean=_clean(text[first:last])
    begin=re.search(r'\S',clean).start()
    end=len(clean.rstrip())
    replacement=', '.join(str(value) for value in values)+','
    return text[:first+begin]+replacement+text[first+end:]


def met_filename(domain,date):
    # WPS runs on Linux; underscores also allow inspecting copied headers on Windows.
    stamp=date.strftime('%Y-%m-%d_%H:%M:%S')
    if os.name=='nt':stamp=stamp.replace(':','_')
    return f'met_em.d{domain:02d}.{stamp}.nc'


def prepare(case,met_dir,output):
    case,met_dir,output=map(Path,[case,met_dir,output])
    namelist=(case/'namelist.input').read_text(encoding='utf-8')
    wps=(case/'namelist.wps').read_text(encoding='utf-8')
    domains=read_values(namelist,'domains','max_dom')[0]
    if domains!=read_values(wps,'share','max_dom')[0] or domains<1:
        raise ValueError('WRF/WPS max_dom must agree and be positive')
    dates={}
    for endpoint in ('start','end'):
        values=read_values(wps,'share',endpoint+'_date')
        if len(values) not in (1,domains) or len(set(values))!=1:
            raise ValueError(f'This case requires identical {endpoint}_date for all domains')
        dates[endpoint]=datetime.strptime(values[0],'%Y-%m-%d_%H:%M:%S')
    start,end=dates['start'],dates['end']
    interval=read_values(wps,'share','interval_seconds')[0]
    if interval<=0 or end<start or (end-start).total_seconds()%interval:
        raise ValueError('Invalid start/end dates or interval_seconds')
    sizes={key:read_values(namelist,'domains',key) for key in ('e_we','e_sn')}
    if any(len(value)!=domains for value in sizes.values()):
        raise ValueError('Provide e_we/e_sn explicitly for every domain')
    levels=set();soil=set();land=set();count=0
    current=start
    while current<=end:
        for domain in range(1,domains+1):
            path=met_dir/met_filename(domain,current)
            with Dataset(path) as nc:
                levels.add(len(nc.dimensions['num_metgrid_levels']))
                for name in ('num_st_layers','num_sm_layers'):
                    if name not in nc.dimensions:raise ValueError(f'{path}: missing {name}')
                    soil.add(len(nc.dimensions[name]))
                if 'NUM_LAND_CAT' in nc.ncattrs():land.add(int(nc.NUM_LAND_CAT))
                elif 'land_cat' in nc.dimensions:land.add(len(nc.dimensions['land_cat']))
                else:raise ValueError(f'{path}: land category count unavailable; inspect geo_em and met_em')
                for dimension,key in [('west_east','e_we'),('south_north','e_sn')]:
                    if len(nc.dimensions[dimension])!=sizes[key][domain-1]-1:
                        raise ValueError(f'{path}: {dimension} does not match new domain')
            count+=1
        current+=timedelta(seconds=interval)
    if any(len(values)!=1 for values in (levels,soil,land)):
        raise ValueError(f'Inconsistent met_em vertical/soil/land dimensions: {levels}, {soil}, {land}')
    namelist=set_integers(namelist,'domains','num_metgrid_levels',[next(iter(levels))])
    namelist=set_integers(namelist,'domains','num_metgrid_soil_levels',[next(iter(soil))])
    namelist=set_integers(namelist,'physics','num_land_cat',[next(iter(land))])
    on=set_integers(namelist,'chem','aer_ra_feedback',[1]*domains)
    off=set_integers(on,'chem','aer_ra_feedback',[0]*domains)
    # Keep chem_opt=9 so real creates chemical initial fields, but do not read absent MEGAN files.
    # This is ONLY for geometry preparation; never use it for the final WRF-Chem run.
    bootstrap=set_integers(on,'chem','bio_emiss_opt',[0]*domains)
    filenames=['namelist.input.ARI_on','namelist.input.ARI_off','namelist.input.bootstrap']
    for name in filenames:
        if (output/name).exists():raise FileExistsError(f'{output/name}: choose a new output directory')
    output.mkdir(parents=True,exist_ok=True)
    for name,text in zip(filenames,[on,off,bootstrap]):
        with (output/name).open('x',encoding='utf-8',newline='\n') as handle:handle.write(text)
    print(f'Checked {count} met_em files: met levels={levels}, soil levels={soil}, land categories={land}')
    print('Created '+', '.join(str(output/f) for f in filenames))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',default=str(Path(__file__).parent))
    p.add_argument('--met-dir',required=True);p.add_argument('--output-dir',required=True)
    a=p.parse_args();prepare(a.case,a.met_dir,a.output_dir)
