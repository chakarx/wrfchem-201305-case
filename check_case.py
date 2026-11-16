"""Check coupled namelists and, optionally, actual real.exe wrfinput files.

No f90nml dependency. Empty groups such as &grib2 / are valid.
The embedded reader supports the ordinary WRF namelist subset used by this case.
"""
import argparse
from datetime import datetime
from pathlib import Path
import re
import numpy as np
from netCDF4 import Dataset


def read_namelist(path):
    """Read the subset of Fortran namelist syntax used by these checks."""
    source = Path(path).read_text(encoding="utf-8-sig")
    # Mask quoted strings and comments while preserving character positions.
    masked = list(source)
    quote = None
    i = 0
    while i < len(source):
        c = source[i]
        if quote:
            masked[i] = " "
            if c == quote:
                if i + 1 < len(source) and source[i + 1] == quote:
                    masked[i + 1] = " "
                    i += 1
                else:
                    quote = None
        elif c in "\"'":
            quote = c
            masked[i] = " "
        elif c == "!":
            stop = source.find("\n", i)
            stop = len(source) if stop < 0 else stop
            source = source[:i] + " " * (stop - i) + source[stop:]
            masked[i:stop] = " " * (stop - i)
            i = stop - 1
        i += 1
    if quote:
        raise ValueError(f"{path}: unterminated quoted string")
    mask = "".join(masked)
    groups = {}
    group_pattern = re.compile(r"&([A-Za-z]\w*)\b(.*?)(/|&end\b)", re.S | re.I)
    assignment = re.compile(r"\b([A-Za-z]\w*)\s*(?:\(\s*(\d+)(?:\s*:\s*(\d+))?\s*\))?\s*=", re.I)
    cursor = 0
    for group in group_pattern.finditer(mask):
        if mask[cursor:group.start()].strip():
            raise ValueError(f"{path}: unsupported text outside namelist groups")
        cursor = group.end()
        name = group[1].lower()
        if name in groups:
            raise ValueError(f"{path}: repeated group {name}")
        body_start, body_end = group.span(2)
        body_mask = mask[body_start:body_end]
        matches = list(assignment.finditer(body_mask))
        if not matches:
            # WRF commonly includes empty &grib2, &fdda, etc. sections.
            if source[body_start:body_end].strip(" \t\r\n,"):
                raise ValueError(f"{path}: invalid assignments in {name}")
            groups[name] = {}
            continue
        if body_mask[:matches[0].start()].strip(" \t\r\n,"):
            raise ValueError(f"{path}: invalid assignments in {name}")
        values = {}
        for k, match in enumerate(matches):
            end = matches[k + 1].start() if k + 1 < len(matches) else len(body_mask)
            text = source[body_start + match.end():body_start + end]
            key = match[1].lower()
            try:
                parsed = parse_values(text, path)
            except ValueError as error:
                line = source.count('\n', 0, body_start + match.start()) + 1
                raise ValueError(f'{path}:{line}: &{name}.{key}: {error}') from error
            if match[2] is None:
                if key in values:
                    raise ValueError(f"{path}: repeated assignment {name}.{key}")
                values[key] = parsed[0] if len(parsed) == 1 else parsed
            else:
                first = int(match[2])
                last = int(match[3]) if match[3] else first
                if first < 1 or last < first or len(parsed) != last - first + 1:
                    raise ValueError(f"{path}: invalid indexed assignment {key}")
                array = values.setdefault(key, [])
                if not isinstance(array, list):
                    raise ValueError(f"{path}: mixed scalar/indexed assignments for {key}")
                array.extend([None] * max(0, last - len(array)))
                array[first - 1:last] = parsed
        groups[name] = values
    if not groups or mask[cursor:].strip():
        raise ValueError(f"{path}: missing group terminator or unsupported namelist syntax")
    return groups


