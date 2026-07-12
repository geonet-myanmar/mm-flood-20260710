# Data sources and attribution

## Sentinel-1

| Attribute | Detail |
|-----------|--------|
| Mission | Copernicus Sentinel-1 (C-band SAR) |
| Platform used here | Sentinel-1D |
| Mode | Interferometric Wide swath (IW), GRD High resolution |
| Polarizations | VV, VH (VV used for flood detection) |
| Orbit | Ascending |
| Processing level (MPC) | Radiometrically Terrain Corrected (RTC) COGs |

**Credit line (recommended):**

> Contains modified Copernicus Sentinel data [2026], processed by ESA / retrieved via the Microsoft Planetary Computer.

## Microsoft Planetary Computer

| Attribute | Detail |
|-----------|--------|
| STAC API | https://planetarycomputer.microsoft.com/api/stac/v1 |
| Collection | [`sentinel-1-rtc`](https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc) |
| Access | Public STAC search; assets accessed via time-limited signed URLs |
| Docs | https://planetarycomputer.microsoft.com/docs |

**Credit line (recommended):**

> Data accessed through the Microsoft Planetary Computer.

## Terms of use

- **Copernicus Sentinel data** — free and open under the [Copernicus Sentinel Data Terms](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice).  
- **Planetary Computer** — [Terms of Use](https://planetarycomputer.microsoft.com/terms).  
- **This repository’s code** — MIT License (see [`LICENSE`](../LICENSE)).

When publishing maps or papers derived from this workflow, always include the
Sentinel and Planetary Computer credits above in addition to citing this software
(see [`CITATION.cff`](../CITATION.cff)).

## Scene inventory (default study)

See [`outputs/stac_items.json`](../outputs/stac_items.json) for the authoritative list.
A human-readable copy is maintained in [`METHODOLOGY.md`](METHODOLOGY.md).
