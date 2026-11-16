# WRF-Chem 运行
案例为 **2013-05-01 00 UTC 至 2013-05-03 00 UTC，共 48 小时**；60/20 km 两域；
CBM-Z/MOSAIC 四段含液相（chem_opt=9），使用 MIX 人为源、MEGAN 生物源、GOCART 扬尘、在线海盐和 MOZBC。

```text
FNL + 地理静态数据
        ↓
geogrid → ungrib → metgrid → 读取实际 met_em 生成 namelist
        ↓
第一次 real（bootstrap，仅暂时 bio_emiss_opt=0）
        ↓
MEGAN 预处理 → wrfbiochemi_d01/d02；检查扬尘静态场
        ↓
第二次 real（bio_emiss_opt=3，chem_in_opt=0）
        ↓
准备 MOZART 化学场 → 生成 inp → MOZBC d01 IC/BC、d02 IC
        ↓
按最终 wrfinput 生成 MIX 逐小时排放，计算 kemit，生成正式 WRF namelist
        ↓


## 1. 本次采用的配置和输入状态

| 项目 | 本次设置 / 需核实内容 |
|---|---|
| 日期 | 两域均为 2013-05-01 00 → 05-03 00 UTC；FNL 6 小时、排放和输出 1 小时 |
| 网格 | d01 90×72、60 km；d02 159×144、20 km|
| 垂直 | 35 个质量层，顶压 5000 Pa；实际 1 km 以下是否多于 10 层由 wrfinput 检查 |
| 物理 | YSU、Noah、Lin、Grell、RRTMG；时间步长 120 s，嵌套比例 3 |
| 化学 | chem_opt=9；emiss_opt=3；emiss_inpt_opt=1；kemit 按实际层高自动确定 |
| 自然源 | bio_emiss_opt=3、dust_opt=13、seas_opt=2；相应输入需实际检查 |
| 气象 | 9 个 FNL|
| MIX | v1.1 的 2010 年 5 月，40 个原始 nc，含 31 个 SAPRC99 VOC 文件|
| MEGAN | 预处理器编译方法及运行命令见第 6 节；完整静态数据尚未在本工作区准备 |


## 2. 上传新版文件、统一目录和环境


```text
mix_emissions_201305/
├── paper_case/                  新版脚本与本说明
├── fnl_20130501_20130503/        9 个 FNL GRIB2
└── raw_mix_v1.1/2010/            40 个原始 nc
```


```bash
#根据自己的路径来
export DATA_ROOT=/data1/share/elzd_2023_00080/xiaji/data/mix_emissions_201305
export CASE_ROOT=/data1/share/elzd_2023_00080/xiaji/cases/wrfchem_20130501_03
export CASE_FILES="$DATA_ROOT/paper_case"
export MIX_DIR="$DATA_ROOT/raw_mix_v1.1/2010"
export FNL_DIR="$DATA_ROOT/fnl_20130501_20130503"
export WPS_CASE="$CASE_ROOT/WPS_case"
export REAL_DIR="$CASE_ROOT/real_work"
export WRF_ENV=/data1/share/elzd_2023_00080/xiaji/WRF_INTEL/wrf-chem_icc.sh
export WRF_SRC=/实际路径/已编译的WRFV3
export WPS_SRC=/实际路径/已编译的WPS
export GEOG_DIR=/实际路径/WPS_GEOG
export MEGAN_DATA=/实际路径/MEGAN已转换静态数据
export MOZBC_EXE=/实际路径/mozbc
#边界场文件
export MOZART_INPUT=/实际路径/mozart4geos5-2024-EastAsia.nc
#实例中边界场文件的剪裁
export MOZART_NC="$CASE_ROOT/mozart4geos5_retimed_20130501_20130503.nc"
export MEGAN_WORK="$CASE_ROOT/megan_work"


