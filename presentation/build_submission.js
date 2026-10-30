// ИнваРадар — презентация для подачи на Экологическую премию Москвы (pptxgenjs 3.12).
// Требования Положения о конкурсе (приказ ДПиООС от 31.10.2024 № 05-09-280/24):
//   п. 3.3.1 — PPT или PDF, горизонтальная вёрстка, формат A4, не более 10 страниц;
//   п. 3.4, 3.6.3 — титульный лист (ФИО, номинация и тема, телефон, e-mail), оглавление, введение,
//                   основная часть из пяти разделов, заключение;
//   п. 3.6.4 — шрифты Arial, Calibri или Verdana.
// Все числа берутся из outputs/*.json; команда и контакты — из team.json.
//   cd presentation && npm ci && node build_submission.js assets InvaRadar_Ecopremia2026_podacha.pptx
"use strict";
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const IMG = path.resolve(process.argv[2] || path.join(__dirname, "assets"));
const OUTFILE = path.resolve(process.argv[3] || path.join(__dirname, "InvaRadar_Ecopremia2026_podacha.pptx"));
const J = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), "utf8"));

// ---------------------------------------------------------------- data
const H = J("outputs/heracleum/metrics.json");
const Hn = J("outputs/variants/heracleum_no_terrain/metrics.json");
const S = J("outputs/solidago/metrics.json");
const UH = J("outputs/heracleum/uncertainty.json");
const US = J("outputs/solidago/uncertainty.json");
const EH = J("outputs/heracleum/enrich_summary.json");
const ES = J("outputs/solidago/enrich_summary.json");
const XL = J("outputs/heracleum/exp_labels.json");
const PH = J("outputs/photo/metrics.json");
const DR = J("outputs/heracleum/district_route.json");
const DB = J("outputs/drone/benchmark.json").pooled;  // модуль БПЛА на реальных аэрофото; f2 — режим разведки (порог подобран на обучающих камерах)
const TEAM = JSON.parse(fs.readFileSync(path.join(__dirname, "team.json"), "utf8"));

// ---------------------------------------------------------------- русская типографика
const NB = " ";
function fmt(x, d = 0) {
  const [i, f] = Number(x).toFixed(d).split(".");
  const ii = i.replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  return f ? `${ii},${f}` : ii;
}
const pct = (x, d = 1) => `${fmt(x * 100, d)}%`;
const ci = (c, d = 1) => `${fmt(c[0] * 100, d)}–${fmt(c[1] * 100, d)}%`;
const pr = EH.prescriptions, prS = ES.prescriptions;
const h10 = UH.spatial_cv["capture@10%area"], s10 = US.spatial_cv["capture@10%area"], s1 = US.spatial_cv["capture@1%area"];
const ht20 = UH.temporal_test["capture@20%area"], st20 = US.temporal_test["capture@20%area"];
const persist10 = XL.results.all_features.persistent["@10%"];
const auto = PH.report.auto_triage;

// ---------------------------------------------------------------- палитра и шрифты
const C = {
  paper: "F4F6F1", white: "FFFFFF", ink: "14231D", forest: "0F2A22", forest2: "173A30", muted: "56655E",
  moss: "2F6B55", sage: "7F9B88", line: "D5DDD7", tint: "E8EEE9", amber: "E0A030", amberDark: "9A6A12",
  rust: "B4532A", gold: "B8941C", water: "2F6F95", cream: "EDE8D6", paperDim: "C4D2CA",
};
const F = "Arial";
const W = 11.693, HH = 8.268, MX = 0.55, CW = W - 2 * MX;
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
const isBlank = (v) => !v || /^\[.*\]$/.test(String(v).trim());
// адрес веб-карты на GitHub Pages выводится из ссылки на репозиторий github.com/<владелец>/<репозиторий>
function pagesUrl(repo) {
  const m = /github\.com\/([^/\s\]]+)\/([^/\s\]]+)/.exec(String(repo));
  return m && !isBlank(repo) ? `${m[1]}.github.io/${m[2]}` : "[<владелец>.github.io/invaradar]";
}

const pres = new pptxgen();
pres.defineLayout({ name: "A4_LANDSCAPE", width: W, height: HH });
pres.layout = "A4_LANDSCAPE";
pres.author = TEAM.members.filter((m) => !isBlank(m.name)).map((m) => m.name).join(", ") || "Команда ИнваРадар";
pres.company = "ИнваРадар";
pres.title = "ИнваРадар — Экологическая премия Москвы 2026";
pres.subject = "Номинация «Цифровизация экологических решений»";
pres.theme = { headFontFace: F, bodyFontFace: F };

// ---------------------------------------------------------------- примитивы
function T(s, t, o) {
  s.addText(t, Object.assign({ isTextBox: true, margin: 0, fontFace: F, fontSize: 11, color: C.ink, valign: "top",
    lineSpacingMultiple: 1.05 }, o));
}
function rect(s, x, y, w, h, fill, line = null, r = 0) {
  s.addShape(r ? pres.shapes.ROUNDED_RECTANGLE : pres.shapes.RECTANGLE, Object.assign({ x, y, w, h,
    fill: { color: fill }, line: line ? { color: line, width: 0.75 } : { color: fill, width: 0 } }, r ? { rectRadius: r } : {}));
}
function hline(s, x, y, w, color = C.line, width = 0.75) {
  s.addShape(pres.shapes.LINE, { x, y, w, h: 0.001, line: { color, width } });
}
function arrow(s, x1, y1, x2, y2, color = C.sage, width = 1.25) {
  s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1, line: { color, width, endArrowType: "triangle" } });
}
function disc(s, name, x, y, d = 0.42, fill = C.tint, col = "moss") {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill, width: 0 } });
  const p = d * 0.6;
  s.addImage({ path: icon(name, col), x: x + (d - p) / 2, y: y + (d - p) / 2, w: p, h: p });
}
function label(s, t, x, y, w, color = C.moss) {
  T(s, t.toUpperCase(), { x, y, w, h: 0.22, fontSize: 8.5, bold: true, color, charSpacing: 1 });
}
function stat(s, value, caption, x, y, w, color = C.rust, size = 22, capH = 0.62, capSize = 9.5) {
  T(s, value, { x, y, w, h: 0.4, fontSize: size, bold: true, color, valign: "bottom" });
  T(s, caption, { x, y: y + 0.44, w, h: capH, fontSize: capSize, color: C.ink });
}
// QR-код фигурами: тёмные модули по строкам сливаются в полосы (с нахлёстом, без швов), светлое поле — 4 модуля
function qr(s, url, x, y, size) {
  const m = require("qrcode").create(url, { errorCorrectionLevel: "M" }).modules;
  const n = m.size, Z = 4, q = size / (n + 2 * Z), ov = q * 0.06;
  rect(s, x, y, size, size, C.white);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n;) {
      if (!m.get(r, c)) { c++; continue; }
      let e = c; while (e < n && m.get(r, e)) e++;
      rect(s, x + (c + Z) * q, y + (r + Z) * q, (e - c) * q + ov, q + ov, "000000");
      c = e;
    }
  }
}
// поле, которое команда ещё не заполнила, выделяется янтарным
const field = (v, o = {}) => ({ text: String(v), options: Object.assign(isBlank(v) ? { color: C.amber, bold: true } : {}, o) });

// ---------------------------------------------------------------- страница: шапка, навигация, подвал
const NAV = ["Введение", "1", "2", "3", "4", "5", "Заключение"];
const TOTAL = 10;
function page(n, nav, kicker, title, sources) {
  const s = pres.addSlide();
  s.background = { color: C.paper };
  rect(s, MX, 0.36, 0.05, 0.2, C.amber);
  T(s, kicker.toUpperCase(), { x: MX + 0.14, y: 0.35, w: 6.6, h: 0.24, fontSize: 9, bold: true, color: C.moss, charSpacing: 1 });
  // навигация по разделам Положения: Введение · Основная часть 1–5 · Заключение
  const ws = NAV.map((t) => (t.length > 2 ? 0.08 * t.length + 0.12 : 0.3));
  let x = W - MX - ws.reduce((a, b) => a + b, 0) - 0.04 * (NAV.length - 1);
  T(s, "основная часть", { x: x + ws[0] + 0.04, y: 0.12, w: ws.slice(1, 6).reduce((a, b) => a + b, 0) + 0.16, h: 0.16,
    fontSize: 6.5, color: C.muted, align: "center" });
  NAV.forEach((t, i) => {
    const on = i === nav;
    rect(s, x, 0.33, ws[i], 0.25, on ? C.moss : C.paper, on ? C.moss : C.line, 0.05);
    T(s, t, { x, y: 0.33, w: ws[i], h: 0.25, fontSize: 7.5, bold: on, color: on ? C.white : C.muted, align: "center", valign: "middle" });
    x += ws[i] + 0.04;
  });
  T(s, title, { x: MX, y: 0.72, w: CW, h: 0.78, fontSize: 18.5, bold: true, color: C.ink, lineSpacingMultiple: 1.0 });
  hline(s, MX, 7.7, CW, C.line);
  if (sources) T(s, sources, { x: MX, y: 7.76, w: CW - 2.9, h: 0.4, fontSize: 7.5, color: C.muted });
  T(s, [{ text: "ИнваРадар · Экопремия Москвы 2026   " }, { text: `${n} / ${TOTAL}`, options: { bold: true, color: C.moss } }],
    { x: W - MX - 2.75, y: 7.76, w: 2.75, h: 0.22, fontSize: 8, color: C.muted, align: "right" });
  return s;
}