def parse_values(text, path):
    atom = r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[^\s,]+"
    pattern = re.compile(r"(?:(\d+)\s*\*\s*)?(" + atom + r")")
    output = []
    cursor = 0
    for match in pattern.finditer(text):
        gap = text[cursor:match.start()]
        if gap.strip(" \t\r\n,") or gap.count(",") > 1:
            raise ValueError(f"{path}: unsupported separator/null value near {gap!r}")
        cursor = match.end()
        token = match[2]
        if token[0] in "\"'":
            value = token[1:-1].replace(token[0] * 2, token[0])
        elif token.lower() in (".true.", ".false.", "t", "f"):
            value = token.lower() in (".true.", "t")
        elif re.fullmatch(r"[+-]?\d+", token):
            value = int(token)
        elif re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?", token):
            value = float(re.sub("[dD]", "e", token))
        else:
            raise ValueError(f"{path}: unsupported value {token!r}; quote strings")
        output.extend([value] * (int(match[1]) if match[1] else 1))
    if text[cursor:].strip(" \t\r\n,") or not output:
        raise ValueError(f"{path}: missing or unsupported value")
    return output


def array(group, key, count):
    value = group[key]
    result = value if isinstance(value, list) else [value]
    assert len(result) >= count and None not in result[:count], f"{key}: expected {count} entries"
    return result[:count]


def check(directory, inputs=()):
    root=Path(directory)
    wps=read_namelist(root/'namelist.wps');wrf=read_namelist(root/'namelist.input')
    share,geo,dom,time,chem=wps['share'],wps['geogrid'],wrf['domains'],wrf['time_control'],wrf['chem']
    count=dom['max_dom']
    assert count==share['max_dom']==2,'Expected two nests'
    for name in ('e_we','e_sn','i_parent_start','j_parent_start','parent_grid_ratio'):
        assert geo[name]==dom[name],name
    for k in range(count):
        ratio=dom['parent_grid_ratio'][k]
        assert dom['dx'][k]==geo['dx']/ratio
        assert dom['dy'][k]==geo['dy']/ratio
        for endpoint in ('start','end'):
            value=datetime(*[time[f'{endpoint}_{n}'][k] for n in ('year','month','day','hour','minute','second')])
            assert value.strftime('%Y-%m-%d_%H:%M:%S')==share[f'{endpoint}_date'][k]
        if k:
            for axis,n,start in [('x','e_we','i_parent_start'),('y','e_sn','j_parent_start')]:
                assert (dom[n][k]-1)%ratio==0,(k,axis,'nest divisibility')
                assert dom[start][k]+(dom[n][k]-1)//ratio<=dom[n][0]-4,(k,axis,'nest outside parent')
    eta=dom['eta_levels']
    assert len(eta)==dom['e_vert'][0]==dom['e_vert'][1]==36
    assert eta[0]==1 and eta[-1]==0 and np.all(np.diff(eta)<0)
    assert dom['p_top_requested']==5000
    assert chem['chem_opt']==[9,9] and chem['emiss_opt']==[3,3] and chem['emiss_inpt_opt']==[1,1]
    assert time['auxinput5_inname']=='wrfchemi_d<domain>_<date>'
    assert time['frames_per_auxinput5']==[1,1]
    assert time['auxinput5_interval_m']==[60,60]
    off=read_namelist(root/'namelist.input.ARI_off')
    assert off['chem']['aer_ra_feedback']==[0,0]
    off['chem']['aer_ra_feedback']=[1,1]
    assert off==wrf,'ARI off must change only aer_ra_feedback'
    for k,path in enumerate(inputs):
        if k>=count:raise ValueError('Too many wrfinput files')
        with Dataset(path) as nc:
            assert len(nc.dimensions['west_east'])==dom['e_we'][k]-1
            assert len(nc.dimensions['south_north'])==dom['e_sn'][k]-1
            assert len(nc.dimensions['bottom_top'])==dom['e_vert'][k]-1
            assert nc.DX==dom['dx'][k] and nc.DY==dom['dy'][k]
            if all(v in nc.variables for v in ('PH','PHB','HGT')):
                interfaces=(nc['PH'][0]+nc['PHB'][0])/9.81-nc['HGT'][0][None,:,:]
                mass_height=(interfaces[1:]+interfaces[:-1])/2
                low=np.sum(mass_height<1000,axis=0)
                print(f'{path}: minimum mass layers below 1 km={low.min()}')
                assert low.min()>10,'Adjust eta levels to meet the paper below-1-km requirement'
    print('PASS: namelist dates, grids, nesting, vertical coordinates, emissions interface, and ARI pair')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',default=str(Path(__file__).parent))
    p.add_argument('--wrfinput',nargs='*',default=[])
    a=p.parse_args();check(a.case,a.wrfinput)
