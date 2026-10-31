// ИнваРадар — сборка презентации PowerPoint (pptxgenjs 3.12).
// Все числа берутся из outputs/*.json, поэтому слайды не расходятся с расчётами.
//   cd presentation && npm ci && node build_deck.js assets InvaRadar_Ecopremia2026.pptx
"use strict";
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const IMG = path.resolve(process.argv[2] || path.join(__dirname, "assets"));
const OUTFILE = path.resolve(process.argv[3] || path.join(__dirname, "InvaRadar_Ecopremia2026.pptx"));
const J = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), "utf8"));

// ---------------------------------------------------------------- data
const H = J("outputs/heracleum/metrics.json");
const Hn = J("outputs/variants/heracleum_no_terrain/metrics.json");
const S = J("outputs/solidago/metrics.json");
const St = J("outputs/variants/solidago_terrain/metrics.json");
const UH = J("outputs/heracleum/uncertainty.json");
const US = J("outputs/solidago/uncertainty.json");
const EH = J("outputs/heracleum/enrich_summary.json");
const ES = J("outputs/solidago/enrich_summary.json");
const XL = J("outputs/heracleum/exp_labels.json");
const PH = J("outputs/photo/metrics.json");
const DR = J("outputs/heracleum/district_route.json");
const DB = J("outputs/drone/benchmark.json").pooled;  // модуль БПЛА на реальных аэрофото, камера исключена из обучения
const TEAM = JSON.parse(fs.readFileSync(path.join(__dirname, "team.json"), "utf8"));
const isBlank = (v) => !v || /^\[.*\]$/.test(String(v).trim());
const MAP_URL = TEAM.map || "https://konkovdv.github.io/InvaRadar/";
// опубликованные наряды: CSV с полями в кавычках (внутри есть запятые и точки с запятой)
function readCsv(p) {
  const txt = fs.readFileSync(path.join(ROOT, p), "utf8");
  const rows = []; let row = [], f = "", q = false;
  for (let i = 0; i < txt.length; i++) {
    const ch = txt[i];
    if (q) { if (ch === '"') { if (txt[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += ch; }
    else if (ch === '"') q = true;
    else if (ch === ",") { row.push(f); f = ""; }
    else if (ch === "\n") { row.push(f); rows.push(row); row = []; f = ""; }
    else if (ch !== "\r") f += ch;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  const [h, ...b] = rows;
  return b.filter((r) => r.length === h.length).map((r) => Object.fromEntries(h.map((k, i) => [k, r[i]])));
}
const WO = readCsv("outputs/heracleum/work_orders_top200_2025.csv");
// пример: первый наряд, где сработали сразу три правила — водоохранная зона, дети рядом, парк или ООПТ
const WX = WO.find((o) => +o.water_zone_m > 0 && o.near_children === "True" && o.in_protected === "True") || WO[0];

// ---------------------------------------------------------------- formatting (русская типографика)
const NB = " ";
function fmt(x, d = 0) {
  const [i, f] = Number(x).toFixed(d).split(".");
  const ii = i.replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  return f ? `${ii},${f}` : ii;
}
const pct = (x, d = 1) => `${fmt(x * 100, d)}%`;
const ci = (c, d = 1) => `${fmt(c[0] * 100, d)}–${fmt(c[1] * 100, d)}%`;
const lift = (x, d = 1) => `${fmt(x, d)}${NB}раза`;

const persist10 = XL.results.all_features.persistent["@10%"];
const nPersist = XL.n_persistent;
const pr = EH.prescriptions;
const prS = ES.prescriptions;
const wz = pr.water_zone_by_width_m;

// ---------------------------------------------------------------- palette & type
// Фирменная палитра Экологической премии Москвы — снята с CSS ecopremia.moscow: изумрудный #00906A, мятный #2CA982,
// фиолетовый акцент #8968AA, текст #454545; шрифт сайта — Montserrat (SIL OFL 1.1, файлы в fonts/).
// Ключи прежние: forest — тёмные панели, moss — основной, amber — акцент на тёмном (лайм), purple — акцент на светлом.
const C = {
  paper: "F7F9F5", white: "FFFFFF", ink: "2E3A35", forest: "00775A", forest2: "0B8869", muted: "5D6A64",
  moss: "00906A", mint: "2CA982", sage: "9FD3C0", sageLight: "BFE3D6", line: "D8E0DC", tint: "E4F4EE", amber: "C9EC8A",
  purple: "8968AA", warn: "F2B33D", rust: "B4532A", gold: "C9A227", water: "2D7FB8", cream: "FFFFFF", paperDim: "D3EFE4",
};
// Montserrat — заголовки, подписи и крупные числа (как на сайте премии); Golos Text — основной текст;
// Literata — латинские названия видов и формулы (в Montserrat нет греческих букв).
const FONT = { head: "Montserrat SemiBold", serif: "Literata", body: "Golos Text", bodyBold: "Golos Text SemiBold",
  label: "Montserrat SemiBold", mono: "JetBrains Mono" };
const THEME = {
  name: "InvaRadar · Ecopremia Moscow",
  colors: { dk1: C.ink, lt1: C.white, dk2: C.forest, lt2: C.paper, accent1: C.moss, accent2: C.rust, accent3: C.purple,
            accent4: C.gold, accent5: C.water, accent6: C.sage, hlink: C.moss, folHlink: C.muted },
};
const W = 13.333, MX = 0.6, CW = W - 2 * MX;
const img = (f) => path.join(IMG, f);
// фото без искажений: внешний размер сохраняет пропорции файла, лишнее обрезается до рамки w × h
// (если задать внешние w/h равными рамке, pptxgenjs ничего не обрежет и растянет снимок);
// focus — какая часть кадра остаётся в рамке: [0, 0] — левый верх, [0.5, 0.5] — центр
const sizeOf = require("image-size");
function photo(s, file, x, y, w, h, focus = [0.5, 0.5]) {
  const d = sizeOf(img(file)), r = d.width / d.height, wide = w / h > r;
  const ow = wide ? w : h * r, oh = wide ? w / r : h;
  s.addImage({ path: img(file), x, y, w: ow, h: oh, sizing: { type: "crop", x: (ow - w) * focus[0], y: (oh - h) * focus[1], w, h } });
}
const icon = (n, c = "moss") => path.join(IMG, "icons", `${n}_${c}.png`);

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Команда ИнваРадар";
pres.company = "ИнваРадар";
pres.title = "ИнваРадар — Экопремия Москвы 2026";
pres.subject = "Номинация «Цифровизация экологических решений»";
pres.theme = { headFontFace: FONT.head, bodyFontFace: FONT.body };

// ---------------------------------------------------------------- layouts
function master(name, dark, titleX, titleW, titleH = 1.0) {
  pres.defineSlideMaster({
    title: name,
    background: dark ? { path: img("brand_cover.png") } : { path: img("brand_light.jpg") },
    margin: [0.4, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: titleX, y: 0.42, w: titleW, h: 0.32, margin: 0,
        fontFace: FONT.label, fontSize: 10.5, color: dark ? C.amber : C.moss, charSpacing: 1.5, valign: "top" }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: titleX, y: 0.76, w: titleW, h: titleH, margin: 0, align: "left",
        fontFace: FONT.head, fontSize: 22, color: dark ? C.cream : C.ink, valign: "top", lineSpacingMultiple: 0.98 },
        text: "" } },
      { text: { text: "ИнваРадар", options: { x: W - MX - 1.85, y: 7.02, w: 1.4, h: 0.3, margin: 0, align: "right",
        fontFace: FONT.label, fontSize: 10, color: dark ? C.sage : C.muted } } },
    ],
    slideNumber: { x: W - MX - 0.4, y: 7.02, w: 0.4, h: 0.3, margin: 0, align: "right", fontFace: FONT.label,
                   fontSize: 10, color: dark ? C.amber : C.moss },
  });
}
master("LIGHT", false, MX, CW);
master("DARK", true, MX, CW);
master("SPLIT", false, 7.05, W - 7.05 - MX, 1.45);
pres.defineSlideMaster({ title: "COVER", background: { color: C.forest }, objects: [] });
// акцентная полоска у надзаголовка — фиолетовая, как кнопки сайта премии
function accent(s, dark = false) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX - 0.2, y: 0.44, w: 0.07, h: 0.22, rectRadius: 0.03,
    fill: { color: dark ? C.amber : C.purple }, line: { color: dark ? C.amber : C.purple, width: 0 } });
}

// ---------------------------------------------------------------- helpers
// Русская типографика: неразрывный пробел после коротких предлогов и союзов, между числом и единицей,
// перед тире и после сокращений «ст.», «п.», «ч.», «№» — чтобы ничего не повисало в конце строки.
const SHORT = "в|к|с|и|а|о|у|я|во|ко|со|на|по|до|от|за|из|об|не|ни|но|В|К|С|И|А|О|У|Я|Во|Ко|Со|На|По|До|От|За|Из|Об|Не|Ни|Но";
const UNITS = "км²|км|м²|м|см|мм|мкм|нм|га|тыс\\.|млн|млрд|руб\\.|₽|ч|мин|дней|дня|лет|года|год|раза|раз|сезонов|точек|фото|снимков|видов|ядрах|ядра|г\\.|гг\\.|января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря";
function typo(str) {
  return String(str)
    .replace(new RegExp(`(?<=^|[\\s(«"\\u00A0])(${SHORT}) `, "g"), "$1 ")
    .replace(new RegExp(`(\\d) (?=(${UNITS})(?![\\p{L}]))`, "gu"), "$1 ")
    .replace(/ —/g, " —")
    .replace(/(?<![\p{L}])(ст|п|ч|г|гг|с|стр|прил)\. (?=[\dIVX])/gu, "$1. ")
    .replace(/(тыс\.|млн|млрд) (?=(руб\.|₽))/g, "$1 ")
    .replace(/(?<![\d,])(\d{1,3}) (?=\d{3}(?!\d))/g, "$1 ")
    .replace(/(\d) × (?=\d)/g, "$1 × ")
    .replace(/№ /g, "№ ");
}
const typoAll = (t) => (Array.isArray(t) ? t.map((r) => Object.assign({}, r, { text: typo(r.text) })) : typo(t));

let section = "";
function slide(layout, kicker, title, notes) {
  const s = pres.addSlide({ masterName: layout, sectionTitle: section });
  if (kicker) { s.addText(kicker.toUpperCase(), { placeholder: "kicker" }); if (layout !== "SPLIT") accent(s, layout === "DARK"); }
  if (title) s.addText(typo(title), { placeholder: "title" });
  if (notes) s.addNotes(notes);
  return s;
}
function newSection(t) { section = t; pres.addSection({ title: t }); }
function text(s, t, o) {
  s.addText(typoAll(t), Object.assign({ isTextBox: true, margin: 0, fontFace: FONT.body, fontSize: 14, color: C.ink, valign: "top",
    lineSpacingMultiple: 1.08 }, o));
}
function source(s, t, dark = false, x = MX, w = W - 2 * MX - 2.1) {
  text(s, t, { x, y: 6.9, w, h: 0.5, fontSize: 10, color: dark ? C.sage : C.muted, valign: "top" });
}
function label(s, t, o) { text(s, t.toUpperCase(), Object.assign({ fontFace: FONT.label, fontSize: 10.5, color: C.moss, charSpacing: 1.5 }, o)); }
function card(s, x, y, w, h, fill = C.white, line = C.line) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.16, fill: { color: fill }, line: { color: line, width: 0.75 } });
}
function iconDisc(s, name, x, y, d = 0.56, disc = C.tint, col = "moss") {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: disc }, line: { color: disc, width: 0 } });
  const p = d * 0.58;
  s.addImage({ path: icon(name, col), x: x + (d - p) / 2, y: y + (d - p) / 2, w: p, h: p });
}
// QR-код фигурами (вектор, без картинки): тёмные модули по строкам сливаются в полосы, светлое поле — 4 модуля
function qr(s, url, x, y, size) {
  const m = require("qrcode").create(url, { errorCorrectionLevel: "M" }).modules;
  const n = m.size, Z = 4, q = size / (n + 2 * Z), ov = q * 0.06;
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: size, h: size, fill: { color: C.white }, line: { color: C.white, width: 0 } });
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n;) {
      if (!m.get(r, c)) { c++; continue; }
      let e = c; while (e < n && m.get(r, e)) e++;
      s.addShape(pres.shapes.RECTANGLE, { x: x + (c + Z) * q, y: y + (r + Z) * q, w: (e - c) * q + ov, h: q + ov,
        fill: { color: "1B2B25" }, line: { color: "1B2B25", width: 0 } });
      c = e;
    }
  }
}
// карточка «живая карта»: белая подложка, QR и подпись
function mapCard(s, x, y, size, caption = "Живая карта очагов") {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.14, y: y - 0.14, w: size + 0.28, h: size + 0.78, rectRadius: 0.12,
    fill: { color: C.white }, line: { color: C.white, width: 0 } });
  qr(s, MAP_URL, x, y, size);
  text(s, [{ text: caption, options: { fontFace: FONT.head, fontSize: 11, color: C.forest, breakLine: true } },
    { text: MAP_URL.replace(/^https?:\/\//, "").replace(/\/$/, ""), options: { fontSize: size < 1.8 ? 7.5 : 9, color: C.muted, hyperlink: { url: MAP_URL } } }],
    { x: x - 0.12, y: y + size + 0.06, w: size + 0.24, h: 0.5, align: "center" });
}
// греческие буквы и штрихи есть не во всех шрифтах: такие символы пишутся Literata
function greek(str, base = {}) {
  const out = []; let buf = "", gr = false;
  const flush = () => { if (buf) out.push({ text: buf, options: Object.assign({}, base, gr ? { fontFace: FONT.serif } : {}) }); buf = ""; };
  for (const ch of str) { const g = /[\u0370-\u03FF\u2032\u2033]/.test(ch); if (g !== gr) { flush(); gr = g; } buf += ch; }
  flush(); return out;
}
function credit(s, t, x, y, w, color = C.cream) {
  text(s, t, { x, y, w, h: 0.26, fontSize: 10, color, fontFace: FONT.body });
}
function arrow(s, x1, y1, x2, y2, color = C.sage, width = 1.5) {
  s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1, line: { color, width, endArrowType: "triangle" } });
}
function bigStat(s, value, caption, x, y, w, color = C.rust, size = 34, capSize = 13.5, capH = 0.95) {
  text(s, value, { x, y, w, h: 0.62, fontFace: FONT.head, fontSize: size, color, valign: "bottom" });
  text(s, caption, { x, y: y + 0.68, w, h: capH, fontSize: capSize, color: C.ink });
}
const chartText = { catAxisLabelFontFace: FONT.body, valAxisLabelFontFace: FONT.body, dataLabelFontFace: FONT.body,
                    legendFontFace: FONT.body, titleFontFace: FONT.body };

// ================================================================ 1. COVER
newSection("Суть");
{
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: section });
  photo(s, "hero_stand.jpg", 4.4, 0, W - 4.4, 7.5);
  s.addImage({ path: img("overlay_left.png"), x: 0, y: 0, w: W, h: 7.5 });
  photo(s, "brand_cover.png", 0, 0, 4.42, 7.5, [0, 0.5]);
  text(s, "ЭКОПРЕМИЯ МОСКВЫ 2026\nЦИФРОВИЗАЦИЯ ЭКОЛОГИЧЕСКИХ РЕШЕНИЙ", { x: MX, y: 0.6, w: 6.2, h: 0.62, fontFace: FONT.label,
    fontSize: 11, color: C.amber, charSpacing: 2, lineSpacingMultiple: 1.3 });
  text(s, "ИнваРадар", { x: MX, y: 1.75, w: 6.4, h: 1.2, fontFace: FONT.head, fontSize: 66, color: C.cream });
  text(s, "Находим борщевик и золотарник по спутниковым данным и отправляем бригаду туда, где они опаснее всего для людей",
    { x: MX, y: 3.15, w: 6.1, h: 1.55, fontSize: 21, color: C.cream, lineSpacingMultiple: 1.12 });
  text(s, [
    { text: "Heracleum sosnowskyi", options: { italic: true } }, { text: " Manden.  ·  " },
    { text: "Solidago canadensis", options: { italic: true } }, { text: " L.  ·  " },
    { text: "S. gigantea", options: { italic: true } }, { text: " Aiton" },
  ], { x: MX, y: 4.9, w: 6.2, h: 0.62, fontFace: FONT.serif, fontSize: 13, color: C.sage });
  text(s, "спутник → очередь по риску → дрон и житель →\nнаряд → контрольный снимок",
    { x: MX, y: 6.1, w: 6.2, h: 0.62, fontFace: FONT.label, fontSize: 11.5, color: C.paperDim, lineSpacingMultiple: 1.3 });
  credit(s, "Фото: Maxim Shashkov, iNaturalist, CC BY", W - 4.2, 7.08, 3.9, C.paperDim);
  mapCard(s, W - 2.35, 4.25, 1.55);
  s.addNotes("Добрый день. ИнваРадар — система, которая находит борщевик Сосновского и золотарники по спутниковым данным и превращает карту в задание для бригады. Главная мысль, которую прошу запомнить: мы не делаем ещё одну карту. Мы замыкаем цикл от снимка до проверки результата работ. На фото — заросли борщевика в Калужской области, так выглядит то, что мы ищем.");
}

