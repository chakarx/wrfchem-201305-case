"""Prepare two MOZBC controls for the legacy MOZART file and chem_opt=9.

Run in the FINAL real.exe directory, with mozart_case_0001.nc linked there.
Reads model/data files only; writes controls, WRF-run namelists and an audit.
Reference aerosol recipe is NCAR's legacy example, NOT a paper-specific mapping.
"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re

import numpy as np
from netCDF4 import Dataset

from check_case import read_namelist
from prepare_runtime_namelists import _clean, _value_span, met_filename, set_integers
from retime_mozart_for_case import checked_values, times_from_date

STAMP = '%Y-%m-%d_%H:%M:%S'
SOURCE_NAME = 'mozart_case_0001.nc'
REFERENCES = [
    'https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/CBMZ-MOSAIC_8bins.inp',
    'https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/CBMZ-MOSAIC_4bins.inp',
]
GASES = dict(
    co='CO', o3='O3', so2='SO2', no='NO', no2='NO2', h2o2='H2O2',
    no3='NO3', n2o5='N2O5', hno3='HNO3', nh3='NH3', hcho='CH2O',
    pan='PAN', tol='.75*TOLUENE', hno4='HO2NO2', eth='C2H6',
    par='C3H6+3*C3H8+2*BIGENE+5*BIGALK', ch3oh='CH3OH',
    ald='GLYALD+CH3CHO', ket='MEK+CH3COCH3+HYAC', mgly='CH3COCHO',
    ol2='C2H4', olt='.5*BIGENE', oli='.5*BIGENE', xyl='.25*TOLUENE',
    csl='CRESOL', open='BIGALD', isoprd='MVK+MACR+HYDRALD',
    onit='ONIT+ONITR', ora2='CH3COOH', op1='CH3OOH', op2='C2H5OOH',
    ch3o2='CH3O2', c2h5oh='C2H5OH', iso='ISOP', ho='OH', ho2='HO2',
)
# Active chemistry package copied from this WRF 3.9.1 Registry, not all
# globally declared Registry species (many belong to other mechanisms).
ACTIVE_GASES = ('so2 sulf no2 no o3 hno3 h2o2 ald hcho op1 op2 ora1 ora2 nh3 '
                'n2o5 no3 pan eth co ol2 olt oli tol xyl hono hno4 ket mgly onit '
                'csl iso ho ho2 hcl ch3o2 ethp ch3oh c2h5oh par to2 cro open '
                'op3 c2o3 ro2 ano2 nap xo2 xpar isoprd isopp isopn isopo2').split()
ACTIVE = set(ACTIVE_GASES)
for _i in range(1, 5):
    ACTIVE.update(f'{s}_a{_i:02d}' for s in
                  'so4 no3 cl nh4 na oin oc bc hysw water num'.split())
    ACTIVE.update(f'{s}_cw{_i:02d}' for s in
                  'so4 no3 cl nh4 na oin oc bc num'.split())


def mapping():
    """Keep NCAR legacy aerosol factors explicit, and simplify its syntax.

    Repeated SA1 terms are combined; products such as 0.5*3.93e17 are
    evaluated beforehand: MOZBC accepts only ONE coefficient per source term.
    Number factors are pulled outside the sum to fit old 164-character maps.
    """
    result = [f'{target}->{source};1e6' for target, source in GASES.items()]
    oc = [('0.0960024', '1.152026'), ('.254356', '3.05226'),
          ('.0600723', '.720865'), ('.00104', '.012481')]
    bc = ['.65325', '.25458', '.0040521', '.0000016794']
    inorganic = ['.024433', '.47111', '.47857', '.025727']
    na = ['.2*SA1', '.4*SA1', '.2*SA1+.8*SA2', '.8*SA3']
    cl = ['.3*SA1', '.6*SA1', '.3*SA1+1.2*SA2', '1.2*SA3']
    dust = ['.5*[DUST1]', '.5*[DUST1]+.24*[DUST2]',
            '.76*[DUST2]+[DUST3]', '[DUST4]']
    # Coefficients below have already been divided by 1e15.
    number = [
        '173*OC1+173*OC2+173*SOA+564*CB1+564*CB2+76.7*SO4+63.9*NH4NO3+14.4*NH4+805*SA1+196.5*[DUST1]',
        '17.1*OC1+17.1*OC2+17.1*SOA+9.91*CB1+9.91*CB2+60.6*SO4+50.5*NH4NO3+11.4*NH4+72.6*SA1+5.85*[DUST1]+2.808*[DUST2]',
        '.113*OC1+.113*OC2+.113*SOA+.0018*CB1+.0018*CB2+2.44*SO4+2.03*NH4NO3+.469*NH4+.412*SA1+1.64*SA2+.07258*[DUST2]+.0955*[DUST3]',
        '.0000409*OC1+.0000409*OC2+.0000409*SOA+.0000000342*CB1+.0000000342*CB2+.00325*SO4+.00271*NH4NO3+.000612*NH4+.076*SA3+.00149*[DUST4]',
    ]
    for i in range(4):
        suffix = f'a{i+1:02d}'
        c, s = oc[i]
        result += [f'oc_{suffix}->{c}*OC1+{c}*OC2+{s}*SOA;1e9',
                   f'bc_{suffix}->{bc[i]}*CB1+{bc[i]}*CB2;.413793103e9']
        for target, source, factor in [('so4', 'SO4', '3.31423e9'),
                                       ('no3', 'NH4NO3', '2.76186e9'),
                                       ('nh4', 'NH4', '6.22876e8')]:
            result.append(f'{target}_{suffix}->{inorganic[i]}*{source};{factor}')
        for target, source in [('na', na[i]), ('cl', cl[i]),
                               ('oin', dust[i]), ('num', number[i])]:
            result.append(f'{target}_{suffix}->{source};'+('1e15' if target == 'num' else '1e9'))
    if len({entry.split('->')[0] for entry in result}) != len(result):
        raise ValueError('Duplicate mapping targets')
    if any(len(entry) > 164 for entry in result):
        raise ValueError('Mapping exceeds old MOZBC 164-character limit')
    return result


def decode(entry):
    target, expr = entry.split('->')
    expr, factor = expr.split(';')
    terms = []
    for term in expr.split('+'):
        pieces = term.split('*')
        if len(pieces) > 2:
            raise ValueError(f'MOZBC permits only one coefficient: {term}')
        coefficient = Decimal(pieces[0]) if len(pieces) == 2 else Decimal(1)
        name = pieces[-1]
        source = name[1:-1] if name.startswith('[') and name.endswith(']') else name+'_VMR_inst'
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', source):
            raise ValueError(f'Invalid source name: {source}')
        terms.append((source, coefficient))
    return target, terms, Decimal(factor)


def control(domain):
    header = ("! Legacy MOZART -> WRF 3.9.1 chem_opt=9; see MOZBC_QUICKSTART.md\n"
              "! Run from the final real.exe directory. Unmapped fields are retained.\n"
              "&control\n"
              f" domain = {domain},\n do_ic = .true.,\n"
              f" do_bc = {'.true.' if domain == 1 else '.false.'},\n"
              " dir_wrf = './',\n dir_moz = './',\n"
              f" fn_moz = '{SOURCE_NAME}',\n"
              " moz_var_suffix = '_VMR_inst',\n def_missing_var = .false.,\n"
              " spc_map =\n")
    return header + ''.join(f"  '{entry}',\n" for entry in mapping()) + '/\n'


def times(nc):
    array = np.ma.asarray(nc['Times'][:])
    if np.ma.is_masked(array):
        raise ValueError(f'{nc.filepath()}: missing Times')
    return [datetime.strptime(b''.join(row).decode('ascii').strip('\x00 '), STAMP)
            for row in np.asarray(array)]


def case_dates(nml, prefix, domain=0):
    return datetime(*(int(nml['time_control'][f'{prefix}_{key}'][domain])
                      for key in ('year', 'month', 'day', 'hour', 'minute', 'second')))


def preflight(work):
    work = Path(work)
    nml = read_namelist(work/'namelist.input')
    if nml['domains']['max_dom'] != 2 or nml['chem']['chem_opt'] != [9, 9]:
        raise ValueError('This mapping requires exactly two domains with chem_opt=9,9')
    if nml['bdy_control']['nested'] != [False, True]:
        raise ValueError('Expected outer specified boundaries and nested d02')
    start, end = case_dates(nml, 'start'), case_dates(nml, 'end')
    if (start, end) != (datetime(2013, 5, 1), datetime(2013, 5, 3)):
        raise ValueError('Expected this case: 2013-05-01 00 UTC to 2013-05-03 00 UTC')
    if any(case_dates(nml, key, 1) != value for key, value in [('start', start), ('end', end)]):
        raise ValueError('Both domains must have the same case dates')
    entries = [decode(entry) for entry in mapping()]
    targets = {target for target, _, _ in entries}
    if targets - ACTIVE:
        raise ValueError(f'Inactive chem_opt=9 targets: {sorted(targets-ACTIVE)}')
    required_source = {name for _, terms, _ in entries for name, _ in terms}
    with Dataset(work/SOURCE_NAME) as source:
        required = required_source | {'PS', 'P0', 'hyam', 'hybm', 'lev', 'lat', 'lon', 'date', 'datesec'}
        if required-set(source.variables):
            raise ValueError(f'MOZART missing variables: {sorted(required-set(source.variables))}')
        dates = times_from_date(checked_values(source['date']), checked_values(source['datesec']))
        if len(set(dates)) != len(dates) or dates != sorted(dates):
            raise ValueError('MOZART time records must be unique and increasing')
        lat, lon = checked_values(source['lat']), checked_values(source['lon'])
        if lat.ndim != 1 or lon.ndim != 1 or np.any(np.diff(lat) <= 0) or np.any(np.diff(lon) <= 0):
            raise ValueError('Legacy MOZBC requires increasing, non-wrapping 1D lat/lon here')
        if float(checked_values(source['P0']).item()) != 100000.:
            raise ValueError('Legacy MOZBC assumes hybrid reference P0=100000 Pa')
        if str(getattr(source['PS'], 'units', '')).lower() not in ('pa', 'pascal', 'pascals'):
            raise ValueError('MOZART PS units must be Pa')
        for name in required_source:
            var = source[name]
            if var.dimensions != ('time', 'lev', 'lat', 'lon'):
                raise ValueError(f'{name}: expected (time,lev,lat,lon)')
            if str(getattr(var, 'units', '')).lower().replace(' ', '') not in ('vmr', 'mol/mol', 'molmol-1'):
                raise ValueError(f'{name}: expected VMR mol/mol, got {getattr(var, "units", None)}')
        source_year = getattr(source, 'retime_source_year', None)
        report = dict(source_file=str((work/SOURCE_NAME).resolve()),
                      retime_source_year=int(source_year) if source_year is not None else None,
                      references=REFERENCES, mapped=sorted(targets),
                      unmapped_retained=sorted(ACTIVE-targets), domains={})
        report['limitations'] = [
            'Retiming changes dates, not concentrations; this is not actual 2013 chemistry.',
            'Gas lumping and aerosol sizes use NCAR examples, not a verified paper-specific recipe.',
            'Legacy NH4NO3 factor is 2.76186e9 (~80/28.97*1e9); this is not the pure nitrate ion factor (~62/28.97*1e9).',
            'NH4, NH4NO3 pseudo-species definitions, aerosol pseudo-molecular weights and number conversions need source-model documentation before quantitative inorganic-salt analysis.',
            'Unmapped gases, aerosol water and cloud-borne aerosol fields are not overwritten; their real.exe values remain in IC/BC.',
        ]
        with Dataset(work/'wrfbdy_d01') as bdy:
            boundary = times(bdy)
            if len(boundary) < 2 or boundary[0] != start:
                raise ValueError('wrfbdy must start at the case start and contain at least two records')
            step = boundary[1]-boundary[0]
            if step != timedelta(seconds=nml['time_control']['interval_seconds']) or any(
                    b-a != step for a, b in zip(boundary, boundary[1:])):
                raise ValueError('wrfbdy intervals do not match namelist interval_seconds')
            # MOZBC appends one time after wrfbdy Times to compute its last tendency.
            boundary.append(boundary[-1]+step)
            if boundary[-1] < end:
                raise ValueError('wrfbdy intervals do not cover the run end')
            required_bdy = {f'{target}_{suffix}' for target in targets
                            for suffix in ('BXS', 'BXE', 'BYS', 'BYE', 'BTXS', 'BTXE', 'BTYS', 'BTYE')}
            if required_bdy-set(bdy.variables):
                raise ValueError(f'wrfbdy missing chemistry fields: {sorted(required_bdy-set(bdy.variables))[:12]}')
        for domain in (1, 2):
            needed_times = boundary if domain == 1 else [start]
            missing = sorted(set(needed_times)-set(dates))
            if missing:
                raise ValueError('MOZART missing exact UTC time(s), including the final tendency endpoint: '+
                                 ', '.join(value.strftime(STAMP) for value in missing))
            with Dataset(work/f'wrfinput_d{domain:02d}') as wrf:
                if times(wrf) != [start]:
                    raise ValueError(f'd{domain:02d}: wrfinput start mismatch')
                if targets-set(wrf.variables):
                    raise ValueError(f'd{domain:02d}: missing target species {sorted(targets-set(wrf.variables))}')
                for target in targets:
                    expected = '#/kg-dryair' if target.startswith('num_') else (
                        'ug/kg-dryair' if '_a0' in target else 'ppmv')
                    if getattr(wrf[target], 'units', '').strip() != expected:
                        raise ValueError(f'{target}: expected WRF units {expected}')
                y, x = checked_values(wrf['XLAT']), checked_values(wrf['XLONG']) % 360
                if y.min() < lat.min() or y.max() >= lat.max() or x.min() < lon.min() or x.max() >= lon.max():
                    raise ValueError(f'd{domain:02d}: source subset does not bracket the entire WRF domain')
                if int(getattr(wrf, 'HYBRID_OPT', 0)) != 0:
                    raise ValueError('This preparation targets eta coordinates, not a hybrid_opt=2 grid')
                report['domains'][str(domain)] = dict(
                    lat_range=[float(y.min()), float(y.max())],
                    lon_range=[float(x.min()), float(x.max())],
                    times=[value.strftime(STAMP) for value in needed_times])
            for stamp in needed_times:
                path = work/met_filename(domain, stamp)
                with Dataset(path) as met:
                    if 'PSFC' not in met.variables or times(met) != [stamp]:
                        raise ValueError(f'{path.name}: PSFC absent or time mismatch')
    return report


def set_logicals(text, section, key, values):
    first, last = _value_span(text, section, key)
    clean = _clean(text[first:last])
    begin = re.search(r'\S', clean).start()
    stop = len(clean.rstrip())
    value = ', '.join('.true.' if item else '.false.' for item in values)+','
    return text[:first+begin]+value+text[first+stop:]


def prepare(work, templates_only=False):
    work = Path(work)
    outputs = {f'mozbc_d{d:02d}.inp': control(d) for d in (1, 2)}
    if not templates_only:
        report = preflight(work)
        text = (work/'namelist.input').read_text(encoding='utf-8-sig')
        text = set_integers(text, 'chem', 'chem_in_opt', [1, 1])
        text = set_logicals(text, 'chem', 'have_bcs_chem', [True, False])
        for label, ari in [('ARI_on', 1), ('ARI_off', 0)]:
            outputs[f'namelist.input.MOZBC.{label}'] = set_integers(text, 'chem', 'aer_ra_feedback', [ari, ari])
        outputs['mozbc_preflight.json'] = json.dumps(report, ensure_ascii=False, indent=2)+'\n'
    for name in outputs:
        if (work/name).exists():
            raise FileExistsError(f'Refusing to overwrite {work/name}; use a fresh work directory or retain/remove the prior generated file explicitly')
    work.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        with (work/name).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    return list(outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=Path('.'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--templates-only', action='store_true', help='Write controls without checking real data')
    group.add_argument('--check-only', action='store_true', help='Read-only checks; do not generate files')
    args = parser.parse_args()
    if args.check_only:
        print(json.dumps(preflight(args.work_dir), ensure_ascii=False, indent=2))
    else:
        for name in prepare(args.work_dir, args.templates_only):
            print('Wrote', args.work_dir/name)
        print('MOZBC has NOT been run. See MOZBC_QUICKSTART.md before editing the model files.')


if __name__ == '__main__':
    main()
