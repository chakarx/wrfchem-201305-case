"""Download the public, original MIX v1.1 archives linked by the MEIC team.

No MIXv2 substitution. Archives include 2008/2010; extract the requested base year.
python download_mix.py --year 2010 --output ../raw_mix_v1.1
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import urllib.request
import zipfile

BASE = "https://meicmodel-website.oss-cn-beijing.aliyuncs.com/wp-cache/meicmodel/download/MIX_v1.1/"
SPECIES = ["SO2", "NOx", "CO", "NH3", "NMVOC", "PM10", "PM2.5", "BC", "OC"]


def fetch(species, root, year):
    url = BASE + species + '.zip'
    archive = root / (species + '.zip')
    if not archive.exists():
        temporary = archive.with_suffix('.zip.part')
        print('Downloading ' + url, flush=True)
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as out:
                while block := response.read(1024*1024):
                    out.write(block)
            # Reject an HTML error page before retaining it as an archive.
            with zipfile.ZipFile(temporary) as z:
                bad = z.testzip()
                if bad:
                    raise ValueError('ZIP CRC failure: ' + bad)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    extracted = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            relative = PurePosixPath(info.filename.replace('\\', '/'))
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe ZIP path: ' + info.filename)
            if str(year) not in relative.name or relative.suffix.lower() != '.nc':
                continue
            target = root / str(year) / relative.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with z.open(info) as src, target.open('wb') as out:
                    while block := src.read(1024*1024):
                        out.write(block)
            extracted.append(str(target.resolve()))
    if not extracted:
        raise ValueError(f'{archive}: no NetCDF for {year}')
    hasher = hashlib.sha256()
    with archive.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            hasher.update(block)
    digest = hasher.hexdigest()
    print(f'{species}: {archive.stat().st_size} bytes; {len(extracted)} NetCDF files', flush=True)
    return dict(species=species, url=url, bytes=archive.stat().st_size,
                sha256=digest, extracted=extracted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, choices=[2008, 2010], default=2010)
    parser.add_argument('--output', default='../raw_mix_v1.1')
    parser.add_argument('--voc', nargs='*', choices=['CB05','SAPRC99'],default=[])
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda s: fetch(s, root, args.year), SPECIES+args.voc))
    (root/'download_manifest.json').write_text(json.dumps({
        'source_page': 'http://meicmodel.org.cn/?page_id=89',
        'version': 'MIX v1.1', 'base_year': args.year,
        'selection_note': '2010 is an implementation choice; Huang 2020 does not disclose its MIX base year.',
        'downloaded_utc': datetime.now(timezone.utc).isoformat(), 'files': results,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
