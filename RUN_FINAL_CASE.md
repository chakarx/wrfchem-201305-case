# WRF-Chem 本次运行最终版：气象场、自然源、MOZBC、MIX 与 WRF

本文件是本案例唯一的完整执行入口，替代之前分散的运行流程。所有命令在服务器 Linux/Bash 中执行。
案例为 **2013-05-01 00 UTC 至 2013-05-03 00 UTC，共 48 小时**；60/20 km 两域；
CBM-Z/MOSAIC 四段含液相（chem_opt=9），使用 MIX 人为源、MEGAN 生物源、GOCART 扬尘、在线海盐和 MOZBC。
完成一小时短测后，分别运行 ARI_on、ARI_off；两组使用同一批初始/边界和排放。

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
独立目录：1 小时短测 → ARI_on 48 小时 → ARI_off 48 小时 → 检查输出
```

已经完成的步骤，核对本节所列文件、时间、网格和成功日志后可以跳过。
**MOZBC 后不要重新 real；若重新 real，须重新做 MOZBC。** 每个 sbatch 都是异步提交，
必须等本步成功后才进行依赖它的下一步。不要整篇一次性粘贴运行。

## 1. 本次采用的配置和输入状态

| 项目 | 本次设置 / 需核实内容 |
|---|---|
| 日期 | 两域均为 2013-05-01 00 → 05-03 00 UTC；FNL 6 小时、排放和输出 1 小时 |
| 网格 | d01 90×72、60 km；d02 159×144、20 km，均指质量点 |
| 垂直 | 35 个质量层，顶压 5000 Pa；实际 1 km 以下是否多于 10 层由 wrfinput 检查 |
| 物理 | YSU、Noah、Lin、Grell、RRTMG；时间步长 120 s，嵌套比例 3 |
| 化学 | chem_opt=9；emiss_opt=3；emiss_inpt_opt=1；kemit 按实际层高自动确定 |
| 自然源 | bio_emiss_opt=3、dust_opt=13、seas_opt=2；相应输入需实际检查 |
| 气象 | 9 个 FNL 已在本机下载；上传服务器或用第 2 节命令下载/校验 |
| MIX | v1.1 的 2010 年 5 月，40 个原始 nc，含 31 个 SAPRC99 VOC 文件；已在本机准备 |
| MEGAN | 预处理器编译方法及运行命令见第 6 节；完整静态数据尚未在本工作区准备 |
| 化学初边值 | 使用你已有的旧 MOZART 文件，提取同月日时并改日期；服务器实际文件仍须通过检查 |
| 配对试验 | ARI_on/off 只改变 aer_ra_feedback；无观测同化 |

论文使用 WRF 3.7.1，本地源码标注 3.9.1；清单基准年、五月模拟时段、精确网格位置和部分处理假设
也未与论文完全一致。本次是参考论文主要设置的基准试验，不能标作论文所有配置的严格复现。
旧 MOZART 改日期仍保留源年份浓度，不能称为真实 2013 年化学边界。

## 2. 上传新版文件、统一目录和环境

新版脚本包内部只有一层 paper_case。先解压到临时目录，再将其中的文件更新到实际 CASE_FILES，
不要在已有 paper_case 中反复解压。保留自己的旧输出和配置备份；不要上传 Windows 的 .venv。
脚本包不包含体积较大的原始 MIX、FNL、MEGAN 或 MOZART 数据。

建议数据布局如下；已有双层 paper_case 的情况由下方设置自动识别。

```text
mix_emissions_201305/
├── paper_case/                  新版脚本与本说明
├── fnl_20130501_20130503/        9 个 FNL GRIB2
└── raw_mix_v1.1/2010/            40 个原始 nc
```

在一个 Bash 会话设置以下变量；其中“实际路径”必须按服务器填写。若中途换终端，先重新设置。
WPS_CASE 如已有本次合格结果，填写那个实际目录，不要无意创建另一套 WPS。

```bash
export DATA_ROOT=/data1/share/elzd_2023_00080/xiaji/data/mix_emissions_201305
export CASE_ROOT=/data1/share/elzd_2023_00080/xiaji/cases/wrfchem_20130501_03
export CASE_FILES="$DATA_ROOT/paper_case"
# 兼容你最近报错中实际存在的双层目录；两处都有脚本时，请手动指定更新后的那一处。
if ! test -f "$CASE_FILES/emission_scheme.py"; then
  export CASE_FILES="$DATA_ROOT/paper_case/paper_case"
