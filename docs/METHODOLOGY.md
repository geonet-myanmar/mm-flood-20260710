# Methodology

This document describes the scientific and technical workflow implemented in
`flood_inundation_s1.py` for mapping flood inundation from Sentinel-1 SAR
using the Microsoft Planetary Computer.

## 1. Rationale

Synthetic Aperture Radar (SAR) is well suited to flood mapping because:

- It is **day/night** and largely **weather-independent** (C-band penetrates cloud).
- Smooth open water acts as a specular reflector and returns **very low backscatter**
  in co-polarized VV (and VH) channels.
- Comparing a **pre-event** and **post-event** image separates **new inundation**
  from **permanent or stable water**, which appears dark on both dates.

This pipeline uses **Radiometrically Terrain Corrected (RTC)** Sentinel-1 products
(`sentinel-1-rtc` on the Planetary Computer). RTC γ⁰/σ⁰-ready layers reduce
terrain-induced radiometric variation relative to uncorrected GRD, which improves
threshold stability over varied relief.

## 2. Study area and dates

| Item | Value |
|------|--------|
| Region | Central Myanmar (Ayeyarwady / Sittaung catchment context) |
| AOI format | GeoJSON Polygon (`data/aoi.geojson`) |
| Approximate bounds | 96.85–98.54°E, 15.77–17.76°N |
| Pre-event | **2026-06-28** |
| Post-event | **2026-07-10** |
| Sensor / mode | Sentinel-1D, IW GRDH, dual-pol VV+VH, ascending |
| Product | RTC analysis-ready COGs (Planetary Computer) |

Two overlapping RTC tiles are mosaicked per date to cover the AOI.

### Scene identifiers

**Pre-event (2026-06-28)**

- `S1D_IW_GRDH_1SDV_20260628T113726_20260628T113751_003436_0060F6_rtc`
- `S1D_IW_GRDH_1SDV_20260628T113701_20260628T113726_003436_0060F6_rtc`

**Post-event (2026-07-10)**

- `S1D_IW_GRDH_1SDV_20260710T113727_20260710T113752_003611_0066E3_rtc`
- `S1D_IW_GRDH_1SDV_20260710T113702_20260710T113727_003611_0066E3_rtc`

## 3. Processing chain

```
STAC search (space + time)
        │
        ▼
Sign asset URLs (planetary_computer)
        │
        ▼
Read VV COGs → reproject to UTM 47N → mosaic → clip AOI
        │
        ▼
Linear σ⁰ → dB   (10 · log₁₀)
        │
        ▼
Median filter (3×3) — mild speckle reduction
        │
        ▼
Water threshold (Otsu on low-backscatter regime, clipped to [−18, −14] dB)
        │
        ▼
Change rule: post dark AND ΔVV < −3 dB
        │
        ▼
Permanent water: dark on both dates AND |ΔVV| < 3 dB
        │
        ▼
Morphology (open / close / remove small objects)
        │
        ▼
Export: JPEG map · GeoTIFF class · JSON stats
```

### 3.1 Data access

- STAC endpoint: `https://planetarycomputer.microsoft.com/api/stac/v1`
- Collection: `sentinel-1-rtc`
- Spatial filter: AOI polygon intersection  
- Temporal filter: full UTC day for each target date  
- Assets: `vv` Cloud-Optimized GeoTIFFs, signed in-place with
  `planetary_computer.sign_inplace`

No API key is required for standard STAC search and signed asset access.

### 3.2 Spatial reference and resolution

| Parameter | Value | Notes |
|-----------|--------|--------|
| Target CRS | EPSG:32647 (WGS 84 / UTM zone 47N) | Appropriate for ~97°E |
| Analysis resolution | **30 m** | Source RTC ~10 m; 30 m balances AOI size, download cost, and map scale |
| Resampling | Average (when downsampling) | Preferable to nearest for continuous backscatter |
| Mosaic overlap | Mean of valid pixels | Reduces edge striping between tiles |

### 3.3 Radiometric units

Planetary Computer RTC `vv` assets are stored as **linear power**. Conversion:

\[
\sigma^0_{\mathrm{dB}} = 10 \log_{10}(\sigma^0_{\mathrm{linear}})
\]

Invalid / no-data samples are preserved as NaN and excluded from thresholding
and area statistics.

### 3.4 Speckle filtering

A **3×3 median filter** is applied in dB space with NaN-safe fill. This reduces
isolated bright/dark speckles without aggressive blurring of water edges.
Heavier multi-looking or Lee/Frost filters can be substituted if needed.

### 3.5 Water threshold

Open water is characterised by low VV backscatter. The threshold is estimated
as follows:

1. Sample valid post-event VV (dB) pixels.  
2. Restrict Otsu’s method to the **lower 40th percentile** of the distribution
   (water–land mixture regime).  
3. Clip the resulting threshold to **[−18, −14] dB** so values remain within
   literature-typical VV open-water ranges for C-band RTC.

For the published run, the constrained threshold was **−14.0 dB**.

> **Note:** Otsu is data-driven and scene-dependent. Dry seasons, wind-roughened
> water, or flooded vegetation can shift optimal thresholds. Always inspect
> pre/post panels before interpreting absolute areas.

### 3.6 Change detection and class definitions

Let \(\mathrm{VV}_{pre}\) and \(\mathrm{VV}_{post}\) be filtered backscatter in dB,
and \(\Delta\mathrm{VV} = \mathrm{VV}_{post} - \mathrm{VV}_{pre}\).

