"""MIX monthly emissions -> hourly WRF-Chem RADM2-input/CBM-Z-MOSAIC files.

inspect: python make_mix_wrfchemi.py inspect /path/to/MIX.nc
build:   python make_mix_wrfchemi.py build --config mix_config.json

Uses explicit source metadata and VOC profiles; never invents absent VOC species.
All source grids must be rectilinear lon/lat. Output targets real.exe wrfinput grids.
"""
import argparse
import calendar
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from pyproj import CRS, Transformer
from scipy.sparse import csr_matrix
from shapely.geometry import Polygon, box
from shapely.strtree import STRtree

RADIUS = 6370000.0
DATE_FMT = "%Y-%m-%d_%H:%M:%S"
CEA = CRS.from_proj4(f"+proj=cea +lat_ts=30 +lon_0=0 +R={RADIUS} +units=m")
TO_AREA = Transformer.from_crs(CRS.from_proj4(f"+proj=longlat +R={RADIUS}"), CEA, always_xy=True)
VOC_FIELDS = "E_ETH E_HC3 E_HC5 E_HC8 E_XYL E_OL2 E_OLT E_OLI E_TOL E_CSL E_HCHO E_ALD E_KET E_ORA2".split()


def checked_array(value, name):
    data = np.asarray(np.ma.filled(np.ma.asarray(value, dtype=float), np.nan))
    if not np.isfinite(data).all():
        raise ValueError(f"{name}: contains missing/nonfinite values; fix the data or explicitly set missing_as_zero")
    return data


def edges(centers):
    centers = np.asarray(centers, dtype=float)
    if centers.ndim != 1 or len(centers) < 2 or np.any(np.diff(centers) <= 0):
        raise ValueError("Coordinates must be strictly increasing 1D vectors with >=2 cells")
    mids = (centers[1:] + centers[:-1]) / 2
    return np.r_[centers[0] - (mids[0] - centers[0]), mids, centers[-1] + (centers[-1] - mids[-1])]


def format_path(value, context):
    return str(value).format(**context)


def source_month(spec, context):
    """Return monthly totals in kg per source cell, and sorted source centers."""
    path = format_path(spec["file"], context)
    with Dataset(path) as nc:
        variable_name = format_path(spec["variable"], context)
        if variable_name not in nc.variables:
            raise ValueError(f"{path}: no variable {variable_name}; use the inspect command")
        var = nc[variable_name]
        lat_var, lon_var = nc[spec.get("lat", "lat")], nc[spec.get("lon", "lon")]
        if lat_var.ndim != 1 or lon_var.ndim != 1:
            raise ValueError(f"{path}: only rectilinear 1D lat/lon grids are supported")
        lat = checked_array(lat_var[:], path + ':latitude')
        lon = checked_array(lon_var[:], path + ':longitude')
        lat_dim, lon_dim = lat_var.dimensions[0], lon_var.dimensions[0]
        if lat_dim == lon_dim:
            raise ValueError("lat and lon must have distinct dimensions")
        selection, remaining = [], []
        selectors = spec.get("isel", {})
        if set(selectors) - set(var.dimensions):
            raise ValueError(f"{path}: isel refers to absent dimensions")
        for dim in var.dimensions:
            if dim in selectors:
                if dim in (lat_dim, lon_dim):
                    raise ValueError("isel cannot remove spatial dimensions")
                selection.append(int(format_path(selectors[dim], context)))
            elif dim in (lat_dim, lon_dim):
                selection.append(slice(None))
                remaining.append(dim)
            else:
                raise ValueError(f"{path}:{variable_name}: explicitly select dimension {dim} using isel")
        if set(remaining) != {lat_dim, lon_dim}:
            raise ValueError("Input must retain exactly two spatial dimensions")
        raw = np.ma.asarray(var[tuple(selection)], dtype=float)
        if spec.get("missing_as_zero", False):
            raw = np.nan_to_num(np.ma.filled(raw, 0), nan=0, posinf=np.nan, neginf=np.nan)
        values = checked_array(raw, path + ':' + variable_name)
        values = np.transpose(values, [remaining.index(lat_dim), remaining.index(lon_dim)])
        # units in the file must be explicitly acknowledged, not silently guessed.
        expected = spec.get("expected_units")
        actual = str(getattr(var, spec.get("units_attribute", "units"), ""))
        if expected is None or actual.strip() != str(expected).strip():
            raise ValueError(f"{path}:{variable_name}: units={actual!r}; set expected_units to the actual verified attribute")
    if np.any(values < 0):
        raise ValueError(f"{path}:{variable_name}: negative emission values")
    lon = (lon + 180) % 360 - 180
    iy, ix = np.argsort(lat), np.argsort(lon)
    lat, lon = lat[iy], lon[ix]
    values = values[np.ix_(iy, ix)]
    le, oe = edges(lat), edges(lon)
    if np.any(np.diff(oe) > 5) or le[0] < -90 or le[-1] > 90:
        raise ValueError("Discontinuous/dateline-crossing grids or invalid cell edges are not supported")
    x, _ = TO_AREA.transform(oe, np.zeros_like(oe))
    _, y = TO_AREA.transform(np.zeros_like(le), le)
    areas = np.diff(y)[:, None] * np.diff(x)[None, :]
    # A source monthly mean flux represents the inventory calendar, not the target year.
    seconds = calendar.monthrange(context["inventory_year"], context["month"])[1] * 86400
    units = spec["conversion_units"]
    factors = {
        "tonne/cell/month": 1000.0,
        "kg/cell/month": 1.0,
        "g/cell/month": .001,
        "kg/m2/s": areas * seconds,
        "g/m2/s": areas * seconds / 1000,
    }
    if units not in factors:
        raise ValueError(f"Unsupported conversion_units={units}; supported: {list(factors)}")
    scale = float(spec.get("scale", 1))
    if not np.isfinite(scale) or scale < 0:
        raise ValueError("Source scale must be nonnegative and finite")
    return lon, lat, values * factors[units] * scale, {"file": path, "variable": variable_name, "units": actual, "scale": scale}


