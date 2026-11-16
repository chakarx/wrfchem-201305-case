import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from netCDF4 import Dataset

import emission_scheme as s
import make_mix_wrfchemi as m
from check_case import read_namelist
import test_make_mix_wrfchemi as legacy
CASE=legacy.CASE


class TestScheme(unittest.TestCase):
    def test_available_real_mix_headers_and_molar_inputs(self):
        directory=CASE.parent/'raw_mix_v1.1'/'2010'
        if not directory.exists():self.skipTest('Original inventory not installed')
        with tempfile.TemporaryDirectory() as tmp:
            cfg,_=legacy.TestEmissions().fixture(Path(tmp))
            cfg['saprc99_dir']=str(directory)
            grid=m.wrf_grid(Path(tmp)/'wrfinput_d01')
            output={}
            report=s.add_speciated_voc(cfg,'power',cfg['sectors']['power'],grid,2013,5,output,{})
            self.assertEqual(len(report),31)
            self.assertTrue(all(np.isfinite(v).all() and (v>=0).all() for v in output.values()))
            self.assertGreater(output['E_ETH'].sum(),0)

    def test_height_overlap_conserves_every_cell(self):
        h=np.array([0,50,200,400,800,1200.])[:,None,None]*np.ones((1,2,2))
        sector={'height_bands_m_agl':[[100,300,.2],[300,600,.5],[600,1000,.3]]}
        w=s.height_weights(h,sector,5)
        np.testing.assert_allclose(w.sum(axis=0),1)
        np.testing.assert_allclose(w[:,0,0],[0,.1,.1+1/6,1/3+.15,.15])
        with self.assertRaisesRegex(ValueError,'does not contain'):
            s.height_weights(h,sector,4)
        with self.assertRaises(ValueError):
            s.height_weights(h[::-1],sector,5)

    def test_prepare_build_units_and_updated_namelist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); cfg,_=legacy.TestEmissions().fixture(root)
            cfg['saprc99_dir']=str(root/'saprc')
            (root/'mix_config.json').write_text(json.dumps(cfg))
            shutil.copy(CASE/'namelist.input',root/'namelist.input')
            with Dataset(root/'wrfinput_d01','a') as nc:
                nc.createDimension('bottom_top_stag',36)
                z=np.r_[0,50,150,350,700,1100,np.arange(6,36)*1000.]
                nc.createVariable('HGT','f8',('Time','south_north','west_east'))[:]=500
                for name,values in [('PH',0),('PHB',(z[:,None,None]+500)*9.81)]:
                    nc.createVariable(name,'f8',('Time','bottom_top_stag','south_north','west_east'))[0]=values
            result=s.prepare(root,root)
            self.assertEqual(result['kemit'],5)
            self.assertEqual(read_namelist(root/'namelist.input.emissions')['chem']['kemit'],5)
            # Synthetic molar inventory, deliberately unrelated to total NMVOC mass.
            directory=root/'saprc';directory.mkdir()
            species={v for terms in s.VOC.values() for v in terms}|set(s.EXCLUDED)
            for species_name in species:
                path=directory/f'MICS_Asia_SAPRC99_{species_name}_2010_0.25x0.25.nc'
                with Dataset(path,'w') as nc:
                    for dim,size in [('time',12),('lat',2),('lon',2)]:nc.createDimension(dim,size)
                    nc.createVariable('lat','f8',('lat',))[:]=[34.75,35.25]
                    nc.createVariable('lon','f8',('lon',))[:]=[104.75,105.25]
                    v=nc.createVariable(f'SAPRC99_{species_name}_POWER','f8',('time','lat','lon'))
                    v.units=' Mmol/month';v[:]=2 if species_name=='ALK1' else 1
            result['saprc99_dir']=str(directory)
            # Keep the test output isolated and source paths from its fixture.
            path=root/'mix_config.scheme.json';path.write_text(json.dumps(result))
            m.build(path)
            grid=m.wrf_grid(root/'wrfinput_d01')
            files=sorted((root/'wrfchemi_201305_scheme').glob('wrfchemi*'))
            self.assertEqual(len(files),2)
            temporal=m.hourly_fractions(2013,5,result['sectors']['power'])[0]
            with Dataset(files[0]) as nc:
                eth=nc['E_ETH'][0].sum(axis=0)
                hc5=nc['E_HC5'][0].sum(axis=0)
                np.testing.assert_allclose(hc5/eth,.97/2,rtol=2e-7)
                np.testing.assert_allclose(nc['E_ETH'][0,0],0)
                # Mmol -> mol (1e6), and m^-2 -> km^-2 (1e6), independently.
                weights=m.conservative_weights(np.array([104.75,105.25]),np.array([34.75,35.25]),grid['polygons'])
                expected=(weights@np.full(4,2e6)).reshape(2,2)/grid['area']*1e6*temporal
                np.testing.assert_allclose(eth,expected,rtol=2e-7)
                self.assertEqual(nc['E_ETH'].shape,(1,5,2,2))
            report=json.loads((files[0].parent/'processing_d01_201305.json').read_text())
            exclusions=[row for row in report['sources'] if row.get('excluded_reason')]
            self.assertEqual(len(exclusions),3)
            self.assertTrue(all(row['target_month_total_mol']>0 for row in exclusions))
            with self.assertRaises(FileExistsError):s.prepare(root,root)


if __name__=='__main__':unittest.main()
