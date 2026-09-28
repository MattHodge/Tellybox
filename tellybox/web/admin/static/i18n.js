// Interface languages (NF-13): the admin pages' runtime text, translated on the server.
// base.html embeds <script type="application/json" id="i18n"> built from
// tellybox/web/admin/js_strings.py; every string used here must be listed there.

const data = (() => {
  try {
    return JSON.parse(document.getElementById("i18n")?.textContent || "{}");
  } catch {
    return {};
  }
})();

// Python-style placeholders, the same as in the catalogs: "%(num)d", "%(name)s".
function fill(text, vars) {
  return text.replace(/%\((\w+)\)[sd]/g, (match, key) => (vars && key in vars ? String(vars[key]) : match));
}

export const lang = document.documentElement.lang || "en";

export function t(msgid, vars) {
  return fill(data.s?.[msgid] ?? msgid, vars);
}

export function tn(singular, plural, n, vars) {
  const forms = data.p?.[singular];
  const text = forms ? forms[n === 1 ? 0 : 1] : n === 1 ? singular : plural;
  return fill(text, { num: n, ...vars });
}