def wrf_grid(path):
    heights = None
    with Dataset(path) as nc:
        def first(name):
            var = nc[name]
            return checked_array(var[0] if var.dimensions[0] == "Time" else var[:], name)
        lat, lon = first("XLAT"), first("XLONG")
        if lat.ndim != 2 or lat.shape != lon.shape or int(nc.MAP_PROJ) != 1:
            raise ValueError("Expected a fixed Lambert-conformal WRF grid with 2D XLAT/XLONG")
        attrs = {name: nc.getncattr(name) for name in nc.ncattrs()}
        if "PH" in nc.variables and "PHB" in nc.variables and "HGT" in nc.variables:
            heights = (first("PH") + first("PHB")) / 9.81 - first("HGT")[None, :, :]
            print(f"{path}: mass layers={heights.shape[0]-1}; min interface count below 1km="
                  f"{np.min(np.sum(heights[1:] < 1000, axis=0))}")
        nz = len(nc.dimensions["bottom_top"])
    lambert = CRS.from_proj4(
        f"+proj=lcc +lat_1={attrs['TRUELAT1']} +lat_2={attrs['TRUELAT2']} "
        f"+lat_0={attrs.get('MOAD_CEN_LAT', attrs['CEN_LAT'])} +lon_0={attrs['STAND_LON']} +R={RADIUS} +units=m"
    )
    forward = Transformer.from_crs(lambert.geodetic_crs, lambert, always_xy=True)
    to_area = Transformer.from_crs(lambert, CEA, always_xy=True)
    xc, yc = forward.transform(lon, lat)
    dx, dy = float(attrs["DX"]), float(attrs["DY"])
    if (not np.allclose(np.diff(xc, axis=1), dx, atol=dx*.01, rtol=0)
            or not np.allclose(np.diff(yc, axis=0), dy, atol=dy*.01, rtol=0)):
        raise ValueError("WRF coordinates do not match the declared projection/DX/DY")
    polygons = []
    # Densify projected cell edges before transforming to the common equal-area plane.
    for x, y in zip(xc.ravel(), yc.ravel()):
        x0, x1, y0, y1 = x-dx/2, x+dx/2, y-dy/2, y+dy/2
        points = []
        for a, b in [((x0,y0),(x1,y0)), ((x1,y0),(x1,y1)), ((x1,y1),(x0,y1)), ((x0,y1),(x0,y0))]:
            points.extend((a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])) for t in np.linspace(0,1,9)[:-1])
        xx, yy = to_area.transform(*np.array(points).T)
        polygon = Polygon(np.column_stack([xx, yy]))
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("Invalid target cell polygon")
        polygons.append(polygon)
    return {"lat": lat, "lon": lon, "attrs": attrs, "polygons": polygons,
            "area": np.array([p.area for p in polygons]).reshape(lat.shape), "nz": nz,
            "heights_agl": heights}


