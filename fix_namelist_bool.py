"""Check/fix extra trailing dots in unquoted Fortran .true../.false.. tokens.

python fix_namelist_bool.py /case/namelist.input --apply
Only these exact typo tokens are changed; quoted strings/comments are preserved.
"""
import argparse
from pathlib import Path
import re
import tempfile
from check_case import read_namelist
from prepare_runtime_namelists import _clean


def fix(path, apply=False):
    path=Path(path)
    original=path.read_bytes()
    text=original.decode('utf-8-sig')
    matches=list(re.finditer(r'(?i)(?<![\w.])\.(true|false)\.{2,}(?![\w.])',_clean(text,mask_strings=True)))
    if not matches:
        read_namelist(path)
        print('Valid:',path)
        return 0
    repaired=text
    for match in reversed(matches):
        repaired=repaired[:match.start()]+'.'+match[1].lower()+'.'+repaired[match.end():]
    with tempfile.TemporaryDirectory() as temporary:
        check=Path(temporary)/'namelist.input'
        check.write_bytes(repaired.encode('utf-8'))
        read_namelist(check)  # Other errors stop before modifying the actual input.
    for match in matches:
        print(f'{path}:{text.count(chr(10),0,match.start())+1}: {match[0]} -> .{match[1].lower()}.')
    if apply:
        backup=path.with_name(path.name+'.before-bool-fix')
        with backup.open('xb') as stream:stream.write(original)
        path.write_bytes(repaired.encode('utf-8'))
        print('Fixed; backup:',backup)
    else:print('Check only. Use --apply to save with a backup.')
    return len(matches)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files',nargs='+',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    for path in args.files:fix(path,args.apply)
