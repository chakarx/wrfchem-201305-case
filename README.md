# 论文设置与 MIX 排放处理

**唯一完整运行入口：[RUN_FINAL_CASE.md](RUN_FINAL_CASE.md)。**

从 FNL/WPS 气象场、两次 real、MEGAN 自然源、MOZBC、MIX 人为排放到短测和
ARI_on/off 的 wrf.exe 运行，均已合并到同一份最终流程，含命令、路径和成功标志。
RUN_THIS_CASE.md 仅保留跳转，不再是另一套执行顺序。
EMISSIONS_SCHEME_RUN.md、MOZBC_QUICKSTART.md 用作方案和映射参考；执行顺序以最终版为准。
新排放路线使用 mix_config.scheme.json，不读取旧 VOC 空白 CSV。
运行工具无需 f90nml。

本目录是本次修改的正式版本。上一级的 `namelist.input.emissions_fixed` 和
`emiss_opt13_variables.csv` 是针对原来 SAPRC99/27 km 配置的旧文件，本案例不要混用。
用户提供的微信目录中的原始 namelist 未改动。

本地源码标注 3.9.1，论文为 3.7.1；2010 MIX 驱动 2013 年 5 月气象、
旧 MOZART 改日期及 VOC 近似均有明确限制。MEGAN 配套静态数据尚未在本工作区准备。
脚本测试通过不等于服务器完整模型已经运行成功。

## 已完成与当前边界

- 根据 Huang et al. (2020) 全文 Methods 整理 `namelist.input`、`namelist.wps`，
  并提供只切换气溶胶辐射反馈的 `namelist.input.ARI_off`。
- 从论文给出的 MEIC/MIX 官方页面实际下载 MIX v1.1 九种污染物和 SAPRC99 分物种 VOC 原始包。
  原始 zip 保存在 `../raw_mix_v1.1/`；2010 年原始 nc 在 `../raw_mix_v1.1/2010/`。
  `download_manifest.json` 记录官方 URL、文件大小和 SHA256；zip 已校验 CRC。
- 已读取实际 nc 的维度、变量、单位、月份，完成 2010 年 5 月清单的原生网格月排放中间文件：
  `../processed/mix_v1.1_2010_05_monthly_kg.nc`，以及 `.qa.json` 核查报告。
  该文件包含 SO2、NOx、CO、NH3、NMVOC、PM25、PM10、BC、OC，五个部门和经纬度；
  单位为 kg/cell/month。它是**排放量，不是环境浓度，也不是最终 wrfchemi**。
- 对应当前气象时段的 9 个 1° FNL GRIB2 也已下载，位于 `../fnl_20130501_20130503/`；
  起止为 2013-05-01 00 UTC 至 05-03 00 UTC，6 小时一次；目录内有来源、校验清单和 WPS 使用说明。
- 已实现逐小时 wrfchemi 转换器；守恒重网格、单位换算、时区/日历、垂直权重和 NetCDF 接口的合成测试通过。
- 原始数据检查覆盖 40 个 nc、5 月的 161 个部门变量，均通过有限值、非负值、月份索引和声明单位检查；
  见 `../raw_mix_v1.1/audit_2010_05.json`。这不等于已验证跨化学机制物种分配。

**尚未生成真实网格上的最终 wrfchemi。** 还缺少新的 60/20 km 网格对应的
`wrfinput_d01`、`wrfinput_d02`；论文没有公开完整的 CBM-Z 排放物种分配与时高分配表。
本脚本要求填入可核实的 RADM2 输入 VOC 分配表，不用虚构系数或全零 VOC 生成貌似完整的文件。
已下载的 SAPRC99 数据单位为 Mmol/month，不能重命名为 RADM2/CBM-Z 物种后直接使用。

## 哪些来自论文，哪些是处理选择