// ================================================================ 1. ТИТУЛЬНЫЙ ЛИСТ
{
  const s = pres.addSlide();
  s.background = { color: C.forest };
  const PX = 5.35;
  photo(s, "hero_stand.jpg", PX, 0, W - PX, HH);
  rect(s, 0, 0, PX + 0.02, HH, C.forest);
  s.addImage({ path: img("fade_forest.png"), x: PX, y: 0, w: 2.2, h: HH });
  T(s, "ЭКОЛОГИЧЕСКАЯ ПРЕМИЯ МОСКВЫ 2026", { x: MX, y: 0.55, w: 4.6, h: 0.25, fontSize: 10, bold: true, color: C.amber, charSpacing: 1.5 });
  T(s, "Номинация «Цифровизация экологических решений»", { x: MX, y: 0.82, w: 4.6, h: 0.25, fontSize: 10.5, color: C.cream });
  T(s, "ИнваРадар", { x: MX, y: 1.45, w: 4.6, h: 0.85, fontSize: 40, bold: true, color: C.cream });
  label(s, "Тема проекта", MX, 2.45, 4.5, C.amber);
  T(s, "Цифровая система раннего обнаружения борщевика Сосновского и золотарников в Москве: от спутникового снимка до наряда бригады и контроля результата",
    { x: MX, y: 2.72, w: 4.45, h: 1.25, fontSize: 13.5, color: C.cream, lineSpacingMultiple: 1.1 });
  label(s, "Участники", MX, 4.2, 4.5, C.amber);
  T(s, TEAM.members.flatMap((m, i) => [field(m.name, { breakLine: false }),
    { text: ` — ${m.role}`, options: { color: C.paperDim, breakLine: i < TEAM.members.length - 1 } }]),
    { x: MX, y: 4.47, w: 4.5, h: 1.05, fontSize: 10.5, color: C.cream, paraSpaceAfter: 3 });
  label(s, "Контакты", MX, 5.68, 4.5, C.amber);
  T(s, [field(TEAM.phone), { text: "   ·   ", options: { color: C.sage } }, field(TEAM.email, { breakLine: true }),
    { text: "Открытый код и данные: ", options: { color: C.paperDim } }, field(TEAM.repo)],
    { x: MX, y: 5.95, w: 4.5, h: 0.55, fontSize: 10.5, color: C.cream, paraSpaceAfter: 2 });
  T(s, [{ text: "Heracleum sosnowskyi", options: { italic: true } }, { text: " Manden. · " },
    { text: "Solidago canadensis", options: { italic: true } }, { text: " L. · " },
    { text: "S. gigantea", options: { italic: true } }, { text: " Aiton" }],
    { x: MX, y: 6.95, w: 4.5, h: 0.25, fontSize: 9.5, color: C.sage });
  T(s, "Москва, 2026", { x: MX, y: 7.42, w: 3, h: 0.25, fontSize: 9.5, color: C.sage });
  T(s, "Фото справа: заросли борщевика Сосновского, Калужская обл. Maxim Shashkov, iNaturalist, CC BY", { x: MX, y: 7.75, w: 4.6, h: 0.22,
    fontSize: 7.5, color: C.sage });
}

// ================================================================ 2. ОГЛАВЛЕНИЕ И ВВЕДЕНИЕ
{
  const s = page(2, 0, "Оглавление · Введение", "ИнваРадар отвечает на все три акцента номинации «Цифровизация экологических решений»: мониторинг, анализ экосистем, участие граждан",
    "Описание номинации и критерии оценки — ecopremia.moscow; Положение о конкурсе, приложение 2 (приказ ДПиООС от 31.10.2024 № 05-09-280/24).");
  // оглавление
  label(s, "Оглавление", MX, 1.68, 3.6);
  const toc = [
    ["Титульный лист", "1", false], ["Оглавление. Введение", "2", false], ["Основная часть", "", true],
    ["1. Обоснованность и актуальность", "3", false], ["2. Цель и задачи", "4", false],
    ["3. Подходы, методики, решения", "5–6", false], ["4. Привлечённые ресурсы", "7", false],
    ["5. Количественные и качественные характеристики", "8–9", false], ["Заключение. Перспективы реализации", "10", false],
  ];
  toc.forEach((r, i) => {
    const y = 1.98 + i * 0.36;
    if (r[2]) { T(s, r[0].toUpperCase(), { x: MX, y: y + 0.08, w: 3.6, h: 0.22, fontSize: 8, bold: true, color: C.muted, charSpacing: 1 }); return; }
    const sub = /^\d\./.test(r[0]);
    T(s, r[0], { x: MX + (sub ? 0.12 : 0), y, w: 3.35, h: 0.32, fontSize: 9.8, bold: !sub, valign: "middle" });
    T(s, r[1], { x: MX + 3.3, y, w: 0.4, h: 0.32, fontSize: 9.8, bold: true, color: C.moss, align: "right", valign: "middle" });
    hline(s, MX, y + 0.33, 3.7, C.line, 0.5);
  });
  // карта критериев
  rect(s, MX, 5.38, 3.7, 2.18, C.tint, null, 0.06);
  label(s, "Критерии оценки — где ответ", MX + 0.18, 5.5, 3.4);
  const crit = [["Обоснованность и актуальность", "3"], ["Цели и задачи, их соответствие теме", "4"], ["Результат представлен и подтверждён", "8–9"],
    ["Тиражирование", "7, 10"], ["Научная обоснованность", "5–6"], ["Наглядность: графики, схемы, фото, видео", "все, 10"],
    ["Уникальность и новаторство", "9"], ["Соответствие содержания целям", "4, 10"], ["Оформление, все разделы", "1–10"]];
  crit.forEach((c, i) => {
    T(s, [{ text: `${i + 1}. `, options: { bold: true, color: C.moss } }, { text: c[0] }], { x: MX + 0.18, y: 5.78 + i * 0.19, w: 2.85, h: 0.19, fontSize: 8.5 });
    T(s, c[1], { x: MX + 3.0, y: 5.78 + i * 0.19, w: 0.55, h: 0.19, fontSize: 8.5, bold: true, color: C.moss, align: "right" });
  });
  // введение
  const X = MX + 4.15, WW = CW - 4.15;
  label(s, "Введение", X, 1.68, WW);
  T(s, "Номинация поддерживает цифровые решения, которые «акцентируют внимание на мониторинге и управлении окружающей средой, помогают анализировать состояние экологических систем, создают условия для активного участия граждан». ИнваРадар отвечает на все три акцента:",
    { x: X, y: 1.98, w: WW, h: 0.8, fontSize: 10.5, color: C.ink, lineSpacingMultiple: 1.1 });
  const fit = [
    ["TbMap2", "Мониторинг и управление средой", `Ежегодная карта очагов с шагом 10${NB}м по всей зоне расчёта, очередь выездов по риску для людей, наряд с допустимым по закону методом работ и контроль результата.`],
    ["TbLeaf", "Анализ состояния экосистем", "Два опасных инвазивных вида, коридоры распространения, рельеф и гидрология; модель проверена на районах и годах, которых не видела, и сама отмечает зону своей применимости."],
    ["TbUserCheck", "Участие граждан", `Житель присылает фото, ИИ проверяет вид и отличает двойников; ${pct(auto.share_auto, 0)} сообщений разбирается без эксперта, статус работ возвращается автору.`],
  ];
  fit.forEach((f, i) => {
    const y = 2.84 + i * 1.03;
    rect(s, X, y, WW, 0.95, C.white, C.line, 0.06);
    disc(s, f[0], X + 0.18, y + 0.24, 0.46);
    T(s, f[1], { x: X + 0.8, y: y + 0.09, w: WW - 1.0, h: 0.26, fontSize: 11, bold: true });
    T(s, f[2], { x: X + 0.8, y: y + 0.36, w: WW - 0.95, h: 0.56, fontSize: 9.3, color: C.muted });
  });
  rect(s, X, 5.98, WW, 1.58, C.forest, null, 0.06);
  T(s, "ПРОЕКТ ДЕЙСТВУЮЩИЙ", { x: X + 0.25, y: 6.1, w: WW - 0.5, h: 0.22, fontSize: 8.5, bold: true, color: C.amber, charSpacing: 1 });
  T(s, [
    { text: `Система работает на данных Москвы и ближнего Подмосковья: ${fmt(4225)}${NB}км², ${fmt(42.25, 2)}${NB}млн пикселей, ${fmt(pr.hotspots)} вероятных очагов борщевика и ${fmt(prS.hotspots)} — золотарника, у каждого есть приоритет и наряд. `, options: { breakLine: true } },
    { text: "Код открыт (Apache-2.0), карты и очаги — открытые данные (CC BY 4.0); веб-карта и видео — по ссылкам на стр. 10. Каждая цифра воспроизводится одной командой.", options: { color: C.paperDim } },
  ], { x: X + 0.25, y: 6.36, w: WW - 0.5, h: 1.15, fontSize: 10, color: C.cream, lineSpacingMultiple: 1.08, paraSpaceAfter: 3 });
}

