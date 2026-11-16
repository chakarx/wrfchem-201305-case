"""Small synthetic cases test conservation, calendars, units and the WRF interface."""
import calendar
import copy
import csv
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from netCDF4 import Dataset
from pyproj import CRS, Transformer
from shapely.geometry import box
import make_mix_wrfchemi as m
from check_case import check

CASE=Path(__file__).resolve().parent


class TestEmissions(unittest.TestCase):
    def test_area_conservation(self):
        lon=np.array([104.75,105.25]);lat=np.array([34.75,35.25])
        x,_=m.TO_AREA.transform(m.edges(lon),np.zeros(3))
        _,y=m.TO_AREA.transform(np.zeros(3),m.edges(lat))
        targets=[box(x[0],y[0],x[1],y[2]),box(x[1],y[0],x[2],y[1]),box(x[1],y[1],x[2],y[2])]
        weights=m.conservative_weights(lon,lat,targets)
        np.testing.assert_allclose(np.asarray(weights.sum(axis=0)).ravel(),1,rtol=0,atol=1e-12)
        self.assertAlmostEqual((weights@np.array([1.,2.,3.,4.])).sum(),10)
        with self.assertRaisesRegex(ValueError,'cover'):
            m.conservative_weights(lon,lat,[box(x[0]-1e4,y[0],x[2],y[2])])

    def test_calendar_and_timezone(self):
        factors=dict(hourly_factors=list(range(1,25)),weekday_factors=[1,2,3,4,5,6,7],utc_offset_hours=8)
        for year,month in [(2013,5),(2020,2),(2019,2)]:
            result=m.hourly_fractions(year,month,factors)
            self.assertEqual(len(result),calendar.monthrange(year,month)[1]*24)
            self.assertAlmostEqual(result.sum(),1)
            # May 1 UTC 00 is local 08:00; compare with next UTC hour, same weekday.
            self.assertAlmostEqual(result[1]/result[0],10/9)
        np.testing.assert_allclose(m.hourly_fractions(2013,5,{}),1/(31*24))

    def fixture(self,root):
        cfg=json.loads((CASE/'mix_config.json').read_text(encoding='utf-8'))
        cfg['interface_csv']=str(CASE/'emission_interface.csv')
        cfg['voc_profile_csv']=str(root/'voc.csv')
        cfg['output_dir']=str(root/'output')
        cfg['domains']=[dict(id=1,wrfinput=str(root/'wrfinput_d01'))]
        cfg['end']='2013-05-01_01:00:00'
        cfg['sectors']={'power':copy.deepcopy(cfg['sectors']['power'])}
        cfg['sectors']['power']['vertical_weights']=[.2,.8,0,0]
        with (root/'voc.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['sector','output','mass_fraction','molecular_weight_g_mol'])
            w.writerow(['power','E_ETH',1,30.07])
        totals={'SO2':3,'NOx':4,'CO':5,'NH3':6,'NMVOC':7,'PM25':10,'PM10':15,'BC':1,'OC':2}
        with Dataset(root/'source.nc','w') as nc:
            nc.createDimension('lat',2);nc.createDimension('lon',2)
            nc.createVariable('lat','f8',('lat',))[:]=[34.75,35.25]
            nc.createVariable('lon','f8',('lon',))[:]=[104.75,105.25]
            for n,total in totals.items():
                v=nc.createVariable(n,'f8',('lat','lon'));v[:]=total;v.units='kg/month'
        for name,spec in cfg['sectors']['power']['sources'].items():
            spec.update(file=str(root/'source.nc'),variable=name,isel={},expected_units='kg/month',
                        units_attribute='units',conversion_units='kg/cell/month')
        crs=CRS.from_proj4(f'+proj=lcc +lat_1=25 +lat_2=40 +lat_0=35 +lon_0=105 +R={m.RADIUS} +units=m')
        inverse=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True)
        x,y=np.meshgrid([-10000.,10000.],[-10000.,10000.]);lon,lat=inverse.transform(x,y)
        with Dataset(root/'wrfinput_d01','w') as nc:
            for n,s in [('Time',1),('south_north',2),('west_east',2),('bottom_top',35)]:nc.createDimension(n,s)
            for n,v in [('XLAT',lat),('XLONG',lon)]:nc.createVariable(n,'f8',('Time','south_north','west_east'))[0]=v
            for n,v in dict(MAP_PROJ=1,TRUELAT1=25.,TRUELAT2=40.,CEN_LAT=35.,STAND_LON=105.,DX=20000.,DY=20000.).items():nc.setncattr(n,v)
        config=root/'config.json';config.write_text(json.dumps(cfg),encoding='utf-8')
        return cfg,config

    def test_full_netcdf_units_vertical_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,config=self.fixture(root)
            m.build(config)
            files=sorted((root/'output').glob('wrfchemi*'));self.assertEqual(len(files),2)
            grid=m.wrf_grid(root/'wrfinput_d01')
            with (CASE/'emission_interface.csv').open(encoding='utf-8') as f:fields={r['name']:r for r in csv.DictReader(f)}
            cfg['sectors']['power']['sources']={k:dict(v) for k,v in cfg['sectors']['power']['sources'].items()}
            mapped,_=m.map_month(cfg,grid,2013,5,fields,{'power':[('E_ETH',1,30.07)]})
            with Dataset(files[0]) as nc:
                self.assertEqual(nc.data_model,'NETCDF3_CLASSIC')
                self.assertEqual(nc['E_CO'].shape,(1,4,2,2))
                self.assertEqual(set(nc.variables),set(fields)|{'Times','XLAT','XLONG'})
                self.assertEqual(b''.join(nc['Times'][0]).decode(),'2013-05-01_00:00:00')
                gas=nc['E_CO'][0].sum(axis=0)*grid['area']/1e6*(31*24)
                particle=nc['E_ECJ'][0].sum(axis=0)*grid['area']*3600*(31*24)
                np.testing.assert_allclose(gas,mapped['power']['E_CO'],rtol=2e-7)
                np.testing.assert_allclose(particle,mapped['power']['E_ECJ'],rtol=2e-7)
                np.testing.assert_allclose(nc['E_CO'][0,1],nc['E_CO'][0,0]*4,rtol=1e-7)
                self.assertTrue(np.all(nc['E_NO2'][:]==0))
            with self.assertRaises(FileExistsError):m.build(config)

    def test_source_flux_uses_inventory_calendar_and_checks_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,_=self.fixture(root)
            spec=cfg['sectors']['power']['sources']['CO'].copy()
            spec.update(conversion_units='kg/m2/s')
            context=dict(inventory_year=2020,year=2013,month=2,month_index=1)
            lon,lat,totals,_=m.source_month(spec,context)
            x,_=m.TO_AREA.transform(m.edges(lon),np.zeros(3));_,y=m.TO_AREA.transform(np.zeros(3),m.edges(lat))
            expected=np.diff(y)[:,None]*np.diff(x)[None,:]*5*29*86400
            np.testing.assert_allclose(totals,expected)
            spec['expected_units']='wrong'
            with self.assertRaisesRegex(ValueError,'units'):m.source_month(spec,context)

    def test_rejects_inconsistent_pm_and_empty_voc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,config=self.fixture(root)
            with Dataset(root/'source.nc','a') as nc:nc['BC'][:]=100
            with self.assertRaisesRegex(ValueError,'negative mapped'):m.build(config)
            with self.assertRaises(ValueError):m.load_voc(CASE/'voc_profile_TO_FILL.csv',cfg['sectors'])

    def test_case_namelists(self):
        check(CASE)

    def test_explicitly_absent_nmvoc_needs_no_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,_=self.fixture(root)
            original=json.loads((CASE/'mix_config.json').read_text(encoding='utf-8'))
            cfg['sectors']['agriculture']=copy.deepcopy(original['sectors']['agriculture'])
            profiles=m.load_voc(root/'voc.csv',cfg['sectors'])
            self.assertEqual(profiles['agriculture'],[])
            self.assertEqual(len(profiles['power']),1)
            # A genuine or unexplained NMVOC source still requires a verified profile.
            cfg['sectors']['agriculture']['sources']['NMVOC']={'file':'some_real_source.nc'}
            with self.assertRaisesRegex(ValueError,'agriculture: VOC mass fractions'):
                m.load_voc(root/'voc.csv',cfg['sectors'])
            cfg['sectors']['agriculture']['sources']['NMVOC']={'zero_with_reason':''}
            with self.assertRaisesRegex(ValueError,'agriculture: VOC mass fractions'):
                m.load_voc(root/'voc.csv',cfg['sectors'])
            cfg['sectors']['agriculture']=copy.deepcopy(original['sectors']['agriculture'])
            with (root/'voc.csv').open('a',encoding='utf-8') as handle:
                handle.write('agriculture,E_ETH,1,30.07\n')
            with self.assertRaisesRegex(ValueError,'remove its VOC profile rows'):
                m.load_voc(root/'voc.csv',cfg['sectors'])


if __name__=='__main__':unittest.main(verbosity=2)
