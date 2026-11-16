"""Check real model/source definitions, unit handling and MOZBC endpoint rules."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

import f90nml  # Independent Fortran reader, test-only dependency.
import numpy as np
from netCDF4 import Dataset

import prepare_mozbc_inputs as m

HERE = Path(__file__).resolve().parent
START = datetime(2013, 5, 1)


def write_times(nc, dates):
    nc.createDimension('Time', len(dates))
    nc.createDimension('DateStrLen', 19)
    nc.createVariable('Times', 'S1', ('Time', 'DateStrLen'))[:] = np.array(
        [list(stamp.strftime(m.STAMP)) for stamp in dates], dtype='S1')


class TestMozbc(unittest.TestCase):
    def fixture(self, root):
        shutil.copyfile(HERE/'namelist.input', root/'namelist.input')
        dates = [START+timedelta(hours=6*i) for i in range(9)]
        targets = {m.decode(entry)[0] for entry in m.mapping()}
        sources = {name for entry in m.mapping() for name, _ in m.decode(entry)[1]}
        with Dataset(root/m.SOURCE_NAME, 'w') as nc:
            for dim, size in [('time', 9), ('lev', 2), ('lat', 3), ('lon', 3)]:
                nc.createDimension(dim, size)
            for name, values in [('lat', [5, 35, 65]), ('lon', [55, 105, 155]),
                                 ('lev', [1, 2]), ('hyam', [.1, .01]), ('hybm', [.1, .9])]:
                nc.createVariable(name, 'f4', (name if name in ('lat', 'lon', 'lev') else 'lev',))[:] = values
            nc.createVariable('P0', 'f4')[...] = 100000
            nc.createVariable('date', 'i4', ('time',))[:] = [int(d.strftime('%Y%m%d')) for d in dates]
            nc.createVariable('datesec', 'i4', ('time',))[:] = [d.hour*3600 for d in dates]
            ps = nc.createVariable('PS', 'f4', ('time', 'lat', 'lon')); ps.units = 'Pa'; ps[:] = 100000
            for name in sources:
                var = nc.createVariable(name, 'f4', ('time', 'lev', 'lat', 'lon'))
                var.units = 'VMR'; var[:] = 1e-9
            nc.retime_source_year = 2017
        for domain in (1, 2):
            with Dataset(root/f'wrfinput_d{domain:02d}', 'w') as nc:
                write_times(nc, [START])
                for dim, size in [('south_north', 2), ('west_east', 2), ('bottom_top', 2)]:
                    nc.createDimension(dim, size)
                for name, values in [('XLAT', [[20, 20], [50, 50]]), ('XLONG', [[70, 130], [70, 130]])]:
                    nc.createVariable(name, 'f4', ('Time', 'south_north', 'west_east'))[:] = [values]
                for target in targets:
                    var = nc.createVariable(target, 'f4', ('Time', 'bottom_top', 'south_north', 'west_east'))
                    var.units = '#/kg-dryair' if target.startswith('num_') else ('ug/kg-dryair' if '_a0' in target else 'ppmv')
                    var[:] = 0
            for date in dates if domain == 1 else [START]:
                with Dataset(root/m.met_filename(domain, date), 'w') as nc:
                    write_times(nc, [date]); nc.createVariable('PSFC', 'f4', ('Time',))[:] = 100000
        with Dataset(root/'wrfbdy_d01', 'w') as nc:
            write_times(nc, dates[:-1])
            for target in targets:
                for suffix in ('BXS', 'BXE', 'BYS', 'BYE', 'BTXS', 'BTXE', 'BTYS', 'BTYE'):
                    nc.createVariable(f'{target}_{suffix}', 'f4', ('Time',))[:] = 0
        return dates

    def test_registry_and_source_header_names(self):
        registry = HERE.parents[1]/'Registry'/'registry.chem'
        if registry.exists():
            text = registry.read_text()
            line = next(line for line in text.splitlines() if line.startswith('package') and 'chem_opt==9 ' in line)
            actual = set(line.split(' chem:')[1].strip().split(','))
            self.assertEqual(actual, m.ACTIVE)
        # Independent source list transcribed from the user's old MOZART header.
        names = set(('CO O3 SO2 NO NO2 H2O2 NO3 N2O5 HNO3 NH3 CH2O PAN TOLUENE HO2NO2 '
                     'C2H6 C3H6 C3H8 BIGENE BIGALK CH3OH GLYALD CH3CHO MEK CH3COCH3 HYAC '
                     'CH3COCHO C2H4 CRESOL BIGALD MVK MACR HYDRALD ONIT ONITR CH3COOH '
                     'CH3OOH C2H5OOH CH3O2 C2H5OH ISOP OH HO2 OC1 OC2 SOA CB1 CB2 '
                     'SO4 NH4NO3 NH4 SA1 SA2 SA3').split())
        actual = {source for entry in m.mapping() for source, _ in m.decode(entry)[1]}
        self.assertEqual(actual, {name+'_VMR_inst' for name in names} | {'DUST1', 'DUST2', 'DUST3', 'DUST4'})
        self.assertTrue({m.decode(entry)[0] for entry in m.mapping()} <= m.ACTIVE)

    def test_controls_and_number_coefficients(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m.prepare(root, templates_only=True)
            for domain in (1, 2):
                control = f90nml.read(root/f'mozbc_d{domain:02d}.inp')['control']
                self.assertEqual(control['do_bc'], domain == 1)
                self.assertTrue(control['do_ic'])
                self.assertFalse(control['def_missing_var'])
                self.assertEqual(control['spc_map'], m.mapping())
                self.assertLessEqual(max(map(len, control['spc_map'])), 164)
        parsed = {target: (dict(terms), factor) for target, terms, factor in map(m.decode, m.mapping())}
        for target, source, expected in [('num_a01', 'SA1_VMR_inst', '8.05e17'),
                                         ('num_a01', 'DUST1', '1.965e17'),
                                         ('num_a02', 'DUST2', '2.808e15'),
                                         ('num_a03', 'DUST2', '7.258e13')]:
            terms, factor = parsed[target]
            self.assertEqual(terms[source]*factor, Decimal(expected))
        # Preserve/reference-label the legacy nitrate convention; do not silently
        # replace it with an unverified pure-ion conversion.
        self.assertEqual(parsed['no3_a01'][1], Decimal('2.76186e9'))

    def test_prepare_keeps_real_files_and_preserves_corrected_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            text = (root/'namelist.input').read_text()
            text = m.set_integers(text, 'domains', 'num_metgrid_levels', [41])
            (root/'namelist.input').write_text(text)
            inputs = [root/'namelist.input', root/m.SOURCE_NAME, root/'wrfinput_d01', root/'wrfinput_d02', root/'wrfbdy_d01']
            before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs]
            output = m.prepare(root)
            self.assertEqual(len(output), 5)
            self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs])
            on = f90nml.read(root/'namelist.input.MOZBC.ARI_on')
            off = f90nml.read(root/'namelist.input.MOZBC.ARI_off')
            self.assertEqual(on['chem']['chem_in_opt'], [1, 1])
            self.assertEqual(on['chem']['have_bcs_chem'], [True, False])
            self.assertEqual(on['domains']['num_metgrid_levels'], 41)
            self.assertEqual(on['chem']['aer_ra_feedback'], [1, 1])
            self.assertEqual(off['chem'].pop('aer_ra_feedback'), [0, 0])
            on['chem'].pop('aer_ra_feedback')
            self.assertEqual(on, off)
            with self.assertRaises(FileExistsError):
                m.prepare(root)

    def test_missing_endpoint_or_fields_or_units_fail(self):
        for failure in ('endpoint', 'species', 'units', 'met', 'coverage'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); dates = self.fixture(root)
                if failure == 'endpoint':
                    with Dataset(root/m.SOURCE_NAME, 'r+') as nc:
                        nc['datesec'][-1] = 3600
                elif failure == 'species':
                    with Dataset(root/'wrfinput_d02', 'r+') as nc:
                        nc.renameVariable('o3', 'wrong_o3')
                elif failure == 'units':
                    with Dataset(root/m.SOURCE_NAME, 'r+') as nc:
                        nc['NO_VMR_inst'].units = 'ppbv'
                elif failure == 'met':
                    (root/m.met_filename(1, dates[-1])).unlink()
                else:
                    with Dataset(root/m.SOURCE_NAME, 'r+') as nc:
                        nc['lat'][-1] = 49
                with self.assertRaises((ValueError, FileNotFoundError)):
                    m.prepare(root)
                self.assertFalse((root/'mozbc_d01.inp').exists())


if __name__ == '__main__':
    unittest.main()