def conservative_weights(lon, lat, polygons):
    """W[t,s]=intersection area/source-cell area; preserves inventory cell totals."""
    oe, le = edges(lon), edges(lat)
    x, _ = TO_AREA.transform(oe, np.zeros_like(oe))
    _, y = TO_AREA.transform(np.zeros_like(le), le)
    tree = STRtree(polygons)
    target_bounds = np.array([p.bounds for p in polygons])
    xmin, ymin = target_bounds[:, :2].min(axis=0)
    xmax, ymax = target_bounds[:, 2:].max(axis=0)
    rows, cols, values, covered = [], [], [], np.zeros(len(polygons))
    nx = len(lon)
    for j in range(len(lat)):
        if y[j+1] <= ymin or y[j] >= ymax:
            continue
        for i in range(nx):
            if x[i+1] <= xmin or x[i] >= xmax:
                continue
            src = box(x[i], y[j], x[i+1], y[j+1])
            for k in tree.query(src, predicate="intersects"):
                overlap = src.intersection(polygons[k]).area
                if overlap > 0:
                    rows.append(int(k)); cols.append(j*nx+i); values.append(overlap/src.area)
                    covered[k] += overlap
    area = np.array([p.area for p in polygons])
    coverage = covered / area
    if np.min(coverage) < .9999:
        raise ValueError(f"MIX grid does not cover the complete WRF domain (min coverage={coverage.min():.4f}); no extrapolation performed")
    return csr_matrix((values, (rows, cols)), shape=(len(polygons), len(lat)*nx))


def hourly_fractions(year, month, sector):
    """Normalize over the FULL simulation-calendar month, including timezone shift."""
    hourly = np.asarray(sector.get("hourly_factors", [1]*24), dtype=float)
    weekly = np.asarray(sector.get("weekday_factors", [1]*7), dtype=float)
    offset = sector.get("utc_offset_hours", 8)
    if not isinstance(offset, int) or not -23 <= offset <= 23:
        raise ValueError("utc_offset_hours must be an integer between -23 and 23")
    if hourly.shape != (24,) or weekly.shape != (7,) or not np.isfinite(hourly).all() or not np.isfinite(weekly).all() or min(hourly.min(),weekly.min()) < 0:
        raise ValueError("Expected 24 hourly and 7 weekday nonnegative finite factors")
    start = datetime(year, month, 1)
    weights = []
    for i in range(calendar.monthrange(year, month)[1]*24):
        local = start + timedelta(hours=i+offset)
        weights.append(hourly[local.hour] * weekly[local.weekday()])
    weights = np.array(weights)
    if weights.sum() <= 0:
        raise ValueError("Temporal factors have zero total")
    return weights / weights.sum()


def load_voc(path, sectors):
    profiles = {name: [] for name in sectors}
    # A sector explicitly lacking NMVOC (e.g. original MIX agriculture) needs no VOC profile.
    zero_sectors = {name for name, sector in sectors.items()
                    if str(sector['sources']['NMVOC'].get('zero_with_reason', '')).strip()}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sector = row["sector"]
            if sector not in profiles or row["output"] not in VOC_FIELDS:
                raise ValueError(f"Invalid VOC profile row: {row}")
            if sector in zero_sectors:
                raise ValueError(f"{sector}: NMVOC is explicitly absent; remove its VOC profile rows")
            try:
                fraction, mw = float(row["mass_fraction"]), float(row["molecular_weight_g_mol"])
            except (ValueError, TypeError) as error:
                raise ValueError(f"{path}: fill the verified VOC mass fraction and MW for {sector}/{row['output']}; empty template is not a scientific profile") from error
            if not np.isfinite([fraction,mw]).all() or fraction < 0 or mw <= 0:
                raise ValueError(f"Invalid VOC fraction/MW: {row}")
            profiles[sector].append((row["output"], fraction, mw))
    for name, rows in profiles.items():
        if name in zero_sectors:
            continue
        if not np.isclose(sum(row[1] for row in rows), 1, rtol=0, atol=1e-6):
            raise ValueError(f"{name}: VOC mass fractions must sum to 1; template blanks must be filled with a verified RADM2 profile")
    return profiles


