# 本次旧 MOZART 文件的 MOZBC 接入

适用：WRF 3.9.1、chem_opt=9（CBM-Z/MOSAIC 四段水相）、d01/d02，
2013-05-01 00 UTC 至 2013-05-03 00 UTC。已有的是用户贴出的旧 MOZART 文件头，
本机没有服务器上的实际 nc、最终 wrfinput 或 MOZBC 可执行程序，尚未执行实际插值。

已提供 `mozbc_d01.inp`、`mozbc_d02.inp`。两份都以运行目录为数据目录，
源文件统一使用短名称 `mozart_case_0001.nc`；`def_missing_var=.false.`，不为错误机制新建变量。
也提供 `prepare_mozbc_inputs.py`：在服务器检查实际数据后，生成这两份 inp、
正式 WRF 用的 ARI_on/off namelist，以及 `mozbc_preflight.json` 审核记录。
依赖现有同目录的 `check_case.py`、`prepare_runtime_namelists.py`、
`retime_mozart_for_case.py`；只需 numpy、netCDF4，不需要 f90nml。

## 1. 先完成改日期和最终 real

用 `retime_mozart_for_case.py` 生成新的日期文件；原文件保留。
修改日期不会产生真实的 2013 年化学场，须将其标为替代年份边界试验。

最终一次 `real.exe` 使用 `chem_in_opt=0,0`，成功后才接 MOZBC。
运行目录必须有本案例实际的 `wrfinput_d01`、`wrfinput_d02`、`wrfbdy_d01`、
`namelist.input`，并链接本案例的 `met_em`（其 PSFC 被 MOZBC 使用）。
不要在仍链接其他案例 wrfinput/wrfbdy 的目录执行，会原位修改链接目标。

在已有 CASE_FILES、REAL_DIR、WPS_CASE 环境变量的服务器终端执行：

```bash
# 只需要把下面两个路径改成服务器上的真实位置。
export MOZART_NC=/你的目录/mozart4geos5_retimed_20130501_20130503.nc
export MOZBC_EXE=/你的目录/mozbc

cd "$REAL_DIR"
test -s "$MOZART_NC" || exit 1
test -x "$MOZBC_EXE" || exit 1
ln -s "$MOZART_NC" mozart_case_0001.nc

# 完整流程中若已链接全部 met_em，就跳过这个循环。
for f in "$WPS_CASE"/met_em.d0*.nc; do
  test -f "$f" || continue
  name="$(basename "$f")"
  if test -e "$name"; then
    cmp -s "$f" "$name" || { echo "已有不同 met_em: $name"; exit 1; }
  else
    ln -s "$f" "$name"
  fi
done

# CASE_FILES 放新版脚本；REAL_DIR 不要预先复制同名 inp，否则生成器会拒绝覆盖。
python "$CASE_FILES/prepare_mozbc_inputs.py" --work-dir .
```

若只是查看检查结果，使用 `--check-only`，不会写输出。
如果已有同名链接或生成文件，先核实来源；脚本不会覆盖它们。

检查包括源/目标变量和单位、日期、两域完整范围、外域 8 类化学边界变量、
各需用时次的 met_em/PSFC，以及旧 MOZBC 的 164 字符映射长度。
实际源文件必须覆盖 MOZBC 所需的**精确时刻**。
该程序会在 wrfbdy 的最后一条 Times 后加一个边界间隔来计算最后的边界趋势，
所以不能仅检查 wrfbdy 的表面末时刻。若检查提示缺 2013-05-03_06:00:00 等时刻，
要重新提取覆盖该时刻的源文件和 met_em，不能改日期绕过缺失记录。

## 2. 备份，然后依次执行两个域

```bash
cd "$REAL_DIR"
# 备份路径已存在时停下，避免覆盖还原依据。
mkdir before_mozbc || exit 1
for f in wrfinput_d01 wrfinput_d02 wrfbdy_d01; do
  test -L "$f" && { echo "$f 是软链接，请先换成本案例的独立副本"; exit 1; }
  cp -p "$f" before_mozbc/ || exit 1
done

# MOZBC 单进程运行，无需 mpirun。
"$MOZBC_EXE" < mozbc_d01.inp > mozbc_d01.log 2>&1
grep -q 'bc_wrfchem completed successfully' mozbc_d01.log || { tail -60 mozbc_d01.log; exit 1; }
"$MOZBC_EXE" < mozbc_d02.inp > mozbc_d02.log 2>&1
grep -q 'bc_wrfchem completed successfully' mozbc_d02.log || { tail -60 mozbc_d02.log; exit 1; }
```

| 配置 | 写入文件 | 功能 |
|---|---|---|
| mozbc_d01.inp | wrfinput_d01、wrfbdy_d01 | 外域化学初始场及随时间变化的边界/趋势 |
| mozbc_d02.inp | wrfinput_d02 | 内域化学初始场；嵌套边界由父域提供 |

