// build_map.mjs - one-time generator for render/vendor/taiwan_map.json.
//
// Turns the Ministry of the Interior county boundaries (via the MIT-licensed
// `taiwan-atlas` TopoJSON package) into plain, already-projected SVG path
// strings. The pipeline never loads TopoJSON or d3 at render time - it only
// reads the small JSON this writes - so renders stay offline and
// deterministic, same reasoning as the vendored GSAP and fonts.
//
// Usage (from this folder):  npm install && npm run build
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { feature } from "topojson-client";
import { presimplify, simplify, quantile } from "topojson-simplify";
import { geoMercator, geoPath } from "d3-geo";

const require = createRequire(import.meta.url);
const WIDTH = 620;    // map box, in the slide's own pixel space
const HEIGHT = 1000;
const KEEP = 0.25;    // quantile(topo, p) keeps roughly the most significant p share of points: ~68 KB out vs ~240 KB unsimplified
// Outlying islands far from the main island would shrink the main island
// to fit the box; they carry no data in this pipeline, so they're dropped.
const EXCLUDE = new Set(["Lienchiang County", "Kinmen County"]);

let topo = JSON.parse(readFileSync(require.resolve("taiwan-atlas/counties-10t.json"), "utf8"));
topo = presimplify(topo);
topo = simplify(topo, quantile(topo, KEEP));

const fc = feature(topo, topo.objects.counties);
fc.features = fc.features.filter((f) => !EXCLUDE.has(f.properties.COUNTYENG));

const projection = geoMercator().fitSize([WIDTH, HEIGHT], fc);
const path = geoPath(projection).digits(1);

const counties = fc.features.map((f) => {
  const [cx, cy] = path.centroid(f);
  return {
    name_en: f.properties.COUNTYENG,
    name_zh: f.properties.COUNTYNAME,
    d: path(f),
    centroid: [Math.round(cx * 10) / 10, Math.round(cy * 10) / 10],
  };
});

const out = {
  source: "taiwan-atlas@2021.9.20 counties-10t (Ministry of the Interior, via npm; MIT)",
  projection: "d3.geoMercator().fitSize",
  width: WIDTH,
  height: HEIGHT,
  excluded: [...EXCLUDE],
  counties,
};
const target = new URL("../../render/vendor/taiwan_map.json", import.meta.url);
writeFileSync(target, JSON.stringify(out));
console.log(`Wrote ${counties.length} counties -> ${target.pathname}`);
