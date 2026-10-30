const { chromium } = require("playwright");
const fs = require("fs");
const icons = JSON.parse(fs.readFileSync("icons.json"));
const colors = { forest: "#0F2A22", moss: "#2F6B55", paper: "#F4F6F1", amber: "#E0A030", rust: "#B4532A" };
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 300, height: 300 } });
  fs.mkdirSync("assets/icons", { recursive: true });
  for (const [n, svg] of Object.entries(icons)) for (const [cn, col] of Object.entries(colors)) {
    await p.setContent(`<html><body style="margin:0;background:transparent"><div id="i" style="width:256px;height:256px;color:${col}">${svg}</div></body></html>`);
    await p.locator("#i").screenshot({ path: `assets/icons/${n}_${cn}.png`, omitBackground: true });
  }
  await b.close(); console.log("done");
})();