成功信息是必要检查，还需查看浓度范围和关键边界变量，不能只凭退出码判断成功。
例如可运行以下命令生成检查摘要；这不是对物种映射科学合理性的验证：

```bash
python - <<'PY'
from netCDF4 import Dataset
import numpy as np
for filename in ('wrfinput_d01', 'wrfinput_d02', 'wrfbdy_d01'):
    with Dataset(filename) as nc:
        suffix = '_BXS' if filename.startswith('wrfbdy') else ''
        for species in ('co', 'o3', 'no2', 'so4_a01', 'no3_a01', 'nh4_a01', 'num_a01'):
            name = species + suffix
            a = np.ma.asarray(nc[name][:])
            if np.ma.is_masked(a) or not np.isfinite(a).all() or (a < 0).any():
                raise ValueError(f'{filename}: invalid concentration in {name}')
            print(filename, name, 'min/max/mean:', float(a.min()), float(a.max()), float(a.mean()))
PY
```

## 3. 正式 wrf 才切换开关

生成器从**当前实际运行目录**的 namelist 保留已经修正的 metgrid/土地分类维度，
另写两份 `namelist.input.MOZBC.ARI_on` 和 `.ARI_off`：

```fortran
 chem_in_opt = 1, 1,
 have_bcs_chem = .true., .false.,
```

两份只有 `aer_ra_feedback=1,1` / `0,0` 不同。
不要提前把它们用于首次 real：本版 real 在 chem_in_opt=1 时会读取另外的化学输入文件。
也不要让正式 wrf 继续 chem_in_opt=0：本版会重新初始化 CBM-Z 背景气体。

```bash
# 建好正式目录并复制经过 MOZBC 的 wrfinput/wrfbdy 后：
cp "$REAL_DIR/namelist.input.MOZBC.ARI_on" "$ON_DIR/namelist.input"
# ARI_off 同理，使用同一批已处理的初始/边界副本：
cp "$REAL_DIR/namelist.input.MOZBC.ARI_off" "$OFF_DIR/namelist.input"
```

按 RUN_THIS_CASE.md 继续链接排放并短测/提交 wrf。
不要再运行 real 覆盖处理后的文件；如确需重跑 real，之后重新接 MOZBC。
MOZBC 不会补齐 MIX VOC 分配、MEGAN 或烟囱高度输入。

## 4. 映射来源与定量使用限制

气体采用 NCAR CBM-Z 示例中与本机制相同的聚合方案，并补充直接对应的
iso←ISOP、ho←OH、ho2←HO2。气相使用 mol/mol→ppmv 的 1e6。
因此使用 eth/par/iso/ket 等本次实际名称，不照抄其他机制的 c2h6/isopr/acet。
不把气溶胶 SO4 写入气相 sulf，也不把稳定有机硝酸酯当作 isopn 过氧自由基。

气溶胶采用 NCAR **旧 MOZART 四段参考配方**（OC1/OC2、CB1/CB2、NH4NO3、SA1 等），
未重新假定粒径谱。DUST1–4 不带 `_VMR_inst`，所以在映射中使用 `[DUST1]` 等写法。
已合并重复项和数值乘积，避免旧模板中 `0.5*3.93e17*[DUST1]` 超出解析器语法。
数浓度项把公共 1e15 提到分号后，结果与参考公式等价，且适配旧版字符串长度。

**这些是参考配置，不是论文作者确认的完整物种转换方案。** 本机核对了变量名与公式语法，
但用户文件头只提供 VMR 单位，不能据此确定气溶胶伪分子量和全部质量定义。
尤其旧例的 `NH4NO3→no3_aXX` 使用 2.76186e9，约为 80/28.97×1e9，
而纯硝酸根按 62/28.97×1e9 换算约为 2.14e9；两者差异不能忽略。
源 NH4 是否已含 NH4NO3 的铵，以及 OC/SOA/海盐/尘土的伪分子量、数浓度推导也需源模式资料确认。
这里保留参考系数并明确记录，**没有声称已完成适用于月均无机盐定量分析的质量守恒核实**。
不能只凭名称把 80 改成 62，或把 NH4NO3 再加到 NH4，来替代源物种定义的确认。

映射只覆盖有上述来源依据的字段。未映射的气体、气溶胶水及云内颗粒物，
在初始文件和边界文件中保留 real 的原值；完整清单在 `mozbc_preflight.json`。
没有批量清零未映射物种，也没有把所有化学字段都伪装成外部数据提供。

参考资料：

- [NCAR CBM-Z 气相参考](https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/CBMZ-MOSAIC_8bins.inp)
- [NCAR 旧 MOZART 四段气溶胶参考](https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/CBMZ-MOSAIC_4bins.inp)
- [MOZBC 控制参数与单位说明](https://github.com/NCAR/WRF-Chem-Preprocessing-Tools/blob/main/mozbc/README.mozbc)