// ================================================================ 2. SUMMARY
{
  const s = slide("LIGHT", "Коротко", "ИнваРадар превращает спутниковые данные в наряд для бригады: адрес очага, допустимый метод работ и правовое основание",
    "Три тезиса. Первый: борщевик растёт быстрее, чем его успевают найти пешком. Второй: мы связываем спутник, модель риска, дрон, жителей и бригаду в один цикл. Третий: это уже работает на реальных данных Москвы. Карта на 4 225 квадратных километров, шестнадцать тысяч очагов, у каждого есть метод работ по закону. В конце попросим один полевой сезон на трёх территориях.");
  const cols = [
    { k: "Проблема", v: `22–27${NB}тыс.${NB}га`, t: "прибавляет борщевик каждый год только на сельхозземлях России. Ищут его пешком и по жалобам жителей." },
    { k: "Решение", v: "5 шагов", t: "Спутник сужает поиск, модель ставит очередь по риску для людей, дрон и жители подтверждают, бригада получает наряд, контрольный снимок закрывает очаг." },
    { k: "Уже работает", v: `${fmt(4225)}${NB}км²`, t: `Москва и ближнее Подмосковье с шагом 10${NB}м: ${fmt(H.hotspots.count)} вероятных очагов борщевика, ${fmt(pr.near_children_100m)} из них в 100${NB}м от детских площадок, садов и школ.` },
  ];
  cols.forEach((c, i) => {
    const x = MX + i * 4.12;
    label(s, c.k, { x, y: 2.15, w: 3.8, h: 0.3 });
    text(s, c.v, { x, y: 2.5, w: 3.85, h: 0.75, fontFace: FONT.head, fontSize: 34, color: i === 2 ? C.moss : C.rust, valign: "bottom" });
    text(s, c.t, { x, y: 3.42, w: 3.75, h: 1.9, fontSize: 15 });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX, y: 5.62, w: CW, h: 0.98, rectRadius: 0.08, fill: { color: C.forest }, line: { color: C.forest, width: 0 } });
  text(s, "ЗАПРОС", { x: MX + 0.35, y: 5.95, w: 1.3, h: 0.3, fontFace: FONT.label, fontSize: 11, color: C.amber, charSpacing: 2 });
  text(s, "Пилот на трёх природных территориях Москвы в сезон 2027 года вместе с Мосприродой и ботаниками ГБС РАН («Инвазиум»)",
    { x: MX + 1.75, y: 5.8, w: CW - 2.1, h: 0.66, fontSize: 16, color: C.cream, valign: "middle" });
  source(s, "Источники: Россельхознадзор (2026); расчёты ИнваРадара 1.2 на открытых данных, октябрь 2026");
}

// ================================================================ 3. PROBLEM
newSection("Проблема");
{
  const s = slide("SPLIT", "Проблема", `Борщевик захватывает 22–27${NB}тыс.${NB}га в год, а ищут его пешком и по жалобам`,
    "Россельхознадзор за четыре года нашёл больше 93 тысяч гектаров заражённых сельхозземель, и каждый год добавляется ещё 22–27 тысяч. Подмосковье только в этом сезоне планировало обработать 23,4 тысячи гектаров. В Москве на ООПТ Мосприрода выкашивает борщевик до десяти раз за лето — это огромный ручной труд, и он начинается с вопроса «где». Сок растения вызывает тяжёлые ожоги, а модель Сколтеха показывает, что к середине века условия для борщевика будут почти на всей европейской части страны.");
  photo(s, "powerline.jpg", 0, 0, 6.6, 7.5);
  s.addImage({ path: img("overlay_bottom.png"), x: 0, y: 5.6, w: 6.6, h: 1.9 });
  credit(s, "Борщевик под ЛЭП, Московская область, июль 2026. Фото: Stanislav Murashkin, iNaturalist, CC BY", 0.35, 6.95, 6.0);
  const x = 7.05, w = W - 7.05 - MX;
  bigStat(s, `93${NB}тыс.${NB}га`, "заражённых сельхозземель выявлено за четыре года; площади растут на 10–20% в год", x, 2.2, w, C.rust, 30, 13, 0.55);
  bigStat(s, `23,4${NB}тыс.${NB}га`, "Подмосковье планировало обработать только в сезон 2026 года", x, 3.45, w, C.rust, 30, 13, 0.55);
  bigStat(s, `до${NB}10${NB}раз`, "за лето Мосприрода выкашивает борщевик на особо охраняемых природных территориях Москвы", x, 4.7, w, C.rust, 30, 13, 0.55);
  text(s, "Сок растения вызывает фотохимические ожоги. По модели Сколтеха, к 2040–2060 годам условия для борщевика сложатся почти на всей европейской части России.",
    { x, y: 5.95, w, h: 0.85, fontSize: 12, color: C.muted });
  source(s, "Россельхознадзор, ВНИИКР (The Moscow Times, 26.08.2026); Минсельхоз МО (06.2026); mos.ru; Koldasbayeva et al., Sci. Rep. 12, 6175 (2022)", false, 7.05, W - 7.05 - MX - 1.9);
}

// ================================================================ 4. WHY NOW
{
  const s = slide("LIGHT", "Почему сейчас", "В 2026 году сошлись три условия: закон обязал бороться с борщевиком, небо Москвы закрыто для дронов, спутниковый ИИ стал открытым",
    "Почему это нельзя было сделать раньше и почему нельзя откладывать. С 1 марта 2026 года действует 294-ФЗ: бороться с опасными инвазивными растениями обязан любой правообладатель, и штрафуют за бездействие. Значит, нужна карта, которой можно доверять. Второе: с мая 2023 года полёты гражданских дронов над Москвой ограничены, а с 20 июня 2026 года Росавиация распространила ограничения на большую часть Подмосковья — летают только государственная и экспериментальная авиация. Сплошной облёт невозможен, поэтому искать надо из космоса, а дрон отправлять точечно по госзаданию. При этом правовой режим для гражданских дронов строится: Минтранс до конца 2027 года тестирует регулярные полёты в пяти регионах, и модуль БПЛА к этому готов. Третье: летом 2025 года Google DeepMind открыла эмбеддинги AlphaEarth, и карту города теперь можно посчитать за минуты. Москва поставила цель: за три года избавиться от борщевика и золотарников, а мероприятия по этой группе в постановлении 369-ПП начинаются с 1 января 2027 года. Сезон 2027 — первый, и к нему нужна карта. Подмосковье уже выписало первый штраф по данным спутника, дрона и ИИ — направление выбрано государством.");
  const cards = [
    { ic: "TbGavel", k: "Закон", t: `С 1 марта 2026 г. бороться с опасными инвазивными растениями обязан каждый правообладатель (294-ФЗ). Штраф по ст. 8.7 КоАП — 20–50${NB}тыс.${NB}₽ для граждан и до 700${NB}тыс.${NB}₽ для компаний. Нужна карта, которая выдержит проверку.` },
    { ic: "TbDrone", k: "Небо", t: "Гражданские дроны над Москвой ограничены с мая 2023 г., а с 20 июня 2026 г. — и над большей частью Подмосковья; летают только государственная и экспериментальная авиация. Искать нужно со спутника, дрон — точечно, по заданию органа власти." },
    { ic: "TbSatellite", k: "Технология", t: `В июле 2025 г. Google DeepMind открыла эмбеддинги AlphaEarth Foundations: 64 числа на каждые 10${NB}м поверхности Земли за каждый год. Карта города считается за минуты, а не месяцы.` },
  ];
  cards.forEach((c, i) => {
    const x = MX + i * 4.12, y = 2.12, w = 3.88, h = 3.35;
    card(s, x, y, w, h);
    iconDisc(s, c.ic, x + 0.3, y + 0.3);
    text(s, c.k, { x: x + 1.0, y: y + 0.38, w: w - 1.2, h: 0.4, fontFace: FONT.head, fontSize: 19, color: C.ink });
    text(s, c.t, { x: x + 0.3, y: y + 1.05, w: w - 0.55, h: h - 1.2, fontSize: 13.5 });
  });
  iconDisc(s, "TbTarget", MX, 5.78, 0.5, C.forest, "amber");
  text(s, `Москва намерена за три года избавиться от видов группы I — борщевика Сосновского и золотарников (369-ПП, мероприятия по группе I — с 01.01.2027). Подмосковье в августе 2026 г. выписало первый штраф по данным спутника, дрона и ИИ — 150${NB}тыс.${NB}₽.`,
    { x: MX + 0.7, y: 5.66, w: CW - 0.7, h: 0.8, fontSize: 14, color: C.ink, valign: "middle" });
  source(s, "294-ФЗ от 31.07.2025; КоАП РФ ст. 8.7; пост. Правительства Москвы от 03.03.2026 № 369-ПП; Ю. Урожаева, Мосгордума, 11.11.2025 (Коммерсантъ, 12.11.2025); решение Мэра Москвы о запрете полётов БПЛА (03.05.2023); Росавиация, 17.06.2026; Google DeepMind, 30.07.2025; riamo.ru, 07.08.2026");
}