def validate_config(cfg, fields):
    if not isinstance(cfg.get("inventory_year"), int):
        raise ValueError("Set inventory_year to the verified MIX base year; the paper does not disclose it")
    if cfg.get("emiss_opt") != 3 or cfg.get("emiss_inpt_opt") != 1:
        raise ValueError("This converter targets emiss_opt=3 / emiss_inpt_opt=1")
    if not isinstance(cfg.get("kemit"), int) or cfg["kemit"] < 1:
        raise ValueError("kemit must be a positive integer")
    if not cfg.get("domains"):
        raise ValueError("Supply at least one domain and its actual wrfinput")
    if any(meta["kind"] not in ("gas", "particle") for meta in fields.values()):
        raise ValueError("Interface kind must be gas or particle")
    sectors = cfg["sectors"]
    if not sectors:
        raise ValueError("At least one sector is required")
    required = {"SO2", "NOx", "CO", "NH3", "NMVOC", "PM25", "PM10", "BC", "OC"}
    for name, sector in sectors.items():
        if not required.issubset(sector["sources"]):
            raise ValueError(f"{name}: source definitions missing {required-set(sector['sources'])}")
        vertical = np.asarray(sector["vertical_weights"], dtype=float)
        if vertical.shape != (cfg["kemit"],) or not np.isfinite(vertical).all() or np.any(vertical < 0) or not np.isclose(vertical.sum(), 1):
            raise ValueError(f"{name}: vertical weights must match kemit and sum to one")
    mapped = set(cfg["outputs"]) | set(VOC_FIELDS)
    zeros = set(cfg["zero_outputs"])
    if mapped & zeros or (mapped | zeros) != set(fields):
        raise ValueError(f"Every interface variable must be explicitly mapped or justified zero; missing={set(fields)-(mapped|zeros)}, extra={(mapped|zeros)-set(fields)}")
    if any(not str(reason).strip() for reason in cfg["zero_outputs"].values()):
        raise ValueError("Every zero output needs a reason")
    for output, terms in cfg["outputs"].items():
        if not terms:
            raise ValueError(f"{output}: no mapping terms")
        for term in terms:
            if not np.isfinite(float(term["factor"])):
                raise ValueError(f"{output}: nonfinite factor")
            if fields[output]["kind"] == "gas" and (not np.isfinite(float(term.get("mw", 0))) or float(term.get("mw", 0)) <= 0):
                raise ValueError(f"{output}: gas mapping needs positive MW")
            for name, sector in sectors.items():
                if term["source"] not in sector["sources"]:
                    raise ValueError(f"{name}: no source {term['source']}")


def map_month(cfg, grid, year, month, fields, voc):
    mapped = {}
    provenance = []
    weight_cache = {}
    for sector_name, sector in cfg["sectors"].items():
        source_data = {}
        for name, spec in sector["sources"].items():
            if "zero_with_reason" in spec:
                if not str(spec["zero_with_reason"]).strip():
                    raise ValueError(f"{sector_name}/{name}: zero source needs a reason")
                source_data[name] = np.zeros(grid["lat"].shape)
                provenance.append(dict(sector=sector_name, source=name,
                                       zero_with_reason=spec["zero_with_reason"], target_month_total_kg=0.0))
                continue
            context = {"inventory_year": cfg["inventory_year"], "year": year,
                       "month": month, "month_index": month-1, "sector": sector_name, "species": name}
            lon, lat, monthly_kg, info = source_month(spec, context)
            key = hashlib.sha256(lon.tobytes()+lat.tobytes()).hexdigest()
            if key not in weight_cache:
                print(f"Building conservative weights for {sector_name}/{name} ...", flush=True)
                weight_cache[key] = conservative_weights(lon, lat, grid["polygons"])
            source_data[name] = (weight_cache[key] @ monthly_kg.ravel()).reshape(grid["lat"].shape)
            provenance.append(dict(info, sector=sector_name, source=name, target_month_total_kg=float(source_data[name].sum())))
        outputs = {}
        for output, terms in cfg["outputs"].items():
            result = np.zeros(grid["lat"].shape)
            magnitude = np.zeros_like(result)
            for term in terms:
                factor = float(term["factor"])
                factor *= 1000/float(term["mw"]) if fields[output]["kind"] == "gas" else 1e9
                contribution = source_data[term["source"]] * factor
                result += contribution
                magnitude += np.abs(contribution)
            # Original MIX is float32: cancellation in PM25-BC-OC can leave a few ULPs.
            tolerance = np.maximum(1e-12, magnitude * 4*np.finfo(np.float32).eps)
            if np.any(result < -tolerance):
                raise ValueError(f"{sector_name}/{output}: negative mapped emission (check PM closure / speciation)")
            outputs[output] = np.maximum(result, 0)
        for output in VOC_FIELDS:
            outputs[output] = np.zeros(grid["lat"].shape)
        for output, fraction, mw in voc[sector_name]:
            outputs[output] += source_data["NMVOC"] * fraction * 1000/mw
        if cfg.get('voc_mode') == 'saprc99_molar':
            from emission_scheme import add_speciated_voc
            provenance.extend(add_speciated_voc(cfg, sector_name, sector, grid, year, month,
                                               outputs, weight_cache))
        mapped[sector_name] = outputs
    return mapped, provenance


