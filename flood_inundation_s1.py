#!/usr/bin/env python3
"""
Sentinel-1 flood inundation mapping via Microsoft Planetary Computer.

Pre-event:  2026-06-28
Post-event: 2026-07-10
Method: VV backscatter change detection (post dark + pre→post decrease)

Documentation
-------------
- README.md              — project overview and quick start
- docs/METHODOLOGY.md    — full processing description
- docs/DATA_SOURCES.md   — data attribution and licences
- outputs/README.md      — product catalogue

Usage
-----
    python flood_inundation_s1.py

Requires network access to the Planetary Computer STAC API. See requirements.txt.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.merge import merge
from rasterio.io import MemoryFile
from scipy import ndimage
from shapely.geometry import shape, mapping, box
from skimage.filters import threshold_otsu
from skimage.morphology import opening, closing, remove_small_objects, disk

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)

AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [96.852722, 17.408305],
            [97.80304, 17.75915],
            [98.539124, 16.143454],
            [97.613525, 15.765823],
            [96.852722, 17.408305],
        ]
    ],
}

PRE_DATE = "2026-06-28"
POST_DATE = "2026-07-10"
COLLECTION = "sentinel-1-rtc"
TARGET_RES_M = 30  # analysis resolution (m); RTC is ~10 m
CHANGE_DB = -3.0  # minimum pre→post VV decrease (dB) for new water
MIN_FLOOD_PIXELS = 40  # remove speckles smaller than this (at 30 m ≈ 3.6 ha)
SPEC_SIZE = 3  # median filter window for speckle reduction

EPSG_UTM = 32647  # WGS 84 / UTM zone 47N (covers Myanmar AOI)


def search_items(date: str):
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=[COLLECTION],
        intersects=AOI,
        datetime=f"{date}T00:00:00Z/{date}T23:59:59Z",
    )
    items = list(search.items())
    if not items:
        raise RuntimeError(f"No {COLLECTION} items for {date} over AOI")
    print(f"  {date}: {len(items)} item(s)")
    for it in items:
        print(f"    - {it.id}")
    return items


def aoi_bounds_utm():
    """Return AOI bounds in UTM and a buffered bbox for reading."""
    geom = shape(AOI)
    # Approximate center lon for UTM; we already fixed 32647
    minx, miny, maxx, maxy = geom.bounds
    # Convert corners to UTM via rasterio
    from rasterio.warp import transform_geom

    geom_utm = transform_geom("EPSG:4326", f"EPSG:{EPSG_UTM}", AOI)
    g = shape(geom_utm)
    return g.bounds, g


def load_vv_mosaic(items, geom_utm, bounds_utm, res=TARGET_RES_M):
    """
    Download VV assets, reproject to UTM, mosaic, and clip to AOI bounds.
    Returns (array linear power, transform, crs).
    """
    minx, miny, maxx, maxy = bounds_utm
    width = int(np.ceil((maxx - minx) / res))
    height = int(np.ceil((maxy - miny) / res))
    dst_transform = from_bounds(minx, miny, maxx, maxy, width, height)
    dst_crs = f"EPSG:{EPSG_UTM}"

    # Accumulate with mean of overlapping pixels
    accum = np.zeros((height, width), dtype=np.float64)
    counts = np.zeros((height, width), dtype=np.float64)

    for item in items:
        asset = item.assets["vv"]
        href = asset.href  # already signed via modifier
        print(f"    reading {item.id} ...")
        with rasterio.open(href) as src:
            # Window read where possible after transforming AOI to source CRS
            src_bounds_geom = {
                "type": "Polygon",
                "coordinates": [
                    [
                        [minx, miny],
                        [maxx, miny],
                        [maxx, maxy],
                        [minx, maxy],
                        [minx, miny],
                    ]
                ],
            }
            from rasterio.warp import transform_geom

            src_poly = transform_geom(dst_crs, src.crs, src_bounds_geom)
            sx0, sy0, sx1, sy1 = shape(src_poly).bounds
            try:
                window = rasterio.windows.from_bounds(
                    sx0, sy0, sx1, sy1, transform=src.transform
                ).intersection(
                    rasterio.windows.Window(0, 0, src.width, src.height)
                )
            except Exception:
                window = rasterio.windows.Window(0, 0, src.width, src.height)

            if window.width <= 0 or window.height <= 0:
                print("      skip: no overlap")
                continue

            data = src.read(1, window=window, masked=True).astype(np.float32)
            win_transform = src.window_transform(window)
            nodata = src.nodata

            dst = np.zeros((height, width), dtype=np.float32)
            reproject(
                source=data.filled(0) if np.ma.isMaskedArray(data) else data,
                destination=dst,
                src_transform=win_transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.average,
                src_nodata=0 if nodata is None else nodata,
                dst_nodata=0,
            )
            valid = dst > 0
            accum[valid] += dst[valid]
            counts[valid] += 1

    with np.errstate(invalid="ignore", divide="ignore"):
        mosaic = np.where(counts > 0, accum / counts, np.nan).astype(np.float32)

    # Mask outside AOI polygon
    mask_out = geometry_mask(
        [mapping(geom_utm)],
        out_shape=(height, width),
        transform=dst_transform,
        invert=False,  # True outside
    )
    mosaic[mask_out] = np.nan

    print(
        f"    mosaic: {width}x{height} px, "
        f"valid={np.isfinite(mosaic).sum():,} "
        f"({100 * np.isfinite(mosaic).mean():.1f}%)"
    )
    return mosaic, dst_transform, dst_crs


def to_db(linear: np.ndarray) -> np.ndarray:
    out = np.full_like(linear, np.nan, dtype=np.float32)
    valid = np.isfinite(linear) & (linear > 0)
    out[valid] = (10.0 * np.log10(linear[valid])).astype(np.float32)
    return out


def median_filter_nan(arr: np.ndarray, size: int = 3) -> np.ndarray:
    """Median filter that ignores NaNs via fill-then-restore."""
    filled = arr.copy()
    nan_mask = ~np.isfinite(filled)
    if nan_mask.any():
        # fill with local mean approximation: use 0 for filter then restore
        fill_val = np.nanmedian(filled)
        if not np.isfinite(fill_val):
            return arr
        filled[nan_mask] = fill_val
    filtered = ndimage.median_filter(filled, size=size)
    filtered[nan_mask] = np.nan
    return filtered.astype(np.float32)


def detect_flood(pre_db: np.ndarray, post_db: np.ndarray):
    """
    Flood = dark post-event water AND significant VV decrease (excludes permanent water).
    Water threshold from Otsu on post VV (valid pixels only), with fallback.
    """
    valid = np.isfinite(pre_db) & np.isfinite(post_db)
    post_vals = post_db[valid]
    if post_vals.size < 1000:
        raise RuntimeError("Too few valid pixels for thresholding")

    # Otsu on the low-backscatter regime (water/land mix), then constrain
    sample = post_vals if post_vals.size < 2_000_000 else np.random.default_rng(0).choice(
        post_vals, 2_000_000, replace=False
    )
    focus = sample[sample < np.percentile(sample, 40)]
    try:
        water_thr = float(threshold_otsu(focus))
    except Exception:
        water_thr = -16.0
    # VV RTC open water is typically ~-15 to -22 dB
    water_thr = float(np.clip(water_thr, -18.0, -14.0))

    delta = post_db - pre_db
    post_water = valid & (post_db < water_thr)
    pre_water = valid & (pre_db < water_thr)
    # New water: dark post + significant darkening; exclude stable dark water
    flood = post_water & (delta < CHANGE_DB) & ~(pre_water & (delta > -1.0))
    permanent = pre_water & post_water & (np.abs(delta) < 3.0)

    # Morphological cleanup
    flood_bool = opening(flood, disk(1))
    flood_bool = closing(flood_bool, disk(2))
    flood_bool = remove_small_objects(flood_bool, max_size=MIN_FLOOD_PIXELS - 1)

    perm_bool = opening(permanent, disk(1))
    perm_bool = remove_small_objects(perm_bool, max_size=MIN_FLOOD_PIXELS - 1)
    perm_bool = perm_bool & ~flood_bool

    stats = {
        "water_threshold_db": water_thr,
        "change_threshold_db": CHANGE_DB,
        "flood_pixels": int(flood_bool.sum()),
        "permanent_water_pixels": int(perm_bool.sum()),
        "valid_pixels": int(valid.sum()),
    }
    return flood_bool, perm_bool, delta, stats


def pixel_area_km2(transform) -> float:
    return abs(transform.a * transform.e) / 1e6


def make_publication_figure(
    pre_db,
    post_db,
    flood,
    permanent,
    transform,
    stats,
    out_path: Path,
):
    """Multi-panel publication-ready flood map as JPEG."""
    height, width = pre_db.shape
    minx = transform.c
    maxy = transform.f
    maxx = minx + transform.a * width
    miny = maxy + transform.e * height
    extent = [minx / 1000, maxx / 1000, miny / 1000, maxy / 1000]  # km UTM

    # Shared VV color scale
    vv_vmin, vv_vmax = -22, -5
    cmap_vv = "gray"

    fig = plt.figure(figsize=(14, 11), dpi=200, facecolor="white")
    gs = fig.add_gridspec(
        2,
        2,
        height_ratios=[1.0, 1.15],
        width_ratios=[1, 1],
        hspace=0.18,
        wspace=0.12,
        left=0.06,
        right=0.96,
        top=0.90,
        bottom=0.06,
    )

    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, :])

    def style_ax(ax, title):
        ax.set_title(title, fontsize=12, fontweight="semibold", pad=8)
        ax.set_xlabel("Easting (km, UTM 47N)", fontsize=9)
        ax.set_ylabel("Northing (km, UTM 47N)", fontsize=9)
        ax.tick_params(labelsize=8)
        ax.set_aspect("equal")
        for spine in ax.spines.values():
            spine.set_linewidth(0.6)

    # Pre
    im0 = ax0.imshow(
        pre_db,
        extent=extent,
        origin="upper",
        cmap=cmap_vv,
        vmin=vv_vmin,
        vmax=vv_vmax,
        interpolation="nearest",
    )
    style_ax(ax0, f"(a) Pre-event VV  |  {PRE_DATE}")
    cbar0 = fig.colorbar(im0, ax=ax0, fraction=0.046, pad=0.02)
    cbar0.set_label("σ⁰ VV (dB)", fontsize=8)
    cbar0.ax.tick_params(labelsize=7)

    # Post
    im1 = ax1.imshow(
        post_db,
        extent=extent,
        origin="upper",
        cmap=cmap_vv,
        vmin=vv_vmin,
        vmax=vv_vmax,
        interpolation="nearest",
    )
    style_ax(ax1, f"(b) Post-event VV  |  {POST_DATE}")
    cbar1 = fig.colorbar(im1, ax=ax1, fraction=0.046, pad=0.02)
    cbar1.set_label("σ⁰ VV (dB)", fontsize=8)
    cbar1.ax.tick_params(labelsize=7)

    # Flood map: hillshade-like context from post VV + classes
    # Base: post VV in light gray
    base = np.clip((post_db - vv_vmin) / (vv_vmax - vv_vmin), 0, 1)
    base = np.where(np.isfinite(post_db), base, np.nan)
    rgb = np.dstack([base, base, base * 0.95 + 0.05])

    # Permanent water: steel blue
    rgb[permanent] = [0.20, 0.40, 0.70]
    # Flood: vivid cyan/teal
    rgb[flood] = [0.00, 0.75, 0.85]
    # Outside AOI already NaN → set white
    nan_mask = ~np.isfinite(post_db)
    rgb[nan_mask] = [1, 1, 1]

    ax2.imshow(rgb, extent=extent, origin="upper", interpolation="nearest")
    style_ax(ax2, "(c) Flood inundation map  (new water vs permanent water)")

    # Scale bar (~50 km)
    sb_len_km = 50
    sb_x = extent[0] + 0.05 * (extent[1] - extent[0])
    sb_y = extent[2] + 0.06 * (extent[3] - extent[2])
    ax2.plot([sb_x, sb_x + sb_len_km], [sb_y, sb_y], "k-", lw=2.5, solid_capstyle="butt")
    ax2.plot([sb_x, sb_x], [sb_y - 2, sb_y + 2], "k-", lw=1.2)
    ax2.plot(
        [sb_x + sb_len_km, sb_x + sb_len_km], [sb_y - 2, sb_y + 2], "k-", lw=1.2
    )
    ax2.text(
        sb_x + sb_len_km / 2,
        sb_y + 5,
        f"{sb_len_km} km",
        ha="center",
        va="bottom",
        fontsize=8,
        fontweight="medium",
    )

    # North arrow
    nx = extent[1] - 0.08 * (extent[1] - extent[0])
    ny = extent[3] - 0.12 * (extent[3] - extent[2])
    ax2.annotate(
        "N",
        xy=(nx, ny),
        xytext=(nx, ny - 18),
        ha="center",
        fontsize=10,
        fontweight="bold",
        arrowprops=dict(arrowstyle="-|>", color="k", lw=1.5),
    )

    px_km2 = pixel_area_km2(transform)
    flood_km2 = stats["flood_pixels"] * px_km2
    perm_km2 = stats["permanent_water_pixels"] * px_km2

    legend_handles = [
        mpatches.Patch(facecolor=(0.00, 0.75, 0.85), edgecolor="k", linewidth=0.4, label=f"Flood inundation ({flood_km2:,.1f} km²)"),
        mpatches.Patch(facecolor=(0.20, 0.40, 0.70), edgecolor="k", linewidth=0.4, label=f"Permanent / stable water ({perm_km2:,.1f} km²)"),
        mpatches.Patch(facecolor=(0.75, 0.75, 0.72), edgecolor="k", linewidth=0.4, label="Land / other"),
    ]
    ax2.legend(
        handles=legend_handles,
        loc="lower right",
        fontsize=9,
        framealpha=0.92,
        edgecolor="0.5",
    )

    # Title + method note
    fig.suptitle(
        "Sentinel-1 SAR Flood Inundation Mapping — Myanmar AOI",
        fontsize=15,
        fontweight="bold",
        y=0.975,
    )
    fig.text(
        0.5,
        0.935,
        (
            f"Data: Sentinel-1 RTC (Microsoft Planetary Computer)  ·  "
            f"Pre: {PRE_DATE}  ·  Post: {POST_DATE}  ·  "
            f"Method: VV dB change detection "
            f"(post < {stats['water_threshold_db']:.1f} dB & ΔVV < {CHANGE_DB:.1f} dB)  ·  "
            f"{TARGET_RES_M} m"
        ),
        ha="center",
        va="top",
        fontsize=8.5,
        color="0.25",
    )

    fig.savefig(out_path, format="jpeg", dpi=200, bbox_inches="tight", pil_kwargs={"quality": 95})
    plt.close(fig)
    print(f"  saved figure → {out_path}")
    return flood_km2, perm_km2


def export_geotiff(flood, permanent, transform, crs, path: Path):
    """Classified GeoTIFF: 0=nodata/land, 1=flood, 2=permanent water."""
    classification = np.zeros(flood.shape, dtype=np.uint8)
    classification[permanent] = 2
    classification[flood] = 1
    # nodata where no valid analysis (use post valid approx)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=flood.shape[0],
        width=flood.shape[1],
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        compress="lzw",
        nodata=0,
    ) as dst:
        dst.write(classification, 1)
        dst.write_colormap(
            1,
            {
                0: (255, 255, 255, 0),
                1: (0, 191, 217, 255),
                2: (51, 102, 179, 255),
            },
        )
    print(f"  saved GeoTIFF → {path}")


def main():
    print("=" * 60)
    print("Sentinel-1 flood inundation (Planetary Computer)")
    print("=" * 60)

    print("\n[1/5] Searching STAC catalog ...")
    pre_items = search_items(PRE_DATE)
    post_items = search_items(POST_DATE)

    # Persist item metadata
    meta = {
        "aoi": AOI,
        "pre_date": PRE_DATE,
        "post_date": POST_DATE,
        "collection": COLLECTION,
        "pre_items": [it.id for it in pre_items],
        "post_items": [it.id for it in post_items],
        "resolution_m": TARGET_RES_M,
        "epsg": EPSG_UTM,
    }
    with open(OUT_DIR / "stac_items.json", "w") as f:
        json.dump(meta, f, indent=2)

    print("\n[2/5] Loading & mosaicking pre-event VV ...")
    bounds_utm, geom_utm = aoi_bounds_utm()
    print(f"  AOI UTM bounds: {bounds_utm}")
    pre_lin, transform, crs = load_vv_mosaic(pre_items, geom_utm, bounds_utm)

    print("\n[3/5] Loading & mosaicking post-event VV ...")
    post_lin, _, _ = load_vv_mosaic(post_items, geom_utm, bounds_utm)

    print("\n[4/5] Processing (dB convert, filter, flood detect) ...")
    pre_db = to_db(pre_lin)
    post_db = to_db(post_lin)
    del pre_lin, post_lin

    pre_db = median_filter_nan(pre_db, SPEC_SIZE)
    post_db = median_filter_nan(post_db, SPEC_SIZE)

    flood, permanent, delta, stats = detect_flood(pre_db, post_db)
    px_km2 = pixel_area_km2(transform)
    flood_km2 = stats["flood_pixels"] * px_km2
    perm_km2 = stats["permanent_water_pixels"] * px_km2
    print(f"  water threshold (Otsu, constrained): {stats['water_threshold_db']:.2f} dB")
    print(f"  flood area: {flood_km2:,.2f} km² ({stats['flood_pixels']:,} px)")
    print(f"  permanent water: {perm_km2:,.2f} km²")

    stats_out = {
        **stats,
        "flood_area_km2": flood_km2,
        "permanent_water_area_km2": perm_km2,
        "pixel_area_km2": px_km2,
    }
    with open(OUT_DIR / "flood_stats.json", "w") as f:
        json.dump(stats_out, f, indent=2)

    # Optional: save intermediate dB arrays as compressed npz
    np.savez_compressed(
        OUT_DIR / "vv_db.npz",
        pre_db=pre_db,
        post_db=post_db,
        flood=flood.astype(np.uint8),
        permanent=permanent.astype(np.uint8),
    )

    print("\n[5/5] Exporting map & products ...")
    jpeg_path = OUT_DIR / "flood_inundation_map.jpg"
    make_publication_figure(
        pre_db, post_db, flood, permanent, transform, stats, jpeg_path
    )
    export_geotiff(
        flood, permanent, transform, crs, OUT_DIR / "flood_classification.tif"
    )

    print("\nDone.")
    print(f"  Publication map: {jpeg_path.resolve()}")
    print(f"  Flood area:      {flood_km2:,.2f} km²")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