// ================================================================ 5. STAKEHOLDERS
{
  const s = slide("LIGHT", "Чья это боль", "У каждого участника своя часть картины, и ни у кого нет цикла целиком",
    "Пройдусь по ролям. С апреля 2026 года инспекторы «Контроля Москвы» осматривают рисковые участки по плану, не дожидаясь жалоб, — первые 43 обследования прошли на 11 особо охраняемых зелёных территориях. Им нужен список таких участков на весь город, и это ровно наша очередь. Мосприроде нужна проверка, что покос сработал. Ботаники «Инвазиума» вручную модерируют фото волонтёров. Жители боятся ожогов и не видят, что их жалобу услышали. Подрядчики обрабатывают сплошь и не могут доказать объём работ. Надзор в Подмосковье тратит время на поиск владельца участка. Каждой роли ИнваРадар даёт свой выход из одной и той же системы.");
  const rows = [
    ["TbBuildingCommunity", "Департамент, «Контроль Москвы», Мосприрода", "Плановые осмотры рисковых участков идут с апреля 2026 г., пока на 11 ООЗТ; эффект покоса сложно измерить", "Очередь рисковых участков на весь город, карта 10 м раз в год, отчёт «до и после»"],
    ["TbMicroscope", "ГБС РАН, «Инвазиум»", "Фото волонтёров проверяют вручную, связи со спутником нет", "ИИ-проверка вида на фото и привязка к карте риска"],
    ["TbUsers", "Жители", "Ожоги, дети рядом с зарослями; хочется видеть, что по сообщению начаты работы", "Фото → проверка → статус работ на карте"],
    ["TbTruck", "Подрядчики", "Сплошная обработка, перерасход гербицида, работу трудно доказать", "Контур куртины, наряд на точечную обработку, фотофиксация"],
    ["TbGavel", "Надзор Подмосковья", "70% обращений касаются частных участков; владельца ищут вручную", "Очаг → кадастровый участок → предписание"],
  ];
  label(s, "кто", { x: MX + 0.75, y: 2.0, w: 2.5, h: 0.28 });
  label(s, "что болит сегодня", { x: MX + 3.4, y: 2.0, w: 4.2, h: 0.28 });
  label(s, "что даёт ИнваРадар", { x: MX + 7.85, y: 2.0, w: 4.2, h: 0.28 });
  rows.forEach((r, i) => {
    const y = 2.38 + i * 0.86;
    if (i % 2 === 0) s.addShape(pres.shapes.RECTANGLE, { x: MX, y: y - 0.06, w: CW, h: 0.8, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
    iconDisc(s, r[0], MX + 0.08, y + 0.06, 0.52, C.white);
    text(s, r[1], { x: MX + 0.75, y, w: 2.5, h: 0.7, fontFace: FONT.bodyBold, fontSize: 14, valign: "middle" });
    text(s, r[2], { x: MX + 3.4, y, w: 4.2, h: 0.7, fontSize: 13, valign: "middle", color: C.muted });
    text(s, r[3], { x: MX + 7.85, y, w: 4.25, h: 0.7, fontSize: 13, valign: "middle" });
  });
  source(s, "Мосприрода и «Контроль Москвы», mos.ru (19.08.2026); проект «Инвазиум», ГБС РАН им. Н. В. Цицина; министр сельского хозяйства МО В. Мосин (август 2026)");
}

// ================================================================ 6. LOOP
newSection("Решение");
{
  const s = slide("DARK", "Решение", "Пять шагов: карта, очередь, проверка вида, проект наряда, контроль с места",
    "Это центральный слайд. Шаг первый — спутник: раз в год карта относительного риска по всему городу с шагом 10 метров. Это процентиль ландшафта, не вероятность. Второй — очередь: рядом с детьми размер не влияет, для сдерживания важнее малый изолированный очаг, массивы от гектара идут отдельной программой. Третий — проверка: дрон по госзаданию обводит куртину, житель присылает фото, модель предлагает вид, человек подтверждает. Четвёртый — проект наряда: метод по открытым слоям, кадастровый номер; сведения о правообладателе запрашивает уполномоченный орган. Пятый — контроль дроном или фото с места; спутник обновляется раз в сезон. Замкнутого дообучения на новых фото в скриптах нет. У Департамента уже есть свой контур, эта система его дополняет.");
  s.addImage({ path: img("contours_dark.png"), x: 6.3, y: -0.3, w: 7.4, h: 7.4, transparency: 55 });
  const steps = [
    ["TbSatellite", "Спутник", "Процентиль ландшафта, шаг 10 м, раз в год. Окна цветения Sentinel-2 в этой версии не считаются"],
    ["TbListNumbers", "Очередь", "У детей размер не влияет; отдельно малые изолированные очаги и массивы от 1 га"],
    ["TbDrone", "Проверка", "Дрон по госзаданию обводит куртину; житель присылает фото, ИИ проверяет вид"],
    ["TbClipboardCheck", "Наряд", "Метод работ по закону, владелец участка по кадастру, оповещение жителей"],
    ["TbRepeat", "Контроль", "Дрон или фото с места: кандидат закрыт или остался. Спутник — раз в сезон"],
  ];
  const w = 2.25, gap = 0.22, y = 2.25, h = 3.0;
  steps.forEach((st, i) => {
    const x = MX + i * (w + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: C.forest2 }, line: { color: "2C5446", width: 0.75 } });
    iconDisc(s, st[0], x + 0.22, y + 0.25, 0.56, C.forest, "amber");
    text(s, `${i + 1}`, { x: x + w - 0.6, y: y + 0.27, w: 0.4, h: 0.4, fontFace: FONT.label, fontSize: 14, color: C.sage, align: "right" });
    text(s, st[1], { x: x + 0.22, y: y + 0.98, w: w - 0.4, h: 0.4, fontFace: FONT.head, fontSize: 18, color: C.cream });
    text(s, st[2], { x: x + 0.22, y: y + 1.45, w: w - 0.38, h: 1.5, fontSize: 12.5, color: C.paperDim });
    if (i < 4) arrow(s, x + w + 0.02, y + h / 2, x + w + gap - 0.02, y + h / 2, C.amber, 1.5);
  });
  // обратная связь: от «Контроля» назад к «Спутнику»
  const xl = MX + w / 2, xr = MX + 4 * (w + gap) + w / 2, yb = y + h + 0.42;
  s.addShape(pres.shapes.LINE, { x: xr, y: y + h, w: 0.001, h: 0.42, line: { color: C.amber, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: xl, y: yb, w: xr - xl, h: 0.001, line: { color: C.amber, width: 1.5 } });
  arrow(s, xl, yb, xl, y + h + 0.02, C.amber, 1.5);
  text(s, "проверенные очаги становятся разметкой: каждый сезон модель точнее, карта становится открытым набором данных",
    { x: xl + 0.4, y: yb + 0.1, w: xr - xl - 0.8, h: 0.5, fontSize: 13.5, color: C.cream, align: "center" });
}

// ================================================================ 7. LEVELS
{
  const s = slide("LIGHT", "Технологии", "Каждый уровень съёмки делает то, что умеет лучше других: космос сужает поиск, дрон обводит куртину, житель подтверждает вид",
    "Мы не привязаны к одной модели. Для космоса берём геопространственные базовые модели — по бенчмарку GEO-Bench-2 на мультиспектральных данных лидируют TerraMind и Prithvi-EO-2.0. Для дрона — замороженная модель DINOv2 и линейный классификатор поверх неё. На картинке посередине — схема: модуль делит снимок на патчи 14 на 14 пикселей и отмечает те, где есть борщевик. Проверка — на 263 реальных аэроснимках Подмосковья из открытого набора Сколтеха, причём камера, снявшая проверочный кадр, в обучении не участвовала: ROC AUC 0,95. Для фото жителей — классификатор вида. Ядро написано на Rust: 42 миллиона пикселей за две минуты на четырёх ядрах.");
  const cols = [
    { im: "heracleum_city.png", ic: "TbSatellite", k: "Космос", now: "AlphaEarth Foundations (10 м), рельеф Copernicus DEM, LightGBM", next: "окна цветения Sentinel-2, TerraMind / Prithvi-EO-2.0", give: "Скрининг всего города за минуты, динамика по годам" },
    { im: "drone_patches.jpg", ic: "TbDrone", k: "Дрон", now: `DINOv2 + линейный классификатор; ${DB.images} аэрофото Подмосковья, камера проверки вне обучения`, next: "дообучение на облётах, RF-DETR-Seg (Apache-2.0)", give: `Борщевик и фон различает в ${fmt(DB.patch_roc_auc * 100)} случаях из 100 (ROC AUC)` },
    { im: "umbel.jpg", ic: "TbCamera", k: "Житель", now: "классификатор вида против двойников, 13 000 фото iNaturalist", next: "дообучение на фото «Инвазиума», BioCLIP 2", give: "Автомодерация сообщений и привязка к карте" },
  ];
  cols.forEach((c, i) => {
    const x = MX + i * 4.12, w = 3.88;
    photo(s, c.im, x, 2.05, w, 1.85);
    iconDisc(s, c.ic, x + 0.12, 2.17, 0.5, C.white);
    text(s, c.k, { x, y: 4.02, w, h: 0.38, fontFace: FONT.head, fontSize: 18 });
    text(s, [
      { text: "Сейчас: ", options: { fontFace: FONT.bodyBold } }, { text: c.now, options: { breakLine: true } },
      { text: "Пилот: ", options: { fontFace: FONT.bodyBold } }, { text: c.next, options: { breakLine: true } },
      { text: c.give, options: { color: C.moss } },
    ], { x, y: 4.42, w, h: 1.75, fontSize: 12.5, paraSpaceAfter: 3 });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX, y: 6.2, w: CW, h: 0.62, rectRadius: 0.08, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
  iconDisc(s, "TbCpu", MX + 0.12, 6.26, 0.5, C.white);
  text(s, `Ядро на Rust: 265 признаков на пиксель, результат совпадает с эталонной моделью до 15-го знака, карта 42 млн пикселей — за 2 минуты на обычном сервере`,
    { x: MX + 0.8, y: 6.2, w: CW - 1.0, h: 0.62, fontSize: 13, valign: "middle" });
}

// ================================================================ 8. BOTANY
newSection("Наука");
{
  const s = slide("LIGHT", "Ботаника и биохимия", "Биология вида задаёт сроки работ, способ удаления и срок наблюдения за очагом",
    "Каждое правило в системе следует из биологии. Борщевик обычно цветёт один раз в жизни, на третий–шестой год, и после плодоношения отмирает. Значит, главное — не дать ему отцвести, порядок объезда по цветению не сортируется. Точка возобновления сидит в корневой шейке: покос её не убивает, нужна подрезка ниже уровня почвы. Одно растение даёт 15–20 тысяч семян; большая часть прорастает следующей весной, но часть живёт два-три года, а скошенные розетки откладывают цветение. Отсюда пять сезонов наблюдения. И внизу — почему борщевик опасен: фурокумарины сока под ультрафиолетом сшиваются с ДНК клеток кожи.");
  photo(s, "umbel.jpg", MX, 2.0, 3.0, 2.5);
  photo(s, "stem.jpg", MX + 3.12, 2.0, 1.5, 2.5);
  text(s, [{ text: "Heracleum sosnowskyi", options: { italic: true } }, { text: " Manden.: сложный зонтик до 50 см и стебель с пурпурными пятнами" }],
    { x: MX, y: 4.58, w: 4.62, h: 0.5, fontFace: FONT.serif, fontSize: 11.5, color: C.muted });
  const rows = [
    ["Цветёт один раз, обычно на 3–6-й год, и после плодоношения отмирает", "Не дать отцвести: зонтики срезают до конца июля. Очередь по фенофазе не строится"],
    ["Точка возобновления — в корневой шейке", "Подрезка на 5–10 см ниже уровня почвы вместо покоса, после которого растение отрастает"],
    ["15–20 тыс. семян; большинство прорастает весной, единицы процентов живут 2–3 года", "Пять сезонов наблюдения: остаток семян в почве и розетки, отложившие цветение"],
    ["Семена падают в основном в нескольких метрах; дальше их несут вода, техника, грунт", "Расстояния до рек, дорог, железных дорог и ЛЭП — признаки модели и множитель приоритета"],
  ];
  const x0 = MX + 5.0, wf = 3.35, wd = CW - 5.0 - wf - 0.25;
  label(s, "факт", { x: x0, y: 2.0, w: wf, h: 0.28 });
  label(s, "решение в системе", { x: x0 + wf + 0.25, y: 2.0, w: wd, h: 0.28 });
  rows.forEach((r, i) => {
    const y = 2.35 + i * 0.7;
    s.addShape(pres.shapes.LINE, { x: x0, y: y - 0.04, w: CW - 5.0, h: 0.001, line: { color: C.line, width: 0.75 } });
    text(s, r[0], { x: x0, y, w: wf, h: 0.66, fontSize: 12, color: C.muted });
    text(s, r[1], { x: x0 + wf + 0.25, y, w: wd, h: 0.66, fontSize: 12 });
  });
  // фотохимия ожога
  const chain = [
    ["TbFlask", "Фурокумарины сока: псорален, ксантотоксин, бергаптен"],
    ["TbDna2", "Встраиваются в ДНК клеток кожи"],
    ["TbSun", "УФ-А 320–400 нм сшивает их с тимином, образуются активные формы кислорода"],
    ["TbHeartbeat", "Ожог через 24–48 ч, пигментация держится месяцами"],
  ];
  const cw = (CW - 3 * 0.35) / 4;
  chain.forEach((c, i) => {
    const x = MX + i * (cw + 0.35), y = 5.3;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: 1.3, rectRadius: 0.08, fill: { color: "F6E6C4" }, line: { color: "F6E6C4", width: 0 } });
    s.addImage({ path: icon(c[0], "rust"), x: x + 0.18, y: y + 0.2, w: 0.36, h: 0.36 });
    text(s, c[1], { x: x + 0.65, y: y + 0.14, w: cw - 0.8, h: 1.05, fontSize: 12.5, valign: "middle" });
    if (i < 3) arrow(s, x + cw + 0.04, y + 0.65, x + cw + 0.31, y + 0.65, C.rust, 1.5);
  });
  source(s, "EPPO Datasheet HERSO; Moravcová et al. 2007 (экология семян); Chadin et al., PeerJ 9:e11821 (2021); фото: Вячеслав Юсупов, Tatiana Strus, iNaturalist, CC BY");
}

// ================================================================ 9. PHYSICS
{
  const s = slide("LIGHT", "Физика сигнала", "Физика задаёт границы: спутник сужает поиск, а контур куртины даёт только съёмка с разрешением в сантиметры",
    "Почему мы не обещаем найти каждое растение со спутника. Пиксель Sentinel-2 — сто квадратных метров. Его отражение — смесь цветков и фона. Чтобы отличить смесь от шума, белых зонтиков в пикселе должно быть от восьми до пятнадцати квадратных метров. Одиночное растение со спутника не видно в принципе, поэтому спутник у нас сужает поиск, а контур даёт дрон. Камера 4/3 дюйма с высоты 100 метров даёт 2,7 сантиметра на пиксель, это десять пикселей на зонтик. Третий блок — окна съёмки: в мае розетки обгоняют траву, в конце июня–июле видны белые зонтики, в августе–сентябре — жёлтые метёлки золотарника.");
  const cards = [
    { k: "Смешанный пиксель", f: [{ text: "ρ = f·ρ", options: {} }, { text: "1", options: { subscript: true } }, { text: " + (1 − f)·ρ", options: {} }, { text: "0", options: { subscript: true, breakLine: true } }, { text: "f", options: {} }, { text: "min", options: { subscript: true } }, { text: " = z·σ / |ρ", options: {} }, { text: "1", options: { subscript: true } }, { text: " − ρ", options: {} }, { text: "0", options: { subscript: true } }, { text: "|", options: {} }],
      t: `Белые зонтики против зелени: Δρ ≈ 0,4, σ ≈ 0,01–0,02, z = 3. Нужно 8–15${NB}м² соцветий на пиксель 100${NB}м². Одиночное растение со спутника не видно — спутник сужает поиск, контур даёт дрон.` },
    { k: "Разрешение дрона", f: [{ text: "GSD = H·p / F", options: {} }],
      t: `Камера 4/3″, 20 Мп, F = 12 мм с высоты 100 м: 2,7 см на пиксель, около 10 пикселей на зонтик 30 см. Высота растения 1,5–4 м по модели поверхности отделяет борщевик от травы.` },
  ];
  cards.forEach((c, i) => {
    const x = MX + i * 4.12, y = 2.05, w = 3.88, h = 4.7;
    card(s, x, y, w, h);
    label(s, c.k, { x: x + 0.3, y: y + 0.28, w: w - 0.6, h: 0.28 });
    text(s, c.f, { x: x + 0.3, y: y + 0.7, w: w - 0.5, h: 1.05, fontFace: FONT.serif, italic: true, fontSize: 21, color: C.ink });
    text(s, greek(c.t), { x: x + 0.3, y: y + 1.95, w: w - 0.55, h: 2.6, fontSize: 13.5 });
  });
  // окна съёмки: мини-календарь
  const x = MX + 2 * 4.12, y = 2.05, w = 3.88;
  card(s, x, y, w, 4.7);
  label(s, "Окна съёмки", { x: x + 0.3, y: y + 0.28, w: w - 0.6, h: 0.28 });
  const months = ["V", "VI", "VII", "VIII", "IX"];
  const mx0 = x + 0.3, mw = (w - 0.6) / 5;
  months.forEach((m, i) => text(s, m, { x: mx0 + i * mw, y: y + 0.7, w: mw, h: 0.3, fontFace: FONT.label, fontSize: 11, color: C.muted, align: "center" }));
  const bars = [
    { a: 0.0, b: 1.0, c: C.sage, t: "Май: розетки борщевика обгоняют траву" },
    { a: 1.6, b: 3.0, c: C.cream, t: "Конец июня – июль: белые зонтики, максимум контраста" },
    { a: 3.0, b: 5.0, c: C.gold, t: "Август – сентябрь: жёлтые метёлки золотарника, каротиноиды гасят синий канал" },
  ];
  bars.forEach((b, i) => {
    const yy = y + 1.15 + i * 1.12;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: mx0 + b.a * mw, y: yy, w: (b.b - b.a) * mw, h: 0.24, rectRadius: 0.05, fill: { color: b.c }, line: { color: b.c === C.cream ? "CFC6A8" : b.c, width: 0.75 } });
    text(s, b.t, { x: mx0, y: yy + 0.3, w: w - 0.6, h: 0.72, fontSize: 12.5 });
  });
  text(s, greek("Оценки порядка величины; σ — остаточная погрешность отражения Sentinel-2 L2A. В красной границе спектра (705–783 нм) инвазивные виды обычно различимы лучше всего"),
    { x: MX, y: 6.9, w: W - 2 * MX - 2.1, h: 0.5, fontSize: 10, color: C.muted });
}

// ================================================================ 10. TERRAIN & HYDROLOGY
{
  const hT = H.temporal_test["capture@20%area"], hN = Hn.temporal_test["capture@20%area"];
  const sT = St.temporal_test["capture@20%area"], sN = S.temporal_test["capture@20%area"];
  const s = slide("LIGHT", "Геофизика и гидрология", "Рельеф и сток проверены как гипотеза: для борщевика их оставили, для золотарника исключили",
    `Мы посчитали по цифровой модели рельефа Copernicus две гидрологические величины. HAND — высоту над ближайшим водотоком вдоль линии стока. TWI — индекс влажности, он показывает, где копится вода. Перед этим заполнили понижения рельефа алгоритмом Priority-Flood, чтобы сток не обрывался в каждой ямке. Дальше важна методика: критерий выбрали заранее — долю новых находок 2025–2026 годов в верхних 20% площади. Для борщевика рельеф поднял её с ${pct(hN)} до ${pct(hT)}, это согласуется с экологией вида: он держится сырых обочин, брошенных полей и берегов. Для золотарника рельеф ухудшил прогноз, с ${pct(sN)} до ${pct(sT)}, сухие залежи от стока не зависят. Поэтому признаки выбираются для каждого вида отдельно.`);
  s.addImage({ path: img("terrain_hand_twi.jpg"), x: MX, y: 1.98, w: 7.55, h: 2.96 });
  text(s, "Долина Москвы-реки у Коломенского, 12 × 9 км. Рассчитано Rust-ядром по Copernicus DEM GLO-30 для всех 42 млн ячеек",
    { x: MX, y: 4.98, w: 7.55, h: 0.3, fontSize: 10.5, color: C.muted });
  s.addChart(pres.charts.BAR, [
    { name: "Без рельефа", labels: ["Борщевик", "Золотарник"], values: [hN * 100, sN * 100] },
    { name: "С рельефом", labels: ["Борщевик", "Золотарник"], values: [hT * 100, sT * 100] },
  ], Object.assign({
    x: 8.4, y: 1.9, w: 4.33, h: 3.45, barDir: "col", barGrouping: "clustered", barGapWidthPct: 70,
    chartColors: [C.sageLight, C.moss], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '0.0"%"',
    dataLabelFontSize: 12, dataLabelColor: C.ink, valAxisHidden: true, valAxisMinVal: 0, valAxisMaxVal: 58,
    valGridLine: { style: "none" }, catAxisLabelFontSize: 12, catAxisLabelColor: C.ink, catAxisLineShow: false,
    showLegend: true, legendPos: "t", legendFontSize: 11, legendColor: C.muted,
    showTitle: true, title: "Новые находки 2025–2026 в верхних 20% площади", titleFontSize: 11.5, titleColor: C.muted,
  }, chartText));
  const steps = [["Copernicus DEM", "30 м → сетка 10 м"], ["Priority-Flood", "заполнение понижений"], ["Сток D8", "площадь водосбора"], ["TWI и HAND", "признаки модели"]];
  const sw = 1.72;
  steps.forEach((st, i) => {
    const x = MX + i * (sw + 0.22), y = 5.55;
    card(s, x, y, sw, 0.95, C.tint, C.tint);
    text(s, st[0], { x: x + 0.15, y: y + 0.12, w: sw - 0.3, h: 0.32, fontFace: FONT.bodyBold, fontSize: 12.5 });
    text(s, st[1], { x: x + 0.15, y: y + 0.47, w: sw - 0.3, h: 0.4, fontSize: 11.5, color: C.muted });
    if (i < 3) arrow(s, x + sw + 0.02, y + 0.47, x + sw + 0.2, y + 0.47, C.sage, 1.25);
  });
  text(s, [{ text: "Правило выбора задано заранее: ", options: { fontFace: FONT.bodyBold } },
           { text: "признак остаётся, если улучшает прогноз новых находок и объясним экологией вида. Борщевик тяготеет к поймам, золотарнику важнее заброшенность участка." }],
    { x: 8.4, y: 5.5, w: 4.33, h: 1.15, fontSize: 12.5 });
  source(s, "Barnes, Lehman & Mulla 2014 (Priority-Flood); O'Callaghan & Mark 1984 (D8); Beven & Kirkby 1979 (TWI); Rennó et al. 2008 (HAND); Copernicus DEM © DLR, Airbus");
}