fi
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
export MOZART_INPUT=/实际路径/mozart4geos5-2024-EastAsia.nc
export MOZART_NC="$CASE_ROOT/mozart4geos5_retimed_20130501_20130503.nc"
export MEGAN_WORK="$CASE_ROOT/megan_work"
export ON_DIR="$CASE_ROOT/ARI_on"
export OFF_DIR="$CASE_ROOT/ARI_off"
export SMOKE_DIR="$CASE_ROOT/smoke_on"

test -f "$CASE_FILES/emission_scheme.py" || { echo 'CASE_FILES 指错目录'; exit 1; }
mkdir -p "$CASE_ROOT"
source "$WRF_ENV"
export OMP_NUM_THREADS=1
ulimit -s unlimited
ls -lh "$WRF_SRC/main/real.exe" "$WRF_SRC/main/wrf.exe"
ls -lh "$WPS_SRC/geogrid.exe" "$WPS_SRC/ungrib.exe" "$WPS_SRC/metgrid.exe"
ldd "$WRF_SRC/main/wrf.exe"
command -v mpirun
command -v ncdump
command -v csh
```

ldd 不能出现 not found；WRF/MPI/NetCDF 使用与编译时匹配的环境。
下面各步骤的 WPS、MEGAN、MOZBC 命令在集群允许的计算节点执行。
先修改 submit_case.slurm 中的分区、核数和必要的墙钟时间；示例为 bigmem、1 节点、24 MPI。
不要直接使用原来固定 144 核且自动串联未知 MOZBC 配置的 m.RUN-WRFCHEM-spatial.sh。

Python 使用已有的可用环境即可，不需要 f90nml。若没有环境，可创建：

```bash
# 已有依赖齐全的 conda 环境时直接激活它，跳过下面前两行。
python3 -m venv "$CASE_ROOT/pyenv"
source "$CASE_ROOT/pyenv/bin/activate"
python -m pip install -r "$CASE_FILES/requirements.txt"
python -c 'import numpy, netCDF4, scipy, pyproj, shapely; print("Python dependencies OK")'
python "$CASE_FILES/check_case.py"
```

后续 source 编译环境若改变了 Python 路径，重新激活你的 Python 环境再运行预处理脚本。
生产工具不使用 f90nml；不要因之前缺这个库而继续安装它。

已有 FNL 时，下面命令会检查已有文件；缺少时从脚本记录的官方来源下载，预期 9 个：

```bash
python "$CASE_FILES/download_fnl.py" --namelist "$CASE_FILES/namelist.wps" --output "$FNL_DIR"
find "$FNL_DIR" -maxdepth 1 -name 'fnl_201305*.grib2' -type f | wc -l
```

MIX 已上传完整 40 个 nc 可跳过下载；否则在有外网的服务器运行：

```bash
python "$CASE_FILES/download_mix.py" --year 2010 --voc SAPRC99 --output "$DATA_ROOT/raw_mix_v1.1"
test -s "$MIX_DIR/MICS_Asia_SAPRC99_ALK1_2010_0.25x0.25.nc" || exit 1
```

上述下载器的清单保留来源和校验记录。MEGAN 静态数据与 MOZART 化学场是另外两套数据，不包含在 MIX 中。

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
当前 `geog_data_res='glc2015_30s'` 是从原配置沿用的选项，要确认 GEOGRID.TBL 和静态数据都支持它。
如实际使用其他土地利用产品，需保持 GEOGRID.TBL、土地利用类别和后续物理表一致。
60/20 km 是论文公开设置；当前格点数、位置和土地利用产品不等于论文已公开的精确值。

### 3.2 geogrid

```bash
./geogrid.exe > geogrid.stdout.log 2>&1
tail -n 20 geogrid.log
ls -lh geo_em.d01.nc geo_em.d02.nc
```

完成标志：日志显示成功；两域 geo_em 均存在。查看 XLAT_M/XLONG_M、LU_INDEX、地形和嵌套位置，
确认 NCP/YRD 均在目标覆盖区，嵌套在父域内。需要时先调整域，再重做后续步骤。
如果修改域尺寸、位置或分辨率，须同步更新 paper_case 中的 namelist.wps 和 namelist.input 模板；
后面的配置工具读取该目录模板，不能只改 WPS 工作目录里的一份。
如需 GOCART 扬尘，核对是否提供正确的 EROD 等匹配网格静态场；不是只写 `dust_opt=13` 就一定有有效扬尘。

### 3.3 FNL → ungrib

```bash
ln -s "$WPS_SRC/ungrib/Variable_Tables/Vtable.GFS" Vtable
csh "$WPS_SRC/link_grib.csh" "$FNL_DIR"/fnl_201305*.grib2
ls -1 GRIBFILE.* | wc -l
./ungrib.exe > ungrib.stdout.log 2>&1
tail -n 20 ungrib.log
ls -1 FILE:2013-05-*
```

GRIBFILE 应为 9 个；FILE 应覆盖 05-01 00/06/12/18、05-02 00/06/12/18、05-03 00，共 9 时次。
FNL 时间就是 UTC，不要把文件名额外加 8 小时。
此产品的官方 WRF 教程使用 [Vtable.GFS](https://www2.mmm.ucar.edu/wrf/OnLineTutorial/DATA/FNL/fnl.php)。

### 3.4 metgrid

```bash
./metgrid.exe > metgrid.stdout.log 2>&1
tail -n 20 metgrid.log
ls -1 met_em.d01.*.nc | wc -l
ls -1 met_em.d02.*.nc | wc -l
ncdump -h met_em.d01.2013-05-01_00:00:00.nc | head -n 65
```

完成标志：每域 9 个 met_em，共 18 个；日志成功，温度、风、湿度、地面气压、土温和土壤湿度等必要场没有缺失错误。
核对各域时次、num_metgrid_levels、num_st_layers、num_sm_layers、NUM_LAND_CAT。
**模板里的 38/4/24 沿用原案例，不能直接认定适合本次 FNL/地理资料。**

## 4. 生成与实际 met_em 一致的运行 namelist

本目录的工具读取全部 18 个 met_em，检查覆盖、质量点尺寸和层数一致性，然后生成新副本：

`prepare_runtime_namelists.py` 已去除 f90nml 依赖，仅需 Python 标准库和 `netCDF4`。
若现有环境已能 `python -c "import netCDF4"`，无需为这一步安装 f90nml；
直接用更新后的脚本替换服务器同名文件。`check_case.py` 也不再依赖 f90nml，支持合法空段（例如 `&grib2 /`）；
f90nml 只用于可选的独立参照测试（requirements-test.txt），不属于运行工具依赖。

```bash
python "$CASE_FILES/prepare_runtime_namelists.py" \
  --met-dir "$WPS_CASE" --output-dir "$CASE_ROOT/prepared"
