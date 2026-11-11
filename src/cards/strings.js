// Each language's strings, by language tag. The files in strings/ fill it in,
// one language each, as the bundle loads.
const STRINGS = {};

// The strings for `locale`: the exact language, then its base language
// (pt-BR falls back to pt for keys it does not override, and any Chinese to
// zh-Hans), then English.
function translate(locale) {
  const base = locale.split("-")[0];
  const exact = Object.keys(STRINGS).find((k) => k.toLowerCase() === locale.toLowerCase());
  const zh = base === "zh" ? STRINGS["zh-Hans"] : undefined;
  return { ...STRINGS.en, ...STRINGS[base], ...zh, ...(exact && STRINGS[exact]) };
}