// ================================================================ 11. MAP
newSection("Доказательства");
{
  const s = slide("SPLIT", "Результат · карта 2025", "Карта Москвы и ближнего Подмосковья с шагом 10 м считается за несколько минут",
    `Это карта борщевика на 2025 год: квадрат 65 на 65 километров, Москва и ближнее Подмосковье. Цветом показаны верхние 10% площади: чем темнее, тем выше ранг. Это не калиброванная вероятность. Модель учится на 1 574 проверенных находках из iNaturalist. Фон — 60 тысяч наблюдений других растений любыми наблюдателями в той же зоне. Это снижает смещение к дорогам и паркам, но не убирает его. Тёмные пятна тянутся вдоль рек, дорог и ЛЭП и густеют у заброшенных полей.`);
  s.addImage({ path: img("heracleum_city.png"), x: 0.3, y: 0.5, w: 6.5, h: 6.5 });
  const x = 7.05, w = W - 7.05 - MX;
  text(s, [
    { text: `65 × 65 км, ${fmt(42.25, 2)} млн пикселей, 265 признаков на каждый.`, options: { breakLine: true } },
    { text: " ", options: { breakLine: true, fontSize: 6 } },
    { text: `Модель учится на ${fmt(H.samples.presence)} проверенных находках борщевика из iNaturalist. Фон — ${fmt(H.samples.background)} наблюдений других растений любыми наблюдателями в той же зоне: смещение к дорогам снижается и не исчезает.`, options: { breakLine: true } },
    { text: " ", options: { breakLine: true, fontSize: 6 } },
    { text: "Цвет — верхние 10% площади. Очаги тянутся вдоль рек, дорог и ЛЭП и густеют в поясе заброшенных полей области." },
  ], { x, y: 2.3, w, h: 3.35, fontSize: 14 });
  const leg = ["F3D9A0", "E0A030", "C4561F", "7A1E12"];
  leg.forEach((c, i) => s.addShape(pres.shapes.RECTANGLE, { x: x + i * 0.62, y: 5.75, w: 0.58, h: 0.22, fill: { color: c }, line: { color: c, width: 0 } }));
  text(s, "верхние 10%  →  1% площади", { x, y: 6.03, w: 3.5, h: 0.3, fontFace: FONT.label, fontSize: 10.5, color: C.muted });
  source(s, "AlphaEarth Foundations © Google, Google DeepMind (CC BY 4.0); iNaturalist; Overture Maps; расчёт ИнваРадар", false, 7.05, W - 7.05 - MX - 1.9);
}

// ================================================================ 12. METRICS
{
  const h10 = UH.spatial_cv["capture@10%area"], s10 = US.spatial_cv["capture@10%area"], s1 = US.spatial_cv["capture@1%area"];
  const ht20 = UH.temporal_test["capture@20%area"];
  const s = slide("LIGHT", "Проверка на новых территориях", `На районах вне обучения в верхних 10% площади карты в ${fmt(h10.lift, 1)}–${fmt(s10.lift, 1)} раза больше известных очагов, чем при случайном обходе`,
    `Как мы проверяли. Город разбит на блоки пять на пять километров, и модель ни разу не видит находок из проверяемого блока — это стандарт для пространственных данных, без него метрики завышаются. Верхние 10% площади карты содержат ${pct(h10.estimate)} известных находок борщевика: это в ${fmt(h10.lift, 1)} раза больше случайного обхода, доверительный интервал от ${fmt(h10.lift_ci95[0], 1)} до ${fmt(h10.lift_ci95[1], 1)}. Для устойчивых очагов, где в 30 метрах есть второй независимый наблюдатель, — ${pct(persist10)}, в четыре раза. У золотарника в верхнем одном проценте площади находок в семь раз больше случайного. И разрез по году метки: обучили на находках до 2024 года и проверили на ${UH.temporal_test.n_new_presence} новых находках 2025–2026 годов. Признаки у обеих сторон — эмбеддинг AlphaEarth 2025 года, новизна дальше 100 м, окно признака 450 м. Метки — точки жителей с погрешностью GPS до 50 метров, а среди фоновых точек есть ненайденный борщевик: обе помехи занижают метрику, поэтому оценка консервативна. По контурам её уточнит пилот.`);
  const cats = ["Золотарник, все находки", `Борщевик, устойчивые очаги (n = ${nPersist})`, "Борщевик, все находки", "Случайный обход"];
  s.addChart(pres.charts.BAR, [
    { name: "Случайный обход", labels: cats, values: [null, null, null, 10] },
    { name: "Борщевик", labels: cats, values: [null, persist10 * 100, h10.estimate * 100, null] },
    { name: "Золотарник", labels: cats, values: [s10.estimate * 100, null, null, null] },
  ], Object.assign({
    x: MX, y: 1.95, w: 7.6, h: 3.75, barDir: "bar", barGrouping: "clustered", barOverlapPct: 100, barGapWidthPct: 55,
    chartColors: ["B8C4BD", C.rust, C.gold], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '0.0"%"',
    dataLabelFontSize: 13, dataLabelColor: C.ink, valAxisHidden: true, valAxisMinVal: 0, valAxisMaxVal: 50,
    valGridLine: { style: "none" }, catAxisLabelFontSize: 12.5, catAxisLabelColor: C.ink, catAxisLineShow: false,
    showLegend: false, showTitle: true, title: "Доля находок в верхних 10% площади карты", titleFontSize: 12, titleColor: C.muted,
  }, chartText));
  text(s, `95% ДИ: борщевик ${ci(h10.ci95)}, золотарник ${ci(s10.ci95)} (кластерный бутстрэп по блокам 5 км)`,
    { x: MX, y: 5.72, w: 7.6, h: 0.3, fontFace: FONT.label, fontSize: 10, color: C.muted });
  const x = 8.55, w = W - 8.55 - MX;
  card(s, x, 1.95, w, 1.95);
  text(s, `×${fmt(s1.lift, 1)}`, { x: x + 0.3, y: 2.1, w: w - 0.6, h: 0.65, fontFace: FONT.head, fontSize: 34, color: C.gold });
  text(s, `золотарник: находок в верхнем 1% площади в ${fmt(s1.lift, 1)} раза больше случайного (95% ДИ ${fmt(s1.lift_ci95[0], 1)}–${fmt(s1.lift_ci95[1], 1)})`,
    { x: x + 0.3, y: 2.8, w: w - 0.55, h: 1.0, fontSize: 13 });
  card(s, x, 4.05, w, 1.95);
  text(s, pct(ht20.estimate), { x: x + 0.3, y: 4.2, w: w - 0.6, h: 0.65, fontFace: FONT.head, fontSize: 34, color: C.rust });
  text(s, `новых находок борщевика 2025–2026 гг. в верхних 20% площади (×${fmt(ht20.lift, 1)}); метки обучения — до 2024 г. (n = ${UH.temporal_test.n_new_presence})`,
    { x: x + 0.3, y: 4.9, w: w - 0.55, h: 1.0, fontSize: 13 });
  text(s, "Пространственная перекрёстная проверка: блоки 5 × 5 км, ни одна находка проверяемого блока не участвует в обучении. Устойчивый очаг — рядом в 30 м есть второй независимый наблюдатель (отдельный расчёт).",
    { x: MX, y: 6.12, w: CW, h: 0.62, fontSize: 12, color: C.muted });
  source(s, "Расчёты ИнваРадара 1.2, октябрь 2026; iNaturalist, исследовательский уровень, точность координат ≤ 50 м");
}

// ================================================================ 13. QUEUE & ROUTE
{
  const s = slide("SPLIT", "Результат · очередь выездов", "Утром бригада получает маршрут по самым опасным очагам, а не карту",
    `Карта сама по себе бригаде не поможет. Поэтому каждый очаг получает приоритет: вероятность, умноженная на близость людей, на близость дорог, рек и ЛЭП и на размер. Все множители видны оператору, никакого чёрного ящика. На карте — юг Москвы, окно девять на девять километров. Пятнадцать самых приоритетных точек, маршрут ${fmt(DR.route_km, 1)} километра, его строит Rust-ядро. Чёрные точки — сообщения жителей в iNaturalist: их здесь ${DR.known_reports_in_view}. Это не независимая проверка — на таких сообщениях модель училась, — а контекст: районом уже интересуются люди.`);
  s.addImage({ path: img("heracleum_district.png"), x: 0.3, y: 0.5, w: 6.5, h: 6.5 });
  const x = 7.05, w = W - 7.05 - MX;
  bigStat(s, fmt(H.hotspots.within_300m_of_child_facility), `очагов высокой вероятности в 300 м от детских садов, школ и площадок; ${fmt(pr.near_children_100m)} — ближе 100 м`, x, 2.2, w, C.rust, 30, 13, 0.55);
  bigStat(s, `${fmt(DR.route_km, 1)}${NB}км`, `прямая ломаная через ${DR.stops} приоритетных точек юга Москвы, не дорожный путь (синяя линия)`, x, 3.45, w, C.water, 30, 13, 0.55);
  bigStat(s, fmt(DR.known_reports_in_view), "сообщений жителей iNaturalist в этом окне 9 × 9 км (чёрные точки): районом уже интересуются люди", x, 4.7, w, C.ink, 30, 13, 0.55);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 5.88, w, h: 0.9, rectRadius: 0.08, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
  text(s, "Приоритет = вероятность × близость людей × близость дорог, рек и ЛЭП × размер очага. Все множители видны оператору.",
    { x: x + 0.2, y: 5.88, w: w - 0.4, h: 0.9, fontSize: 12.5, valign: "middle" });
}

// ================================================================ 14. CITIZENS
{
  const r = PH.report;
  const s = slide("LIGHT", "Результат · фото жителей", "ИИ разбирает две трети фотографий жителей сам и отличает борщевик и золотарник от безобидных двойников",
    `Жители — наши главные сенсоры, но их фото кто-то должен проверять, а борщевик легко спутать с дудником или борщевиком сибирским. Мы обучили классификатор на 13 тысячах фото iNaturalist: четыре класса — два инвазивных вида и их двойники. Проверка строгая: ни один автор фото не попадает одновременно в обучение и проверку, как будет с новыми волонтёрами. Если модель уверена больше чем на 0,9 — а это ${pct(r.auto_triage.share_auto, 0)} сообщений — она права в ${pct(r.auto_triage.accuracy_on_auto, 0)} случаев. Остальное уходит к ботанику. Это снимает с экспертов две трети ручной модерации.`);
  const pics = [
    ["umbel.jpg", "Борщевик Сосновского", "Heracleum sosnowskyi", C.rust],
    ["angelica.jpg", "Дудник лесной — двойник", "Angelica sylvestris", C.muted],
    ["solidago_panicle.jpg", "Золотарник гигантский", "Solidago gigantea", C.gold],
    ["tansy.jpg", "Пижма — двойник", "Tanacetum vulgare", C.muted],
  ];
  const pw = 1.78, ph = 2.1;
  pics.forEach((p, i) => {
    const x = MX + i * (pw + 0.16), y = 2.0;
    photo(s, p[0], x, y, pw, ph);
    text(s, p[1], { x, y: y + ph + 0.08, w: pw, h: 0.48, fontFace: FONT.bodyBold, fontSize: 11.5, color: p[3] });
    text(s, p[2], { x, y: y + ph + 0.5, w: pw, h: 0.3, fontFace: FONT.serif, italic: true, fontSize: 11, color: C.muted });
  });
  text(s, "Фото: Вячеслав Юсупов, Екатерина Гущина, Dr. Sven Gippner, Natalya Ivanova — iNaturalist, CC BY",
    { x: MX, y: 5.0, w: 7.6, h: 0.3, fontSize: 10, color: C.muted });
  const x = 8.55, w = W - 8.55 - MX;
  bigStat(s, pct(r.auto_triage.share_auto, 0), `сообщений модель разбирает сама при уверенности от 0,9; среди них верны ${pct(r.auto_triage.accuracy_on_auto, 1)}`, x, 1.95, w, C.moss, 32, 13, 0.75);
  bigStat(s, pct(r.heracleum_binary.precision, 1), `точность (полнота ${pct(r.heracleum_binary.recall, 1)}) для борщевика против дудника, борщевика сибирского, купыря и сныти`, x, 3.45, w, C.rust, 28, 13, 0.75);
  bigStat(s, pct(r.solidago_binary.precision, 1), `точность (полнота ${pct(r.solidago_binary.recall, 1)}) для золотарника против пижмы, крестовника и зверобоя`, x, 4.95, w, C.gold, 28, 13, 0.75);
  text(s, `${fmt(PH.n_images)} фотографий iNaturalist, 4 класса. Проверка без пересечения авторов: 5 фолдов по наблюдателям. YOLO11-cls + логистическая регрессия.`,
    { x: MX, y: 5.5, w: 7.6, h: 0.9, fontSize: 12.5, color: C.ink });
  source(s, "Расчёты ИнваРадара 1.2, октябрь 2026; Ultralytics YOLO11 (AGPL-3.0); scikit-learn");
}

// ================================================================ 15. LAW
{
  const s = slide("LIGHT", "Право в коде", "Метод работ выбирается по закону, и в Москве дрон остаётся разведчиком, а не опрыскивателем",
    `Для каждого из ${fmt(pr.hotspots)} очагов система сама проверяет пять правил и пишет основание в заказ-наряд. Водоохранные зоны считаются по Водному кодексу: ширина 50, 100 или 200 метров по длине реки; у Москвы-реки 200. В них запрещены и авиаобработка, и любые пестициды — это ${fmt(pr.in_water_zone_no_pesticides)} очагов, там только механика. Дальше СанПиН: в черте населённых пунктов зелёные насаждения обрабатывают только наземной аппаратурой, а беспилотник с пестицидом держится не ближе 700 метров от жилья, водоёмов и ООПТ. В Москве это значит, что опрыскивать с дрона нельзя, и система это прямо показывает: дрон находит и обводит, а обрабатывает наземная бригада точно по контуру. Опрыскивание с дрона допустимо только для ${fmt(pr.drone_spraying_allowed)} очагов в полях за пределами населённых пунктов. На ООПТ — только механика, как и работает Мосприрода. У детей — без пестицидов и в начале очереди. У памятников — без земляных работ. И важное: ИИ не выписывает штрафов. Он даёт индикатор риска для надзора, решение и протокол — за человеком.`);
  const rules = [
    ["TbDroplet", "Водоохранная зона", `ВК РФ ст. 65 ч. 4–6, ч. 15 п. 3 и 6`, fmt(pr.in_water_zone_no_pesticides), "без пестицидов, механика"],
    ["TbHome", "Город или < 700 м до жилья", "СанПиН 2.1.3684-21, п. 273, 282", fmt(pr.aerial_blocked_uav_700m), "дрону нельзя, только наземно"],
    ["TbTrees", "ООПТ и парки", "режим ООПТ, практика Мосприроды", fmt(pr.in_protected_mechanical), "только механика"],
    ["TbMoodKid", "Дети в 100 м", "СанПиН п. 273; осторожность системы", fmt(pr.near_children_100m), "без пестицидов, первыми"],
    ["TbBuildingMonument", "Памятник в 50 м", "73-ФЗ об объектах наследия", fmt(pr.near_heritage_no_digging), "без земляных работ"],
  ];
  const w0 = 7.75;
  rules.forEach((r, i) => {
    const y = 2.0 + i * 0.8;
    if (i % 2 === 0) s.addShape(pres.shapes.RECTANGLE, { x: MX, y: y - 0.05, w: w0, h: 0.74, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
    iconDisc(s, r[0], MX + 0.1, y + 0.05, 0.52, C.white);
    text(s, r[1], { x: MX + 0.8, y: y + 0.02, w: 3.0, h: 0.34, fontFace: FONT.bodyBold, fontSize: 13.5 });
    text(s, r[2], { x: MX + 0.8, y: y + 0.34, w: 3.3, h: 0.32, fontSize: 11, color: C.muted });
    text(s, r[3], { x: MX + 4.25, y: y + 0.02, w: 1.25, h: 0.6, fontFace: FONT.head, fontSize: 20, color: C.rust, align: "right", valign: "middle" });
    text(s, r[4], { x: MX + 5.7, y: y + 0.02, w: 2.0, h: 0.6, fontSize: 12, valign: "middle" });
  });
  const x = MX + w0 + 0.35, w = CW - w0 - 0.35;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.95, w, h: 3.95, rectRadius: 0.08, fill: { color: C.forest }, line: { color: C.forest, width: 0 } });
  text(s, `ИТОГ ДЛЯ ${fmt(pr.hotspots)} ОЧАГОВ БОРЩЕВИКА`, { x: x + 0.3, y: 2.15, w: w - 0.5, h: 0.3, fontFace: FONT.label, fontSize: 10.5, color: C.amber, charSpacing: 1.5 });
  const outs = [[fmt(pr.drone_spraying_allowed), "опрыскивание с дрона допустимо"], [fmt(pr.ground_spot_treatment), "наземная точечная обработка по контуру очага"], [fmt(pr.mechanical_only), "только механические методы"]];
  outs.forEach((o, i) => {
    const y = 2.6 + i * 1.08;
    text(s, o[0], { x: x + 0.3, y, w: 1.55, h: 0.6, fontFace: FONT.head, fontSize: 28, color: i === 0 ? C.amber : C.cream, valign: "middle" });
    text(s, o[1], { x: x + 1.9, y, w: w - 2.15, h: 0.75, fontSize: 12.5, color: C.paperDim, valign: "middle" });
  });
  text(s, "ИИ даёт индикатор риска для надзора (248-ФЗ); протокол по ст. 8.7 КоАП составляет инспектор по фотофиксации. Наряд подписывает человек.",
    { x: MX, y: 6.08, w: CW, h: 0.62, fontSize: 12.5, color: C.ink });
  source(s, `Слои: Overture Maps (вода, жилая застройка, парки, детские объекты, памятники); в пилоте — границы водоохранных зон по ГВР, ООПТ и ЕГРОКН. Золотарник: ${fmt(prS.ground_spot_treatment)} наземных и ${fmt(prS.mechanical_only)} механических из ${fmt(prS.hotspots)}`);
}