// ================================================================ 3. ОБОСНОВАННОСТЬ И АКТУАЛЬНОСТЬ
{
  const s = page(3, 1, "Основная часть · 1. Обоснованность и актуальность",
    `Борщевик расширяется быстрее, чем его находят, а с 1 марта 2026 года бороться с ним обязан каждый правообладатель`,
    "Россельхознадзор, ВНИИКР (The Moscow Times, 26.08.2026); Минсельхоз МО (abnews.ru, 19.06.2026); Мосприрода (mos.ru); 294-ФЗ от 31.07.2025; КоАП РФ ст. 8.7; решение Мэра Москвы от 03.05.2023; Google DeepMind (30.07.2025); EPPO HERSO; Koldasbayeva et al., Sci. Rep. 12, 6175 (2022); riamo.ru (07.08.2026).");
  photo(s, "powerline.jpg", MX, 1.66, 2.95, 5.0, [0.12, 0.5]);  // опора ЛЭП слева остаётся в кадре
  T(s, "Борщевик Сосновского под ЛЭП, Московская область, июль 2026. Фото: Stanislav Murashkin, iNaturalist, CC BY",
    { x: MX, y: 6.72, w: 2.95, h: 0.4, fontSize: 7.5, color: C.muted });
  const X = MX + 3.25, WW = CW - 3.25;
  const stats = [
    [`93${NB}тыс.${NB}га`, `заражённых сельхозземель выявлено в России за четыре года; ежегодно добавляется 22–27${NB}тыс.${NB}га`, C.rust],
    [`23,4${NB}тыс.${NB}га`, "Подмосковье планировало обработать от борщевика только в сезон 2026 года", C.rust],
    [`до${NB}10${NB}раз`, "за лето Мосприрода выкашивает борщевик на особо охраняемых природных территориях Москвы", C.rust],
    [`до${NB}700${NB}тыс.${NB}₽`, "штраф по ст. 8.7 КоАП (граждане — от 20 тыс. ₽): с 01.03.2026 бороться обязан любой правообладатель (294-ФЗ)", C.moss],
  ];
  const cw = (WW - 0.3) / 2;
  stats.forEach((st, i) => {
    const x = X + (i % 2) * (cw + 0.3), y = 1.66 + Math.floor(i / 2) * 1.12;
    stat(s, st[0], st[1], x, y, cw, st[2], 21, 0.6, 9.5);
  });
  // почему сейчас
  label(s, "Почему именно сейчас", X, 4.0, WW);
  const why = [
    ["TbGavel", "Закон", "Обязанность и штрафы с 1 марта 2026 г.: нужна карта, которая выдержит проверку"],
    ["TbDrone", "Небо", "С мая 2023 г. полёты дронов над Москвой ограничены: сплошной облёт невозможен, искать надо из космоса"],
    ["TbSatellite", "Технология", `С июля 2025 г. открыты эмбеддинги AlphaEarth Foundations: 64 признака на каждые 10${NB}м Земли`],
  ];
  const ww = (WW - 0.3) / 3;
  why.forEach((w, i) => {
    const x = X + i * (ww + 0.15);
    rect(s, x, 4.27, ww, 1.28, C.white, C.line, 0.06);
    disc(s, w[0], x + 0.14, 4.39, 0.38);
    T(s, w[1], { x: x + 0.6, y: 4.43, w: ww - 0.7, h: 0.3, fontSize: 10.5, bold: true, valign: "middle" });
    T(s, w[2], { x: x + 0.14, y: 4.82, w: ww - 0.26, h: 0.7, fontSize: 8.8, color: C.muted });
  });
  // здоровье и кто страдает
  rect(s, X, 5.7, WW, 1.42, C.tint, null, 0.06);
  disc(s, "TbSun", X + 0.15, 5.83, 0.4, C.white, "rust");
  T(s, [{ text: "Опасность для людей. ", options: { bold: true } },
    { text: "Фурокумарины сока (псорален, бергаптен, ксантотоксин) под ультрафиолетом А сшиваются с ДНК клеток кожи; ожог проявляется через 24–48 ч, пигментация держится месяцами. Самые уязвимые — дети у зарослей во дворах и на пустырях." }],
    { x: X + 0.7, y: 5.8, w: WW - 0.9, h: 0.62, fontSize: 9.2 });
  T(s, [{ text: "Кому и что даёт: ", options: { bold: true } },
    { text: "Департаменту и Мосприроде — единую карту очагов и измеримый эффект работ; ГБС РАН («Инвазиум») — автоматическую проверку фото волонтёров; подрядчикам — точечный наряд и доказательство работ; жителям — статус работ по их сообщению." }],
    { x: X + 0.7, y: 6.44, w: WW - 0.9, h: 0.66, fontSize: 9.2 });
  T(s, "Прогноз Сколтеха: к 2040–2060 гг. условия для борщевика сложатся почти на всей европейской части России. Пилот Подмосковья в 2026 г. уже выписал первый штраф по данным спутника, дрона и ИИ — государство идёт этим путём.",
    { x: MX, y: 7.2, w: CW, h: 0.42, fontSize: 9, color: C.muted, italic: true });
}

// ================================================================ 4. ЦЕЛЬ И ЗАДАЧИ
{
  const s = page(4, 2, "Основная часть · 2. Цель и задачи",
    "Цель — замкнуть для Москвы цикл «нашли → обработали законным методом → проверили результат», чтобы бригады работали адресно, а не вслепую",
    "Статусы — на 30.10.2026. Номера страниц — где показан результат. Сезон 2027 года — см. заключение.");
  rect(s, MX, 1.66, CW, 0.95, C.forest, null, 0.06);
  T(s, "ЦЕЛЬ", { x: MX + 0.25, y: 1.78, w: 1.0, h: 0.22, fontSize: 8.5, bold: true, color: C.amber, charSpacing: 1 });
  T(s, `Дать Москве открытую цифровую систему, которая раз в сезон находит очаги борщевика Сосновского и золотарников с шагом 10${NB}м, ставит их в очередь по риску для людей, назначает допустимый по закону метод работ и проверяет результат повторным снимком.`,
    { x: MX + 1.25, y: 1.74, w: CW - 1.5, h: 0.8, fontSize: 11, color: C.cream, valign: "middle", lineSpacingMultiple: 1.08 });
  // задачи
  const head = ["№", "Задача", "Результат на сегодня", "Статус", "Стр."];
  const rows = [
    ["1", "Найти: карта вероятности очагов на 4 225 км²", `${fmt(42.25, 2)}${NB}млн пикселей по 10${NB}м, два вида; проверка на новых районах и годах`, "выполнено", "8"],
    ["2", "Расставить приоритеты по риску для людей и путям распространения", `${fmt(pr.hotspots)} + ${fmt(prS.hotspots)} очагов в очереди; дневной маршрут ${fmt(DR.route_km, 1)}${NB}км`, "выполнено", "9"],
    ["3", "Подтвердить находку: фото жителей и съёмка с дрона", `ИИ-проверка фото: точность ${pct(PH.report.heracleum_binary.precision)} (борщевик); модуль БПЛА проверен на ${DB.images} реальных аэрофото Подмосковья: ROC AUC ${fmt(DB.patch_roc_auc, 2)}`, "выполнено", "6, 9"],
    ["4", "Назначить метод работ по Водному кодексу, СанПиН и 73-ФЗ", "Правила в коде: для каждого очага — метод, основание и сроки; автотесты на каждом наряде", "выполнено", "6"],
    ["5", "Проверить результат и дообучить модель", "Контрольный снимок, полевая выборка 250 точек и дообучение готовы к запуску", "сезон 2027", "10"],
  ];
  const colW = [0.4, 3.35, 4.4, 1.6, 0.83];
  const hdr = head.map((t, i) => ({ text: t, options: { bold: true, fontSize: 8.5, color: C.moss, align: i === 4 ? "center" : "left", fill: { color: C.paper } } }));
  const body = rows.map((r, ri) => r.map((c, ci) => ({ text: c, options: {
    fontSize: ci === 0 ? 12 : 9.5, bold: ci === 0 || ci === 1 || ci === 4, valign: "middle", align: ci === 4 || ci === 0 ? "center" : "left",
    color: ci === 0 ? C.moss : (ci === 3 ? (c.startsWith("выполнено") ? C.moss : C.amberDark) : C.ink),
    fill: { color: ri % 2 ? C.paper : C.tint } } })));
  s.addTable([hdr, ...body], { x: MX, y: 2.78, w: CW, colW, rowH: [0.3, 0.54, 0.54, 0.6, 0.54, 0.54], fontFace: F,
    border: { type: "none" }, margin: [0.03, 0.08, 0.03, 0.08] });
  // цикл
  label(s, "Пять задач — пять шагов одного цикла; мера успеха — KPI пилота на стр. 10", MX, 6.02, 8);
  const steps = [["TbSatellite", "Спутник"], ["TbListNumbers", "Очередь"], ["TbCamera", "Проверка"], ["TbClipboardCheck", "Наряд"], ["TbRepeat", "Контроль"]];
  const sw = 1.72, gap = 0.5, y = 6.32;
  steps.forEach((st, i) => {
    const x = MX + i * (sw + gap);
    rect(s, x, y, sw, 0.5, C.white, C.moss, 0.25);
    disc(s, st[0], x + 0.07, y + 0.06, 0.38, C.tint);
    T(s, `${i + 1}. ${st[1]}`, { x: x + 0.5, y, w: sw - 0.55, h: 0.5, fontSize: 10, bold: true, valign: "middle" });
    if (i < 4) arrow(s, x + sw + 0.04, y + 0.25, x + sw + gap - 0.04, y + 0.25, C.amber, 1.5);
  });
  const xl = MX + sw / 2, xr = MX + 4 * (sw + gap) + sw / 2;
  s.addShape(pres.shapes.LINE, { x: xr, y: y + 0.5, w: 0.001, h: 0.3, line: { color: C.amber, width: 1.25 } });
  s.addShape(pres.shapes.LINE, { x: xl, y: y + 0.8, w: xr - xl, h: 0.001, line: { color: C.amber, width: 1.25 } });
  arrow(s, xl, y + 0.8, xl, y + 0.52, C.amber, 1.25);
  T(s, "результат контроля становится разметкой: с каждым сезоном модель точнее", { x: xl + 0.3, y: y + 0.84, w: xr - xl - 0.6, h: 0.24,
    fontSize: 8.5, color: C.muted, align: "center", italic: true });
}