| Class | Decision rule (conceptual) |
|-------|----------------------------|
| **Post water** | \(\mathrm{VV}_{post} < T_w\) |
| **Pre water** | \(\mathrm{VV}_{pre} < T_w\) |
| **Flood inundation** | Post water **and** \(\Delta\mathrm{VV} < -3\,\mathrm{dB}\), excluding pixels that are stable pre-water with little change |
| **Permanent / stable water** | Pre water **and** post water **and** \(\lvert\Delta\mathrm{VV}\rvert < 3\,\mathrm{dB}\) |
| **Land / other** | All remaining valid pixels |

Default change magnitude: **\(\Delta\mathrm{VV} < -3.0\) dB** (post darker than pre).

This two-condition rule is a standard operational pattern for SAR flood mapping:
absolute darkness identifies water-like surfaces; the change term emphasises
**new** inundation.

### 3.7 Morphological cleanup

Applied to binary masks:

1. Morphological **opening** (disk radius 1) — remove salt noise  
2. Morphological **closing** (disk radius 2) — fill small gaps in flood bodies  
3. **Remove small objects** — discard components smaller than 40 pixels  
   (≈ 3.6 ha at 30 m)

### 3.8 Area calculation

Pixel area in map units:

\[
A_{\mathrm{pixel}} = \lvert a \cdot e \rvert
\]

where \(a\) and \(e\) are the geotransform pixel width and height (metres).
Flood area (km²) is pixel count × \(A_{\mathrm{pixel}} / 10^6\).

## 4. Published quantitative results

Results for the default configuration and AOI (July 2026 processing run):

| Quantity | Value |
|----------|--------|
| Flood inundation | **670.5 km²** |
| Permanent / stable water | **1,253.6 km²** |
| Water threshold \(T_w\) | −14.0 dB |
| Change threshold | −3.0 dB |
| Valid AOI pixels (30 m) | 23,601,141 |
| Flood pixels | 745,221 |

Exact values are written to `outputs/flood_stats.json` on each run.

## 5. Outputs

| File | Description |
|------|-------------|
| `outputs/flood_inundation_map.jpg` | Publication multi-panel figure (JPEG, high quality) |
| `outputs/flood_inundation_map.png` | Same figure as lossless PNG (optional) |
| `outputs/flood_classification.tif` | Classified GeoTIFF: 0 = nodata/land, 1 = flood, 2 = permanent water |
| `outputs/flood_stats.json` | Thresholds, pixel counts, areas |
| `outputs/stac_items.json` | STAC item IDs and AOI metadata |
| `outputs/vv_db.npz` | Cached pre/post dB arrays (large; **not** version-controlled) |

### Map figure layout

- **(a)** Pre-event VV (dB)  
- **(b)** Post-event VV (dB)  
- **(c)** Classification composite: flood (cyan), permanent water (blue), land (grey VV base)  
- Cartographic elements: 50 km scale bar, north arrow, legend with areas, method subtitle  

## 6. Limitations and caveats

1. **No independent ground truth** is included; the product is a first-pass
   SAR change detection map, not a validated emergency service product.
2. **Flooded vegetation** and **wind-roughened water** can raise VV and cause
   under-detection.
3. **Urban double-bounce** and dry flat surfaces can create false dark areas;
   the change constraint mitigates but does not eliminate commission errors.
4. **Only two dates** are used; multi-date baselining or Z-score methods can
   improve robustness (e.g. DeVries et al., 2020).
5. **HAND / DEM / JRC permanent water** masks are not applied; adding them would
   further reduce false positives on slopes and refine permanent-water class.
6. **Orbital geometry** is matched (ascending RTC pairs); mixing ascending and
   descending passes without care can introduce geometric/radiometric bias.
7. Thresholds are **scene-specific**; re-tuning is expected for other regions
   or seasons.

## 7. Configuration reference

Edit constants at the top of `flood_inundation_s1.py`:

| Constant | Default | Meaning |
|----------|---------|---------|
| `PRE_DATE` | `2026-06-28` | Pre-event UTC date |
| `POST_DATE` | `2026-07-10` | Post-event UTC date |
| `COLLECTION` | `sentinel-1-rtc` | STAC collection |
| `TARGET_RES_M` | `30` | Output resolution (m) |
| `CHANGE_DB` | `-3.0` | Max ΔVV (dB) for flood |
| `MIN_FLOOD_PIXELS` | `40` | Min object size (pixels) |
| `SPEC_SIZE` | `3` | Median filter window |
| `EPSG_UTM` | `32647` | Target projected CRS |
| `AOI` | polygon dict | Area of interest |

## 8. Selected references

- DeVries, B., et al. (2020). Rapid and robust monitoring of flood events using Sentinel-1. *Remote Sensing of Environment*.  
- Twele, A., et al. (2016). Sentinel-1-based flood mapping: a fully automated processing chain. *International Journal of Remote Sensing*.  
- Ulloa, N.I., et al. / Tupas, M.E., et al. — change indices (NDSI, etc.) for Sentinel-1 flood mapping (*Remote Sensing*).  
- Microsoft Planetary Computer — Sentinel-1 RTC dataset documentation:  
  https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc  
- ESA Copernicus Sentinel-1 User Guides:  
  https://sentinels.copernicus.eu/web/sentinel/user-guides/sentinel-1-sar  

## 9. Reproducibility checklist

- [ ] Python 3.11+ with `requirements.txt` installed  
- [ ] Network access to Planetary Computer STAC and Azure blob asset hosts  
- [ ] Unchanged `data/aoi.geojson` / script AOI (or documented AOI change)  
- [ ] Same dates and collection  
- [ ] Record `outputs/stac_items.json` item IDs for the run  
- [ ] Report `flood_stats.json` thresholds alongside area figures  

Minor differences may arise from signed URL refresh, library version changes,
or floating-point order in mosaicking; areas should agree within a small
tolerance for the same inputs and parameters.