```

输出为：

- `prepared/namelist.input.ARI_on`：修正气象层数、土壤层数和土地类别数后的正式配置。
- `prepared/namelist.input.ARI_off`：仅 ARI 开关与上份不同。
- `prepared/namelist.input.bootstrap`：与 on 相比，只暂时把 bio_emiss_opt 改为 0，用于第一次 real。

工具拒绝覆盖已有输出；如重做 WPS，使用新的 prepared 目录并同步后续路径。
原始模板不会被修改。若层数/土地类别元数据缺失或不一致，先查清 met_em，不能跳过错误随意写一个数字。
脚本只读取本案例需要的简单整数数组和引号日期，并定点修改参数，保留其他配置和注释；
不是通用 Fortran namelist 解析器，所读取参数不支持下标赋值或重复值简写。

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
新父域仅 90×72 质量点；原来的 144 核不应直接照搬，过细分块可能触发最小 patch 尺寸错误。

任务结束后：

```bash
tail -n 25 rsl.error.0000
ls -lh wrfinput_d01 wrfinput_d02 wrfbdy_d01 wrflowinp_d01 wrflowinp_d02
python "$CASE_FILES/check_case.py" --wrfinput wrfinput_d01 wrfinput_d02
```

成功标志为 `SUCCESS COMPLETE REAL_EM INIT`，以及两个 wrfinput、外域 wrfbdy、两个 wrflowinp。
`sst_update=1` 所以这里需要 wrflowinp。检查工具还验证 35 个质量层和 1 km 以下的层数；
若不满足论文“多于 10 层”的要求，调整 eta 后重做 real，再重做所有依赖网格/层高的排放处理。

第一次 real 不需要最终 wrfchemi。暂时关闭 MEGAN 是为解决“预处理需要 wrfinput，但正式 real 又要读 wrfbiochemi”的先后依赖；
**不能用这份 bootstrap namelist 进行正式 wrf 积分。** 本地 `main/real_em.F` 的 MEGAN 读取分支已核实。

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
export FC=ifort
export NETCDF_DIR="$(nc-config --prefix)"
./make_util megan_bio_emiss
export MEGAN_EXE="$PWD/megan_bio_emiss"
test -x "$MEGAN_EXE" || exit 1
```