def write_hour(path, grid, timestamp, arrays, fields, cfg):
    with Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        ny, nx = grid["lat"].shape
        for name, size in [("Time",None),("DateStrLen",19),("emissions_zdim",cfg["kemit"]),("south_north",ny),("west_east",nx)]:
            nc.createDimension(name, size)
        # Copy WRF projection metadata, not unrelated model state attributes.
        for name in ("TITLE","SIMULATION_START_DATE","WEST-EAST_GRID_DIMENSION","SOUTH-NORTH_GRID_DIMENSION",
                     "DX","DY","GRID_ID","PARENT_ID","I_PARENT_START","J_PARENT_START","PARENT_GRID_RATIO",
                     "MAP_PROJ","MAP_PROJ_CHAR","CEN_LAT","CEN_LON","TRUELAT1","TRUELAT2","MOAD_CEN_LAT","STAND_LON","POLE_LAT","POLE_LON","MMINLU"):
            if name in grid["attrs"]:
                nc.setncattr(name, grid["attrs"][name])
        nc.setncattr("TITLE", "MIX anthropogenic emissions; RADM2 input for CBM-Z/MOSAIC")
        nc.setncattr("START_DATE", timestamp.strftime(DATE_FMT))
        nc.setncattr("inventory_year", cfg["inventory_year"])
        nc.setncattr("emiss_opt", 3)
        nc.setncattr("emiss_inpt_opt", 1)
        nc.setncattr("processing_config_sha256", cfg["_sha256"])
        if cfg.get('voc_mode') == 'saprc99_molar':
            nc.setncattr('voc_mode',cfg['voc_mode'])
            nc.setncattr('vertical_mode',cfg['vertical_mode'])
            nc.setncattr('scheme_notes',json.dumps(cfg['scheme_notes'],ensure_ascii=False))
        nc.createVariable("Times", "S1", ("Time","DateStrLen"))[0,:] = np.frombuffer(timestamp.strftime(DATE_FMT).encode("ascii"), dtype="S1")
        for name, data, units in [("XLAT",grid["lat"],"degrees_north"),("XLONG",grid["lon"],"degrees_east")]:
            var = nc.createVariable(name,"f4",("Time","south_north","west_east"))
            var[0] = data
            var.units, var.FieldType, var.MemoryOrder, var.stagger = units, 104, "XY ", ""
        for name, meta in fields.items():
            var = nc.createVariable(name,"f4",("Time","emissions_zdim","south_north","west_east"))
            var.units = meta["units"]
            var.description, var.FieldType, var.MemoryOrder = meta["description"], 104, "XYZ"
            var.stagger, var.coordinates = "", "XLONG XLAT"
            var[0] = arrays.get(name, np.zeros((cfg["kemit"],ny,nx)))