// ================================================================ 16. WORK ORDER (настоящая строка из опубликованной очереди)
{
  const s = slide("LIGHT", "Результат · наряд-проект", "Бригада получает не точку на карте, а готовый наряд: где, каким методом и на каком основании",
    `Вот как выглядит результат для бригады. Это настоящая строка из опубликованной очереди, номер ${WX.rank}. Координаты, площадь, место в ранге. Дальше — основания: водоохранная зона, рядом детская площадка, парк. Поэтому система сама исключила химию и назначила механику: покос, срез зонтиков до конца июля, защитная одежда, наблюдение пять сезонов. Статус — черновик: подписывает ответственный сотрудник, а не программа. Таких нарядов в очереди шестнадцать тысяч по борщевику, все приоритетные открыты на живой карте — QR-код справа.`);
  const x0 = MX, w0 = 8.05, y0 = 1.95, h0 = 4.8;
  card(s, x0, y0, w0, h0, C.white, C.line);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x0, y: y0, w: w0, h: 0.62, rectRadius: 0.16, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: x0, y: y0 + 0.4, w: w0, h: 0.22, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
  text(s, [{ text: `НАРЯД-ПРОЕКТ №${NB}${WX.rank}`, options: { fontFace: FONT.head, color: C.forest } }, { text: "   ·   борщевик Сосновского", options: { color: C.muted } }],
    { x: x0 + 0.3, y: y0 + 0.14, w: 5.4, h: 0.36, fontFace: FONT.label, fontSize: 13, valign: "middle" });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x0 + w0 - 2.55, y: y0 + 0.15, w: 2.3, h: 0.34, rectRadius: 0.17, fill: { color: C.white }, line: { color: C.purple, width: 1 } });
  text(s, "черновик · подпись человека", { x: x0 + w0 - 2.55, y: y0 + 0.15, w: 2.3, h: 0.34, fontSize: 10.5, color: C.purple, align: "center", valign: "middle" });
  const facts = [
    ["Координаты", `${fmt(+WX.lat, 3)}° с. ш., ${fmt(+WX.lon, 3)}° в. д.`],
    ["Площадь", `${fmt(+WX.area_m2 / 1e4, 2)} га`],
    ["Ранг на карте", `${fmt(+WX.mean_rank * 100, 1)}-й процентиль ландшафта`],
    ["Детская площадка или школа", +WX.d_child_m < 1 ? "на участке очага" : `${fmt(+WX.d_child_m)} м`],
    ["Водоохранная зона", +WX.water_zone_m > 0 ? `${fmt(+WX.water_zone_m)} м (ВК РФ, ст. 65)` : "нет"],
    ["Область применимости", WX.inside_aoa === "True" ? "внутри: прогнозу можно доверять" : "вне: нужен осмотр"],
  ];
  facts.forEach((f, i) => {
    const yy = y0 + 0.78 + i * 0.37;
    text(s, f[0], { x: x0 + 0.3, y: yy, w: 2.45, h: 0.34, fontSize: 11, color: C.muted, valign: "middle" });
    text(s, f[1], { x: x0 + 2.7, y: yy, w: 2.35, h: 0.34, fontFace: FONT.bodyBold, fontSize: 11, valign: "middle" });
  });
  const basis = [];
  if (+WX.water_zone_m > 0) basis.push(`Водоохранная зона ${fmt(+WX.water_zone_m)} м — пестициды и авиаобработка запрещены (ВК РФ, ст. 65 ч. 15)`);
  if (WX.near_children === "True") basis.push("Рядом дети — без химии, первым в очереди безопасности");
  if (WX.in_protected === "True") basis.push("Парк или ООПТ — только механические методы");
  if (WX.near_heritage === "True") basis.push("Объект наследия — без земляных работ (73-ФЗ, ст. 36)");
  const xb = x0 + 5.2, wb = w0 - 5.45;
  label(s, "основание", { x: xb, y: y0 + 0.82, w: wb, h: 0.28 });
  text(s, basis.map((b, i) => ({ text: b, options: { bullet: { indent: 12 }, breakLine: i < basis.length - 1 } })),
    { x: xb, y: y0 + 1.12, w: wb, h: 1.45, fontSize: 11, paraSpaceAfter: 4 });
  const steps = WX.method.split(";").map((t) => t.trim()).filter(Boolean);
  const umb = steps.find((t) => t.startsWith("зонтики"));
  const pick = [steps[0].split(",")[0], umb && "зонтики срезать до конца июля, вторичные — в августе; вывезти в герметичных мешках",
    "СИЗ: влагонепроницаемая одежда, перчатки, защита глаз; наблюдение 5 сезонов"].filter(Boolean);
  s.addShape(pres.shapes.LINE, { x: x0 + 0.3, y: y0 + 3.07, w: w0 - 0.6, h: 0.001, line: { color: C.line, width: 0.75 } });
  label(s, "метод работ", { x: x0 + 0.3, y: y0 + 3.17, w: 4, h: 0.28 });
  text(s, pick.map((t, i) => ({ text: t[0].toUpperCase() + t.slice(1), options: { bullet: { indent: 12 }, breakLine: i < pick.length - 1 } })),
    { x: x0 + 0.3, y: y0 + 3.47, w: w0 - 0.6, h: 1.2, fontSize: 11.5, paraSpaceAfter: 3 });
  // справа: масштаб и живая карта
  const x1 = x0 + w0 + 0.3, w1 = W - MX - x1;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x1, y: y0, w: w1, h: h0, rectRadius: 0.16, fill: { color: C.forest }, line: { color: C.forest, width: 0 } });
  text(s, "ТАКИХ НАРЯДОВ", { x: x1 + 0.3, y: y0 + 0.22, w: w1 - 0.5, h: 0.28, fontFace: FONT.label, fontSize: 10.5, color: C.amber, charSpacing: 1.5 });
  text(s, fmt(pr.hotspots), { x: x1 + 0.3, y: y0 + 0.5, w: w1 - 0.5, h: 0.6, fontFace: FONT.head, fontSize: 30, color: C.cream, valign: "bottom" });
  text(s, `по борщевику и ${fmt(prS.hotspots)} — по золотарнику; закон проверяется автотестами на опубликованных нарядах`,
    { x: x1 + 0.3, y: y0 + 1.2, w: w1 - 0.5, h: 1.0, fontSize: 11.5, color: C.paperDim });
  mapCard(s, x1 + (w1 - 1.65) / 2, y0 + 2.35, 1.65, "Все приоритетные наряды");
  source(s, "Строка из outputs/heracleum/work_orders_top200_2025.csv; правила — ВК РФ ст. 65, СанПиН 2.1.3684-21 п. 272–273, 282; 73-ФЗ".replace("outputs/heracleum/work_orders_top200_2025.csv", "опубликованной очереди нарядов (200 первых по каждому виду)"));
}

// ================================================================ 17. RIVALS
newSection("Рынок и план");
{
  const s = slide("LIGHT", "Аналоги", "Сильные решения уже есть, но каждое закрывает один-два шага цикла; ИнваРадар соединяет их",
    "Мы уважаем всех, кто в этой таблице, и не конкурируем с ними, а соединяем. Яндекс со «СтопБорщевиком» нашли по снимкам 421 гектар очагов в 17 регионах, но очереди и контроля нет. Подмосковье строит контур надзора: спутник, дрон, ИИ, штраф — но без приоритета по людям. «СР дата», призёр этой премии в 2024 году, ищет по космоснимкам свалки и самострой: спутник и ИИ жюри уже видело. Наше отличие — что происходит после карты. В Петербурге ГАТИ поставила нейросеть «Городовой» на восемь патрульных машин: она видит борщевик с улицы, готовит постановление владельцу и проверяет устранение. Это сильный пример контроля, но камера видит только то, что у дороги, и не расставляет приоритеты по риску. Сколтех сделал бортовой ИИ для дрона. «Инвазиум» собирает данные волонтёров, но без ИИ. ИнваРадар закрывает весь цикл и открыт: карта Яндекса, данные «Инвазиума» и дроны подрядчиков могут стать его входами.");
  const Y = "●", P = "○", N = "—";
  const head = ["Решение", "Космос", "Дрон", "Жители + ИИ", "Риск для людей", "Право в коде", "Контроль", "Открытость"];
  const rows = [
    ["ШАД Яндекса + «СтопБорщевик», 2026", Y, N, P, N, N, N, "бесплатный сервис"],
    ["«СР дата»: ИИ по космоснимкам, призёр премии 2024", Y, N, N, N, N, N, N],
    ["Пилот Минсельхоза МО, 2026", Y, Y, N, N, P, N, N],
    ["Сколтех, бортовой ИИ дрона, 2021", N, Y, N, N, N, N, "статья"],
    ["ГАТИ Петербурга, «Городовой»: ИИ на патрульных машинах", N, N, N, N, P, Y, N],
    ["«Инвазиум», ГБС РАН", N, N, "без ИИ", N, N, N, "данные"],
    ["InvaDrone, Дания", N, Y, N, N, N, N, N],
    ["ИнваРадар", Y, Y, Y, Y, Y, "2027", "открытый код"],
  ];
  const hdr = head.map((t, i) => ({ text: t, options: { bold: false, fontFace: FONT.label, fontSize: 10, color: C.moss, align: i ? "center" : "left", fill: { color: C.paper } } }));
  const body = rows.map((r, ri) => r.map((c, ci) => ({ text: typo(c), options: {
    fontFace: ci === 0 ? FONT.bodyBold : (c === Y || c === P ? "Arial" : FONT.body), fontSize: ci === 0 ? 12 : (c === Y || c === P ? 15 : 11.5),
    color: ri === rows.length - 1 ? (ci === 0 ? C.cream : (c === N ? C.sage : C.amber)) : (c === N ? "A9B5AE" : (c === Y || c === P ? C.moss : C.ink)),
    align: ci ? "center" : "left", valign: "middle", fill: { color: ri === rows.length - 1 ? C.forest : (ri % 2 ? C.white : C.tint) } } })));
  s.addTable([hdr, ...body], { x: MX, y: 1.9, w: CW, colW: [3.6, 1.08, 1.08, 1.3, 1.33, 1.3, 1.08, 1.36], rowH: 0.45,
    border: { type: "none" }, margin: [0.04, 0.12, 0.04, 0.12] });
  text(s, "● есть   ○ частично   — нет", { x: MX, y: 6.0, w: 4, h: 0.3, fontFace: "Arial", fontSize: 10.5, color: C.muted });
  text(s, "Мы не конкурируем, а соединяем: карта Яндекса, данные «Инвазиума» и дроны подрядчиков становятся входами одного цикла.",
    { x: MX + 4.2, y: 5.95, w: CW - 4.2, h: 0.6, fontSize: 13, color: C.ink });
  source(s, "comnews.ru, 02.04.2026 (421 га в 17 регионах); riamo.ru, 07.08.2026; mos.ru, 10.12.2024 (призёры премии 2024); ГАТИ СПб, «Городовой» (hi-tech.mail.ru; dp.ru, 14.06.2026); Menshchikov et al., IEEE Trans. Computers 70(8), 2021; gbsad.ru; SDU UAS Center");
}

// ================================================================ 18. WORLD PRACTICE
{
  const s = slide("LIGHT", "Мировая практика", "Мы взяли лучшее из мировой науки об инвазиях и геоИИ и собрали это в один городской цикл",
    "Мы ничего не изобретали там, где есть проверенная мировая практика. Европа и США борются с инвазиями по схеме раннего обнаружения и быстрого реагирования: малый очаг убрать дешевле, чем массив. Смещение народных наблюдений к дорогам снимаем методом Phillips, качество меряем пространственными блоками по Roberts, недоверенные зоны карта отмечает по Meyer и Pebesma, полевую проверку строим по Olofsson — это стандарт оценки карт. Признаки берём из открытых спутниковых эмбеддингов AlphaEarth, дрон работает на DINOv2, фото жителей — классификатор вида. Новое у нас — что всё это связано в один цикл для города и выводит закон в наряд.");
  const rows = [
    ["Практика", "Где принята", "Как в ИнваРадаре"],
    ["Раннее обнаружение и быстрое реагирование (EDRR)", "Регламент ЕС 1143/2014, ст. 16–17; NISC, США", "очередь по риску и наряд для каждого кандидата: малый очаг убирают, пока он не стал массивом"],
    ["Фон целевой группы против смещения выборки", "Phillips et al., 2009", `${fmt(H.samples.background)} наблюдений других растений вместо случайных точек`],
    ["Проверка пространственными блоками", "Roberts et al., 2017; Valavi et al., 2019", "блоки 5 × 5 км, кластерный бутстрэп, проверка на следующих годах"],
    ["Область применимости модели", "Meyer & Pebesma, 2021", `карта сама отмечает ${pct(1 - EH.aoa.share_area_inside_AOA, 1)} площади, где прогнозу нельзя верить`],
    ["Стратифицированная оценка площади и точности", "Olofsson et al., 2014", "250 точек полевой выборки по четырём слоям ранга"],
    ["Открытые спутниковые эмбеддинги", "AlphaEarth (Google DeepMind, 2025); TESSERA; OlmoEarth", "64 признака на каждые 10 м; источник заменяемый"],
    ["Самообучающееся зрение для дронов", "DINOv2 (Oquab et al., 2024); Сколтех, 2021", `зонд поверх DINOv2: ${DB.f2.images_with_hogweed_detected.replace("/", " из ")} снимков с борщевиком найдены`],
    ["Гражданская наука и ИИ", "iNaturalist, Pl@ntNet, BioCLIP 2", `ИИ сам разбирает ${pct(PH.report.auto_triage.share_auto, 0)} сообщений жителей`],
  ];
  s.addTable(rows.map((r, ri) => r.map((c, ci) => ({ text: typo(c), options: {
    fontFace: ri === 0 ? FONT.label : (ci === 0 ? FONT.bodyBold : FONT.body), fontSize: ri === 0 ? 10 : (ci === 1 ? 11 : 12),
    color: ri === 0 ? C.moss : (ci === 1 ? C.muted : C.ink), valign: "middle",
    fill: { color: ri === 0 ? C.white : (ri % 2 ? C.tint : C.white) } } }))),
    { x: MX, y: 1.95, w: CW, colW: [3.55, 3.45, 5.13], rowH: [0.36, ...Array(8).fill(0.52)], border: { type: "none" }, margin: [0.03, 0.12, 0.03, 0.12] });
  source(s, "Регламент (ЕС) № 1143/2014; Phillips et al., Ecol. Appl. 19 (2009); Roberts et al., Ecography 40 (2017); Valavi et al., Methods Ecol. Evol. 10 (2019); Meyer & Pebesma, Methods Ecol. Evol. 12 (2021); Olofsson et al., RSE 148 (2014); Oquab et al., TMLR (2024)");
}

