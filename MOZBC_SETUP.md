# 本次案例加入 MOZBC：数据准备和接入顺序

用户已选择使用 MOZBC，并提供旧 MOZART 化学场的文件头，要求改日期后接入本次案例。
已制作两个参考 inp 和实际数据检查/配置生成脚本，直接执行步骤见 [MOZBC_QUICKSTART.md](MOZBC_QUICKSTART.md)。
本机尚无服务器上的实际化学场和最终 wrfinput，未运行 MOZBC；修改日期不等于获得真实 2013 年化学场。
MIX 排放 nc 或 FNL 气象文件不能代替全球化学浓度场。

## 当前补充：已有旧 MOZART 文件头，用户选择映射到 2013 年

用户随后提供 `mozart4geos5-2024-EastAsia.nc` 的完整文件头，并要求修改时间。
该头包含 56 层、`PS/P0/hyam/hybm`、`*_VMR_inst` 气体及旧 MOZART 气溶胶字段。
文件名含 2024，但 history 涉及 2016-12-30 至 2018-01-02；实际年份以 `date/datesec` 数据为准。
本地只有文件头，未取得服务器上的原始 nc，也未实际改写它。

新增 `retime_mozart_for_case.py`：把源文件中相同月/日/时的化学场复制到
2013-05-01 00 UTC 至 2013-05-03 00 UTC 的新时间轴，提取 9 时次和用户指定区域。
这是一种明确使用替代年份边界的试验，不是重建或下载到真实 2013 年化学场。
区域外侧保留原网格相邻点以完整包围请求范围；不做空间插值、不改变保留点浓度、不覆写原文件。

把新版脚本上传到服务器的 paper_case，进入存放原 nc 的目录后执行：

```bash
python "$CASE_FILES/retime_mozart_for_case.py" \
  --input mozart4geos5-2024-EastAsia.nc \
  --output mozart4geos5_retimed_20130501_20130503.nc \
  --start 2013-05-01_00:00:00 \
  --end 2013-05-03_00:00:00 \
  --north 58 --south 10 --west 62 --east 142
```

程序直接读取 date/datesec，避免用带 year=0000 的 time 单位猜测源年份。
自动选择唯一覆盖全部所需月/日/时的源年份；如果有多个候选，需用 `--source-year 实际年份` 指定。
缺时次、重复时间、范围不足、闰日不匹配或输出已存在时会报错。

输出包括：

- 新 nc：目标 date/datesec/time 坐标，以及原始化学/气象/垂直坐标字段的相应子集。
- `retime_source_date`、`retime_source_datesec`、`retime_source_time`：原始记录时间，保留原 time 的单位。
- `*.retime.json`：源年份、原始/目标时次、请求/实际区域及使用限制。
- 全局 retime 元数据与 history：明确指出来源年份及“改日期不改变浓度”。

除绝对时间坐标 date/datesec/time 外，原模式运行计数器及 nbdate 等源运行元数据保留原值。
后续用 mozart_case_0001.nc 链接这个新文件，作为 inp 中的 fn_moz；物种映射仍须检查实际数据，
修改日期不能代替 spc_map，也不会解决 MIX 人为 VOC 分配的问题。

以下官方数据下载路线仍可用于取得真实年份匹配的化学场；前述替代年份试验应单独标注。

## 1. 取得化学场

NCAR 目前推荐的 CAM-chem 边界数据为 CESM2.2，使用 MOZART-T1 气相化学及 MAM4-VBS 气溶胶。
数据集包含本案例的 2013 年，选择瞬时、每 6 小时的数据，不能下载月平均产品来充当逐时变化边界。

- 官方区域/时间子集入口：https://www.acom.ucar.edu/cesm/subset.shtml
- 数据集：https://gdex.ucar.edu/datasets/d313008/
- 官方说明：https://wiki.ucar.edu/spaces/camchem/pages/502301240/CESM2.2%2BCAM-chem%2Bas%2BBoundary%2BConditions

子集页面要求使用者填写自己的邮箱；全球文件下载入口说明需要注册。
本任务尚未代填或提交个人信息，也没有拿到子集文件下载地址。

申请参数：

| 项目 | 本案例填写内容 |
|---|---|
| 日期 | 至少覆盖 2013-05-01 00 UTC 至 2013-05-03 00 UTC，含终点；若页面只按整日选择，可选 05-01 至 05-04 留出余量 |
| 时间分辨率 | 6 小时瞬时场，与 FNL/气象边界时次一致；下载后用实际 date/datesec 核实 |
| 区域 | 完整覆盖 d01，并在四周保留插值余量；仅覆盖 d02 或研究省份不够 |
| 垂直 | 完整模型层及其坐标/地面气压变量，不能只取地面浓度 |
| 变量 | 保留完整化学和坐标变量，不预先只筛 NO3/SO4/NH4 |

在服务器含 wrfinput_d01 的目录运行下面的命令，得到本次外域对应的申请范围。
额外 3 度是此处选择的插值余量，不是论文公开参数；此代码适用于本案例未跨 0/360 经线的亚洲网格。

