"""Prepare the explicit baseline scheme and implement its molar VOC/AGL mapping.

python emission_scheme.py --wrf-dir /case/real_work
python make_mix_wrfchemi.py build --config mix_config.scheme.json
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

TABLE = 'https://acp.copernicus.org/preprints/acp-2018-889/acp-2018-889-supplement.pdf'
# Molar coefficients from Table S1, with three explicitly labelled proxies below.
VOC = {
    'E_ETH': {'ALK1': 1},
    'E_HC3': {'ALK2': 1, 'ALK3': 1.11, 'MEOH': .4},
    'E_HC5': {'ALK4': .97}, 'E_HC8': {'ALK5': 1},
    'E_TOL': {'ARO1': 1}, 'E_XYL': {'ARO2': 1}, 'E_OL2': {'ETHE': 1},
    'E_OLT': {'OLE1': 1, 'MACR': .5, 'MVK': .5, 'IPRD': .5, 'ISOP': .5},
    'E_OLI': {'OLE2': 1, 'TERP': 1}, 'E_CSL': {'CRES': 1, 'PHEN': 1},
    'E_HCHO': {'HCHO': 1},
    'E_ALD': {'CCHO': 1, 'RCHO': 1, 'BALD': 1, 'MACR': .5, 'GLY': 1,
              'MGLY': 1, 'BACL': .5, 'IPRD': .5, 'ISOP': .5},
    'E_KET': {'ACET': .33, 'PRD2': 1.61, 'MEK': 1.61, 'MVK': .5},
    'E_ORA2': {},  # No AACD/PACD fields in this MIX SAPRC99 release.
}
EXCLUDED = {'CH4': 'No CH4 tracer in this chem_opt=9 package; no anthropogenic increment.',
            'NROG': 'Unreactive organic group has no target tracer.',
            'NVOL': 'No gas surrogate; not added to existing PM/OC to avoid double counting.'}
HOURS = {'power': [.90,.95,1.10,1.10,1.05,.90],
         'industry': [.60,.80,1.20,1.20,1.10,.80],
         'residential': [.50,.90,1.20,1.,1.50,.90],
         'transportation': [.30,.90,1.20,1.,1.50,.70],
         'agriculture': [.50,.70,1.20,1.40,1.10,.70]}
NOTES = [
    'Baseline experiment, not the paper authors\' complete emissions recipe.',
    'SAPRC99 -> RADM2 molar mapping: '+TABLE+' Table S1; then existing WRF CBMZ conversion.',
    'Additional proxies (not Table S1): PHEN->CSL; TERP->OLI; ISOP->0.5 ALD+0.5 OLT. These lose explicit terpene/isoprene chemistry and are not proven carbon/reactivity conserving.',
    'CH4/NROG/NVOL excluded with amounts reported. ORA2=0 because this input has no explicit organic-acid groups; not a claim of zero real emissions.',
    'Temporal profiles are user-case assumptions: 4-hour local UTC+8 blocks; weekday factors=1; full UTC-calendar month normalization.',
    'Fixed effective AGL injection bands based on initial PH/PHB/HGT, uniform emission per metre within each band; no dynamic plume rise.',
    '2010 inventory used with 2013 meteorology without automatic interannual scaling.',
]


def interfaces(path):
    with Dataset(path) as nc:
        def get(name):
            a = np.ma.asarray(nc[name][0], dtype=float)
            if np.ma.is_masked(a) or not np.isfinite(a).all():
                raise ValueError(f'{path}: invalid {name}')
            return np.asarray(a)
        h = (get('PH')+get('PHB'))/9.81-get('HGT')[None]
    check_heights(h)
    return h


def check_heights(h):
    if h is None or h.ndim != 3 or not np.isfinite(h).all() or np.any(np.diff(h,axis=0)<=0):
        raise ValueError('Need finite, increasing PH/PHB/HGT AGL interfaces')
    if not np.allclose(h[0], 0, atol=.1):
        raise ValueError('Bottom interface must be at ground level')


def height_weights(h, sector, kemit):
    check_heights(h)
    if not 1 <= kemit < h.shape[0]:
        raise ValueError('kemit outside available model layers')
    w = np.zeros((kemit,)+h.shape[1:])
    if sector.get('surface_injection'):
        w[0] = 1
        return w
    bands = sector['height_bands_m_agl']
    if not np.isclose(sum(b[2] for b in bands),1):
        raise ValueError('Height band fractions must sum to 1')
    for low, high, fraction in bands:
        if not 0 <= low < high or not np.isfinite([low,high,fraction]).all() or fraction < 0:
            raise ValueError('Invalid AGL band')
        if np.any(h[kemit] < high):
            raise ValueError(f'kemit={kemit} does not contain the {high} m injection band everywhere')
        overlap = np.maximum(0, np.minimum(h[1:kemit+1],high)-np.maximum(h[:kemit],low))
        w += fraction*overlap/(high-low)
    if not np.allclose(w.sum(axis=0),1,atol=1e-8):
        raise ValueError('Vertical emissions are not conserved')
    return w


def add_speciated_voc(cfg, name, sector, grid, year, month, outputs, cache):
    import make_mix_wrfchemi as m
    if sector['sources']['NMVOC'].get('zero_with_reason'):
        return [dict(sector=name, voc_note='Original MIX agriculture has no NMVOC fields.')]
    sector_code = {'transportation':'TRANSPORT'}.get(name,name.upper())
    required = {s for terms in VOC.values() for s in terms} | set(EXCLUDED)
    data, reports = {}, []
    for species in sorted(required):
        path = Path(cfg['saprc99_dir'])/f'MICS_Asia_SAPRC99_{species}_{cfg["inventory_year"]}_0.25x0.25.nc'
        # Reuse the checked rectilinear reader without a molecular-weight guess.
        # Its kg/cell/month identity factor is purely numeric; quantity is relabelled below.
        spec = dict(file=str(path),variable=f'SAPRC99_{species}_{sector_code}',lat='lat',lon='lon',
                    isel={'time':month-1},expected_units='Mmol/month',conversion_units='kg/cell/month')
        lon,lat,mmol,info = m.source_month(spec,dict(inventory_year=cfg['inventory_year'],month=month,year=year))
        key = hashlib.sha256(lon.tobytes()+lat.tobytes()).hexdigest()
        if key not in cache:
            cache[key] = m.conservative_weights(lon,lat,grid['polygons'])
        mol = (cache[key] @ (mmol*1e6).ravel()).reshape(grid['lat'].shape)
        info.update(sector=name, source=species, quantity='mol/cell/month',
                    target_month_total_mol=float(mol.sum()), excluded_reason=EXCLUDED.get(species))
        reports.append(info)
        data[species] = mol
    for target, terms in VOC.items():
        outputs[target] = sum((factor*data[s] for s,factor in terms.items()),
                              np.zeros(grid['lat'].shape))
    return reports


def prepare(wrf_dir, case, mix_dir=None):
    from prepare_runtime_namelists import set_integers
    from check_case import read_namelist
    case,wrf_dir = Path(case).resolve(),Path(wrf_dir).resolve()
    cfg = json.loads((case/'mix_config.json').read_text(encoding='utf-8-sig'))
    if mix_dir is None:
        options=[p/'raw_mix_v1.1'/str(cfg['inventory_year']) for p in (case.parent,case.parent.parent)]
        options=[p for p in options if (p/f'MICS_Asia_SAPRC99_ALK1_{cfg["inventory_year"]}_0.25x0.25.nc').is_file()]
        if len(options)>1:raise ValueError('Multiple MIX directories; specify --mix-dir')
        mix_dir=options[0] if options else None
    if mix_dir is not None:
        mix_dir=Path(mix_dir).resolve()
        if not mix_dir.is_dir():raise FileNotFoundError(mix_dir)
        for sector in cfg['sectors'].values():
            for spec in sector['sources'].values():
                if 'file' in spec:spec['file']=str(mix_dir/Path(spec['file']).name)
    heights = []
    for domain in cfg['domains']:
        path = wrf_dir/f'wrfinput_d{domain["id"]:02d}'
        domain['wrfinput'] = str(path)
        h = interfaces(path)
        if np.any(h[-1] < 1000):
            raise ValueError('Model top does not contain 1000 m AGL')
        heights.append(h)
    # Number of layers required to enclose 1000m at every grid point of both domains.
    kemit = max(int(np.max(np.sum(h[1:] < 1000,axis=0)))+1 for h in heights)
    cfg.update(kemit=kemit,voc_mode='saprc99_molar',vertical_mode='height_agl',
               saprc99_dir=str(mix_dir) if mix_dir is not None else '../raw_mix_v1.1/2010',scheme_notes=NOTES,
               output_dir='wrfchemi_201305_scheme')
    cfg.pop('voc_profile_csv',None)
    for name,sector in cfg['sectors'].items():
        sector['hourly_factors'] = [v for v in HOURS[name] for _ in range(4)]
        sector['weekday_factors'] = [1]*7
        sector['utc_offset_hours'] = 8
        sector['profile_note'] = 'Explicit baseline assumptions; see scheme_notes'
        # Compatibility with legacy configuration validation. Not used for injection.
        sector['vertical_weights'] = [1]+[0]*(kemit-1)
        if name == 'power':
            sector['height_bands_m_agl'] = [[100,300,.2],[300,600,.5],[600,1000,.3]]
        elif name == 'industry':
            sector['height_bands_m_agl'] = [[0,100,.6],[100,300,.3],[300,600,.1]]
        else:
            sector['surface_injection'] = True
        for h in heights:
            height_weights(h,sector,kemit)
    cfg['zero_outputs']['E_ISO'] = 'Anthropogenic ISOP is approximated through ALD/OLT in this RADM2 input; MEGAN remains separate.'
    outputs = {case/'mix_config.scheme.json':json.dumps(cfg,ensure_ascii=False,indent=2)+'\n'}
    # Preserve actual runtime dimensions and MOZBC settings. Write separate files.
    candidates = [wrf_dir/'namelist.input'] + sorted(wrf_dir.glob('namelist.input.MOZBC.ARI_*'))
    for path in candidates:
        nml = read_namelist(path)
        if nml['chem']['chem_opt'] != [9,9] or nml['chem']['emiss_opt'] != [3,3] or nml['chem']['emiss_inpt_opt'] != [1,1]:
            raise ValueError(f'{path}: expected chem_opt=9 / emiss_opt=3 / emiss_inpt_opt=1 in both domains')
        outputs[case/(path.name+'.emissions')] = set_integers(path.read_text(encoding='utf-8-sig'),'chem','kemit',[kemit])
    for path in outputs:
        if path.exists(): raise FileExistsError(f'Refusing to overwrite {path}')
    for path,text in outputs.items():
        with path.open('x',encoding='utf-8',newline='\n') as stream: stream.write(text)
        print('Wrote',path)
    print('kemit =',kemit,'; profiles fit both initial grids. Actual emissions have NOT yet been built.')
    return cfg


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wrf-dir',required=True,type=Path)
    parser.add_argument('--case',default=Path(__file__).resolve().parent,type=Path)
    parser.add_argument('--mix-dir',type=Path,help='Original MIX year directory, containing mass and SAPRC99 nc files')
    args = parser.parse_args()
    prepare(args.wrf_dir,args.case,args.mix_dir)