// ================================================================ 19. REAL PROGRAMMES — что сработало у других
{
  const s = slide("LIGHT", "Реальные программы", "Что уже сработало у других: малые очаги первыми, план на годы, контроль после работ — ИнваРадар делает это для Москвы",
    "Четыре реальные программы. Дания: с 2017 года по приказу каждый муниципалитет ведёт план борьбы с борщевиком на десять лет. Гладсаксе за 2011–2021 годы убрала больше 95% очагов на муниципальной земле, а Рандерс сначала убирает малые куртины, потом колонии — ровно наш ранг сдерживания. Латвия: служба защиты растений обходит очаги с GPS и передаёт карту муниципалитетам; в реестре почти 11 тысяч гектаров. Мы делаем эту разведку из космоса и сразу ставим очередь. Петербург: нейросеть «Городовой» на патрульных машинах находит борщевик с улицы и проверяет устранение — это сильный контроль, но только у дорог. Подмосковье: спутник, кадастр, дрон и постановление. Каждый взял одно звено; ИнваРадар связывает все.");
  const cases = [
    { flag: "Дания", head: "Муниципальные планы на 10 лет", fact: "С 2017 г. каждый муниципалитет обязан вести план. Гладсаксе: за 2011–2021 гг. убрано более 95% очагов на муниципальной земле. Рандерс: малые куртины — за 2–5 лет, колонии — за 5–15 лет", take: "ранг сдерживания: малый изолированный очаг — первым" },
    { flag: "Латвия", head: "Государственный реестр очагов", fact: "Регламент № 559 (2008). Служба защиты растений обходит очаги с GPS и передаёт карту муниципалитетам; в реестре 10,8 тыс. га (2020)", take: "та же разведка — из космоса, на весь город за сезон" },
    { flag: "Петербург", head: "«Городовой» на машинах ГАТИ", fact: "ГАТИ: нейросеть на восьми машинах видит борщевик с улицы, готовит постановление владельцу и при повторном объезде проверяет устранение", take: "контроль после работ — и за пределами дорог, где камера не видит" },
    { flag: "Подмосковье", head: "Спутник → кадастр → дрон → штраф", fact: "23,4 тыс. га обработки в 2026 г., около 250 млн ₽; дроны на оврагах и обочинах; первый штраф по данным ДЗЗ и ИИ — 150 тыс. ₽", take: "приоритет по риску для людей и законный метод в наряде" },
  ];
  cases.forEach((c, i) => {
    const x = MX + i * 3.08, y = 1.95, w = 2.92, h = 4.75;
    card(s, x, y, w, h);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.22, y: y + 0.22, w: 1.55, h: 0.36, rectRadius: 0.18, fill: { color: C.forest }, line: { color: C.forest, width: 0 } });
    text(s, c.flag.toUpperCase(), { x: x + 0.22, y: y + 0.22, w: 1.55, h: 0.36, fontFace: FONT.label, fontSize: 10, color: C.white, align: "center", valign: "middle", charSpacing: 1 });
    text(s, c.head, { x: x + 0.22, y: y + 0.72, w: w - 0.4, h: 0.62, fontFace: FONT.head, fontSize: 14, valign: "top" });
    text(s, c.fact, { x: x + 0.22, y: y + 1.42, w: w - 0.4, h: 2.0, fontSize: 11.5 });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.14, y: y + 3.48, w: w - 0.28, h: 1.12, rectRadius: 0.12, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
    text(s, [{ text: "ИнваРадар: ", options: { fontFace: FONT.bodyBold, color: C.moss } }, { text: c.take }],
      { x: x + 0.26, y: y + 3.52, w: w - 0.5, h: 1.04, fontSize: 11.5, valign: "middle" });
  });
  source(s, "Bekendtgørelse nr. 842 af 23.06.2017; планы Gladsaxe 2022–2031 и Randers; Cabinet Regulation No. 559 (2008), VAAD, FAO; ГАТИ СПб («Городовой», hi-tech.mail.ru, dp.ru); Минсельхоз МО (abnews.ru, РГ, riamo.ru, 2026)");
}

// ================================================================ 20. EFFECT
{
  const s = slide("LIGHT", "Эффект", `Точечная обработка вместо сплошной: каждые 10% площади экономят около 32${NB}млн${NB}₽ за сезон`,
    "Экономику считаем аккуратно, как сценарий. Подмосковье планирует обработать 23,4 тысячи гектаров. При нормативе 8,3–19,3 тысячи рублей за гектар, середина — 13,8 тысячи, сезон стоит около 323 миллионов рублей. Если благодаря карте и контурам точечная обработка заменит сплошную хотя бы на десятой части площади, это 32 миллиона в год. Плюс меньше гербицида — точечная обработка по контуру вместо сплошной — и меньше ожогов: очаги у школ и площадок обрабатываются первыми. Фактические цифры дадут замеры в пилоте.");
  const cards = [
    { ic: "TbCoin", v: `≈${NB}323${NB}млн${NB}₽`, t: `стоимость сезона обработки в Подмосковье: 23,4 тыс. га × 13,8 тыс. ₽/га (середина норматива 8,3–19,3 тыс.)`, c: C.rust },
    { ic: "TbDroplet", v: "−гербицид", t: "обработка только по контуру куртины вместо сплошной: смесь идёт на заросли, а не на газон", c: C.moss },
    { ic: "TbMoodKid", v: "−ожоги", t: "очаги у школ и площадок обрабатываются первыми, жители видят статус работ", c: C.purple },
  ];
  cards.forEach((c, i) => {
    const x = MX + i * 4.12, y = 2.05, w = 3.88, h = 2.85;
    card(s, x, y, w, h);
    iconDisc(s, c.ic, x + 0.3, y + 0.3);
    text(s, c.v, { x: x + 0.3, y: y + 1.0, w: w - 0.5, h: 0.62, fontFace: FONT.head, fontSize: 28, color: c.c });
    text(s, c.t, { x: x + 0.3, y: y + 1.68, w: w - 0.55, h: 1.1, fontSize: 13 });
  });
  label(s, "что измерим в пилоте", { x: MX, y: 5.2, w: 6, h: 0.3 });
  text(s, "фактическую площадь обработки · расход препарата · долю вернувшихся очагов · время от сигнала до выезда · число обращений жителей",
    { x: MX, y: 5.55, w: CW, h: 0.6, fontSize: 14 });
  text(s, "Расчёт — сценарная оценка по открытым нормативам.", { x: MX, y: 6.2, w: CW, h: 0.35, fontSize: 12, color: C.muted });
  source(s, "Минсельхоз МО (план 2026); норматив стоимости работ по борьбе с борщевиком, Минагропром Ярославской обл. (2026)");
}

// ================================================================ 20. ENFORCEMENT — штраф как крайняя мера (сценарий)
{
  // допущения до полевой проверки: доля подтверждённых, доля частной земли, доля неисполненных предписаний
  const E = { conf: [0.30, 0.50, 0.70], priv: [0.20, 0.35, 0.50], miss: [0.10, 0.20, 0.30] };
  const fineLo = 0.85 * 20e3 + 0.15 * 400e3, fineHi = 0.85 * 35e3 + 0.15 * 550e3;  // граждане 85% / юрлица 15%, ст. 8.7 ч. 2 КоАП
  const n = pr.hotspots, sc = [0, 1, 2].map((i) => {
    const conf = n * E.conf[i], orders = conf * E.priv[i], fines = orders * E.miss[i];
    return { conf, orders, done: orders - fines, fines, lo: fines * fineLo / 1e6, hi: fines * fineHi / 1e6 };
  });
  const m = sc[1];
  const r100 = (v) => Math.round(v / 10) * 10;
  const s = slide("LIGHT", "Эффект · правоприменение", "Штраф — крайняя мера: система превращает карту в предписания, и четыре очага из пяти убирают без штрафа",
    `Нас часто спрашивают, будет ли система штрафовать. Нет, и вот почему это хорошо. Из ${fmt(n)} кандидатов по борщевику в среднем сценарии половина подтвердится на месте. Около трети из них — на частной земле: это ${fmt(r100(m.orders))} предписаний за сезон, каждое с адресом, контуром и законным методом работ. По опыту надзора большинство владельцев выполняет предписание — тогда очаг убран без штрафа. Штраф по статье 8.7 КоАП выписывает инспектор, и только тем, кто проигнорировал предписание: в среднем сценарии это около ${fmt(r100(m.fines))} случаев и ${fmt(m.lo, 0)}–${fmt(m.hi, 0)} миллионов рублей. Это сценарий, доли мы измерим в пилоте. Главный результат — убранные очаги и защищённые дети, а не штрафы.`);
  const steps = [
    [fmt(n), "кандидатов на осмотр по борщевику", C.forest, 1.0],
    [fmt(r100(m.conf)), `подтверждены на месте (${pct(E.conf[1], 0)})`, C.moss, 0.91],
    [fmt(r100(m.orders)), `на частной земле: предписание с адресом, контуром и методом (${pct(E.priv[1], 0)})`, C.mint, 0.82],
    [fmt(r100(m.done)), `владелец убрал сам — без штрафа (${pct(1 - E.miss[1], 0)})`, "4FB892", 0.73],
    [fmt(r100(m.fines)), `штраф — только за неисполненное предписание (${pct(E.miss[1], 0)})`, C.purple, 0.64],
  ];
  const fx = MX, fw = 7.6, fy = 1.98, fh = 0.74, gap = 0.12;
  steps.forEach((st, i) => {
    const w = fw * st[3], x = fx + (fw - w) / 2, y = fy + i * (fh + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: fh, rectRadius: 0.18, fill: { color: st[2] }, line: { color: st[2], width: 0 } });
    text(s, st[0], { x: x + 0.2, y, w: 1.5, h: fh, fontFace: FONT.head, fontSize: 22, color: C.white, valign: "middle" });
    text(s, st[1], { x: x + 1.6, y, w: w - 1.75, h: fh, fontSize: 11.5, color: C.white, valign: "middle" });
  });
  // три сценария
  const x1 = fx + fw + 0.35, w1 = W - MX - x1;
  card(s, x1, 1.98, w1, 3.3, C.white, C.line);
  text(s, "ТРИ СЦЕНАРИЯ ЗА СЕЗОН", { x: x1 + 0.25, y: 2.12, w: w1 - 0.4, h: 0.28, fontFace: FONT.label, fontSize: 10, color: C.moss, charSpacing: 1.2 });
  const head = ["", "низкий", "средний", "высокий"];
  const rows = [["предписаний", ...sc.map((v) => fmt(r100(v.orders)))], ["штрафов", ...sc.map((v) => fmt(r100(v.fines)))],
    ["млн руб.", ...sc.map((v) => `${fmt(v.lo, 0)}–${fmt(v.hi, 0)}`)]];
  s.addTable([head, ...rows].map((r, ri) => r.map((c, ci) => ({ text: c, options: {
    fontFace: ri === 0 || ci === 0 ? FONT.label : FONT.head, fontSize: ri === 0 || ci === 0 ? 10 : 13,
    color: ri === 0 ? C.muted : (ci === 2 ? C.purple : C.ink), align: ci ? "center" : "left", valign: "middle",
    fill: { color: ci === 2 && ri > 0 ? "F1ECF6" : C.white } } }))),
    { x: x1 + 0.2, y: 2.5, w: w1 - 0.4, colW: [1.25, 0.95, 0.95, 0.95].map((v) => v * (w1 - 0.4) / 4.1), rowH: [0.34, 0.48, 0.48, 0.48],
      border: { type: "none" }, margin: [0.02, 0.06, 0.02, 0.06] });
  text(s, "Доли подтверждения, частной земли и неисполнения — допущения до полевой проверки; штраф 20–50 тыс. ₽ для граждан и 400–700 тыс. ₽ для юрлиц.",
    { x: x1 + 0.25, y: 4.42, w: w1 - 0.45, h: 0.8, fontSize: 10, color: C.muted });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x1, y: 5.42, w: w1, h: 1.3, rectRadius: 0.16, fill: { color: C.forest }, line: { color: C.forest, width: 0 } });
  text(s, [{ text: "ИИ не штрафует. ", options: { fontFace: FONT.head, color: C.amber } },
    { text: "Он даёт инспектору адрес, контур, фото и основание, а владельцу — понятное предписание. Протокол и решение — за человеком (248-ФЗ, ст. 8.7 КоАП)." }],
    { x: x1 + 0.25, y: 5.47, w: w1 - 0.45, h: 1.2, fontSize: 11.5, color: C.cream, valign: "middle" });
  source(s, `Сценарий для ${fmt(n)} кандидатов по борщевику в квадрате 65 × 65 км (Москва и ближнее Подмосковье); КоАП РФ ст. 8.7 ч. 2; 294-ФЗ; первый штраф по данным ДЗЗ, дрона и ИИ — Рузский округ, 150 тыс. ₽ (riamo.ru, 07.08.2026)`);
}

// ================================================================ 21. ROADMAP
{
  const s = slide("LIGHT", "План", "Полевой сезон 2027 года — первая проверка на земле",
    "План простой. Версия 1.2 работает сейчас. С декабря по март подключаем данные: бот «Инвазиума», кадастр, аэрофото города, обращения жителей, модуль цветения по Sentinel-2. С апреля по сентябрь — пилот на трёх территориях: полёты в мае, в июле на цветении борщевика и в августе на золотарнике, сравнение с работой бригад. С октября — масштаб на Москву и область и 13 видов списка «Инвазиума». Внизу — метрики пилота, по ним нас можно будет проверить.");
  const ph = [
    ["ноя 2026", "Версия 1.2", "Карты борщевика и золотарника, очередь, маршрут, ИИ-проверка фото, модуль БПЛА, право в коде", "готово"],
    ["дек 2026 – мар 2027", "Данные", "Бот «Инвазиума», кадастр, аэрофото города, обращения жителей, модуль цветения Sentinel-2", "доступ к данным"],
    ["апр – сен 2027", "Пилот", "3 территории; полёты в мае, июле и августе; сравнение с работой бригад", "KPI достигнуты"],
    ["окт 2027 – 2028", "Масштаб", "Москва и область, API для подрядчиков, 13 видов «Инвазиума», открытый датасет", "решение города"],
  ];
  const y0 = 2.35, w = (CW - 3 * 0.3) / 4;
  s.addShape(pres.shapes.LINE, { x: MX + 0.12, y: y0, w: CW - 0.24, h: 0.001, line: { color: C.sage, width: 1.5 } });
  ph.forEach((p, i) => {
    const x = MX + i * (w + 0.3);
    s.addShape(pres.shapes.OVAL, { x: x + 0.02, y: y0 - 0.12, w: 0.24, h: 0.24, fill: { color: i === 0 ? C.moss : C.paper }, line: { color: C.moss, width: 1.5 } });
    text(s, p[0], { x, y: y0 + 0.22, w, h: 0.3, fontFace: FONT.label, fontSize: 11, color: C.moss });
    text(s, p[1], { x, y: y0 + 0.58, w, h: 0.45, fontFace: FONT.head, fontSize: 20 });
    text(s, p[2], { x, y: y0 + 1.1, w: w - 0.1, h: 1.35, fontSize: 13 });
    text(s, `условие перехода: ${p[3]}`, { x, y: y0 + 2.5, w, h: 0.3, fontFace: FONT.label, fontSize: 10.5, color: C.muted });
  });
  const kpi = [["≥ 90%", "полнота для очагов от 25 м²"], ["≥ 85%", "точность контуров"], ["≤ 5 дней", "от сигнала до выезда"], ["−50%", "расход гербицида"], ["≥ 80%", "очагов закрыто по контролю"]];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX, y: 5.45, w: CW, h: 1.25, rectRadius: 0.08, fill: { color: C.forest }, line: { color: C.forest, width: 0 } });
  text(s, "ЦЕЛЕВЫЕ KPI ПИЛОТА 2027", { x: MX + 0.3, y: 5.6, w: 5, h: 0.3, fontFace: FONT.label, fontSize: 10.5, color: C.amber, charSpacing: 1.5 });
  kpi.forEach((k, i) => {
    const x = MX + 0.3 + i * 2.38;
    text(s, k[0], { x, y: 5.88, w: 2.25, h: 0.45, fontFace: FONT.head, fontSize: 22, color: C.cream });
    text(s, k[1], { x, y: 6.3, w: 2.3, h: 0.35, fontSize: 12, color: C.paperDim });
  });
}