需要与工具匹配的 Fortran 和 NetCDF 库，按该目录 README.bio_emiss、make_util、Makefile 处理链接差异。
Python netCDF4 不能代替 Fortran 链接库。若程序实际输出路径不同，修正 MEGAN_EXE。
官方 [MEGAN 说明](https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/megan_bio_emiss/README.bio_emiss)
要求“当月和上个月”的输入，因此本次选择 **4、5 月**。

**MEGAN_DATA 要先有该工具所需的完整已转换静态数据。** 从上方 ACOM 官方工具入口获取配套数据，
不是下载 GitHub 源码就会自动得到数据。若取得的是原始 MEGAN/地表数据，须先按 README 用
megan_xform 和 surfdata_xform 转换；已有配套转换数据则不重复转换。
不能用 MIX、WPS_GEOG 或旧网格的 wrfbiochemi 代替。目录核查后，在独立工作目录生成配置并运行：

```bash
test -x "$MEGAN_EXE" || { echo '请先设置可用 MEGAN_EXE'; exit 1; }
test -d "$MEGAN_DATA" || { echo '尚未准备 MEGAN 静态数据'; exit 1; }
mkdir "$MEGAN_WORK" || { echo 'MEGAN 工作目录已存在，请核查既有结果'; exit 1; }
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

MEGAN 是单进程预处理，不用 mpirun。官方要求 inp 中目录末尾不带斜杠，上述命令已去除末尾斜杠。
目录变量在部分老工具中有 100 字符长度限制，长路径应使用较短的工作路径并重新核查。
确认两域网格分别 90×72、159×144，4/5 月记录和 MLAI、MTSA、MSWDOWN、MSEBIO_ISOP、PFTP_* 等
字段齐全、有限且植被覆盖合理。MSEBIO_ISOP 是参考排放因子，在线 MEGAN 随 WRF 气象计算逐时排放，
不另做一套重复叠加的“逐小时 MEGAN wrfchemi”。

### 6.2 GOCART 扬尘

本地 MOSAIC 使用 dust_opt=13 的 GOCART 分支，并读取 EROD、土壤湿度、地表类型和风等字段。
在 geo_em、met_em 和 wrfinput 间追踪 EROD 是否正确提供及保留，检查类型、维度和数值范围。
如果没有 EROD 或在有沙尘源的区域全部为无效零，需补齐适用的静态数据和预处理，再重做相关 WPS/real 步骤。
不要以创建全零文件的方式“修复”缺失，也不要为了消除错误把 dust_opt 从 13 随意改成 1。
这里尚没有准备一套独立扬尘静态清单，不能把该项标为已经完成。

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
海盐 seas_opt=2 为在线过程，不需要另一个人为海盐排放文件；需有合理海陆掩膜和海面气象输入。
本流程不另外开启未经配置的火点或闪电清单。

你前面报错中的 `.true..` 是布尔值尾部多一个点，不应改成带引号字符串。
对已有服务器 namelist，可用新版工具在验证和备份后修正；新生成且无错误的文件只检查：

```bash
python "$CASE_FILES/fix_namelist_bool.py" "$REAL_DIR/namelist.input" --apply
```

其他解析错误按具体行号和 &段.参数处理；不要跳过检查。下面开始 MOZBC，之后不再运行 real。

## 8. 准备化学场并生成 MOZBC 配置

如果改日期的新文件还没有生成，运行：

```bash
python "$CASE_FILES/retime_mozart_for_case.py" \
  --input "$MOZART_INPUT" \
  --output "$MOZART_NC" \
  --start 2013-05-01_00:00:00 --end 2013-05-03_00:00:00 \
  --north 58 --south 10 --west 62 --east 142
