const { chromium } = require("playwright");
const fs = require("fs");
const icons = JSON.parse(fs.readFileSync("icons.json"));
// Фирменная палитра Экологической премии Москвы (ecopremia.moscow): изумрудный #00906A, мятный #2CA982,
// фиолетовый акцент #8968AA. Имена слотов прежние: forest — тёмный, moss — основной, paper — на тёмном фоне,
// amber — акцент на тёмном (лаймовый), rust — опасность (борщевик), purple — акцент на светлом.
const colors = { forest: "#00664C", moss: "#00906A", paper: "#FFFFFF", amber: "#C9EC8A", rust: "#B4532A", purple: "#8968AA" };
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 300, height: 300 } });
  fs.mkdirSync("assets/icons", { recursive: true });
  for (const [n, svg] of Object.entries(icons)) for (const [cn, col] of Object.entries(colors)) {
    await p.setContent(`<html><body style="margin:0;background:transparent"><div id="i" style="width:256px;height:256px;color:${col}">${svg}</div></body></html>`);
    await p.locator("#i").screenshot({ path: `assets/icons/${n}_${cn}.png`, omitBackground: true });
  }
  await b.close(); console.log("done");
})();