// ================================================================ 19. FIT
{
  const s = slide("LIGHT", "Соответствие номинации", "Проект отвечает на все три акцента номинации: мониторинг среды, анализ экосистем и участие горожан",
    "Номинация «Цифровизация экологических решений» ценит работающие цифровые продукты. Мы показываем три вещи. Мониторинг и управление: карта, очередь, наряды с правовым основанием. Анализ экосистем: две инвазивные угрозы, рельеф и гидрология, область применимости модели, проверка во времени. Участие граждан: фото жителей проверяет ИИ, статус работ возвращается волонтёру. Справа — критерии оценки из инструкции для участников и слайды, где на них ответ. ИнваРадар — расчёт на открытых данных Москвы и ближнего Подмосковья: карта, проекты нарядов и веб-карта. Обход 250 полевых точек ещё впереди.");
  const rows = [
    ["TbMap2", "Мониторинг и управление средой", "Карта города 10 м, очередь выездов, заказ-наряды с допустимым методом и правовым основанием"],
    ["TbLeaf", "Анализ состояния экосистем", "Две инвазивные угрозы, рельеф и гидрология, область применимости модели, разрез по году метки на снимке 2025 года"],
    ["TbUserCheck", "Участие граждан", `ИИ-проверка фото: ${pct(PH.report.auto_triage.share_auto, 0)} сообщений без эксперта; статус работ возвращается волонтёру`],
  ];
  rows.forEach((r, i) => {
    const y = 2.05 + i * 1.12;
    card(s, MX, y, 7.9, 0.98);
    iconDisc(s, r[0], MX + 0.22, y + 0.21);
    text(s, r[1], { x: MX + 1.0, y: y + 0.12, w: 6.7, h: 0.35, fontFace: FONT.bodyBold, fontSize: 14 });
    text(s, r[2], { x: MX + 1.0, y: y + 0.47, w: 6.75, h: 0.48, fontSize: 12.5, color: C.muted });
  });
  const x = 8.85, w = W - 8.85 - MX;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.05, w, h: 3.22, rectRadius: 0.16, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
  text(s, "КРИТЕРИИ ОЦЕНКИ → СЛАЙДЫ", { x: x + 0.3, y: 2.22, w: w - 0.5, h: 0.3, fontFace: FONT.label, fontSize: 10.5, color: C.moss, charSpacing: 1.5 });
  const crit = [["Качество заявки, оформление", "1–32"], ["Актуальность темы", "3–5"], ["Ясность цели и задач", "2, 6"],
    ["Представлен результат работы", "11–16, 21"], ["Уникальность и новаторство", "17–19"], ["Наглядность", "7–21"]];
  crit.forEach((c, i) => {
    const yy = 2.6 + i * 0.43;
    text(s, c[0], { x: x + 0.3, y: yy, w: w - 1.3, h: 0.4, fontSize: 12, valign: "middle" });
    text(s, c[1], { x: x + w - 1.0, y: yy, w: 0.75, h: 0.4, fontFace: FONT.head, fontSize: 12, color: C.purple, align: "right", valign: "middle" });
  });
  text(s, "Отличие от призёров прошлых лет: не только карта или сервис, а замкнутый цикл — найти, поставить в очередь по риску для детей, назначить законный метод и проверить результат.",
    { x: MX, y: 5.55, w: CW, h: 0.65, fontSize: 13 });
  source(s, "ecopremia.moscow: описание номинации и инструкция для участников; mos.ru, 10.12.2024 (призёры 2024)");
}