```

已有该输出就检查并使用，不重复运行覆盖。改日期保留源浓度，不是真实 2013 年全球化学场。
随后链接源文件和实际 met_em：

```bash
cd "$REAL_DIR"
test -s "$MOZART_NC" || exit 1
test -x "$MOZBC_EXE" || exit 1
if test -e mozart_case_0001.nc; then
  cmp -s "$MOZART_NC" mozart_case_0001.nc || { echo '已有不同 MOZART 文件'; exit 1; }
else
  ln -s "$MOZART_NC" mozart_case_0001.nc
fi
for f in "$WPS_CASE"/met_em.d0*.nc; do
  test -f "$f" || continue
  name="$(basename "$f")"
  if test -e "$name"; then
    cmp -s "$f" "$name" || { echo "已有不同文件 $name"; exit 1; }
  else
    ln -s "$f" "$name"
  fi
done

python "$CASE_FILES/prepare_mozbc_inputs.py" --work-dir .
```

生成 mozbc_d01.inp、mozbc_d02.inp、mozbc_preflight.json、
namelist.input.MOZBC.ARI_on/off。若这些文件已生成，先执行 `--check-only` 检查实际输入；
仅当先前配置与当前脚本生成的配置一致时复用。要重新生成时先备份/移走列出的旧生成文件，脚本不覆盖。
不要预先把上传包中的参考 inp 复制到 REAL_DIR 后又要求生成同名文件。

检查器会检查完整区域、物种、单位、源时次及 MOZBC 最后一个趋势所需的额外端点。
若提示源文件缺少某时次，必须扩展源数据和对应 met_em 覆盖，不能跳过检查。

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

MOZBC 是单进程任务，不用 mpirun。若集群要求计算任务通过调度器运行，在申请到的交互计算资源中执行，
不要在登录节点长期运行。日志成功后，在 REAL_DIR 执行以下检查（四个边界侧面均检查；边界趋势允许正负，不作负值判断）：

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

还应与 before_mozbc 中对应变量比较，确认需要映射的字段确实发生合理变化。
当前映射继承 NCAR 旧参考系数。尤其 NH4NO3 → NO3 的系数约对应分子量 80，而纯硝酸根是 62；
源 NH4 是否包含其中铵仍需源模式定义核实。因此本版能执行参考映射，但尚不能认为 NO3/NH4
的定量质量定义已经验证；正式无机盐定量分析前必须解决，不能仅凭成功插值判断。
之后不要再次 real 覆盖这三个文件；如重跑 real，就要重新 MOZBC。

## 10. 制作人为排放与最终运行 namelist

重新进入有 Python 依赖的环境（如果上一步 source 改变了 Python 环境）。

```bash
cd "$CASE_FILES"
python emission_scheme.py --wrf-dir "$REAL_DIR" --mix-dir "$MIX_DIR"
python make_mix_wrfchemi.py build --config mix_config.scheme.json
```

此处显式 MIX_DIR 避免脚本层级导致原始数据相对路径错误。
新方案直接读取 SAPRC99 摩尔排放并转换到本次接口，不再读空白 voc_profile_TO_FILL.csv；
不要回到旧的 mix_config.json 直接 build。新增 VOC 替代映射是近似，详见 EMISSIONS_SCHEME_RUN.md。
小时分配采用 UTC+8 部门曲线、星期权重均为 1、整月归一化；电力/工业按固定 AGL 高度带注入，
其余部门表面注入。这些是明确的基准假设，不是动态烟羽抬升或已知的论文原始分配表。
输出为 `$CASE_FILES/wrfchemi_201305_scheme/`，每域 49 文件，合计 98。
配置还会另写两份匹配 kemit 的正式 MOZBC 运行 namelist：
namelist.input.MOZBC.ARI_on.emissions、namelist.input.MOZBC.ARI_off.emissions。
输出存在时不会覆盖；只有完成相同配置/数据的完整输出才可复用，不要把中断后的一部分输出当成成功。

```bash
for d in 01 02; do
  find "$CASE_FILES/wrfchemi_201305_scheme" -maxdepth 1 -type f -name "wrfchemi_d${d}_*" | wc -l