// ================================================================ 5. ПОДХОДЫ И МЕТОДИКИ: КАК УСТРОЕНА СИСТЕМА
{
  const s = page(5, 3, "Основная часть · 3. Подходы, методики, решения (1/2)",
    "Каждый уровень делает то, что умеет лучше других: спутник сужает поиск, модель ставит очередь, дрон и житель подтверждают",
    "Barnes et al. 2014 (Priority-Flood); O'Callaghan, Mark 1984 (D8); Beven, Kirkby 1979 (TWI); Rennó et al. 2008 (HAND); Phillips et al. 2009; Roberts et al. 2017; Meyer, Pebesma 2021; Olofsson et al. 2014; EPPO HERSO; Moravcová et al. 2007; Google DeepMind 2025.");
  // схема: данные → ядро → выходы → проверка
  const cols = [
    { t: "Открытые данные", ic: "TbBook2", items: ["AlphaEarth Foundations: 64 признака на 10 м, 2025", "iNaturalist: находки жителей и фон", "Overture Maps: дороги, реки, ЛЭП, школы, ООПТ", "Copernicus DEM GLO-30: рельеф"] },
    { t: "Ядро на Rust", ic: "TbCpu", items: ["Признаки в окнах 50, 150, 450 м: 265 на пиксель", "Рельеф: Priority-Flood → D8 → TWI, HAND", "Инференс LightGBM (расхождение 9·10⁻¹⁶)", `Карта ${fmt(42.25, 2)} млн пикселей ≈ 2 мин на 4 ядрах`] },
    { t: "Решения для города", ic: "TbClipboardCheck", items: ["Карта вероятности 10 м (COG)", "Очаги ≥ 400 м² и приоритет", "Маршрут бригады на день", "Наряд: метод, закон, сроки"] },
    { t: "Проверка и контроль", ic: "TbRepeat", items: ["Фото жителя → ИИ-проверка вида", "Дрон по госзаданию обводит куртину", "Контрольный снимок через 3–4 недели", "Итог → разметка следующего сезона"] },
  ];
  const cw = 2.38, gap = 0.355, y0 = 1.68, ch = 2.28;
  cols.forEach((c, i) => {
    const x = MX + i * (cw + gap), dark = i === 1;
    rect(s, x, y0, cw, ch, dark ? C.forest : C.white, dark ? null : C.line, 0.06);
    disc(s, c.ic, x + 0.15, y0 + 0.14, 0.4, dark ? C.forest2 : C.tint, dark ? "amber" : "moss");
    T(s, c.t, { x: x + 0.62, y: y0 + 0.14, w: cw - 0.7, h: 0.4, fontSize: 10.5, bold: true, color: dark ? C.cream : C.ink, valign: "middle" });
    T(s, c.items.map((t, k) => ({ text: t, options: { bullet: { indent: 10 }, breakLine: k < c.items.length - 1 } })),
      { x: x + 0.12, y: y0 + 0.66, w: cw - 0.2, h: ch - 0.75, fontSize: 9, color: dark ? C.paperDim : C.ink, paraSpaceAfter: 4 });
    if (i < 3) arrow(s, x + cw + 0.04, y0 + ch / 2, x + cw + gap - 0.04, y0 + ch / 2, C.amber, 1.75);
  });
  // научные основания
  label(s, "Научные основания решений", MX, 4.12, 6);
  const sci = [
    ["Физика сигнала", `Пиксель Sentinel-2 — смесь цветков и фона: ρ = f·ρ₁ + (1 − f)·ρ₀. Различима доля f ≥ z·σ / |ρ₁ − ρ₀| ≈ 0,08–0,15, т. е. 8–15${NB}м² соцветий на 100${NB}м². Одиночное растение из космоса не видно — поэтому спутник сужает поиск, а контур даёт дрон: GSD = H·p / F = 2,7${NB}см с высоты 100${NB}м.`],
    ["Экология и статистика", "Фон — наблюдения других растений теми же людьми (снимает смещение к дорогам и паркам, Phillips 2009). Проверка блоками 5 × 5 км и «вперёд во времени» (Roberts 2017). Область применимости модели (Meyer, Pebesma 2021). Полевая выборка по слоям (Olofsson 2014)."],
    ["Геофизика и гидрология", `Рельеф проверен как гипотеза с заранее заданным критерием: для борщевика, который держится сырых обочин, брошенных полей и берегов, он улучшил прогноз новых находок (${pct(Hn.temporal_test["capture@20%area"])} → ${pct(H.temporal_test["capture@20%area"])}) и оставлен; для золотарника — ухудшил и исключён.`],
    ["Ботаника", "Борщевик — монокарпик: цветёт раз на 3–6-й год и отмирает; 15–20 тыс. семян, единицы процентов живут 2–3 года. Отсюда правила наряда: срезать зонтики до конца июля, подрезать корневую шейку на 5–10 см, наблюдать очаг 5 сезонов."],
  ];
  const sw = (CW - 0.45) / 4;
  sci.forEach((c, i) => {
    const x = MX + i * (sw + 0.15);
    rect(s, x, 4.4, sw, 2.12, C.tint, null, 0.06);
    T(s, c[0], { x: x + 0.14, y: 4.5, w: sw - 0.28, h: 0.26, fontSize: 10, bold: true, color: C.moss });
    T(s, c[1], { x: x + 0.14, y: 4.8, w: sw - 0.26, h: 1.68, fontSize: 9.1, lineSpacingMultiple: 1.05 });
  });
  // модуль БПЛА на реальных аэрофото: полоса из трёх снимков разных камер (1867 × 420 px)
  const dw = 4.0, dh = dw * 420 / 1867;
  s.addImage({ path: img("drone_real_strip.jpg"), x: MX, y: 6.58, w: dw, h: dh });
  T(s, "Mavic Pro · Phantom 3 · Xiaomi Yi", { x: MX, y: 6.58 + dh + 0.01, w: dw, h: 0.16, fontSize: 7, color: C.muted, align: "center" });
  T(s, [{ text: "Модуль БПЛА на реальных аэрофото Подмосковья. ", options: { bold: true, color: C.ink } },
    { text: "Белый контур — разметка ботаников, янтарь — ИнваРадар; снимавшая камера в обучении не участвовала." }],
    { x: MX + dw + 0.12, y: 6.62, w: 6.3 - dw - 0.22, h: 1.0, fontSize: 7.8, color: C.muted, valign: "middle" });
  rect(s, MX + 6.3, 6.66, CW - 6.3, 0.95, C.white, C.line, 0.06);
  T(s, [{ text: "Метрика, понятная заказчику: ", options: { bold: true } },
    { text: "какая доля известных очагов попадает в k% площади, которые бригада обойдёт первыми (кривая выигрыша, ср. отношение P/E индекса Бойса, Hirzel 2006). Случайный обход даёт ровно k%." }],
    { x: MX + 6.45, y: 6.7, w: CW - 6.6, h: 0.88, fontSize: 8.6, valign: "middle" });
}

