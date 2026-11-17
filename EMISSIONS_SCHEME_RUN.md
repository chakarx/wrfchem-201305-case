# 排放制作


## 执行


```bash
cd "$CASE_FILES"
python emission_scheme.py --wrf-dir "$REAL_DIR"
python make_mix_wrfchemi.py build --config mix_config.scheme.json
```

第一个命令读取实际两域的 PH/PHB/HGT，计算足够容纳 1000 m 注入范围的公共 kemit，另写：

- mix_config.scheme.json：
- namelist.input.emissions：从 real 工作目录当前 namelist 复制，仅更新 kemit。

第二个命令生成 wrfchemi_201305_scheme/ 中的逐小时排放
每域还有 processing_dXX_201305.json，记录 VOC 原始排放量、排除量、时间/高度权重、假设和配置 SHA256。
已存在的输出不会覆盖。kemit 与新排放文件 emissions_zdim 必须一致。



## 本次采用的明确选择

VOC 直接从分物种 Mmol/month 乘 1e6 得 mol/month，守恒映射到实际网格，
主要转换采用公开研究中的 SAPRC→RADM2 映射，再通过当前 WRF 的 RADM2 输入接口进入 CBM-Z。例如：
| WRF 排放变量 | SAPRC99 输入及摩尔权重 |
|---|---|
| `E_ETH` | `ALK1` |
| `E_HC3` | `ALK2 + 1.11×ALK3 + 0.4×MEOH` |
| `E_HC5` | `0.97×ALK4` |
| `E_HC8` | `ALK5` |
| `E_TOL` | `ARO1` |
| `E_XYL` | `ARO2` |
| `E_OL2` | `ETHE` |
| `E_OLI` | `OLE2` |
| `E_CSL` | `PHEN + CRES` |
| `E_HCHO` | `HCHO` |

醛、酮和不饱和含氧物采用同一张转换表的对应分配，包含拆分到多个目标物种的项，不能只按名称一对一转换。具体参考如“Effects of Urbanization
on Regional Meteorology and Air Quality in Southern
California”


北京时间每四小时一档的小时因子：

| 部门 | 00–03 | 04–07 | 08–11 | 12–15 | 16–19 | 20–23 |
|---|---:|---:|---:|---:|---:|---:|
| 电力 | .90 | .95 | 1.10 | 1.10 | 1.05 | .90 |
| 工业 | .60 | .80 | 1.20 | 1.20 | 1.10 | .80 |
| 民用 | .50 | .90 | 1.20 | 1.00 | 1.50 | .90 |
| 交通 | .30 | .90 | 1.20 | 1.00 | 1.50 | .70 |
| 农业 | .50 | .70 | 1.20 | 1.40 | 1.10 | .70 |

高度分配：电厂和工业采用固定有效注入高度范围，其余部门近地排放。
| 部门 | 距地高度范围与排放比例 |
|---|---|
| 电力 | 100–300 m：20%；300–600 m：50%；600–1000 m：30% |
| 工业 | 0–100 m：60%；100–300 m：30%；300–600 m：10% |
| 民用 | 全部进入第一模式层 |
| 交通 | 全部进入第一模式层 |
| 农业 | 全部进入第一模式层 |

其余部门第一模式层。每个高度带内按每米均匀分配，用实际 AGL 层界的重叠厚度映射；
每格各层权重和须为 1。采用初始几何固定分配，不包含气象随时间变化引起的层高/烟羽抬升变化。

其余排放处理先固定为当前明确的基准选择。
- SO₂、CO、NH₃ 使用 MIX 对应部门的月排放。
- NOx 按 NO₂ 当量质量换算摩尔数，当前接口全部由 E_NO 输入。
- BC、OC 分别输入对应一次颗粒物字段；暂取 OM/OC＝1。
- 未识别细颗粒物取 PM2.5−BC−OC，粗颗粒物取 PM10−PM2.5。
- 缺少一次硫酸盐、硝酸盐分配资料时，不额外从总 PM 中虚构分配；保留 SO₂、NOx、NH₃ 的二次生成。