mkdir -p "$CASE_ROOT"
source "$WRF_ENV"
```


```bash
# 已有依赖齐全的 conda 环境时直接激活它，跳过下面前两行。
python3 -m venv "$CASE_ROOT/pyenv"
source "$CASE_ROOT/pyenv/bin/activate"
python -m pip install -r "$CASE_FILES/requirements.txt"
python -c 'import numpy, netCDF4, scipy, pyproj, shapely; print("Python dependencies OK")'
python "$CASE_FILES/check_case.py"
```

## 3. WPS：生成地理场和气象场

### 3.1 建立独立 WPS 工作目录

```bash
mkdir "$WPS_CASE" || { echo '目录已存在：先核查现有 WPS，不要重复建立链接'; exit 1; }
mkdir "$WPS_CASE/geogrid" "$WPS_CASE/metgrid"
ln -s "$WPS_SRC/geogrid.exe" "$WPS_CASE/geogrid.exe"
ln -s "$WPS_SRC/ungrib.exe" "$WPS_CASE/ungrib.exe"
ln -s "$WPS_SRC/metgrid.exe" "$WPS_CASE/metgrid.exe"
ln -s "$WPS_SRC/geogrid/GEOGRID.TBL" "$WPS_CASE/geogrid/GEOGRID.TBL"
ln -s "$WPS_SRC/metgrid/METGRID.TBL" "$WPS_CASE/metgrid/METGRID.TBL"
cp "$CASE_FILES/namelist.wps" "$WPS_CASE/namelist.wps"
python - "$WPS_CASE/namelist.wps" "$GEOG_DIR" <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1]); value = sys.argv[2]
if not Path(value).is_dir() or "'" in value:
    raise ValueError('GEOG_DIR 必须是真实地理数据目录，且路径不能含单引号')
s, n = re.subn(r"(?m)^(\s*geog_data_path\s*=)\s*'[^']*'", lambda m: m[1]+" '"+value+"'", p.read_text())
if n != 1: raise ValueError('geog_data_path assignment not found uniquely')
p.write_text(s)
PY
cd "$WPS_CASE"
```
上述命令已写入 GEOG_DIR；再核对这里的 namelist.wps。

### 3.2 geogrid

```bash
./geogrid.exe > geogrid.stdout.log 2>&1
tail -n 20 geogrid.log
ls -lh geo_em.d01.nc geo_em.d02.nc
```

### 3.3 FNL → ungrib

```bash
ln -s "$WPS_SRC/ungrib/Variable_Tables/Vtable.GFS" Vtable
csh "$WPS_SRC/link_grib.csh" "$FNL_DIR"/fnl_201305*.grib2
ls -1 GRIBFILE.* | wc -l
./ungrib.exe > ungrib.stdout.log 2>&1
tail -n 20 ungrib.log
ls -1 FILE:2013-05-*
```

### 3.4 metgrid

```bash
./metgrid.exe > metgrid.stdout.log 2>&1
tail -n 20 metgrid.log
ls -1 met_em.d01.*.nc | wc -l
ls -1 met_em.d02.*.nc | wc -l
ncdump -h met_em.d01.2013-05-01_00:00:00.nc | head -n 65
```
## 4. 生成与实际 met_em 一致的运行 namelist

本目录的工具读取全部 18 个 met_em，检查覆盖、质量点尺寸和层数一致性，然后生成新副本：

```bash
python "$CASE_FILES/prepare_runtime_namelists.py" \
  --met-dir "$WPS_CASE" --output-dir "$CASE_ROOT/prepared"