```bash
python - <<'PY'
import math
import numpy as np
from netCDF4 import Dataset
with Dataset('wrfinput_d01') as nc:
    lat = np.ma.asarray(nc['XLAT'][0], dtype=float)
    lon = np.ma.asarray(nc['XLONG'][0], dtype=float) % 360
    if np.ma.is_masked(lat) or np.ma.is_masked(lon):
        raise ValueError('经纬度有缺失值，先检查 wrfinput')
    if not np.isfinite(lat).all() or not np.isfinite(lon).all():
        raise ValueError('经纬度有无效值，先检查 wrfinput')
    west, east = math.floor(float(lon.min())-3), math.ceil(float(lon.max())+3)
    if east-west > 180 or west < 0 or east > 360:
        raise ValueError('需要单独处理跨经线的申请范围，不能直接使用 min/max')
    print('North latitude:', min(90, math.ceil(float(lat.max())+3)))
    print('South latitude:', max(-90, math.floor(float(lat.min())-3)))
    print('West longitude:', west)
    print('East longitude:', east)
PY
```

## 2. 下载后先检查文件，而不是立即填写任意映射

把实际下载文件放到服务器独立的 CAM-chem 数据目录，保留原名。随后执行：

```bash
# 把此路径替换成真实文件名
export CAM_NC=/实际目录/实际下载文件.nc
ncdump -h "$CAM_NC" > camchem_header.txt
ncdump -v date,datesec "$CAM_NC" > camchem_times.txt
```

要核对完整时次、lon/lat/lev、垂直坐标、PS、化学物种名、维度和单位。
目录必须覆盖整个 d01；下载日文件的文件名日期不一定等于其中每个时次，必须检查 date/datesec。
文件数量不等于时间覆盖正确。如果使用多个日文件，需要确认本版本 mozbc 的连续文件命名规则，
或先在保留坐标、单位和时间定义的前提下沿时间合并并重新检查。

## 3. 为实际数据生成两个 inp

已按本次 CBM-Z/MOSAIC 四段机制制作两份参考配置：

- d01：domain=1，do_ic=.true.，do_bc=.true.，更新 wrfinput_d01 和 wrfbdy_d01。
- d02：domain=2，do_ic=.true.，do_bc=.false.，更新 wrfinput_d02；嵌套边界从父域获得。
- dir_wrf、dir_moz 都是 ./；从最终 real 的运行目录启动，源数据用 mozart_case_0001.nc 链接。
- 气相聚合采用 NCAR CBM-Z 示例，气溶胶采用旧 MOZART 四段参考配方；目标名称核对了本地 chem_opt=9 的实际 Registry 包。

用户文件头含 OC1/OC2、CB1/CB2、SA1 等旧字段，区别于 CESM2/MAM4；当前 inp 不能直接用于后者。
官方四段示例中若干气体目标属于其他机制，已经替换为本次活动包的名称，未启用 def_missing_var 新建错误物种。
NH4NO3/NH4 的质量定义、气溶胶伪分子量及数浓度系数尚需源模型资料确认，不能声称已经完成定量质量核实。
完整公式来源、剩余假设和未映射字段处理见快速说明第 4 节。

参考：

- https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/CBMZ-MOSAIC_4bins.inp
- https://www2.acom.ucar.edu/sites/default/files/documents/CESM-WRFchem_aerosols_20190822.pdf
- https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/README.mozbc

先运行 prepare_mozbc_inputs.py 检查服务器的实际源/目标文件、时次与区域；通过后会生成两个 inp、
保留实际气象维度的正式 WRF ARI_on/off namelist，以及 mozbc_preflight.json。
本地合成文件检查通过不等于服务器数据或实际 MOZBC 插值已经通过。

## 4. 插入现有流程的位置

```text
最终一次 real（保留 chem_in_opt=0 生成初始文件）
    → 备份 wrfinput_d01、wrfinput_d02、wrfbdy_d01
    → MOZBC d01：化学 IC+BC
    → MOZBC d02：化学 IC
    → 检查化学场/边界、日志及气象变量未被意外修改
    → 正式 WRF 运行配置
    → 短测 → 完整模拟
```

正式 WRF 积分需要使用写入的化学初始场；本地 chem/chemics_init.F 在 chem_in_opt=0 时
会执行 CBM-Z 背景气体初始化。因此采用这种 real→MOZBC→WRF 路线时，须将正式 WRF 的
chem_in_opt 改为 1,1；不得把 WRF 用的配置直接提前用于首次 real，
否则 real 会转而读取 input_chem_inname 指定的另一个化学输入文件。

外域实际化学边界写入并检查后，正式 WRF 使用 have_bcs_chem=.true.,.false.，
内域 nested=.true. 使用父域边界，不制作 wrfbdy_d02。
生成器另写的 namelist.input.MOZBC.ARI_on/off 已包含这些开关；real 用的原模板仍保留 chem_in_opt=0。

MOZBC 在文件上原位写入，因此先备份，且不要把待修改文件软链到不应改动的其他试验。
MOZBC 成功后不能再运行 real 覆盖它；如必须重跑 real，随后重新运行 MOZBC。
ARI_on 和 ARI_off 都应从同一批经过 MOZBC 的初始与边界文件复制起跑。

已有 MOZBC 程序仍需检查可执行权限、ldd 动态库及它支持的数据格式。
WRF 3.9.1 如实际启用混合垂直坐标，还需相容的 MOZBC 版本；不能只凭模型版本号或程序文件名判断。
原来申请 144 核的串联脚本仍不应直接照搬本案例；MOZBC 通常按单进程运行。

MOZBC 处理的是初始/边界浓度，不会补齐 MIX 人为排放中的 VOC 分配表；两项需要分别准备。
