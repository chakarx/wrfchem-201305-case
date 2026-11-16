# 本次排放制作：可执行的基准方案

上传新版 paper_case 全部脚本，保留同级 raw_mix_v1.1/2010 中九种污染物及 31 个 SAPRC99 原始 nc。
运行依赖仍为 requirements.txt（numpy/netCDF4/scipy/pyproj/shapely），不需要 f90nml。
本机没有服务器上的最终 wrfinput，未声称已经生成真实双域的最终排放。

## 执行

先完成最终 real，并按 MOZBC_QUICKSTART.md 生成 MOZBC 的正式 WRF namelist。
MOZBC 修改浓度不改变排放所用的网格几何。
在服务器执行：

```bash
cd "$CASE_FILES"
python emission_scheme.py --wrf-dir "$REAL_DIR"
python make_mix_wrfchemi.py build --config mix_config.scheme.json
```

第一个命令读取实际两域的 PH/PHB/HGT，计算足够容纳 1000 m 注入范围的公共 kemit，另写：

- mix_config.scheme.json：本次明确方案；不再读取空白 VOC CSV。
- namelist.input.emissions：从 real 工作目录当前 namelist 复制，仅更新 kemit。
- namelist.input.MOZBC.ARI_on.emissions / .ARI_off.emissions：若 real 目录已有这两个 MOZBC 运行配置，则各自复制并更新 kemit。

第二个命令生成 wrfchemi_201305_scheme/ 中的逐小时排放，默认 49 个/域，共 98 个。
每域还有 processing_dXX_201305.json，记录 VOC 原始排放量、排除量、时间/高度权重、假设和配置 SHA256。
已存在的输出不会覆盖。kemit 与新排放文件 emissions_zdim 必须一致。
必须在 Linux 上制作最终文件，以获得含冒号的标准文件名。

MOZBC 成功并检查后，正式 ARI 运行使用更新过 kemit 的配置：

```bash
cp "$CASE_FILES/namelist.input.MOZBC.ARI_on.emissions" "$ON_DIR/namelist.input"
cp "$CASE_FILES/namelist.input.MOZBC.ARI_off.emissions" "$OFF_DIR/namelist.input"

# 两个运行目录应为新目录，没有旧同名 wrfchemi；已有旧链接须先核实来源。
for d in "$ON_DIR" "$OFF_DIR"; do
  for f in "$CASE_FILES"/wrfchemi_201305_scheme/wrfchemi_d0*; do
    ln -s "$f" "$d/$(basename "$f")" || exit 1
  done
done
```

不要用 namelist.input.emissions 覆盖正式 MOZBC 配置：它保留 real 阶段的初边值开关。
若没有生成 MOZBC 两份配置，先按快速说明执行该步骤，再重新制作排放配置；保留或改名上一次生成文件，避免覆盖。
ARI_on/off 使用同一批初始/边界和排放副本。只改 kemit 不需要再次运行 real 覆盖 MOZBC 结果。

## 本次采用的明确选择

VOC 直接从分物种 Mmol/month 乘 1e6 得 mol/month，守恒映射到实际网格，
按 Table S1 的摩尔转换系数聚合到 RADM2 输入，再交给本地 WRF 的 CBM-Z 添加排放程序。
不使用总 NMVOC 重复分配，也不再填写混合物等效分子量。
公式集中在 emission_scheme.py 的 VOC 字典，可逐项审核。

文献：[Li et al. 补充材料 Table S1](https://acp.copernicus.org/preprints/acp-2018-889/acp-2018-889-supplement.pdf)。
其中 ALK/OLE 的分组边界与 MIX 的定义不完全相同，本方案是跨机制的近似映射，不声称保存全部反应性或碳总量。

额外三项是明确的替代假设，不能归为 Table S1 原系数：

- PHEN -> CSL，摩尔系数 1。
- TERP -> OLI，摩尔系数 1，损失显式萜烯化学，未实现严格碳守恒。
- 人为 ISOP -> 0.5 ALD + 0.5 OLT，以适配当前 RADM2 输入路由；在线 MEGAN 生物源仍单独处理。

CH4/NROG/NVOL 不强塞入活性烃；各自被排除的源摩尔排放量会写入报告。
NVOL 不再叠加到 PM/OC，避免潜在重复计数，但本方案没有进一步解决其半挥发/凝结分配。
原数据没有 AACD/PACD 等显式酸字段，因此 E_ORA2=0，是输入表达的限制。
这些近似使本方案可用于明确记录假设的基准/敏感性试验，不等于完成论文原方案或定量 VOC 反应性验证。

北京时间每四小时一档的小时因子：

| 部门 | 00–03 | 04–07 | 08–11 | 12–15 | 16–19 | 20–23 |
|---|---:|---:|---:|---:|---:|---:|
| 电力 | .90 | .95 | 1.10 | 1.10 | 1.05 | .90 |
| 工业 | .60 | .80 | 1.20 | 1.20 | 1.10 | .80 |
| 民用 | .50 | .90 | 1.20 | 1.00 | 1.50 | .90 |
| 交通 | .30 | .90 | 1.20 | 1.00 | 1.50 | .70 |
| 农业 | .50 | .70 | 1.20 | 1.40 | 1.10 | .70 |

星期因子全 1；不猜测五一假期额外比例。按完整 2013 年 5 月 UTC 时间轴归一化，提取本次时段。
这组因子是本次假设，不是论文公开值或观测拟合值。

电力：100–300/300–600/600–1000 m，比例 .2/.5/.3。
工业：0–100/100–300/300–600 m，比例 .6/.3/.1。
其余部门第一模式层。每个高度带内按每米均匀分配，用实际 AGL 层界的重叠厚度映射；
每格各层权重和须为 1。采用初始几何固定分配，不包含气象随时间变化引起的层高/烟羽抬升变化。

NOx、BC、OC、PM 的其他处理沿用 README 的明确约定，未自动年际缩放 2010 排放至 2013。
