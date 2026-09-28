# Taiwan map asset (`render/vendor/taiwan_map.json`)

The regional map slide (`map_slide.py`) draws Taiwan's county outlines from
`render/vendor/taiwan_map.json`, a small file of already-projected SVG paths.
This folder is the one-time generator for that file. **You don't need to run it
to use the pipeline.** The generated JSON is committed, so builds and renders
never need these packages or a network connection.

## Packages

| Package | Version | License | Used for |
|---|---|---|---|
| [`taiwan-atlas`](https://www.npmjs.com/package/taiwan-atlas) | 2021.9.20 | MIT | County boundaries (TopoJSON), built from Ministry of the Interior open data |
| [`topojson-client`](https://www.npmjs.com/package/topojson-client) | 3.1.0 | ISC | TopoJSON → GeoJSON features |
| [`topojson-simplify`](https://www.npmjs.com/package/topojson-simplify) | 3.0.3 | ISC | Drops low-significance points (~240 KB → ~68 KB) |
| [`d3-geo`](https://www.npmjs.com/package/d3-geo) | 3.1.1 | ISC | Mercator projection fitted to the map box, then GeoJSON → SVG path strings |

All four are free and need no API key or signup.

## Regenerate

```bash
cd tools/taiwan_map
npm install
npm run build        # writes ../../render/vendor/taiwan_map.json
```

Settings live at the top of `build_map.mjs`:

- `WIDTH` / `HEIGHT`: the map box in slide pixels (620 × 1000).
- `KEEP`: the share of boundary points kept by simplification (0.25).
- `EXCLUDE`: counties left off the map. Kinmen and Lienchiang (Matsu) sit far
  off the main island and would shrink it to fit the box. They carry no data here.

## Output shape

```json
{
  "source": "...", "projection": "...", "width": 620, "height": 1000,
  "excluded": ["Lienchiang County", "Kinmen County"],
  "counties": [
    { "name_en": "Taipei City", "name_zh": "臺北市", "d": "M...Z", "centroid": [515.6, 127.4] }
  ]
}
```

`map_slide.py` matches cities by `name_en`. It uses `centroid` to place each
city's pin and leader line.

`node_modules/` in this folder is git-ignored.
