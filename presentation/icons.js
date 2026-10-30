const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const tb = require("react-icons/tb");
const fs = require("fs");
const names = ["TbSatellite", "TbDrone", "TbUsers", "TbScale", "TbRoute", "TbCamera", "TbDroplet", "TbMoodKid",
  "TbBuildingMonument", "TbTrees", "TbHome", "TbLeaf", "TbShieldCheck", "TbBuildingCommunity", "TbMicroscope",
  "TbTruck", "TbGavel", "TbPlant2", "TbRepeat", "TbClipboardCheck", "TbListNumbers", "TbCpu", "TbMap2", "TbSun",
  "TbFlask", "TbDna2", "TbWind", "TbCalendarEvent", "TbUserCheck", "TbBook2", "TbCoin", "TbHeartbeat", "TbTarget"];
const out = {};
for (const n of names) {
  if (!tb[n]) { console.error("missing", n); continue; }
  out[n] = renderToStaticMarkup(React.createElement(tb[n], { size: 256, strokeWidth: 1.6 }));
}
fs.writeFileSync("icons.json", JSON.stringify(out));
console.log(Object.keys(out).length);
