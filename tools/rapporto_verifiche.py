"""Unisce i risultati delle verifiche automatiche in un unico rapporto HTML.

Uso:  python tools/rapporto_verifiche.py <cartella_risultati>

Nella cartella si aspettano (prodotti dal flusso di GitHub Actions):
  test.xml        risultati dei test (pytest --junitxml)
  bandit.json     analisi di sicurezza del codice (bandit -f json)
  pip-audit.json  vulnerabilità note delle librerie (pip-audit -f json)
  librerie.txt    versioni delle librerie installate (pip freeze)

Scrive RAPPORTO_VERIFICHE.html e, se eseguito su GitHub, il riepilogo della pagina dell'esecuzione.
Esce con codice 1 se un test fallisce, se l'analisi trova problemi di gravità media o alta,
se una libreria ha vulnerabilità note o se una verifica non ha prodotto risultati.
"""
import datetime
import hashlib
import html
import json
import os
import sys
import xml.etree.ElementTree as ET  # nosec B405 - legge solo il file prodotto da pytest nella stessa esecuzione

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = ["pdfpaper.py", "requirements.txt"]


def esc(v):
    return html.escape(str(v))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def read_tests(path):
    if not os.path.isfile(path):
        return None
    root = ET.parse(path).getroot()  # nosec B314
    rows = []
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '').split('.')[-1]} › {case.get('name')}"
        status, detail = "superato", ""
        for tag, label in (("failure", "fallito"), ("error", "errore"), ("skipped", "saltato")):
            el = case.find(tag)
            if el is not None:
                status, detail = label, (el.get("message") or el.text or "").strip()
                break
        rows.append((name, status, detail, float(case.get("time") or 0)))
    return rows