// ================================================================ 6. ПОДХОДЫ: ПРАВО В КОДЕ И УЧАСТИЕ ГРАЖДАН
{
  const s = page(6, 3, "Основная часть · 3. Подходы, методики, решения (2/2)",
    "Метод работ выбирается по закону: в водоохранных зонах — только механика, в городе дрон — разведчик, а фото жителей проверяет ИИ",
    "ВК РФ ст. 65 (ред. от 04.08.2026); СанПиН 2.1.3684-21 п. 272–273, 282 (ред. пост. Главного санитарного врача РФ от 12.02.2026 № 2); 73-ФЗ; 248-ФЗ; Overture Maps. Фото: Вячеслав Юсупов, Екатерина Гущина, Dr. Sven Gippner, Natalya Ivanova — iNaturalist, CC BY.");
  const WL = 6.55;
  label(s, `Правила для ${fmt(pr.hotspots)} очагов борщевика`, MX, 1.68, WL);
  const rules = [
    ["TbDroplet", "Водоохранная зона 50 / 100 / 200 м", "ВК РФ ст. 65 ч. 4–6; ч. 15 п. 3 и 6", pr.in_water_zone_no_pesticides, "пестициды запрещены — только механика"],
    ["TbMoodKid", "Территория школы или детского сада", "СанПиН 2.1.3684-21 п. 273", pr.child_org_territory, "пестициды запрещены"],
    ["TbMoodKid", "Дети в 100 м: школы, сады, площадки", "правило осторожности системы", pr.near_children_100m, "без пестицидов, первыми в очереди"],
    ["TbTrees", "ООПТ и парки", "режим ООПТ; практика Мосприроды", pr.in_protected_mechanical, "только механика"],
    ["TbHome", "В городе или < 700 м до жилья, вод, ООПТ", "СанПиН п. 282 (для БАС с 10.03.2026), п. 273", pr.aerial_blocked_uav_700m, "дрон с пестицидом запрещён — наземная бригада"],
    ["TbBuildingMonument", "Объект наследия в 50 м", "73-ФЗ", pr.near_heritage_no_digging, "без земляных работ"],
  ];
  rules.forEach((r, i) => {
    const y = 1.96 + i * 0.5;
    if (i % 2 === 0) rect(s, MX, y - 0.02, WL, 0.48, C.tint);
    disc(s, r[0], MX + 0.06, y + 0.04, 0.38, C.white);
    T(s, r[1], { x: MX + 0.52, y: y + 0.02, w: 3.0, h: 0.22, fontSize: 9.3, bold: true });
    T(s, r[2], { x: MX + 0.52, y: y + 0.23, w: 3.05, h: 0.2, fontSize: 7.8, color: C.muted });
    T(s, fmt(r[3]), { x: MX + 3.55, y, w: 0.95, h: 0.44, fontSize: 15, bold: true, color: C.rust, align: "right", valign: "middle" });
    T(s, r[4], { x: MX + 4.62, y, w: WL - 4.7, h: 0.44, fontSize: 8.6, valign: "middle" });
  });
  // итог
  const yI = 5.0;
  rect(s, MX, yI, WL, 1.42, C.forest, null, 0.06);
  T(s, "ИТОГ ДЛЯ НАРЯДОВ (БОРЩЕВИК / ЗОЛОТАРНИК)", { x: MX + 0.22, y: yI + 0.1, w: WL - 0.4, h: 0.22, fontSize: 8.5, bold: true, color: C.amber, charSpacing: 1 });
  const outs = [[pr.mechanical_only, prS.mechanical_only, "только механические методы"], [pr.ground_spot_treatment, prS.ground_spot_treatment, "наземная точечная обработка по контуру"],
    [pr.drone_spraying_allowed, prS.drone_spraying_allowed, "опрыскивание с дрона допустимо — только вне населённых пунктов"]];
  const ow = (WL - 0.44) / 3;
  outs.forEach((o, i) => {
    const x = MX + 0.22 + i * ow;
    T(s, [{ text: fmt(o[0]), options: { color: i === 2 ? C.amber : C.cream } }, { text: ` / ${fmt(o[1])}`, options: { color: C.sage, fontSize: 11 } }],
      { x, y: yI + 0.38, w: ow - 0.1, h: 0.42, fontSize: 18, bold: true, valign: "bottom" });
    T(s, o[2], { x, y: yI + 0.84, w: ow - 0.15, h: 0.5, fontSize: 8.6, color: C.paperDim });
  });
  T(s, [{ text: "ИИ не выписывает штрафов. ", options: { bold: true } },
    { text: "Он даёт индикатор риска для надзора (248-ФЗ); наряд подписывает человек. В каждом наряде — условия СанПиН: оповещение жителей за 5 дней, знаки, работа до 7 или после 22 ч в безветрие. Слои подключаются к официальным реестрам (ГВР, ООПТ, ЕГРОКН) без изменения правил; 12 автотестов проверяют закон на каждом наряде." }],
    { x: MX, y: 6.52, w: WL, h: 1.1, fontSize: 8.8 });
  // жители
  const X = MX + WL + 0.3, WR = CW - WL - 0.3;
  label(s, "Участие граждан: фото → ИИ → статус работ", X, 1.68, WR);
  const pics = [["umbel.jpg", "Борщевик Сосновского", "Heracleum sosnowskyi", C.rust], ["angelica.jpg", "Дудник лесной — двойник", "Angelica sylvestris", C.muted],
    ["solidago_panicle.jpg", "Золотарник гигантский", "Solidago gigantea", C.gold], ["tansy.jpg", "Пижма — двойник", "Tanacetum vulgare", C.muted]];
  const pw = (WR - 0.3) / 4, ph = 1.55;
  pics.forEach((p, i) => {
    const x = X + i * (pw + 0.1);
    photo(s, p[0], x, 1.96, pw, ph);
    T(s, p[1], { x, y: 3.55, w: pw, h: 0.34, fontSize: 7.8, bold: true, color: p[3] });
    T(s, p[2], { x, y: 3.88, w: pw, h: 0.2, fontSize: 7.5, italic: true, color: C.muted });
  });
  const ph3 = [[pct(auto.share_auto, 0), `сообщений ИИ разбирает сам (уверенность ≥ 0,9); среди них верны ${pct(auto.accuracy_on_auto)}. Остальные — ботанику`, C.moss],
    [pct(PH.report.heracleum_binary.precision), `точность (полнота ${pct(PH.report.heracleum_binary.recall)}): борщевик против дудника, борщевика сибирского, купыря и сныти`, C.rust],
    [pct(PH.report.solidago_binary.precision), `точность (полнота ${pct(PH.report.solidago_binary.recall)}): золотарник против пижмы, крестовника и зверобоя`, C.gold]];
  ph3.forEach((p, i) => stat(s, p[0], p[1], X, 4.22 + i * 0.98, WR, p[2], 20, 0.5, 9));
  rect(s, X, 7.12, WR, 0.5, C.tint, null, 0.05);
  T(s, `${fmt(PH.n_images)} фото iNaturalist, 4 класса; проверка без пересечения авторов (5 фолдов по наблюдателям); YOLO11-cls + логистическая регрессия.`,
    { x: X + 0.12, y: 7.12, w: WR - 0.24, h: 0.5, fontSize: 8, color: C.muted, valign: "middle" });
}