```
输出为：
- `prepared/namelist.input.ARI_on`：修正气象层数、土壤层数和土地类别数后的正式配置。
- `prepared/namelist.input.ARI_off`：仅 ARI 开关与上份不同。
- `prepared/namelist.input.bootstrap`：与 on 相比，只暂时把 bio_emiss_opt 改为 0，用于第一次 real。

## 5. 第一次 real：给排放预处理提供网格

### 5.1 建立独立 real 工作目录

下面只在新目录执行。把 WRF run 的运行期表/数据链接过来，跳过旧 namelist、exe、模型输入输出和日志：

```bash
mkdir "$REAL_DIR" || { echo '已有 real_work：先核查进度，不要在旧输入上重做初始化'; exit 1; }
for file in "$WRF_SRC"/run/*; do
  [ -f "$file" ] || continue
  name="$(basename "$file")"
  case "$name" in
    namelist.input*|*.exe|rsl.*|wrf*|met_em*|GRIBFILE.*|FILE:*) continue ;;
  esac
  ln -s "$file" "$REAL_DIR/$name"
done
ln -s "$WRF_SRC/main/real.exe" "$REAL_DIR/real.exe"
ln -s "$WRF_SRC/main/wrf.exe" "$REAL_DIR/wrf.exe"
for file in "$WPS_CASE"/met_em.d0*.nc; do
  ln -s "$file" "$REAL_DIR/$(basename "$file")"
done
cp "$CASE_ROOT/prepared/namelist.input.bootstrap" "$REAL_DIR/namelist.input"
cd "$REAL_DIR"
sbatch "$CASE_FILES/submit_case.slurm" real
```

提交脚本示例采用现有脚本出现的 bigmem 分区，1 节点 24 MPI 进程。分区、核数、墙钟时间按集群实际要求修改。

任务结束后：

```bash
tail -n 25 rsl.error.0000
ls -lh wrfinput_d01 wrfinput_d02 wrfbdy_d01 wrflowinp_d01 wrflowinp_d02
python "$CASE_FILES/check_case.py" --wrfinput wrfinput_d01 wrfinput_d02
```

成功标志为 `SUCCESS COMPLETE REAL_EM INIT`，以及两个 wrfinput、外域 wrfbdy、两个 wrflowinp。
`sst_update=1` 所以这里需要 wrflowinp。检查工具还验证 35 个质量层和 1 km 以下的层数；
第一次 real 不需要最终 wrfchemi。暂时关闭 MEGAN 是为解决“预处理需要 wrfinput，但正式 real 又要读 wrfbiochemi”的先后依赖；


## 6. 制作 MEGAN，核查扬尘静态输入

### 6.1 MEGAN

当前没有准备好匹配新网格的 wrfbiochemi，需取得 MEGAN 预处理器和它需要的已转换静态数据。
NCAR 的 [官方工具仓库](https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/tree/main/megan_bio_emiss)
提供 megan_bio_emiss；所需数据入口见仓库 README 和 [ACOM 工具页面](https://www2.acom.ucar.edu/wrf-chem/wrf-chem-tools-community)。
已下载的 MIX 数据不包含这些自然源输入。

若服务器没有预处理器，可编译官方工具；已有可用程序就跳过编译，设置 MEGAN_EXE：

```bash
mkdir -p "$CASE_ROOT/external_tools"
cd "$CASE_ROOT/external_tools"
git clone https://github.com/NCAR/WRF-Chem-Preprocessing-Tools.git
cd WRF-Chem-Preprocessing-Tools/megan_bio_emiss
##编译
./make_util megan_bio_emiss
export MEGAN_EXE="$PWD/megan_bio_emiss"
test -x "$MEGAN_EXE" || exit 1
```
**MEGAN_DATA 要先有该工具所需的完整已转换静态数据。** 从上方 ACOM 官方工具入口获取配套数据，

```bash

cd "$MEGAN_WORK"
cat > megan_bio_emiss.inp <<EOF
&control
 domains = 2,
 start_lai_mnth = 4,
 end_lai_mnth = 5,
 wrf_dir = '${REAL_DIR%/}',
 megan_dir = '${MEGAN_DATA%/}'
/
EOF
"$MEGAN_EXE" < megan_bio_emiss.inp > megan_bio_emiss.log 2>&1
tail -n 40 megan_bio_emiss.log
test -s wrfbiochemi_d01 && test -s wrfbiochemi_d02 || exit 1
ncdump -h wrfbiochemi_d01
ncdump -h wrfbiochemi_d02
cp -p wrfbiochemi_d01 wrfbiochemi_d02 "$REAL_DIR/"
```



## 7. 第二次 real：生成正式化学初始与气象边界文件

wrfbiochemi 和静态场准备好后，恢复正式 namelist，再次运行 real。
第一次的输出可先复制到专用备份目录；不要把正式目录里的 wrfinput 软链回旧案例。

```bash
cd "$REAL_DIR"
mkdir bootstrap_backup || { echo '备份已存在，先确认是否已经完成最终 real'; exit 1; }
cp -p wrfinput_d01 wrfinput_d02 wrfbdy_d01 wrflowinp_d01 wrflowinp_d02 bootstrap_backup/
cp "$CASE_ROOT/prepared/namelist.input.ARI_on" namelist.input
sbatch "$CASE_FILES/submit_case.slurm" real
```

结束后再次核对成功标志、文件和网格；本次应读入 MEGAN，bio_emiss_opt=3，chem_opt=9。
这一步 real 仍使用 chem_in_opt=0 创建化学字段，不提前使用 MOZBC 正式积分配置。
结束后再次执行第 5 节的文件/网格检查，并确认 MEGAN 读取没有报错。


```
## 9. 备份后执行 MOZBC

```bash
cd "$REAL_DIR"
mkdir before_mozbc || { echo '备份目录已存在，先确认是否已经做过 MOZBC'; exit 1; }
for f in wrfinput_d01 wrfinput_d02 wrfbdy_d01; do
  test -L "$f" && { echo "$f 是软链接，请先使用本案例独立副本"; exit 1; }
  cp -p "$f" before_mozbc/ || exit 1
done

# 先加载 MOZBC 所需的动态库环境；现有程序若与 WRF 同环境可用这一行。
source "$WRF_ENV"
"$MOZBC_EXE" < mozbc_d01.inp > mozbc_d01.log 2>&1
grep -q 'bc_wrfchem completed successfully' mozbc_d01.log || { tail -60 mozbc_d01.log; exit 1; }
"$MOZBC_EXE" < mozbc_d02.inp > mozbc_d02.log 2>&1
grep -q 'bc_wrfchem completed successfully' mozbc_d02.log || { tail -60 mozbc_d02.log; exit 1; }
```

```bash
python - <<'PY'
from netCDF4 import Dataset
import numpy as np
for filename in ('wrfinput_d01','wrfinput_d02','wrfbdy_d01'):
    with Dataset(filename) as nc:
        sides = ('_BXS','_BXE','_BYS','_BYE') if filename.startswith('wrfbdy') else ('',)
        for sp in ('co','o3','no2','so4_a01','no3_a01','nh4_a01','num_a01'):
            for side in sides:
                name = sp+side; a = np.ma.asarray(nc[name][:])
                if np.ma.is_masked(a) or not np.isfinite(a).all() or (a < 0).any():
                    raise ValueError(f'{filename}: invalid concentration {name}')
                print(filename, name, float(a.min()), float(a.max()), float(a.mean()))
        if filename.startswith('wrfbdy'):
            for name in nc.variables:
                if any(name.endswith(s) for s in ('_BTXS','_BTXE','_BTYS','_BTYE')):
                    a = np.ma.asarray(nc[name][:])
                    if np.ma.is_masked(a) or not np.isfinite(a).all():
                        raise ValueError(f'Invalid boundary tendency: {name}')
PY
```

mozbc运行成功后修改namelist.input
```fortran
 chem_in_opt = 1, 1,
 have_bcs_chem = .true., .false.,
```

## 10. 制作人为排放与最终运行 namelist

```bash
cd "$CASE_FILES"
python emission_scheme.py --wrf-dir "$REAL_DIR" --mix-dir "$MIX_DIR"
这一步输出的kemit的值，然后根据这个值修改namelist.input的对应地方
python make_mix_wrfchemi.py build --config mix_config.scheme.json
```

输出为 `$CASE_FILES/wrfchemi_201305_scheme/`，每域 49 文件，合计 98。


```bash
for d in 01 02; do
  find "$CASE_FILES/wrfchemi_201305_scheme" -maxdepth 1 -type f -name "wrfchemi_d${d}_*" | wc -l
done
```
然后软链接wrfchemi_d* 到该路径下"$CASE_ROOT/real_work" 

## 13. 检查最终配置，提交 wrf.exe

正式配置应为：

| 参数 |
| chem_opt | 9,9 | 
| emiss_opt / emiss_inpt_opt | 3,3 / 1,1 |
| chem_in_opt | 1,1 | 
| have_bcs_chem | .true.,.false. |
| bio_emiss_opt | 3,3 |
| kemit | emission_scheme 自动计算值 | 
| aer_ra_feedback | 1,1 | 
| restart | .false. |

auxinput5 每 60 分钟读一个 wrfchemi，每文件一时次；sst_update=1 需要两个 wrflowinp。

```bash
sbatch "$CASE_FILES/submit_case.slurm" wrf
```