def read_bandit(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    loc = data.get("metrics", {}).get("_totals", {}).get("loc")
    issues = [(r["issue_severity"], r["issue_confidence"], r["test_id"], r["test_name"],
               os.path.relpath(r["filename"], ROOT) if os.path.isabs(r["filename"]) else r["filename"],
               r["line_number"], r["issue_text"]) for r in data.get("results", [])]
    return issues, loc


def read_audit(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    deps = data.get("dependencies", data) if isinstance(data, dict) else data
    rows = []
    for d in deps:
        vulns = d.get("vulns", [])
        rows.append((d.get("name"), d.get("version", d.get("skip_reason", "")),
                     [(v.get("id"), ", ".join(v.get("fix_versions", []))) for v in vulns]))
    return rows


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "verifiche"
    tests = read_tests(os.path.join(out_dir, "test.xml"))
    bandit = read_bandit(os.path.join(out_dir, "bandit.json"))
    audit = read_audit(os.path.join(out_dir, "pip-audit.json"))
    libs = ""
    if os.path.isfile(os.path.join(out_dir, "librerie.txt")):
        with open(os.path.join(out_dir, "librerie.txt"), encoding="utf-8", errors="replace") as fh:
            libs = fh.read().strip()

    problems = []
    # --- test
    if tests is None:
        problems.append("test automatici non eseguiti")
        t_ok = t_fail = t_skip = 0
    else:
        t_fail = sum(1 for r in tests if r[1] in ("fallito", "errore"))
        t_skip = sum(1 for r in tests if r[1] == "saltato")
        t_ok = sum(1 for r in tests if r[1] == "superato")
        if t_fail:
            problems.append(f"{t_fail} test non superati")
        if not tests:
            problems.append("nessun test trovato")
    # --- bandit
    if bandit is None:
        problems.append("analisi del codice non eseguita")
        b_issues, b_loc = [], None
    else:
        b_issues, b_loc = bandit
        serious = [i for i in b_issues if i[0] in ("MEDIUM", "HIGH")]
        if serious:
            problems.append(f"{len(serious)} segnalazioni di gravità media o alta nell'analisi del codice")
    # --- pip-audit
    if audit is None:
        problems.append("controllo delle vulnerabilità delle librerie non eseguito")
        a_vuln = 0
    else:
        a_vuln = sum(len(r[2]) for r in audit)
        if a_vuln:
            problems.append(f"{a_vuln} vulnerabilità note nelle librerie")

    ok = not problems
    sha = os.environ.get("GITHUB_SHA", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/"
               f"{os.environ.get('GITHUB_RUN_ID')}") if os.environ.get("GITHUB_RUN_ID") else ""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    version = ""
    try:
        with open(os.path.join(ROOT, "version_info.txt"), encoding="utf-8") as fh:
            for line in fh:
                if "ProductVersion" in line:
                    version = ".".join(line.split("'")[3].split(".")[:3])  # 1.3.0.0 -> 1.3.0
    except (OSError, IndexError):
        pass

    sev_it = {"LOW": "bassa", "MEDIUM": "media", "HIGH": "alta"}
    p = []
    p.append(f"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8">
<title>PdfPaper - Rapporto delle verifiche automatiche</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1d2433}}
h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #d6dae3;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border:1px solid #d6dae3;padding:5px 7px;text-align:left;vertical-align:top}}
th{{background:#f1f3f7}} .ok{{color:#11703a;font-weight:600}} .ko{{color:#b42318;font-weight:600}} .sk{{color:#8a6100}}
.esito{{padding:12px 14px;border-radius:6px;margin:16px 0;font-size:15px}}
.esito.ok{{background:#e8f6ee}} .esito.ko{{background:#fdecea}} code,pre{{font-family:Consolas,monospace;font-size:12px}}
pre{{background:#f6f7f9;padding:10px;white-space:pre-wrap}} .muted{{color:#5b6475;font-size:13px}}
</style></head><body>
<h1>PdfPaper {esc(version)} – Rapporto delle verifiche automatiche</h1>
<div class="muted">Generato il {esc(now)}{' da GitHub Actions' if run_url else ''}</div>
<div class="esito {'ok' if ok else 'ko'}">{'Tutte le verifiche sono state superate.' if ok else
        'Verifiche NON superate: ' + esc('; '.join(problems)) + '.'}</div>
<h2>Codice verificato</h2><table>""")
    if repo:
        p.append(f"<tr><th>Repository</th><td>https://github.com/{esc(repo)}</td></tr>")
    if sha:
        p.append(f"<tr><th>Commit</th><td><code>{esc(sha)}</code></td></tr>")
    if run_url:
        p.append(f"<tr><th>Esecuzione</th><td>{esc(run_url)}</td></tr>")
    for f in SOURCES:
        fp = os.path.join(ROOT, f)
        if os.path.isfile(fp):
            p.append(f"<tr><th>SHA-256 {esc(f)}</th><td><code>{sha256(fp)}</code></td></tr>")
    p.append("</table>")

    p.append("""<h2>Riepilogo</h2><table><tr><th>Verifica</th><th>Strumento</th><th>Esito</th></tr>""")

    def cell(good, text):
        return f"<td class=\"{'ok' if good else 'ko'}\">{esc(text)}</td>"
    p.append("<tr><td>Test automatici delle funzioni (salvataggio, omissis, pulizia, moduli, "
             "compressione, OCR, assenza di rete)</td><td>pytest</td>" +
             (cell(False, "non eseguiti") if tests is None else
              cell(t_fail == 0 and tests, f"{t_ok} superati, {t_fail} non superati, {t_skip} saltati")) + "</tr>")
    if bandit is None:
        p.append("<tr><td>Analisi statica di sicurezza del codice</td><td>Bandit</td>" + cell(False, "non eseguita") + "</tr>")
    else:
        counts = {s: sum(1 for i in b_issues if i[0] == s) for s in ("HIGH", "MEDIUM", "LOW")}
        p.append("<tr><td>Analisi statica di sicurezza del codice</td><td>Bandit</td>" +
                 cell(counts["HIGH"] + counts["MEDIUM"] == 0,
                      f"alta: {counts['HIGH']}, media: {counts['MEDIUM']}, bassa: {counts['LOW']}"
                      + (f" ({b_loc} righe analizzate)" if b_loc else "")) + "</tr>")
    p.append("<tr><td>Vulnerabilità note delle librerie</td><td>pip-audit</td>" +
             (cell(False, "non eseguito") if audit is None else
              cell(a_vuln == 0, f"{a_vuln} vulnerabilità su {len(audit)} librerie")) + "</tr></table>")

    if tests:
        p.append("<h2>Test automatici</h2><table><tr><th>Test</th><th>Esito</th><th>Dettaglio</th></tr>")
        for name, status, detail, _t in tests:
            cls = {"superato": "ok", "saltato": "sk"}.get(status, "ko")
            p.append(f"<tr><td>{esc(name)}</td><td class=\"{cls}\">{esc(status)}</td>"
                     f"<td>{esc(detail[:300])}</td></tr>")
        p.append("</table>")

    if bandit is not None:
        p.append("<h2>Analisi di sicurezza del codice (Bandit)</h2>")
        if b_issues:
            p.append("<p class=\"muted\">Le segnalazioni di gravità bassa sono indicazioni di stile "
                     "(per esempio un errore ignorato volutamente) e non bloccano la verifica.</p>")
            p.append("<table><tr><th>Gravità</th><th>Affidabilità</th><th>Regola</th><th>Posizione</th>"
                     "<th>Descrizione</th></tr>")
            for sev, conf, tid, tname, fname, line, text in sorted(b_issues, key=lambda i: ("HIGH", "MEDIUM", "LOW").index(i[0])):
                p.append(f"<tr><td>{esc(sev_it.get(sev, sev))}</td><td>{esc(sev_it.get(conf, conf))}</td>"
                         f"<td>{esc(tid)} {esc(tname)}</td><td>{esc(fname)}:{esc(line)}</td><td>{esc(text)}</td></tr>")
            p.append("</table>")
        else:
            p.append("<p class=\"ok\">Nessuna segnalazione.</p>")

    if audit is not None:
        p.append("<h2>Vulnerabilità note delle librerie (pip-audit)</h2><table>"
                 "<tr><th>Libreria</th><th>Versione</th><th>Vulnerabilità</th></tr>")
        for name, ver, vulns in audit:
            v = "; ".join(f"{i} (corretta in {fx or 'n.d.'})" for i, fx in vulns) if vulns else "nessuna"
            p.append(f"<tr><td>{esc(name)}</td><td>{esc(ver)}</td>"
                     f"<td class=\"{'ko' if vulns else 'ok'}\">{esc(v)}</td></tr>")
        p.append("</table>")

    if libs:
        p.append(f"<h2>Versioni delle librerie installate durante le verifiche</h2><pre>{esc(libs)}</pre>")
    p.append("</body></html>")

    report = os.path.join(out_dir, "RAPPORTO_VERIFICHE.html")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p))
    print(f"Rapporto: {report}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Verifiche automatiche PdfPaper\n\n")
            fh.write("**Tutte superate.**\n\n" if ok else f"**Non superate:** {'; '.join(problems)}.\n\n")
            if tests is not None:
                fh.write(f"- Test: {t_ok} superati, {t_fail} non superati, {t_skip} saltati\n")
            if bandit is not None:
                fh.write(f"- Bandit: {len(b_issues)} segnalazioni "
                         f"({sum(1 for i in b_issues if i[0] in ('MEDIUM', 'HIGH'))} di gravità media o alta)\n")
            if audit is not None:
                fh.write(f"- pip-audit: {a_vuln} vulnerabilità note\n")
            fh.write("\nIl rapporto completo è nell'artefatto **PdfPaper-verifiche**.\n")
    for prob in problems:
        print(f"PROBLEMA: {prob}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