// ================================================================ 20. ASK
{
  const s = slide("DARK", "Запрос", "Нам нужен один полевой сезон и три территории, чтобы показать цикл целиком",
    "Наш запрос конкретный. Пилот с Мосприродой на трёх природных территориях с известными очагами — сравним с текущей практикой. Разрешение на точечные облёты приоритетных зон в окна цветения, по госзаданию. Доступ к аэрофотосъёмке города и обезличенным обращениям жителей о борщевике. И экспертиза ботаников «Инвазиума»: они проверяют разметку, мы автоматизируем их модерацию. Спасибо, готовы ответить на вопросы.");
  mapCard(s, 10.25, 2.25, 2.0, "Живая карта очагов");
  const asks = [
    ["TbTrees", "Пилот с Мосприродой", "Три природные территории с известными очагами, сравнение с текущей практикой покоса"],
    ["TbDrone", "Облёты по госзаданию", "Точечные полёты над приоритетными зонами в окна цветения"],
    ["TbMap2", "Городские данные", "Аэрофотосъёмка города и обезличенные обращения жителей о борщевике"],
    ["TbMicroscope", "Экспертиза ГБС РАН", "Ботаники «Инвазиума» проверяют разметку, мы автоматизируем модерацию"],
  ];
  asks.forEach((a, i) => {
    const x = MX + (i % 2) * 4.65, y = 2.15 + Math.floor(i / 2) * 1.6, w = 4.45, h = 1.4;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: C.forest2 }, line: { color: "2C5446", width: 0.75 } });
    iconDisc(s, a[0], x + 0.22, y + 0.25, 0.52, C.forest, "amber");
    text(s, a[1], { x: x + 0.95, y: y + 0.22, w: w - 1.1, h: 0.36, fontFace: FONT.head, fontSize: 16, color: C.cream });
    text(s, a[2], { x: x + 0.95, y: y + 0.62, w: w - 1.15, h: 0.72, fontSize: 12.5, color: C.paperDim });
  });
  text(s, "КОМАНДА", { x: MX, y: 5.5, w: 2, h: 0.3, fontFace: FONT.label, fontSize: 10.5, color: C.amber, charSpacing: 1.5 });
  const blank = isBlank;
  const fld = (v, o = {}) => ({ text: String(v), options: Object.assign(blank(v) ? { color: C.warn } : {}, o) });
  text(s, TEAM.members.flatMap((m, i) => [fld(m.name), { text: ` — ${m.role}${i < TEAM.members.length - 1 ? "   ·   " : ""}` }]),
    { x: MX, y: 5.82, w: 9.2, h: 0.35, fontSize: 12, color: C.cream });
  text(s, [fld(TEAM.email), { text: " · " }, fld(TEAM.phone), { text: " · " },
    fld(String(TEAM.repo).replace(/^https?:\/\//, ""), blank(TEAM.repo) ? {} : { hyperlink: { url: TEAM.repo } })],
    { x: MX, y: 6.22, w: 9.2, h: 0.35, fontFace: FONT.label, fontSize: 11, color: C.sage });
}

// ================================================================ APPENDIX
newSection("Приложение");
{
  const s = slide("LIGHT", "Приложение A · методика и данные", "Все данные открытые, а каждая метрика воспроизводится одной командой",
    "Слайд для вопросов о методике. Слева данные и лицензии. Справа кривая захвата: по горизонтали доля площади, которую обходим по карте, по вертикали доля находок, которую при этом встречаем. Серая диагональ — случайный обход. Обе кривые идут выше диагонали на всём диапазоне.");
  const data = [
    ["AlphaEarth Foundations", "эмбеддинги 2025 г., 64 измерения, 10 м", "CC BY 4.0"],
    ["iNaturalist open data", `${fmt(H.samples.presence)} находок борщевика, ${fmt(S.samples.presence)} золотарника; фон из других растений`, "CC0 / CC BY / CC BY-NC"],
    ["Overture Maps", "дороги, ЖД, вода, ЛЭП, застройка, школы, парки", "ODbL / CDLA"],
    ["Copernicus DEM GLO-30", "рельеф, сток, TWI, HAND", "© DLR, Airbus; лицензия Copernicus"],
  ];
  label(s, "данные", { x: MX, y: 2.0, w: 5, h: 0.28 });
  data.forEach((d, i) => {
    const y = 2.35 + i * 0.78;
    s.addShape(pres.shapes.LINE, { x: MX, y: y - 0.04, w: 6.2, h: 0.001, line: { color: C.line, width: 0.75 } });
    text(s, d[0], { x: MX, y, w: 6.2, h: 0.3, fontFace: FONT.bodyBold, fontSize: 13 });
    text(s, d[1], { x: MX, y: y + 0.3, w: 4.3, h: 0.42, fontSize: 11.5, color: C.muted });
    text(s, d[2], { x: MX + 4.35, y: y + 0.3, w: 1.85, h: 0.42, fontFace: FONT.label, fontSize: 9.5, color: C.moss, align: "right" });
  });
  label(s, "проверка", { x: MX, y: 5.55, w: 5, h: 0.28 });
  text(s, "Фон — наблюдения других растений (Phillips et al. 2009) · пространственные блоки 5 км · разрез по году метки на одном снимке AlphaEarth · расчёт на Rust совпадает с эталонной моделью LightGBM до 15-го знака",
    { x: MX, y: 5.88, w: 6.2, h: 0.8, fontSize: 12 });
  const ks = [0, 1, 5, 10, 20];
  const hv = [0, ...[1, 5, 10, 20].map((k) => UH.spatial_cv[`capture@${k}%area`].estimate * 100)];
  const sv = [0, ...[1, 5, 10, 20].map((k) => US.spatial_cv[`capture@${k}%area`].estimate * 100)];
  s.addChart(pres.charts.SCATTER, [
    { name: "X", values: ks },
    { name: "Случайный обход", values: ks },
    { name: "Борщевик", values: hv },
    { name: "Золотарник", values: sv },
  ], Object.assign({
    x: 7.2, y: 1.95, w: 5.55, h: 4.75, lineSize: 2.25, lineDataSymbol: "circle", lineDataSymbolSize: 7, valAxisLabelFormatCode: "0;-0;;@",
    chartColors: ["A9B5AE", C.rust, C.gold], valAxisMinVal: 0, valAxisMaxVal: 55, catAxisMinVal: 0, catAxisMaxVal: 20,
    valAxisLabelFontSize: 11, catAxisLabelFontSize: 11, valAxisLabelColor: C.muted, catAxisLabelColor: C.muted,
    valGridLine: { color: "E1E7E2", size: 0.5 }, catGridLine: { style: "none" },
    showValAxisTitle: true, valAxisTitle: "доля находок, %", valAxisTitleFontSize: 11, valAxisTitleColor: C.muted,
    showCatAxisTitle: true, catAxisTitle: "доля площади, которую обходим по карте, %", catAxisTitleFontSize: 11, catAxisTitleColor: C.muted,
    showLegend: true, legendPos: "t", legendFontSize: 11, legendColor: C.ink,
  }, chartText));
  source(s, "“The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind.” Наблюдения © авторы iNaturalist");
}

{
  const v = EH.validation_design;
  const s = slide("LIGHT", "Приложение B · неопределённость и полевая проверка", "Карта показывает, где она уверена, и сама планирует свою проверку в поле",
    `Две карты. Слева — область применимости модели по методу Meyer и Pebesma: красным отмечены места, признаки которых слишком далеки от обучающих данных. Это ${pct(1 - EH.aoa.share_area_inside_AOA, 1)} площади, и там прогнозу не доверяем. Справа — 250 точек полевой проверки. Они случайные внутри четырёх слоёв карты, поэтому дадут несмещённую оценку площади зарослей, точности и полноты с доверительными интервалами. Находки граждан такого не дают: люди ходят там, где удобно.`);
  s.addImage({ path: img("aoa_heracleum.jpg"), x: MX, y: 2.0, w: 4.1, h: 3.39 });
  text(s, `Область применимости (AOA): ${pct(EH.aoa.share_area_inside_AOA, 1)} площади; вне её — красным`, { x: MX, y: 5.45, w: 4.1, h: 0.5, fontSize: 11.5, color: C.muted });
  s.addImage({ path: img("validation_design.png"), x: MX + 4.3, y: 2.0, w: 3.39, h: 3.39 });
  text(s, "250 точек стратифицированной выборки по слоям вероятности", { x: MX + 4.3, y: 5.45, w: 3.4, h: 0.5, fontSize: 11.5, color: C.muted });
  const x = 8.65, w = W - 8.65 - MX;
  const rows = [["Слой карты", "км²", "точек"]].concat(["0–80%", "80–95%", "95–98%", "98–100%"].map((b, i) => [b, fmt(v.area_km2[i], 1), String(v.n_per_stratum[i])]));
  s.addTable(rows.map((r, ri) => r.map((c, ci) => ({ text: typo(c), options: { fontFace: ri === 0 ? FONT.label : FONT.body, fontSize: ri === 0 ? 10 : 12.5,
    color: ri === 0 ? C.moss : C.ink, align: ci ? "right" : "left", fill: { color: ri % 2 ? C.tint : C.paper } } }))),
    { x, y: 2.0, w, colW: [1.7, 1.25, 1.03], rowH: 0.42, border: { type: "none" }, margin: [0.03, 0.1, 0.03, 0.1] });
  text(s, [
    { text: "Оценка (Olofsson et al. 2014): ", options: { fontFace: FONT.bodyBold } },
    { text: "p = Σ W", options: {} }, { text: "h", options: { subscript: true } }, { text: "·p", options: {} }, { text: "h", options: { subscript: true } },
    { text: ", SE = √(Σ W", options: {} }, { text: "h", options: { subscript: true } }, { text: "²·p", options: {} }, { text: "h", options: { subscript: true } },
    { text: "(1 − p", options: {} }, { text: "h", options: { subscript: true } }, { text: ") / (n", options: {} }, { text: "h", options: { subscript: true } }, { text: " − 1))", options: {} },
  ], { x, y: 4.3, w, h: 0.9, fontFace: FONT.serif, fontSize: 12.5 });
  text(s, "Площади считаются в UTM 37N; привязка к кадастру — пересчёт в ГСК-2011 и МСК-77. Минимальная единица картирования — 400 м².",
    { x, y: 5.3, w, h: 1.0, fontSize: 12, color: C.muted });
  source(s, "Meyer & Pebesma, Methods Ecol. Evol. 12 (2021); Olofsson et al., Remote Sens. Environ. 148 (2014); выборка воспроизводима: повторный расчёт даёт те же точки");
}

{
  const s = slide("LIGHT", "Приложение C · водоохранные зоны", "Водоохранные зоны считаются по Водному кодексу, а длину реки система восстанавливает по сети водотоков",
    `Ширина водоохранной зоны по статье 65 зависит от длины реки, а её нет в открытых слоях. Мы восстанавливаем её сами: линии водотоков в OSM нарисованы по течению, на каждом слиянии главной считаем ветвь с самым длинным путём к истоку. Так Москва-река, Пахра и Десна получают 200 метров, Яуза — 100, ручьи — 50. Пруды меньше 0,5 квадратного километра собственной зоны не имеют, если не стоят на реке. В пилоте заменим это на границы из Государственного водного реестра.`);
  const rows = [["Водный объект", "Ширина зоны", "Очагов борщевика"],
    ["Река длиной 50 км и больше (Москва-река, Пахра, Десна)", "200 м", fmt(wz["200"] || 0)],
    ["Река 10–50 км (Яуза, Сетунь)", "100 м", fmt(wz["100"] || 0)],
    ["Река короче 10 км, ручей, канал; озеро ≥ 0,5 км²; родник", "50 м", fmt(wz["50"] || 0)],
    ["Пруд < 0,5 км² вне реки, технические водоёмы", "нет", "—"]];
  s.addTable(rows.map((r, ri) => r.map((c, ci) => ({ text: typo(c), options: { fontFace: ri === 0 ? FONT.label : (ci === 1 ? FONT.head : FONT.body),
    fontSize: ri === 0 ? 10 : (ci === 1 ? 15 : 13), color: ri === 0 ? C.moss : (ci === 2 ? C.rust : C.ink), align: ci ? "center" : "left", valign: "middle",
    fill: { color: ri % 2 ? C.tint : C.paper } } }))), { x: MX, y: 2.0, w: 8.1, colW: [5.0, 1.4, 1.7], rowH: 0.62, border: { type: "none" }, margin: [0.04, 0.12, 0.04, 0.12] });
  const x = 9.0, w = W - 9.0 - MX;
  card(s, x, 2.0, w, 3.15);
  label(s, "как восстанавливаем длину", { x: x + 0.25, y: 2.18, w: w - 0.4, h: 0.28 });
  text(s, [
    { text: "1. Линии рек в OSM нарисованы по течению — это направленный граф.", options: { breakLine: true } },
    { text: "2. На слиянии главная ветвь та, у которой длиннее путь к истоку.", options: { breakLine: true } },
    { text: "3. Длина водотока — сумма его звеньев; ширина зоны — по ст. 65 ч. 4.", options: { breakLine: true } },
    { text: "4. Пруды и озёра наследуют зону реки, если стоят на ней (≤ 30 м)." },
  ], { x: x + 0.25, y: 2.55, w: w - 0.45, h: 2.5, fontSize: 12.5, paraSpaceAfter: 4 });
  text(s, `Всего в водоохранных зонах ${fmt(pr.in_water_zone_no_pesticides)} очагов борщевика из ${fmt(pr.hotspots)} и ${fmt(prS.in_water_zone_no_pesticides)} очагов золотарника из ${fmt(prS.hotspots)}. Внутри зоны запрещены авиационные меры борьбы с вредными организмами и применение пестицидов (ст. 65 ч. 15 п. 3 и 6), поэтому там только механические методы.`,
    { x: MX, y: 5.35, w: CW, h: 0.9, fontSize: 13.5 });
  source(s, "Водный кодекс РФ, ст. 65 ч. 4, 6, 15; Overture Maps (водные объекты); правила записаны в открытом коде проекта");
}

{
  const s = slide("LIGHT", "Приложение D · общество и наследие", "Инвазия — это и история сельского хозяйства, и риск для археологического наследия",
    "Немного гуманитарного контекста. Борщевик Сосновского описан в 1944 году и с конца 1940-х его сеяли как силосную культуру; заброшенные поля стали резервуаром. Само слово «борщ» у Фасмера исходно значит растение борщевик, а уже потом похлёбку из него. Дачники одновременно жертвы и переносчики. Для наследия важно: подрезка корневой шейки — земляные работы, и рядом с памятниками нужна осторожность. На юге Москвы есть курганы вятичей, например в Царицыне, их изучал Институт археологии РАН.");
  const L = [
    ["TbBook2", "Происхождение", "Вид описан И. П. Манденовой в 1944 г.; с конца 1940-х его сеяли как силосную культуру. Заброшенные поля стали резервуаром инвазии."],
    ["TbLeaf", "Язык", "По словарю Фасмера, «борщ» исходно — растение борщевик (Heracleum sphondylium), затем похлёбка из него. Путаница с двойниками рождает ложные жалобы."],
    ["TbUsers", "Люди", "70% обращений в Подмосковье касаются частных участков: дачники — и жертвы, и переносчики. Приоритет по детям защищает тихие районы, где жалуются реже."],
  ];
  const R = [
    ["TbBuildingMonument", "Земляные работы", "Подрезка корней — это земляные работы; в зонах объектов культурного наследия нужно согласование по 73-ФЗ."],
    ["TbMap2", "Курганы вятичей", "Курганные группы XI–XIII вв. сохранились в лесопарках юга Москвы; группу Царицыно-2 исследовал Институт археологии РАН."],
    ["TbCamera", "Побочный эффект", "Снимки дрона несут микрорельеф, полезный для мониторинга памятников; позднее слияние датчиков взято из нашего проекта КОЗ-3."],
  ];
  [[L, MX], [R, MX + 6.2]].forEach(([arr, x0]) => arr.forEach((r, i) => {
    const y = 2.05 + i * 1.5;
    iconDisc(s, r[0], x0, y, 0.52);
    text(s, r[1], { x: x0 + 0.7, y: y + 0.02, w: 5.2, h: 0.32, fontFace: FONT.bodyBold, fontSize: 14 });
    text(s, r[2], { x: x0 + 0.7, y: y + 0.38, w: 5.2, h: 1.05, fontSize: 12.5, color: C.ink });
  }));
  source(s, "Словарь М. Фасмера, ст. «борщ»; «Археология парка Царицыно», ИА РАН (2008); Минсельхоз МО (2026); 73-ФЗ; github.com/KonkovDV/expds-koz3");
}

{
  const s = slide("LIGHT", "Приложение E · вопросы жюри", "Короткие ответы на вопросы, которые нам задают чаще всего",
    "Шпаргалка к вопросам. Отвечаю коротко и с цифрой.");
  const qa = [
    ["Почему не один нейросетевой детектор по снимкам?", "Одиночное растение меньше пикселя Sentinel-2. Спутник сужает поиск, контур даёт дрон: это разделение следует из физики, а не из удобства."],
    [`Что означают ${pct(UH.spatial_cv["capture@10%area"].estimate)}?`, `Это в ${fmt(UH.spatial_cv["capture@10%area"].lift, 1)} раза лучше случайного обхода на чужих районах, по меткам с погрешностью GPS до 50 м. По устойчивым очагам — ×4, у золотарника в верхнем 1% — ×${fmt(US.spatial_cv["capture@1%area"].lift, 1)}.`],
    ["Чем вы лучше Яндекса?", "Мы не заменяем их детектор, а добавляем очередь по риску для людей, право в коде, фото жителей и контроль. Их карта может стать нашим входом."],
    ["Законно ли опрыскивать с дрона?", "В Москве — нет: в городе зелень обрабатывают только наземно, а беспилотник с пестицидом держится 700 м от жилья, вод и ООПТ (СанПиН п. 273, 282). Дрон обводит куртину, обрабатывает наземная бригада по контуру."],
    ["Что с персональными данными?", "Фото жителей без лиц и геометок дома; хранение в РФ (152-ФЗ); в модели нет персональных данных, только координаты очага."],
    ["Система сама штрафует?", "Нет. Она готовит наряд и доказательства: координаты, контур, фото, дату. Предписание и протокол по ст. 8.7 КоАП — дело инспектора, наряд подписывает человек."],
  ];
  qa.forEach((q, i) => {
    const x = MX + (i % 2) * 6.2, y = 2.0 + Math.floor(i / 2) * 1.6;
    text(s, q[0], { x, y, w: 5.9, h: 0.36, fontFace: FONT.bodyBold, fontSize: 13.5, color: C.moss });
    text(s, q[1], { x, y: y + 0.4, w: 5.9, h: 1.1, fontSize: 12.5 });
  });
}

{
  const s = slide("LIGHT", "Приложение F · источники", "Источники", "Полный список с ссылками — в docs/SOURCES.md в репозитории.");
  const src = [
    "1. 294-ФЗ от 31.07.2025 (вступил в силу 01.03.2026); КоАП РФ ст. 8.7; пост. Правительства Москвы от 03.03.2026 № 369-ПП",
    "2. Россельхознадзор, ВНИИКР: 93 тыс. га за 4 года, +22–27 тыс. га в год (The Moscow Times, 26.08.2026)",
    "3. Минсельхоз МО: план обработки 23,4 тыс. га (abnews.ru, 19.06.2026); первый штраф по данным ИИ и дрона (riamo.ru, 07.08.2026)",
    "4. Мосприрода: покос борщевика на ООПТ до 10 раз за сезон (mos.ru)",
    "5. Запрет полётов БПЛА над Москвой с 03.05.2023 (Meduza, 03.05.2023)",
    "6. Koldasbayeva D. et al. Scientific Reports 12, 6175 (2022), doi:10.1038/s41598-022-09953-9",
    "7. EPPO Global Database, datasheet HERSO; Moravcová L. et al. 2007; Chadin I. et al. PeerJ 9:e11821 (2021)",
    "8. Google DeepMind, AlphaEarth Foundations (30.07.2025); GEO-Bench-2, arXiv:2511.15658",
    "9. Яндекс, ШАД и «СтопБорщевик»: 421 га в 17 регионах (comnews.ru, 02.04.2026)",
    "10. Menshchikov A. et al. Real-Time Detection of Hogweed, IEEE Trans. Computers 70(8), 2021",
    "11. Водный кодекс РФ, ст. 65; СанПиН 2.1.3684-21, разд. XII, п. 282; 73-ФЗ; 248-ФЗ; 152-ФЗ",
    "12. Barnes R. et al. 2014 (Priority-Flood); Beven & Kirkby 1979; Rennó C. D. et al. 2008 (HAND)",
    "13. Meyer H., Pebesma E. 2021 (AOA); Olofsson P. et al. 2014; Phillips S. J. et al. 2009",
    "14. Регламент (ЕС) № 1143/2014 об инвазивных чужеродных видах, ст. 14–17; Valavi R. et al. 2019 (blockCV); Коммерсантъ, 12.11.2025",
    "15. Фасмер М. Этимологический словарь, ст. «борщ»; «Археология парка Царицыно», ИА РАН, 2008",
  ];
  text(s, src.slice(0, 8).join("\n"), { x: MX, y: 1.6, w: 6.0, h: 5.2, fontSize: 11.5, paraSpaceAfter: 5 });
  text(s, src.slice(8).join("\n"), { x: MX + 6.25, y: 1.6, w: 5.9, h: 5.2, fontSize: 11.5, paraSpaceAfter: 5 });
}

{
  const s = slide("LIGHT", "Приложение G · фото, шрифты и лицензии", "Фотографии, данные и шрифты", "Все фото — наблюдения iNaturalist под CC BY или CC0 с указанием авторов; аэрофото — открытый набор Сколтеха.");
  const credits = fs.readFileSync(path.join(IMG, "CREDITS.csv"), "utf8").trim().split("\n").slice(1).map((l) => l.split(","));
  const used = { "hero_stand.jpg": "Обложка", "powerline.jpg": "Слайд 3", "umbel_leaves.jpg": "Слайд 7 (схема патчей)", "umbel.jpg": "Слайды 7, 8, 14",
                 "stem.jpg": "Слайд 8", "angelica.jpg": "Слайд 14", "solidago_panicle.jpg": "Слайд 14", "tansy.jpg": "Слайд 14" };
  const lines = Object.keys(used).map((f) => credits.find((c) => c[0] === f)).filter(Boolean)
    .map((c) => `${used[c[0]]}: ${c[8] || c[7]} (@${c[7]}), ${c[6].replace("CC-BY", "CC BY")}, iNaturalist, фото ${c[1]}`);
  text(s, lines.join("\n"), { x: MX, y: 1.6, w: 7.2, h: 4.5, fontSize: 11.5, paraSpaceAfter: 5 });
  text(s, [
    { text: "Шрифты: ", options: { fontFace: FONT.bodyBold } }, { text: "Montserrat (шрифт сайта премии), Golos Text, Literata — SIL Open Font License 1.1, файлы приложены в папке fonts. Цвета — палитра ecopremia.moscow.", options: { breakLine: true } },
    { text: " ", options: { breakLine: true, fontSize: 6 } },
    { text: "Данные: ", options: { fontFace: FONT.bodyBold } }, { text: "AlphaEarth Foundations © Google, Google DeepMind (CC BY 4.0); iNaturalist; Overture Maps (ODbL, CDLA); Copernicus DEM © DLR e.V., Airbus.", options: { breakLine: true } },
    { text: " ", options: { breakLine: true, fontSize: 6 } },
    { text: "Аэрофото: ", options: { fontFace: FONT.bodyBold } }, { text: "Heracleum Dataset, Menshchikov et al., IEEE Trans. Computers 70(8), 2021 — только для проверки модуля БПЛА, снимки не распространяются. Схема патчей на слайде 7 нарисована по фото iNaturalist.", options: { breakLine: true } },
    { text: " ", options: { breakLine: true, fontSize: 6 } },
    { text: "Иллюстрации: ", options: { fontFace: FONT.bodyBold } }, { text: "горизонтали построены по рельефу Москвы, рисунки зонтика и метёлки — процедурная графика проекта." },
  ], { x: 8.2, y: 1.6, w: W - 8.2 - MX, h: 4.8, fontSize: 12 });
}


{
  const s = slide("LIGHT", "Приложение H · спутник, дрон, пешком", "Три уровня проверки: что доступно Москве в 2026 году и как ИнваРадар это использует",
    "Этот слайд — для вопроса «а почему не дроны?». Спутник: открытые эмбеддинги и Sentinel-2 бесплатны, а снимки ДЗЗ для госзаказчиков с 2026 года платные по 89-ФЗ — ИнваРадар без них обходится. Дрон: с 20 июня 2026 года Росавиация ограничила полёты гражданских беспилотников над Москвой и большей частью Подмосковья до 5 200 метров; летают только государственная и экспериментальная авиация. Экспериментальный режим для агродронов продлён до 2029 года в 19 регионах, но без Москвы и области. Значит, дрон у нас — точечно, по госзаданию. Пешком: с апреля 2026 года инспекторы «Контроля Москвы» осматривают рисковые участки по плану, не дожидаясь жалоб. Это ровно то, для чего нужна наша очередь: сегодня осмотры прошли на 11 территориях, а очередь покрывает весь город.");
  const cols = [
    { ic: "TbSatellite", k: "Спутник", now: [
      "Открытые данные бесплатны: эмбеддинги AlphaEarth (CC BY 4.0), Sentinel-2 — снимок раз в 5 дней",
      "Снимки ДЗЗ для госзаказчиков с 2026 г. платные (89-ФЗ); с 07.07.2026 — порядок закупки у частных спутников",
      "Одиночное растение меньше пикселя 10 м"],
      use: "Карта риска на весь город раз в сезон без закупки снимков" },
    { ic: "TbDrone", k: "Дрон", now: [
      "С 20.06.2026 полёты гражданских БАС над Москвой и большей частью Подмосковья ограничены до 5 200 м; летают госавиация и экспериментальная авиация",
      "Режим для агродронов продлён до 26.09.2029 в 19 регионах — без Москвы и области",
      "В Подмосковье дроны уже обрабатывают борщевик на оврагах и обочинах"],
      use: "Точечный облёт по госзаданию в порядке очереди; контур куртины для наземной бригады" },
    { ic: "TbUsers", k: "Пешком", now: [
      "С апреля 2026 г. «Контроль Москвы» осматривает рисковые участки по плану: первые 43 обследования на 11 ООЗТ",
      "Мосприрода ведёт поадресный перечень очагов и выкашивает новые участки",
      "Жители сообщают через городские сервисы, iNaturalist и «Инвазиум»"],
      use: "Очередь рисковых участков на весь город, полевая выборка 250 точек, ИИ-проверка фото жителей" },
  ];
  cols.forEach((c, i) => {
    const x = MX + i * 4.12, y = 1.95, w = 3.88, h = 4.75;
    card(s, x, y, w, h);
    iconDisc(s, c.ic, x + 0.25, y + 0.22, 0.52);
    text(s, c.k, { x: x + 0.9, y: y + 0.24, w: w - 1.1, h: 0.48, fontFace: FONT.head, fontSize: 18, valign: "middle" });
    text(s, c.now.map((t, k) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: k < c.now.length - 1 } })),
      { x: x + 0.25, y: y + 0.9, w: w - 0.45, h: 2.55, fontSize: 11.5, paraSpaceAfter: 5 });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.18, y: y + 3.52, w: w - 0.36, h: 1.05, rectRadius: 0.12, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
    text(s, [{ text: "ИнваРадар: ", options: { fontFace: FONT.bodyBold, color: C.moss } }, { text: c.use }],
      { x: x + 0.32, y: y + 3.56, w: w - 0.62, h: 0.97, fontSize: 11.5, valign: "middle" });
  });
  source(s, "ComNews, 20.10.2025 (89-ФЗ); kachkin.ru (приказ Роскосмоса, 07.07.2026); Росавиация (fontanka.ru, 17.06.2026); Интерфакс и ГАРАНТ (ПП РФ от 22.05.2026 № 587); Минсельхоз МО (РГ, 19.06.2026); mos.ru, 19.08.2026 и 01.04.2025");
}

// ---------------------------------------------------------------- write
// pptxgenjs writes Office's stock palette into the theme; put the deck's own colours and name there,
// so scheme colours in PowerPoint (Design → Variants) match the slides.
async function applyThemeColors(file, theme) {
  const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const part = "ppt/theme/theme1.xml";
  let xml = await zip.file(part).async("string");
  for (const [slot, hex] of Object.entries(theme.colors)) {
    const re = new RegExp(`(<a:${slot}>)[\\s\\S]*?(</a:${slot}>)`);
    xml = xml.replace(re, `$1<a:srgbClr val="${hex}"/>$2`);
  }
  xml = xml.replace(/(<a:theme [^>]*name=")[^"]*(")/, `$1${theme.name}$2`).replace(/(<a:clrScheme name=")[^"]*(")/, `$1${theme.name}$2`);
  zip.file(part, xml);
  // слайды: мягкий переход «выцветание» для показа на экране; маркерам списков — шрифт текста, а не символьный
  for (const name of Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    let sx = await zip.file(name).async("string");
    sx = sx.replace(/<a:buChar /g, `<a:buFont typeface="${FONT.body}"/><a:buChar `);
    if (!sx.includes("<p:transition")) sx = sx.replace("</p:clrMapOvr>", '</p:clrMapOvr><p:transition spd="med"><p:fade/></p:transition>');
    zip.file(name, sx);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  await pres.writeFile({ fileName: OUTFILE });
  await applyThemeColors(OUTFILE, THEME);
  console.log("written", OUTFILE);
})();
