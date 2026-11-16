"""Regression checks for empty namelist groups and strict configuration validation."""
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_case import check, read_namelist

CASE=Path(__file__).resolve().parent


class TestCheckCase(unittest.TestCase):
    def test_bool_typo_repair_preserves_strings_and_makes_backup(self):
        from fix_namelist_bool import fix
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'namelist.input'
            text="&chem\n enabled=.true.., disabled=.false...,\n label='.true..', ! .false.. comment\n/\n"
            path.write_text(text)
            original=path.read_bytes()
            self.assertEqual(fix(path),2)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(fix(path,apply=True),2)
            self.assertEqual(path.with_name(path.name+'.before-bool-fix').read_bytes(),original)
            result=read_namelist(path)['chem']
            self.assertTrue(result['enabled']);self.assertFalse(result['disabled'])
            self.assertEqual(result['label'],'.true..')
            self.assertIn('! .false.. comment',path.read_text())
            self.assertEqual(fix(path,apply=True),0)

    def parse(self,text):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'namelist.input'
            path.write_text(text,encoding='utf-8')
            return read_namelist(path)

    def test_empty_and_commented_groups(self):
        result=self.parse('''! A comment outside groups
&grib2
/
&fdda
 ! Only a comment, with fake assignments x=9 and terminator /.
/
&another / ! Empty inline group
&last
&end
''')
        self.assertEqual(result,{'grib2':{},'fdda':{},'another':{},'last':{}})

    def test_types_and_quoted_delimiters(self):
        result=self.parse('''&example
 path='/a!b/c', text='it''s valid',
 numbers=2*1.0d-3, -2, .5,
 switches=.true., .false.,
 grid(1:2)=91,160,
/
''')['example']
        self.assertEqual(result['path'],'/a!b/c')
        self.assertEqual(result['text'],"it's valid")
        self.assertEqual(result['numbers'],[.001,.001,-2,.5])
        self.assertEqual(result['switches'],[True,False])
        self.assertEqual(result['grid'],[91,160])

    def test_invalid_content_is_still_rejected(self):
        for source in ('&grib2\n invalid content\n/',
                       "&grib2\n 'unassigned string'\n/",
                       '&grib2\n value=\n/',
                       '&grib2\n value=1,\n',
                       '&grib2 /\n&grib2 /'):
            with self.subTest(source=source),self.assertRaises(ValueError):self.parse(source)

    def test_full_case_without_f90nml(self):
        # Exercise the shipped templates including their original empty &grib2 group.
        with patch.dict(sys.modules,{'f90nml':None}):
            standalone=runpy.run_path(str(CASE/'check_case.py'))
            standalone['check'](CASE)
        self.assertEqual(read_namelist(CASE/'namelist.input')['grib2'],{})

    def test_actual_domain_mismatch_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('namelist.wps','namelist.input','namelist.input.ARI_off'):
                (root/name).write_text((CASE/name).read_text(encoding='utf-8'),encoding='utf-8')
            path=root/'namelist.input'
            path.write_text(path.read_text().replace('e_we = 91, 160,','e_we = 91, 163,'))
            with self.assertRaisesRegex(AssertionError,'e_we'):check(root)


if __name__=='__main__':unittest.main(verbosity=2)