论文：[Huang et al., Nature Geoscience (2020)](https://doi.org/10.1038/s41561-020-0583-4)。
全文已保存在上一级 `Huang_2020_Nature_Geoscience.pdf`，Methods 为 PDF 第 8 页。

| 项目 | 论文公开信息 | 当前处理 |
|---|---|---|
| 模型 | WRF-Chem 3.7.1 | namelist 不能切换可执行程序版本；服务器须核实源码与编译配置 |
| 模拟时段 | 2013–2018 多次跨区域霾过程，主要例子为 2017 年末 | **保留用户明确确认的 2013-05-01 00 UTC 至 05-03 00 UTC**，不声称复现冬季个例 |
| 水平分辨率 | 60/20 km 双层嵌套 | 已设置两域；原单域 27 km 文件必须重做 |
| 格点数与边界 | 未公开完整数值 | d01 91×73，d02 160×145 是当前选定值；Lambert 参数沿用原配置，须检查覆盖 NCP/YRD |
| 垂直网格 | 35 层，顶层 50 hPa，1 km 以下多于 10 层 | e_vert=36 表示 36 个界面、35 个质量层，p_top=5000 Pa；eta 是本次设计，需用 PH/PHB 实测高度验证 |
| 气象驱动 | NCEP FNL | WPS 按 6 小时边界配置；本次 9 个 FNL 已下载至相邻目录，ADP 同化资料未准备 |
| 物理方案 | YSU、Noah、Lin、Grell、RRTMG 短/长波 | 分别为 PBL=1、LSM=2、MP=2、CU=3、LW/SW=4；Grell 具体子版本论文未明确，3 是本次选择 |
| 化学机制 | CBM-Z + MOSAIC | chem_opt=9，即本地源码的四粒径段含云水化学方案；粒径段数和具体编号未由论文确认 |
| 人为源 | MIX，电力/工业/民用/交通/农业 | 下载官网 MIX v1.1；九种污染物，农业只提供 NH3 |
| MIX 基准年 | 未明确，引用 Li et al. 2017 | 原版官方清单只有 2008/2010；**本次选择 2010，不是论文已证实的年份**；不采用后来发布的 MIXv2，也不自动缩放成 2013 年排放 |
| 自然源 | 在线 MEGAN、GOCART 扬尘 | bio_emiss_opt=3；本地 MOSAIC 的 GOCART 扬尘分支是 dust_opt=13，不能照搬 GOCART 气溶胶机制下的 dust_opt=1 |
| 气溶胶反馈 | ARI on/off 平行试验 | 两份 namelist 仅 aer_ra_feedback=1/0 不同 |
| 数据同化 | 总体描述使用 NCEP ADP；ARI 平行试验明确未同化观测 | 当前配对案例 grid_fdda=0、obs_nudge_opt=0；并非否认论文其他试验使用同化 |
| 化学初边值 | 未给出完整制作文件 | 当前用模型默认廓线，没有伪造外部化学边界；have_bcs_chem=false |
| 其他时间步长、排放高度等 | 未完整公开 | 均为当前实现选择，不应标为论文原参数 |

论文还使用改进的液相/非均相反应和多组区域减排试验；这些可能涉及作者源码、地理掩膜、初始化和多次独立运行，
不能仅靠修改 namelist 完整复现。本包不把 12 月 26/30 日的 50% 减排情景自动挪到 5 月。
原 WPS 中 `geog_data_path` 和土地利用分辨率沿用；实际静态数据必须存在，`num_land_cat`
应与 geo_em 的 LU_INDEX/MMINLU 对应。`num_metgrid_levels=38` 和土壤层数沿用原案例，需核对新 met_em。

## 排放接口和计算约定

`emission_interface.csv` 的 37 个变量和单位直接提取自当前工作区 `Registry/registry.chem`
的 emiss_opt=3 包。选用 `emiss_opt=3 / emiss_inpt_opt=1` 的 RADM2 输入，由本地
`module_cbmz_addemiss.F` 转换进 CBM-Z；并非把气相机制改为 RADM2。
当前源码 emiss_opt=4 的包没有 E_PM_10，而 MOSAIC 的粗粒子添加仍读取它，因此本包选用包含该字段的接口。
若服务器源码不同，先核对服务器的 Registry 和排放驱动，不能只看机制编号。

`mix_config.json` 已按下载的**实际文件名、变量名、单位属性和 time=4 的 5 月索引**配置：

- 大部分变量属性是 `units='Mg/month'`；NH3 用大写属性 `Unit='Mg/month'`。
  Mg 是兆克，即吨；每格每月先乘 1000 转 kg。脚本不把 Mg 当毫克。
- 输入是规则的一维 lon/lat 网格；按球面等积投影中的交叠面积分配**每格总量**。
  目标格必须被原清单覆盖，不做边界外推；WRF 实际格点和投影读取自 wrfinput。
  曲线格边密化后近似计算面积；可守恒到此面积近似的精度，不声称解析球面多边形精度。
- 气体：kg → mol，再除实际格面积和完整目标月小时数；输出 mol/km²/hour。
  NOx 按 NO2 当量质量除 46.0055；在当前 input=1 的 CBM-Z 路由中全部以 E_NO 发出。
  E_NO2=0 是该路由的显式选择。
- 颗粒物输出 μg/m²/s（Registry 的 `ug/m3 m/s` 与其等价）。
  当前 BC→E_ECJ，OC→E_ORGJ；没有额外 OM/OC 倍数。
  未识别细颗粒物为 PM25−BC−OC，粗颗粒物为 PM10−PM25，避免把总 PM 重复叠加。
  细颗粒物先进入 j 模态输入，再由 MOSAIC 内部做粒径分配；不是论文已确认的粒径谱。
- 原始 MIX float32 在个别格点的 PM 差值有微小舍入误差，允许四倍 float32 精度乘各项绝对量之和的容差，
  容差内残差截到 0；超出即报错。不会静默抹掉实质负排放。
- 缺失值默认报错；只有配置明确 `missing_as_zero=true` 才补零。
  农业非 NH3 源使用带原因的显式零，因为下载的原版清单未提供这些字段。
- 小时与星期因子在**完整目标日历月**上归一化后抽取模拟时段，不把整月量集中到这两天。
  旧 mix_config.json 的均匀时间分配和全地面注入是占位设置；本次由 emission_scheme.py
  另写部门小时曲线、固定 AGL 高度带及自动 kemit，不采用旧占位设置。星期顺序为周一至周日，时区 UTC+8。
- 仅保留的旧 mass-profile 路线需要 VOC 表 `voc_profile_TO_FILL.csv`，填写质量分数和等效分子量；每部门分数和为 1。
  本次 saprc99_molar 新路线不使用该表，替代映射及局限见 EMISSIONS_SCHEME_RUN.md。
  此处指有 NMVOC 源的电力、工业、民用和交通四部门；原版 MIX 农业仅有 NH3，不填农业 VOC。
  脚本仅对配置中以非空 `zero_with_reason` 明确说明 NMVOC 缺项的部门免除 VOC 分配表要求。
  表内空白会报错，不能用合成测试里单一乙烷的示例作为科研配置。
  SAPRC99→RADM2/CBM-Z 跨机制转换须有物种/反应性映射和原始定义，不能把 NMVOC 全赋给某一种烃。
- 所有接口字段必须明确映射或提供置零原因。一次、二次无机组分不同：一次 SO4/NO3 缺少分配数据时为显式零，
  气体前体与二次化学仍启用；这不是把环境中的硫酸盐/硝酸盐浓度设为零。

## 旧 mass-profile 路线示例（本次不执行）

本节保留供接口参考。当前案例的唯一执行入口是 RUN_FINAL_CASE.md，
使用 emission_scheme.py 和 mix_config.scheme.json；不要直接运行本节的旧 build 示例。

将 `paper_case` 和相邻 `raw_mix_v1.1/2010` 保持原来的相对位置上传。
原始下载包较大，不包含在轻量代码 zip 中；可在服务器重新下载。

```bash
cd paper_case
python -m pip install -r requirements.txt
python check_case.py
python audit_mix_downloads.py --root ../raw_mix_v1.1 --month 5

# 仅在需要重新下载时执行；官网 zip 同时包含 2008/2010，脚本只解压所选年份。
python download_mix.py --year 2010 --output ../raw_mix_v1.1 --voc SAPRC99

# 查看真实数据，不需要 ncdump。
python make_mix_wrfchemi.py inspect ../raw_mix_v1.1/2010/MICS_Asia_SO2_2010_0.25x0.25.nc

# 生成原清单月排放中间文件；已有结果不会覆盖。
python prepare_monthly_mix.py --config mix_config.json --month 2013-05 \
  --output ../processed/mix_v1.1_2010_05_monthly_kg.nc
```

在 WPS/WRF 对应运行目录使用这里的新 namelist，重新运行 geogrid → ungrib → metgrid → real。
原有 27 km 的 geo_em/met_em/wrfinput/wrfchemi 与本案例不匹配，不能沿用。
新生成的 wrfinput 放到本目录，或修改 config 内 domains 的路径。

```bash
python check_case.py --wrfinput wrfinput_d01 wrfinput_d02

# 先补齐有依据的 VOC 表、时间与高度分配，再制作最终排放。
python make_mix_wrfchemi.py build --config mix_config.json

# 合成数据验证（不用原始大文件）
python -m unittest -v test_make_mix_wrfchemi
```

预期每域 49 个逐小时文件（含 5 月 3 日 00 时终点），共 98 个：

```text
wrfchemi_d01_2013-05-01_00:00:00
wrfchemi_d02_2013-05-01_00:00:00
...
wrfchemi_d02_2013-05-03_00:00:00
```

`frames_per_auxinput5=1` 与每文件一时次相配，`<date>` 拼写已修正。
Windows 文件名不能含冒号，所以脚本在 Windows 用 `_00_00_00`；**最终请在 Linux 运行 build**，
以得到 namelist 所需的标准冒号文件名，不能直接把 Windows 输出按原名放进 WRF。

脚本写的是 NETCDF3_CLASSIC，Time 为无限维，Times 长 19，排放维度为
`(Time, emissions_zdim, south_north, west_east)`；同时包含 XLAT/XLONG 和投影元数据。
输出逐域逐月来源报告，默认拒绝覆盖已有 wrfchemi。

本脚本只处理人为排放。MEGAN 需要与新网格一致的 wrfbiochemi；GOCART 扬尘需要相应土壤/侵蚀性等静态输入；
SST 更新需要 real 生成的 wrflowinp；这些不能由 MIX 九种污染物代替。
需在服务器完成 real 和短时段 WRF-Chem 检查后，再评估数值稳定性和科学结果。当前通过的是输入检查和合成测试，未宣称已运行模式。

## 原始来源

MOZBC 接入已增加两域参考配置 `mozbc_d01.inp` / `mozbc_d02.inp` 和
`prepare_mozbc_inputs.py`，操作见 [MOZBC_QUICKSTART.md](MOZBC_QUICKSTART.md)。
生成器在服务器核对实际数据后另写正式 WRF 的 ARI_on/off namelist，原 real 模板保留不变。
旧数据改日期是替代年份试验，气溶胶伪物种定义和质量换算仍有待确认项；未声称已完成实际 MOZBC 或模式运行。

- 目标论文：https://doi.org/10.1038/s41561-020-0583-4
- 原版 MIX 论文（2008/2010、0.25°、五部门）：https://doi.org/10.5194/acp-17-935-2017
- 目标论文指向的旧下载页：http://www.meicmodel.org/dataset-mix.html
- 当前官方页：http://meicmodel.org.cn/?page_id=89
- 官方原始包：见 `../raw_mix_v1.1/download_manifest.json`，包括 SAPRC99 的 31 个原始物种文件。
- WRF-Chem 用户指南中有跨机制转换的示例，但它针对具体原始物种定义，不能当成 Huang 2020 的处理表：
  https://repository.library.noaa.gov/view/noaa/11119/noaa_11119_DS1.pdf

MIX 官网说明数据仅供非商业研究、需引用原成果，并限制向第三方共享；原始数据在本机工作目录保留，不打进待分发代码 zip。
