"""Ensure date remapping is explicit, complete, and leaves source fields unchanged."""
from datetime import datetime,timedelta
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
from netCDF4 import Dataset
from retime_mozart_for_case import retime,source_indices,times_from_date

START=datetime(2013,5,1);END=datetime(2013,5,3)


class TestRetime(unittest.TestCase):
    def fixture(self,root,years=(2017,),records=9):
        path=root/'mozart4geos5-2024-EastAsia.nc'
        dates=[datetime(year,5,1)+timedelta(hours=6*i) for year in years for i in range(records)]
        with Dataset(path,'w') as nc:
            for name,size in [('time',None),('lev',2),('lat',7),('lon',6),('nchar',3)]:nc.createDimension(name,size)
            for name,values,units in [('lat',[0,10,20,30,40,50,60],'degrees_north'),
                                       ('lon',[60,80,100,120,140,160],'degrees_east'),
                                       ('lev',[1,2],'hybrid_sigma_pressure'),
                                       ('hyam',[.1,.2],''),('hybm',[.9,.8],'')]:
                variable=nc.createVariable(name,'f4',(name if name in ('lat','lon','lev') else 'lev',))
                variable[:]=values;variable.units=units
            nc.createVariable('P0','f4',())[...]=100000
            nc.createVariable('date','i4',('time',))[:]=[int(value.strftime('%Y%m%d')) for value in dates]
            nc.createVariable('datesec','i4',('time',))[:]=[value.hour*3600 for value in dates]
            time=nc.createVariable('time','f8',('time',));time.units='days since 0000-01-01 00:00:00';time.calendar='gregorian'
            time[:]=700000+np.arange(len(dates))/4
            nc.createVariable('days','i4',('time',))[:]=np.arange(len(dates))//4
            nc.createVariable('PS','f4',('time','lat','lon'))[:]=101325
            gas=nc.createVariable('CO_VMR_inst','f4',('time','lev','lat','lon'),fill_value=-9999.)
            gas.units='VMR';gas[:]=(np.arange(len(dates)*2*7*6)+1).reshape(len(dates),2,7,6)*1e-9
            packed=nc.createVariable('packed','i2',('time','lat','lon'));packed.scale_factor=.5;packed.add_offset=2.
            packed.set_auto_maskandscale(False);packed[:]=np.arange(len(dates)*7*6).reshape(len(dates),7,6)
            nc.createVariable('current_mss','S1',('nchar',))[:]=np.array(list('abc'),dtype='S1')
            nc.history='Original source history mentioning 2017'
        return path

    def test_copy_fields_dates_provenance_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=self.fixture(root,records=12);output=root/'retimed.nc'
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            report=retime(source,output,START,END)
            self.assertEqual(report['source_year'],2017)
            with Dataset(source) as original,Dataset(output) as result:
                self.assertEqual(len(result.dimensions['time']),9)
                self.assertEqual(len(result.dimensions['lev']),2)
                np.testing.assert_array_equal(result['CO_VMR_inst'][:],original['CO_VMR_inst'][:9,:,1:,:])
                self.assertEqual(result['CO_VMR_inst'].units,'VMR')
                self.assertEqual(result['CO_VMR_inst']._FillValue,-9999.)
                self.assertEqual(result['current_mss'][:].tobytes(),b'abc')
                self.assertEqual(float(result['P0'][...]),100000.)
                for nc in (original,result):nc['packed'].set_auto_maskandscale(False)
                np.testing.assert_array_equal(result['packed'][:],original['packed'][:9,1:,:])
                self.assertEqual(result['packed'].scale_factor,.5)
                self.assertEqual(result['date'][0],20130501)
                self.assertEqual(result['date'][-1],20130503)
                self.assertEqual(result['retime_source_date'][0],20170501)
                np.testing.assert_array_equal(result['retime_source_time'][:],original['time'][:9])
                np.testing.assert_array_equal(result['time'][:],np.arange(9)*6)
                self.assertIn('2013-05-01',result['time'].units)
                self.assertIn('not reconstructed',result.retime_limitation)
                self.assertEqual(result.retime_source_year,2017)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            self.assertTrue((root/'retimed.nc.retime.json').exists())
            with self.assertRaises(FileExistsError):retime(source,output,START,END)

    def test_missing_times_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=self.fixture(root,records=8);output=root/'retimed.nc'
            with self.assertRaisesRegex(ValueError,'complete source year'):retime(source,output,START,END)
            self.assertFalse(output.exists());self.assertFalse((root/'retimed.nc.partial').exists())

    def test_ambiguous_source_year_requires_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=self.fixture(root,years=(2017,2018));output=root/'retimed.nc'
            with self.assertRaisesRegex(ValueError,'source-year'):retime(source,output,START,END)
            report=retime(source,output,START,END,source_year=2018)
            self.assertEqual(report['source_year'],2018)

    def test_no_coverage_or_duplicate_times_cannot_be_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=self.fixture(root);output=root/'retimed.nc'
            with self.assertRaisesRegex(ValueError,'does not cover'):
                retime(source,output,START,END,west=40)
            with Dataset(source,'a') as nc:nc['date'][1]=nc['date'][0];nc['datesec'][1]=nc['datesec'][0]
            with self.assertRaisesRegex(ValueError,'complete source year'):retime(source,output,START,END)
            self.assertFalse(output.exists())

    def test_no_implicit_leap_day_and_legacy_dates(self):
        self.assertEqual(times_from_date([170501],[21600]),[datetime(2017,5,1,6)])
        with self.assertRaises(ValueError):source_indices([datetime(2017,2,28)],[datetime(2016,2,29)])


if __name__=='__main__':unittest.main(verbosity=2)
