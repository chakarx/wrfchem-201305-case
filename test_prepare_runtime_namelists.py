"""Verify runtime namelists follow met_em headers without changing experiment controls."""
from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
import runpy
import sys
from unittest.mock import patch
import f90nml
from netCDF4 import Dataset
from prepare_runtime_namelists import prepare,met_filename,read_values,set_integers

CASE=Path(__file__).resolve().parent


class TestRuntimeNamelists(unittest.TestCase):
    def met_files(self,root):
        met=root/'met';met.mkdir()
        for i in range(9):
            date=datetime(2013,5,1)+timedelta(hours=6*i)
            for domain,nx,ny in [(1,90,72),(2,159,144)]:
                path=met/met_filename(domain,date)
                with Dataset(path,'w') as nc:
                    for n,size in [('num_metgrid_levels',27),('num_st_layers',4),('num_sm_layers',4),
                                   ('west_east',nx),('south_north',ny)]:nc.createDimension(n,size)
                    nc.NUM_LAND_CAT=21
        return met

    def test_headers_and_only_intended_experiment_differences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);met=self.met_files(root);output=root/'prepared'
            # Block f90nml imports while loading AND executing the actual tool.
            # Use f90nml below only as an independent reference for the output semantics.
            with patch.dict(sys.modules,{'f90nml':None}):
                standalone=runpy.run_path(str(CASE/'prepare_runtime_namelists.py'))
                standalone['prepare'](CASE,met,output)
            on=f90nml.read(output/'namelist.input.ARI_on')
            off=f90nml.read(output/'namelist.input.ARI_off')
            bootstrap=f90nml.read(output/'namelist.input.bootstrap')
            self.assertEqual(on['domains']['num_metgrid_levels'],27)
            self.assertEqual(on['domains']['num_metgrid_soil_levels'],4)
            self.assertEqual(on['physics']['num_land_cat'],21)
            self.assertEqual(on['chem']['chem_opt'],[9,9])
            self.assertEqual(bootstrap['chem']['bio_emiss_opt'],[0,0])
            bootstrap['chem']['bio_emiss_opt']=[3,3]
            self.assertEqual(on,bootstrap)
            off['chem']['aer_ra_feedback']=[1,1]
            self.assertEqual(on,off)
            source=f90nml.read(CASE/'namelist.input')
            for n in ('num_metgrid_levels','num_metgrid_soil_levels'):
                on['domains'][n]=source['domains'][n]
            on['physics']['num_land_cat']=source['physics']['num_land_cat']
            self.assertEqual(on,source)
            with self.assertRaises(FileExistsError):prepare(CASE,met,output)

    def test_missing_endpoint_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);met=self.met_files(root)
            (met/met_filename(2,datetime(2013,5,3))).unlink()
            with self.assertRaises(FileNotFoundError):prepare(CASE,met,root/'prepared')
            self.assertFalse((root/'prepared').exists())

    def test_inconsistent_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);met=self.met_files(root)
            with Dataset(met/met_filename(2,datetime(2013,5,3)),'a') as nc:nc.NUM_LAND_CAT=24
            with self.assertRaisesRegex(ValueError,'Inconsistent'):prepare(CASE,met,root/'prepared')
            self.assertFalse((root/'prepared').exists())

    def test_targeted_text_edit_preserves_other_fields_and_comments(self):
        source="""! &domains max_dom=99 / is only a comment
&SHARE
 start_date = '2013-05-01_00:00:00', ! first domain
              '2013-05-01_00:00:00',
 path = '/data/a!b/name',
/
&DOMAINS
 max_dom = 2, e_we = 91,
                    160, ! preserve this comment
 unrelated = 38,
/
"""
        self.assertEqual(read_values(source,'share','start_date'),['2013-05-01_00:00:00']*2)
        self.assertEqual(read_values(source,'share','path'),['/data/a!b/name'])
        result=set_integers(source,'domains','e_we',[100,200])
        self.assertIn('! preserve this comment',result)
        expected=f90nml.reads(source)
        expected['domains']['e_we']=[100,200]
        self.assertEqual(f90nml.reads(result),expected)
        with self.assertRaisesRegex(ValueError,'Expected one'):
            set_integers(source,'domains','missing',[1])
        with self.assertRaisesRegex(ValueError,'Expected one'):
            read_values('&domains\n max_dom=2, max_dom=3,\n/','domains','max_dom')
        with self.assertRaisesRegex(ValueError,'Indexed'):
            read_values('&domains\n e_we(1)=91,\n/','domains','e_we')


if __name__=='__main__':unittest.main(verbosity=2)
