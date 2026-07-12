# Publishing this repository on GitHub

Checklist for turning this project into a public GitHub repository.

## 1. Before the first push

1. **Update placeholders**
   - [ ] `README.md` — replace `USERNAME/REPO` in clone URL and badges if needed  
   - [ ] `CITATION.cff` — set real `authors`, `repository-code` URL  
   - [ ] `CONTRIBUTING.md` — set clone URL  
   - [ ] Optional: add your name/organisation to the README acknowledgements or authors section  

2. **Confirm licence choice**
   - Code is MIT by default (`LICENSE`).  
   - If your institution requires another licence (Apache-2.0, GPL, etc.), replace `LICENSE` and update badges/CITATION.  

3. **Review large files**
   - Ensure `outputs/vv_db.npz` is **not** staged (listed in `.gitignore`).  
   - Maps and the classification GeoTIFF (~few MB) are fine for GitHub.  
   - If GitHub rejects a file, use [Git LFS](https://git-lfs.com/) or host large rasters on Zenodo/OSF and link them.  

4. **Sanity-check outputs**
   - Open `outputs/flood_inundation_map.jpg`.  
   - Confirm `outputs/flood_stats.json` matches the numbers cited in the README.  

## 2. Create the GitHub repository

```bash
# From the project root (example)
git status
git add .
git status   # confirm vv_db.npz is NOT listed
git commit -m "Initial release: Sentinel-1 flood inundation mapping pipeline"
```

On GitHub: **New repository** → choose public → do **not** initialise with a README if you already have one locally.

```bash
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

## 3. Repository settings (recommended)

| Setting | Suggestion |
|---------|------------|
| Description | `Sentinel-1 RTC flood inundation mapping (Planetary Computer) — Myanmar AOI, Jun–Jul 2026` |
| Topics / tags | `sentinel-1`, `flood-mapping`, `sar`, `planetary-computer`, `remote-sensing`, `geospatial`, `python` |
| Website | Optional DOI or project page |
| Social preview | Upload `outputs/flood_inundation_map.jpg` as the repository social image |
| About → Releases | Tag `v1.0.0` after first stable publish |

## 4. Optional enhancements

- **Zenodo DOI** — connect the GitHub repo to Zenodo for a citable DOI on each release.  
- **GitHub Pages** — serve `docs/` or a simple landing page with the map.  
- **Actions CI** — lint-only workflow (full STAC download may be too heavy/slow for free CI without caching).  
- **CODE_OF_CONDUCT.md** — add if you expect community contributions.  

## 5. Suggested release notes (`v1.0.0`)

```markdown
## v1.0.0 — Initial public release

- Sentinel-1 RTC download via Microsoft Planetary Computer STAC API
- VV change-detection flood mapping for Central Myanmar AOI
- Pre: 2026-06-28 · Post: 2026-07-10
- Flood inundation area: 670.5 km² (default parameters)
- Publication figure: outputs/flood_inundation_map.jpg
- Documentation: README, methodology, data sources, citation file
```

## 6. After publishing

- Update any private notes with the public URL.  
- If you write a paper or blog post, link the commit or release tag for reproducibility.  
- Keep `outputs/stac_items.json` in sync when re-running with new scenes.