// ================================================================ 7. ПРИВЛЕЧЁННЫЕ РЕСУРСЫ
{
  const s = page(7, 4, "Основная часть · 4. Привлечённые ресурсы",
    "Проект собран на открытых данных и открытом коде: запуск в другом городе не требует закупок, а премия целиком идёт в полевой пилот",
    "Лицензии: AlphaEarth Foundations Satellite Embedding — CC BY 4.0 («produced by Google and Google DeepMind»); iNaturalist — CC0 / CC BY / CC BY-NC; Overture Maps — ODbL / CDLA-Permissive-2.0; Copernicus DEM © DLR e.V., Airbus; DINOv2 — Apache-2.0; Ultralytics YOLO11 — AGPL-3.0; аэрофото — Menshchikov et al. 2021.");
  const cols = [
    { t: "Данные", ic: "TbBook2", rows: [
      ["AlphaEarth Foundations", "эмбеддинги 2025 г., 64 признака на 10 м"],
      ["iNaturalist", `${fmt(H.samples.presence)} находок борщевика, ${fmt(S.samples.presence)} — золотарника, ${fmt(H.samples.background)} фоновых наблюдений, ${fmt(PH.n_images)} фото`],
      ["Overture Maps, Copernicus DEM", "дороги, ЖД, вода, ЛЭП, застройка, школы, сады, площадки, парки; рельеф"],
      ["Аэрофото Сколтеха", `${DB.images} реальных снимков борщевика в Подмосковье с масками — проверка модуля БПЛА`]] },
    { t: "Технологии", ic: "TbCpu", rows: [
      ["Rust-ядро", "признаки, рельеф и гидрология, инференс, очаги, маршрут, выборка"],
      ["Python и ИИ", "LightGBM, GeoPandas, rasterio; DINOv2 для дрона, YOLO11-cls для фото"],
      ["Открытые форматы", "Cloud Optimized GeoTIFF, GeoParquet, каталог STAC 1.1"],
      ["Качество", "33 автотеста (6 Rust, 27 Python), из них 12 — закон на каждом наряде; CI на каждый коммит"]] },
    { t: "Вычисления и сроки", ic: "TbCalendarEvent", rows: [
      ["Железо", "обычный сервер: 4 ядра CPU, без GPU для карты"],
      ["Скорость", `карта ${fmt(42.25, 2)} млн пикселей ≈ 2 мин; весь прогон вида с проверкой 13–15 мин`],
      ["Данные на диске", "около 9 ГБ исходников, всё скачивается скриптами"],
      ["Хранение в РФ", "в пилоте — облако в РФ, фото жителей без лиц и геометок дома (152-ФЗ)"]] },
  ];
  const cw = (CW - 0.4) / 3;
  cols.forEach((c, i) => {
    const x = MX + i * (cw + 0.2);
    rect(s, x, 1.66, cw, 3.12, C.white, C.line, 0.06);
    disc(s, c.ic, x + 0.15, 1.78, 0.4);
    T(s, c.t, { x: x + 0.65, y: 1.78, w: cw - 0.8, h: 0.4, fontSize: 11.5, bold: true, valign: "middle" });
    c.rows.forEach((r, k) => {
      const y = 2.3 + k * 0.61;
      if (k) hline(s, x + 0.15, y - 0.05, cw - 0.3, C.line, 0.5);
      T(s, r[0], { x: x + 0.15, y, w: cw - 0.3, h: 0.2, fontSize: 8.8, bold: true, color: C.moss });
      T(s, r[1], { x: x + 0.15, y: y + 0.2, w: cw - 0.3, h: 0.38, fontSize: 8.6 });
    });
  });
  // команда и партнёры
  const yb = 4.95;
  rect(s, MX, yb, 5.1, 2.62, C.tint, null, 0.06);
  label(s, "Команда", MX + 0.2, yb + 0.13, 4.6);
  T(s, TEAM.members.flatMap((m, i) => [field(m.name), { text: ` — ${m.role}`, options: { color: C.muted, breakLine: i < TEAM.members.length - 1 } }]),
    { x: MX + 0.2, y: yb + 0.4, w: 4.7, h: 0.82, fontSize: 9.5, paraSpaceAfter: 2 });
  label(s, "Роли городских партнёров в пилоте 2027 года", MX + 0.2, yb + 1.28, 4.7);
  T(s, [{ text: "Мосприрода", options: { bold: true } }, { text: " — три природные территории с известными очагами, сравнение с текущей практикой.", options: { breakLine: true } },
    { text: "ГБС РАН им. Н. В. Цицина («Инвазиум»)", options: { bold: true } }, { text: " — экспертная разметка, данные волонтёров о 13 видах.", options: { breakLine: true } },
    { text: "Оператор БПЛА", options: { bold: true } }, { text: " — облёты приоритетных зон по госзаданию." }],
    { x: MX + 0.2, y: yb + 1.53, w: 4.7, h: 1.05, fontSize: 8.8, paraSpaceAfter: 2 });
  // бюджет
  const X = MX + 5.3, WR = CW - 5.3;
  label(s, "Премия → полевой пилот 2027 года (1 млн ₽)", X, yb + 0.02, WR);
  const budget = [["Полевые выезды и облёты", 35, C.moss], ["Экспертная разметка ботаников", 25, C.rust], ["Интеграции: бот, кадастр, API", 20, C.water],
    ["Вычисления и хранение в РФ", 15, C.gold], ["Резерв", 5, C.sage]];
  let bx = X;
  budget.forEach((b) => {
    const bw = WR * b[1] / 100;
    rect(s, bx, yb + 0.32, bw, 0.42, b[2]);
    T(s, `${b[1]}%`, { x: bx, y: yb + 0.32, w: bw, h: 0.42, fontSize: 9.5, bold: true, color: C.white, align: "center", valign: "middle" });
    bx += bw;
  });
  budget.forEach((b, i) => {
    const x = X + (i % 2) * (WR / 2), y = yb + 0.82 + Math.floor(i / 2) * 0.22;
    rect(s, x, y + 0.05, 0.12, 0.12, b[2]);
    T(s, `${b[0]} — ${fmt(b[1] * 10)} тыс. ₽`, { x: x + 0.18, y, w: WR / 2 - 0.2, h: 0.22, fontSize: 8, valign: "middle" });
  });
  rect(s, X, yb + 1.55, WR, 1.07, C.white, C.line, 0.06);
  disc(s, "TbMap2", X + 0.15, yb + 1.7, 0.4);
  T(s, [{ text: "Тиражирование. ", options: { bold: true } },
    { text: "Все входные данные глобальные и открытые: тот же код считает карту любого города России, где есть наблюдения вида. Новые виды (13 видов списка «Инвазиума») добавляются разметкой, без переписывания системы. Код — Apache-2.0, карты и очаги — CC BY 4.0." }],
    { x: X + 0.68, y: yb + 1.62, w: WR - 0.82, h: 0.95, fontSize: 8.8, valign: "middle" });
}

