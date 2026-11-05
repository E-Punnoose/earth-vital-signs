"""Write docs/RESULTS.md from data/processed/dashboard.json (run after pipeline.run)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ym(s):
    m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{m[int(s[5:7]) - 1]} {s[:4]}"


def main():
    d = json.loads((ROOT / "data/processed/dashboard.json").read_text())
    by = {p["id"]: p for p in d["parameters"]}
    L = [f"# Results — models run {d['meta']['generated_utc']}", "",
         "Generated automatically from `data/processed/dashboard.json`. Reference month October 2026; "
         "forecast window November 2026 – October 2028.", "",
         "## Ranking: parameters projected to increase", "",
         "Change = forecast mean Nov 2027–Oct 2028 minus the mean of the latest 12 observed months. "
         "P(increase) uses the selected model's out-of-sample error for that 12-month mean.", "",
         "| # | Parameter | Unit | Latest 12 months | Nov 2027–Oct 2028 | Change (95% interval) | P(increase) | Likelihood | 30-yr trend | Selected model |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(d["ranking"], 1):
        p = by[r["id"]]
        k = p["decimals"]
        L.append(f"| {i} | {r['short']} | {p['unit']} | {r['last12_obs_mean']:.{k}f} ({r['last12_obs_period']}) | "
                 f"{r['forecast_mean_nov2027_oct2028']:.{k}f} | {r['projected_change']:+.{k}f} "
                 f"({r['projected_change_ci95'][0]:+.{k}f} to {r['projected_change_ci95'][1]:+.{k}f}) | "
                 f"{100 * r['prob_increase']:.1f}% | {r['likelihood']} | {p['analysis']['classification']} | "
                 f"{p['modelling']['models'][r['selected_model']]['label']} |")
    L += ["", "## Latest observations and projections", "",
          "| Parameter | Latest observation | Baseline 1991–2020 | Rate (last 30 yr) | +6 mo (Apr 2027) | +12 mo (Oct 2027) | +18 mo (Apr 2028) | +24 mo (Oct 2028) |",
          "|---|---|---|---|---|---|---|---|"]
    for r in d["ranking"]:
        p = by[r["id"]]
        k = p["decimals"]
        tr = p["analysis"]["trend_last_30y"]
        cells = [f"{h['mean']:.{k}f} [{h['lo95']:.{k}f}, {h['hi95']:.{k}f}]" for h in p["horizons"].values()]
        L.append(f"| {p['short']} ({p['unit']}) | {p['latest']['value']:.{k}f} ({ym(p['latest']['date'])}) | "
                 f"{p['analysis']['baseline_1991_2020']['mean']:.{k}f} | {tr['per_year']:+.4g}/yr "
                 f"(95% CI {tr['ci95_per_decade'][0] / 10:+.3g} to {tr['ci95_per_decade'][1] / 10:+.3g}) | " + " | ".join(cells) + " |")
    L += ["", "Values in brackets are 95% prediction intervals.", "", "## Model validation", "",
          "Rolling-origin evaluation: 20 origins, 6 months apart, each forecasting to October 2028.", "",
          "| Parameter | Selected | RMSE | MAE | MAPE | MASE | Skill vs best baseline | Best baseline | 80% / 95% coverage | Residual check |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in d["ranking"]:
        p = by[r["id"]]
        md = p["modelling"]
        m = md["metrics"]["by_model"][md["selected_model"]]
        cov = md["interval_coverage_check"]
        mape = f"{m['mape']:.2f}%" if m.get("mape") is not None else "n/a"
        L.append(f"| {p['short']} | {md['models'][md['selected_model']]['label']}"
                 f"{' ' + md['models']['sarima']['spec'] if md['selected_model'] == 'sarima' else ''} | {m['rmse']:.4g} | {m['mae']:.4g} | {mape} | "
                 f"{m['mase']:.3f} | {100 * m['skill_vs_best_baseline']:+.0f}% | {md['models'][md['metrics']['best_baseline']]['label']} | "
                 f"{100 * cov['empirical_80']:.0f}% / {100 * cov['empirical_95']:.0f}% | {md['residuals'].get('interpretation', 'n/a')} |")
    L += ["", "### All models (RMSE)", "", "| Parameter | " + " | ".join(
        by["co2"]["modelling"]["models"][n]["label"] for n in by["co2"]["modelling"]["models"]) + " |",
          "|---|" + "---|" * len(by["co2"]["modelling"]["models"])]
    for r in d["ranking"]:
        p = by[r["id"]]
        mm = p["modelling"]["metrics"]["by_model"]
        L.append(f"| {p['short']} | " + " | ".join(
            ("**" if n == p["modelling"]["selected_model"] else "") + (f"{mm[n]['rmse']:.4g}" if n in mm and not mm[n].get("failed") else "failed")
            + ("**" if n == p["modelling"]["selected_model"] else "") for n in by["co2"]["modelling"]["models"]) + " |")
    L += ["", "## Not available", ""]
    for p in d["parameters"]:
        if p["status"] != "ok":
            L.append(f"- **{p['name']}** — {p['reason']}")
    L += ["", "## Insights", ""] + [f"- **{i['title']}.** {i['text']}" for i in d["insights"]]
    out = ROOT / "docs" / "RESULTS.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(out)


if __name__ == "__main__":
    main()