done
```

每次应输出 49。再检查 processing_dXX_201305.json 的源数据、排除组分、时间/高度方案及所有警告。
原始 CSV 空模板不再被新方案读取。具体映射限制见 EMISSIONS_SCHEME_RUN.md。

## 11. 建立独立的短测、ARI_on、ARI_off 目录

下面函数在当前 Bash 会话定义一次。使用全新目录，避免旧排放、旧日志或 restart 混入。
物理/化学表链接自 real 工作目录，wrfinput/wrfbdy 和其他指定模型输入复制成本案例独立文件。

```bash
export ON_DIR="$CASE_ROOT/ARI_on"
export OFF_DIR="$CASE_ROOT/ARI_off"
export SMOKE_DIR="$CASE_ROOT/smoke_on"

create_run_dir() {
  target="$1"
  nml="$2"
  test -s "$nml" || return 1
  mkdir "$target" || { echo "目录已存在，请检查后使用全新目录：$target"; return 1; }
  for f in "$REAL_DIR"/*; do
    test -f "$f" || continue
    name="$(basename "$f")"
    case "$name" in
      namelist*|rsl.*|wrfinput*|wrfbdy*|wrflowinp*|wrfbiochemi*|wrfout*|wrfrst*|wrfchemi*|met_em*|moz*|job-*|*.log|*.py|*.json|*.csv|*.inp|*.md|*.zip|*.before-bool-fix) continue ;;
    esac
    ln -s "$f" "$target/$name" || return 1
  done
  for name in wrfinput_d01 wrfinput_d02 wrfbdy_d01 wrflowinp_d01 wrflowinp_d02 wrfbiochemi_d01 wrfbiochemi_d02; do
    cp -p "$REAL_DIR/$name" "$target/$name" || return 1
  done
  for f in "$CASE_FILES"/wrfchemi_201305_scheme/wrfchemi_d0*; do
    test -f "$f" || return 1
    ln -s "$f" "$target/$(basename "$f")" || return 1
  done
  cp "$nml" "$target/namelist.input" || return 1
  test -x "$target/wrf.exe"
}

create_run_dir "$SMOKE_DIR" "$CASE_FILES/namelist.input.MOZBC.ARI_on.emissions" || exit 1
create_run_dir "$ON_DIR" "$CASE_FILES/namelist.input.MOZBC.ARI_on.emissions" || exit 1
create_run_dir "$OFF_DIR" "$CASE_FILES/namelist.input.MOZBC.ARI_off.emissions" || exit 1
```

三个目录都使用 MOZBC 后的同一批初始/边界。不要把 on 的模拟结束状态或 restart 作为 off 初始条件。
如果某目录准备中断，请先确认其内容，使用新的目录名重新准备；不要重复链接覆盖已有文件。

在两个正式目录都准备好后，检查实际 namelist 的差异，不能仅凭模板判断：

```bash
cd "$CASE_FILES"
python - "$ON_DIR/namelist.input" "$OFF_DIR/namelist.input" <<'PY'
import sys
from pathlib import Path
from check_case import read_namelist
on, off = [read_namelist(Path(p)) for p in sys.argv[1:]]
assert on['chem']['aer_ra_feedback'] == [1,1]
assert off['chem']['aer_ra_feedback'] == [0,0]
for n in (on, off):
    assert n['chem']['chem_in_opt'] == [1,1]
    assert n['chem']['have_bcs_chem'] == [True,False]
    assert n['chem']['bio_emiss_opt'] == [3,3]
on['chem'].pop('aer_ra_feedback'); off['chem'].pop('aer_ra_feedback')
assert on == off, 'ARI_on/off 还有其他参数不同'
print('Formal namelists OK: only ARI differs')
PY
```

## 12. 只把短测目录改为 1 小时

```bash
cd "$CASE_FILES"
python - "$SMOKE_DIR/namelist.input" <<'PY'
import sys
from pathlib import Path
from prepare_runtime_namelists import set_integers
p=Path(sys.argv[1]); text=p.read_text()
for key,values in [('run_days',[0]),('run_hours',[1]),('run_minutes',[0]),('run_seconds',[0]),
                   ('end_year',[2013,2013]),('end_month',[5,5]),('end_day',[1,1]),
                   ('end_hour',[1,1]),('end_minute',[0,0]),('end_second',[0,0])]:
    # Original case omits run_minutes/run_seconds, whose WRF defaults are zero.
    if key in ('run_minutes','run_seconds') and key not in text:
        continue
    text=set_integers(text,'time_control',key,values)
p.write_text(text)
PY
```

正式 ON_DIR/OFF_DIR 不修改，仍为 48 小时。短测仍链接完整 98 个排放文件，匹配现有提交脚本的输入检查。

## 13. 检查最终配置，提交 wrf.exe

正式配置应为：

| 参数 | ARI_on | ARI_off |
|---|---|---|
| chem_opt | 9,9 | 9,9 |
| emiss_opt / emiss_inpt_opt | 3,3 / 1,1 | 相同 |
| chem_in_opt | 1,1 | 1,1 |
| have_bcs_chem | .true.,.false. | 相同 |
| bio_emiss_opt | 3,3 | 3,3 |
| kemit | emission_scheme 自动计算值 | 相同 |
| aer_ra_feedback | 1,1 | 0,0 |
| restart | .false. | .false. |

auxinput5 每 60 分钟读一个 wrfchemi，每文件一时次；sst_update=1 需要两个 wrflowinp。
先检查 submit_case.slurm 顶部：默认 bigmem 分区、1 节点、24 MPI 进程；按集群实际资源修改，
若要求墙钟时间则补充合法的 #SBATCH --time。不要直接使用原来的 144 核串联脚本。

```bash
cd "$SMOKE_DIR"
sbatch "$CASE_FILES/submit_case.slurm" wrf
```

**以上 sbatch 会启动异步作业，提交成功不代表 WRF 已经跑完。** 等作业结束后检查：

```bash
squeue -u "$USER"
tail -n 40 "$SMOKE_DIR/rsl.error.0000"
grep -F 'SUCCESS COMPLETE WRF' "$SMOKE_DIR/rsl.error.0000"
ls -lh "$SMOKE_DIR"/wrfout_d0*2013-05-01_01:00:00
```

成功且浓度、气象无异常后再提交正式 on：

```bash
cd "$ON_DIR"
sbatch "$CASE_FILES/submit_case.slurm" wrf
```

on 成功后提交 off（也可在资源允许时独立并行，输入必须相同）：

```bash
cd "$OFF_DIR"
sbatch "$CASE_FILES/submit_case.slurm" wrf
```

提交脚本已经执行 `mpirun -np "$SLURM_NTASKS" ./wrf.exe`，无需再手动额外启动 wrf.exe。
不要在同一目录同时运行两份 WRF。关闭终端不会取消已经提交的 Slurm 作业。

## 14. 确认完整结束与结果检查

```bash
for d in "$ON_DIR" "$OFF_DIR"; do
  grep -F 'SUCCESS COMPLETE WRF' "$d/rsl.error.0000"
  ls -lh "$d"/wrfout_d01_2013-05-03_00:00:00 "$d"/wrfout_d02_2013-05-03_00:00:00
  for dom in 01 02; do
    find "$d" -maxdepth 1 -type f -name "wrfout_d${dom}_*" | wc -l
  done
done
```

history_interval=60、frames_per_outfile=1 时，每域预期 49 个 wrfout，含起点与终点。
还要读实际 Times 和变量，不能只凭文件名、文件数或队列消失判断成功。

下面读取所有输出的实际 Times，检查各域从起点至终点连续 49 条小时记录：

```bash
python - "$ON_DIR" "$OFF_DIR" <<'PY'
import sys
from pathlib import Path
from datetime import datetime, timedelta
from netCDF4 import Dataset, chartostring
expected = [(datetime(2013,5,1)+timedelta(hours=i)).strftime('%Y-%m-%d_%H:%M:%S') for i in range(49)]
for directory in map(Path,sys.argv[1:]):
    for domain in ('01','02'):
        times=[]
        for p in sorted(directory.glob(f'wrfout_d{domain}_*')):
            with Dataset(p) as nc:
                times.extend(str(t) for t in chartostring(nc['Times'][:]).reshape(-1))
        assert times == expected, f'{directory}: d{domain} actual Times are incomplete or duplicated'
        print(directory, 'd'+domain, 'PASS: 49 hourly records')
PY
```

检查完整过程的 NO2/O3/SO4/NO3/NH4 是否有限且无系统性异常，近地温度、湿度、风和 PBLH 是否合理。
数值成功不等于排放/化学机制已经科学验证。

结果只有 48 小时，能计算“本次 48 小时平均”；不能标为“2013 年 5 月完整月均”。
48 小时平均通常用 [05-01 00,05-03 00) 的 48 条小时记录，终点用于完整性检查。
正式定量研究还需要评估预热期和当前边界/排放近似的敏感性。

出现问题先查出错目录当前作业的 rsl.error.0000、其他进程 rsl.error.* 和 job-作业号.err：

- 缺 wrfchemi：目录链接、文件名冒号、时次、kemit 和文件维度。
- 缺 wrfbiochemi：MEGAN 文件和新网格，不能使用 bootstrap 配置冒充正式配置。
- 动态库错误：WRF_ENV、编译环境和 ldd wrf.exe，不能只安装 Python 库。
- CFL/最小 patch：实际时间步长、层高、边界与并行分块；不要盲目增加核数。
- namelist 语法错误：按新版报错的行号和 &段.参数检查，布尔值不加引号。

所有生成器默认拒绝覆盖输出；要重做时先保留上一版，并在新目录/明确的新输出中运行。