// ================================================================ 8. РЕЗУЛЬТАТЫ: КАРТА И ЕЁ ПРОВЕРКА
{
  const s = page(8, 5, "Основная часть · 5. Количественные и качественные характеристики (1/2)",
    `Карта Москвы с шагом 10 м: на районах, которых модель не видела, она находит очаги в ${fmt(h10.lift, 1)}–${fmt(s10.lift, 1)} раза чаще случайного обхода`,
    "Расчёты ИнваРадара 1.2, октябрь 2026; AlphaEarth Foundations © Google, Google DeepMind (CC BY 4.0); iNaturalist, исследовательский уровень, точность координат ≤ 50 м; Overture Maps. 95% ДИ — кластерный бутстрэп по блокам 5 км (2000 повторов) и интервал Уилсона.");
  const MS = 5.25;
  s.addImage({ path: img("heracleum_city.png"), x: MX, y: 1.62, w: MS, h: MS });
  rect(s, MX + 0.12, 1.74, 2.75, 0.62, C.white, C.line, 0.04);
  T(s, "Борщевик Сосновского, 2025: верхние 10% площади по вероятности", { x: MX + 0.22, y: 1.77, w: 2.6, h: 0.32, fontSize: 7.8, bold: true });
  const hot = ["F3D9A0", "E0A030", "C4561F", "7A1E12"];
  hot.forEach((c, i) => rect(s, MX + 0.22 + i * 0.42, 2.12, 0.42, 0.12, c));
  T(s, "10%  →  1%", { x: MX + 1.95, y: 2.07, w: 0.85, h: 0.2, fontSize: 7.5, color: C.muted });
  T(s, `Территория 65 × 65 км = ${fmt(4225)} км², ${fmt(42.25, 2)} млн пикселей по 10 м`, { x: MX, y: 6.93, w: MS, h: 0.22, fontSize: 8, color: C.muted });
  // кривая выигрыша
  const X = MX + MS + 0.3, WR = CW - MS - 0.3;
  const k = ["1", "5", "10", "20"];
  const get = (U) => k.map((q) => U.spatial_cv[`capture@${q}%area`].estimate * 100);
  s.addChart(pres.charts.LINE, [
    { name: "Случайный обход", labels: k.map((q) => `${q}%`), values: [1, 5, 10, 20] },
    { name: "Борщевик", labels: k.map((q) => `${q}%`), values: get(UH) },
    { name: "Золотарник", labels: k.map((q) => `${q}%`), values: get(US) },
  ], { x: X - 0.05, y: 1.6, w: WR + 0.05, h: 2.75, chartColors: ["9AA8A0", C.rust, C.gold], lineSize: 2.25, lineDataSymbol: "circle", lineDataSymbolSize: 6,
    showLegend: true, legendPos: "t", legendFontSize: 8.5, legendFontFace: F, catAxisLabelFontSize: 8.5, valAxisLabelFontSize: 8.5,
    catAxisLabelFontFace: F, valAxisLabelFontFace: F, valAxisMaxVal: 50, valAxisMinVal: 0, valAxisMajorUnit: 10,
    valAxisLabelFormatCode: '0"%"', valGridLine: { color: "E3E8E4", size: 0.5 }, catAxisLineShow: true,
    showValue: false,
    showTitle: true, title: "Доля находок в k% площади, обойдённых первыми (новые районы)", titleFontSize: 9, titleFontFace: F, titleColor: C.muted,
    showCatAxisTitle: true, catAxisTitle: "k — доля площади карты", catAxisTitleFontSize: 8, catAxisTitleColor: C.muted });
  const cards = [
    [`×${fmt(h10.lift, 1)}`, `борщевик: в верхних 10% площади ${pct(h10.estimate)} находок (95% ДИ ${ci(h10.ci95)})`, C.rust],
    [`×${fmt(s10.lift, 1)}`, `золотарник: ${pct(s10.estimate)} находок в верхних 10% (95% ДИ ${ci(s10.ci95)}); в верхнем 1% — ×${fmt(s1.lift, 1)}`, C.gold],
    [pct(ht20.estimate), `новых находок борщевика 2025–2026 гг. в верхних 20% площади; модель видела данные до 2024 г. (n${NB}=${NB}${UH.temporal_test.n_new_presence}, ДИ ${ci(ht20.ci95)})`, C.rust],
    [`×${fmt(persist10 * 10, 1)}`, `устойчивые очаги (≥ 2 независимых наблюдателя, n${NB}=${NB}${XL.n_persistent}): ${pct(persist10)} в верхних 10% площади`, C.moss],
  ];
  const cw2 = (WR - 0.2) / 2;
  cards.forEach((c, i) => {
    const x = X + (i % 2) * (cw2 + 0.2), y = 4.45 + Math.floor(i / 2) * 1.1;
    rect(s, x, y, cw2, 1.0, C.white, C.line, 0.05);
    T(s, c[0], { x: x + 0.12, y: y + 0.05, w: cw2 - 0.2, h: 0.36, fontSize: 17, bold: true, color: c[2] });
    T(s, c[1], { x: x + 0.12, y: y + 0.42, w: cw2 - 0.22, h: 0.56, fontSize: 7.9 });
  });
  rect(s, X, 6.67, WR, 0.92, C.tint, null, 0.05);
  T(s, [{ text: "Как проверяли. ", options: { bold: true } },
    { text: `Территория разбита на блоки 5 × 5 км; находки проверяемого блока не участвуют в обучении. Тест «вперёд во времени» — обучение до 2024 г., проверка на находках 2025–2026 гг. Метрика не требует подбора порогов. Область применимости — ${pct(EH.aoa.share_area_inside_AOA)} площади (борщевик) и ${pct(ES.aoa.share_area_inside_AOA)} (золотарник); остальное карта отмечает сама.` }],
    { x: X + 0.12, y: 6.68, w: WR - 0.24, h: 0.9, fontSize: 7.9, valign: "middle" });
}

// ================================================================ 9. РЕЗУЛЬТАТЫ: ОЧЕРЕДЬ, НАРЯДЫ, НОВИЗНА
{
  const s = page(9, 5, "Основная часть · 5. Количественные и качественные характеристики (2/2)",
    `Каждый вероятный очаг получает приоритет, место в маршруте и наряд; ${fmt(H.hotspots.within_300m_of_child_facility)} очагов борщевика — в 300 м от школ, садов и площадок`,
    "Расчёты ИнваРадара 1.2, октябрь 2026; Overture Maps; iNaturalist (сообщения жителей в окне карты — по API, 30.10.2026); comnews.ru (02.04.2026); riamo.ru (07.08.2026); Menshchikov et al., IEEE Trans. Computers 70(8), 2021 и их открытый набор аэрофото; gbsad.ru.");
  const MS = 4.55;
  s.addImage({ path: img("heracleum_district.png"), x: MX, y: 1.62, w: MS, h: MS });
  T(s, `Юг Москвы, окно 9 × 9 км: ${DR.stops} самых приоритетных очагов и дневной маршрут ${fmt(DR.route_km, 1)} км (синяя линия); чёрные точки — ${DR.known_reports_in_view} сообщений жителей iNaturalist`,
    { x: MX, y: 6.22, w: MS, h: 0.45, fontSize: 8, color: C.muted });
  const X = MX + MS + 0.3, WR = CW - MS - 0.3;
  const st = [
    [fmt(pr.hotspots), `вероятных очагов борщевика и ${fmt(prS.hotspots)} — золотарника (≥ 400 м²), у каждого приоритет, метод и основание`, C.rust],
    [fmt(H.hotspots.within_300m_of_child_facility), `очагов борщевика в 300 м от школ, детских садов и площадок; ${fmt(pr.near_children_100m)} — ближе 100 м`, C.rust],
    [`${fmt(DR.route_km, 1)} км`, `маршрут бригады через ${DR.stops} приоритетных точек; ядро строит его за доли секунды`, C.water],
  ];
  const sw3 = (WR - 0.3) / 3;
  st.forEach((v, i) => stat(s, v[0], v[1], X + i * (sw3 + 0.15), 1.62, sw3, v[2], 19, 0.78, 8.6));
  rect(s, X, 2.88, WR, 0.85, C.tint, null, 0.05);
  T(s, [{ text: "Приоритет = ", options: { bold: true } }, { text: "вероятность × близость людей × близость дорог, рек и ЛЭП × размер очага. Каждый множитель виден оператору. " },
    { text: "Модуль БПЛА ", options: { bold: true } }, { text: `(DINOv2 + линейный классификатор, контуры, полётное задание) проверен на ${DB.images} реальных аэрофото Подмосковья, камера проверки в обучении не участвовала: ROC AUC ${fmt(DB.patch_roc_auc, 2)}, Dice ${fmt(DB.f2.pixel_dice, 2)}; борщевик найден на ${DB.f2.images_with_hogweed_detected.replace("/", " из ")} снимков.` }],
    { x: X + 0.12, y: 2.9, w: WR - 0.24, h: 0.82, fontSize: 8.4, valign: "middle" });
  // новизна
  label(s, "Уникальность: весь цикл вместо одного-двух шагов", X, 3.88, WR);
  const Y = "●", P = "○", N = "—";  // символы из набора WGL4: есть в Arial
  const head = ["Решение", "Космос", "Дрон", "Жители + ИИ", "Риск для людей", "Право в коде", "Контроль"];
  const rows = [
    ["ШАД Яндекса + «СтопБорщевик», 2026", Y, N, P, N, N, N],
    ["Пилот Минсельхоза МО, 2026", Y, Y, N, N, P, N],
    ["Сколтех, бортовой ИИ дрона, 2021", N, Y, N, N, N, N],
    ["«Инвазиум», ГБС РАН", N, N, P, N, N, N],
    ["ИнваРадар", Y, Y, Y, Y, Y, "2027"],
  ];
  const hdr = head.map((t, i) => ({ text: t, options: { bold: true, fontSize: 7, color: C.moss, align: i ? "center" : "left", valign: "bottom", fill: { color: C.paper } } }));
  const body = rows.map((r, ri) => r.map((c, ci) => ({ text: c, options: {
    fontSize: ci === 0 ? 8.3 : (c === Y || c === P ? 11 : 8), bold: ci === 0 || ri === 4, valign: "middle", align: ci ? "center" : "left",
    color: ri === 4 ? (ci === 0 ? C.cream : C.amber) : (c === N ? "A9B5AE" : (ci === 0 ? C.ink : C.moss)),
    fill: { color: ri === 4 ? C.forest : (ri % 2 ? C.paper : C.tint) } } })));
  s.addTable([hdr, ...body], { x: X, y: 4.12, w: WR, colW: [2.0, 0.58, 0.52, 0.66, 0.66, 0.66, 0.66].map((v) => v * WR / 5.74), rowH: [0.36, 0.34, 0.34, 0.34, 0.34, 0.36],
    fontFace: F, border: { type: "none" }, margin: [0.02, 0.04, 0.02, 0.04] });
  T(s, "● есть   ○ частично   — нет; 2027 — методика готова, первый сезон. Новое: закон выводится в наряд каждого очага, очередь строится по риску для детей. Карта Яндекса, данные «Инвазиума» и дроны подрядчиков становятся входами одного цикла.",
    { x: X, y: 6.25, w: WR, h: 0.42, fontSize: 8, color: C.muted });
  rect(s, MX, 6.78, CW, 0.82, C.forest, null, 0.05);
  T(s, "КАЧЕСТВЕННЫЙ РЕЗУЛЬТАТ", { x: MX + 0.2, y: 6.86, w: 3, h: 0.2, fontSize: 8, bold: true, color: C.amber, charSpacing: 1 });
  T(s, "Вместо «карты для отчёта» — рабочие документы: очередь выездов, маршрут на день и наряд с методом, сроками и правовым основанием для каждого очага. Всё это можно открыть в браузере: интерактивная карта очагов с нарядами — ссылка на стр. 10.",
    { x: MX + 0.2, y: 7.08, w: CW - 0.4, h: 0.48, fontSize: 9, color: C.cream });
}