def build(config_path):
    config_path = Path(config_path).resolve()
    raw = config_path.read_bytes()
    cfg = json.loads(raw.decode("utf-8-sig"))
    cfg["_sha256"] = hashlib.sha256(raw).hexdigest()
    # Relative paths in the configuration are relative to that configuration.
    def local(path):
        path = Path(path)
        return str(path if path.is_absolute() else config_path.parent / path)
    with Path(local(cfg["interface_csv"])).open(encoding="utf-8-sig",newline="") as handle:
        fields = {r["name"]:r for r in csv.DictReader(handle)}
    validate_config(cfg, fields)
    voc = ({s: [] for s in cfg['sectors']} if cfg.get('voc_mode') == 'saprc99_molar'
           else load_voc(local(cfg["voc_profile_csv"]), cfg["sectors"]))
    if cfg.get('voc_mode') == 'saprc99_molar':
        cfg['saprc99_dir'] = local(cfg['saprc99_dir'])
    for sector in cfg["sectors"].values():
        for spec in sector["sources"].values():
            if "zero_with_reason" not in spec:
                spec["file"] = local(spec["file"])
    start, end = (datetime.strptime(cfg[k], DATE_FMT) for k in ("start", "end"))
    if end < start or any((t.minute,t.second,t.microsecond) != (0,0,0) for t in (start,end)):
        raise ValueError("Expected an increasing interval on full hours")
    outdir = Path(local(cfg["output_dir"]))
    if len({int(d["id"]) for d in cfg["domains"]}) != len(cfg["domains"]):
        raise ValueError("Duplicate domain IDs")
    outdir.mkdir(parents=True,exist_ok=True)
    for domain in cfg["domains"]:
        grid = wrf_grid(local(domain["wrfinput"]))
        if cfg["kemit"] > grid["nz"]:
            raise ValueError("kemit exceeds WRF mass levels")
        if cfg.get('vertical_mode') == 'height_agl':
            from emission_scheme import height_weights
            vertical_profiles = {s: height_weights(grid['heights_agl'], sector, cfg['kemit'])
                                 for s, sector in cfg['sectors'].items()}
        current, active_month, monthly = start, None, None
        while current <= end:  # Include the end-time record for WRF's boundary-time read.
            month_key = (current.year,current.month)
            if month_key != active_month:
                monthly, provenance = map_month(cfg,grid,*month_key,fields,voc)
                temporal = {s:hourly_fractions(*month_key,sector) for s,sector in cfg["sectors"].items()}
                report = {"domain":domain["id"],"target_month":f"{current:%Y-%m}","inventory_year":cfg["inventory_year"],
                          "sources":provenance,"config_sha256":cfg["_sha256"],"zero_outputs":cfg["zero_outputs"],
                          "voc_mode":cfg.get('voc_mode','mass_profile'),
                          "scheme_notes":cfg.get('scheme_notes',[]),
                          "sector_profiles":{s:{k:v for k,v in sector.items() if k != 'sources'}
                                             for s,sector in cfg['sectors'].items()}}
                (outdir/f"processing_d{domain['id']:02d}_{current:%Y%m}.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
                active_month = month_key
            hour = int((current-datetime(current.year,current.month,1)).total_seconds()/3600)
            arrays = {}
            for sector_name, outputs in monthly.items():
                sector = cfg["sectors"][sector_name]
                vertical = (vertical_profiles[sector_name] if cfg.get('vertical_mode') == 'height_agl'
                            else np.array(sector["vertical_weights"])[:,None,None])
                fraction = temporal[sector_name][hour]
                for name, total in outputs.items():
                    # Gas total is mol/cell/month, particle total ug/cell/month.
                    factor = 1e6 if fields[name]["kind"] == "gas" else 1/3600
                    flux = total/grid["area"] * factor * fraction
                    arrays[name] = arrays.get(name,0) + vertical*flux[None,:,:]
            path = outdir/f"wrfchemi_d{domain['id']:02d}_{current.strftime(DATE_FMT)}"
            # Windows cannot contain ':' in filenames. On Windows retain real Times but use underscores.
            if __import__('os').name == 'nt':
                path = path.with_name(path.name.replace(':','_'))
            if path.exists():
                raise FileExistsError(f"Refusing to overwrite {path}; select a new output_dir")
            temporary = path.with_name(path.name+'.tmp')
            try:
                write_hour(temporary,grid,current,arrays,fields,cfg)
                temporary.replace(path)
            finally:
                if temporary.exists():
                    temporary.unlink()
            print(path,flush=True)
            current += timedelta(hours=1)


def inspect(paths):
    for path in paths:
        with Dataset(path) as nc:
            print(f"\nFILE: {path}")
            print('DIMENSIONS:', {k:len(v) for k,v in nc.dimensions.items()})
            for name,var in nc.variables.items():
                print(name,var.dimensions,var.shape,
                      {k:var.getncattr(k) for k in ("units","Unit","long_name") if k in var.ncattrs()})


def main():
    parser = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command",required=True)
    sub.add_parser("inspect").add_argument("files",nargs="+")
    sub.add_parser("build").add_argument("--config",required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.files)
    else:
        build(args.config)


if __name__ == '__main__':
    main()