// ================================================================ 10. ЗАКЛЮЧЕНИЕ
{
  const s = page(10, 6, "Заключение · Перспективы реализации",
    "Система работает и проверена на данных Москвы; полевой сезон 2027 года делает её городским сервисом, который тиражируется на любой регион",
    "Сроки и KPI — план команды; пилот проводится по соглашению с городскими организациями. Открытый репозиторий: код Apache-2.0, данные CC BY 4.0.");
  // выводы
  const WL = 4.3;
  label(s, "Выводы", MX, 1.68, WL);
  const concl = [
    `Создана работающая система: карта двух инвазивных видов на ${fmt(4225)} км² с шагом 10 м, очередь, маршрут и наряды для ${fmt(pr.hotspots + prS.hotspots)} вероятных очагов.`,
    `Качество подтверждено на районах и годах, которых модель не видела: в ${fmt(h10.lift, 1)}–${fmt(s10.lift, 1)} раза лучше случайного обхода; модуль БПЛА — на ${DB.images} реальных аэрофото (ROC AUC ${fmt(DB.patch_roc_auc, 2)}).`,
    "Правила Водного кодекса, СанПиН и 73-ФЗ заложены в код и проверяются автотестами: система не назначит пестициды в водоохранной зоне или у детей.",
    `Жители становятся сенсорами: ИИ разбирает ${pct(auto.share_auto, 0)} сообщений сам и отличает двойников.`,
  ];
  concl.forEach((c, i) => {
    const y = 1.96 + i * 0.86;
    T(s, `${i + 1}`, { x: MX, y, w: 0.35, h: 0.4, fontSize: 18, bold: true, color: C.amber });
    T(s, c, { x: MX + 0.4, y: y + 0.02, w: WL - 0.4, h: 0.8, fontSize: 9.5 });
  });
  // дорожная карта
  const X = MX + WL + 0.3, WR = CW - WL - 0.3;
  label(s, "Перспективы реализации", X, 1.68, WR);
  const ph = [["ноя 2026", "Версия 1.2", "карты, очередь, маршрут, ИИ-фото, модуль БПЛА, право в коде", "готово"],
    ["дек 2026 – мар 2027", "Данные", "бот «Инвазиума», кадастр, аэрофото, обращения, цветение Sentinel-2", "доступ к данным"],
    ["апр – сен 2027", "Пилот", "3 территории, облёты в мае, июле, августе, сравнение с бригадами", "KPI достигнуты"],
    ["окт 2027 – 2028", "Масштаб", "Москва и область, API для подрядчиков, 13 видов, открытый датасет", "решение города"]];
  const pw = (WR - 0.45) / 4, y0 = 2.1;
  hline(s, X + 0.1, y0, WR - 0.2, C.sage, 1.25);
  ph.forEach((p, i) => {
    const x = X + i * (pw + 0.15);
    s.addShape(pres.shapes.OVAL, { x, y: y0 - 0.1, w: 0.2, h: 0.2, fill: { color: i === 0 ? C.moss : C.paper }, line: { color: C.moss, width: 1.25 } });
    T(s, p[0], { x, y: y0 + 0.16, w: pw, h: 0.2, fontSize: 8, bold: true, color: C.moss });
    T(s, p[1], { x, y: y0 + 0.38, w: pw, h: 0.3, fontSize: 12, bold: true });
    T(s, p[2], { x, y: y0 + 0.7, w: pw - 0.05, h: 0.78, fontSize: 8.4 });
    T(s, `ворота: ${p[3]}`, { x, y: y0 + 1.5, w: pw, h: 0.2, fontSize: 7.5, color: C.muted, italic: true });
  });
  rect(s, X, 3.95, WR, 1.0, C.forest, null, 0.06);
  T(s, "KPI ПИЛОТА", { x: X + 0.2, y: 4.03, w: 2, h: 0.2, fontSize: 8, bold: true, color: C.amber, charSpacing: 1 });
  const kpi = [["≥ 90%", "полнота для очагов от 25 м²"], ["≥ 85%", "точность контуров"], ["≤ 5 дней", "от сигнала до выезда"], ["−50%", "расход гербицида"], ["≥ 80%", "очагов закрыто по контролю"]];
  const kw = (WR - 0.4) / 5;
  kpi.forEach((k2, i) => {
    T(s, k2[0], { x: X + 0.2 + i * kw, y: 4.25, w: kw, h: 0.34, fontSize: 14, bold: true, color: C.cream });
    T(s, k2[1], { x: X + 0.2 + i * kw, y: 4.6, w: kw - 0.08, h: 0.32, fontSize: 7.6, color: C.paperDim });
  });
  // тиражирование и запрос
  const hw = (WR - 0.2) / 2;
  rect(s, X, 5.1, hw, 2.5, C.white, C.line, 0.06);
  disc(s, "TbMap2", X + 0.15, 5.22, 0.38);
  T(s, "Тиражирование", { x: X + 0.6, y: 5.22, w: hw - 0.7, h: 0.38, fontSize: 10.5, bold: true, valign: "middle" });
  T(s, [{ text: "Любой город России: входные данные глобальные и открытые.", options: { bullet: { indent: 9 }, breakLine: true } },
    { text: "Новые виды — разметкой, без переписывания системы.", options: { bullet: { indent: 9 }, breakLine: true } },
    { text: "Сценарий для Подмосковья: каждые 10% площади, не обработанные вслепую, — около 32 млн ₽ за сезон (23,4 тыс. га × 13,8 тыс. ₽/га).", options: { bullet: { indent: 9 } } }],
    { x: X + 0.15, y: 5.68, w: hw - 0.3, h: 1.85, fontSize: 8.6, paraSpaceAfter: 3 });
  const X2 = X + hw + 0.2;
  rect(s, X2, 5.1, hw, 2.5, C.tint, null, 0.06);
  disc(s, "TbTarget", X2 + 0.15, 5.22, 0.38, C.white);
  T(s, "Что предлагаем городу", { x: X2 + 0.6, y: 5.22, w: hw - 0.7, h: 0.38, fontSize: 10.5, bold: true, valign: "middle" });
  T(s, [{ text: "Пилот с Мосприродой на трёх природных территориях.", options: { bullet: { indent: 9 }, breakLine: true } },
    { text: "Точечные облёты приоритетных зон по госзаданию.", options: { bullet: { indent: 9 }, breakLine: true } },
    { text: "Аэрофото города и обезличенные обращения жителей.", options: { bullet: { indent: 9 }, breakLine: true } },
    { text: "Экспертиза ботаников ГБС РАН («Инвазиум»).", options: { bullet: { indent: 9 } } }],
    { x: X2 + 0.15, y: 5.68, w: hw - 0.3, h: 1.85, fontSize: 8.6, paraSpaceAfter: 3 });
  // контакты и QR-код репозитория (рисуется фигурами, когда ссылка заполнена)
  rect(s, MX, 5.55, WL, 2.05, C.forest, null, 0.06);
  T(s, "ОТКРЫТЫЙ КОД И КОНТАКТЫ", { x: MX + 0.2, y: 5.65, w: WL - 0.4, h: 0.2, fontSize: 8, bold: true, color: C.amber, charSpacing: 1 });
  const qrOn = !isBlank(TEAM.repo), tw = qrOn ? WL - 2.0 : WL - 0.4;
  T(s, [{ text: "Код: ", options: { color: C.paperDim } }, field(TEAM.repo, { breakLine: true }),
    { text: "Карта очагов: ", options: { color: C.paperDim } }, field(TEAM.map || pagesUrl(TEAM.repo), { breakLine: true }),
    field(TEAM.email, { breakLine: true }), field(TEAM.phone, { breakLine: true }),
    ...(TEAM.video ? [{ text: "Видео: ", options: { color: C.paperDim } }, field(TEAM.video, { breakLine: true })] : []),
    { text: "Каждую цифру можно воспроизвести из репозитория одной командой: make all.", options: { color: C.paperDim, fontSize: 8.5 } }],
    { x: MX + 0.2, y: 5.92, w: tw, h: 1.6, fontSize: 10, color: C.cream, paraSpaceAfter: 4 });
  if (qrOn) qr(s, `https://${TEAM.repo.replace(/^https?:\/\//, "")}`, MX + WL - 1.72, 5.72, 1.6);
}

pres.writeFile({ fileName: OUTFILE }).then((f) => console.log("written", f));
