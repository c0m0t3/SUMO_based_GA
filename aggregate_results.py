import argparse
import csv
import glob
import json
import math
import os
import sys
from collections import defaultdict


# ============================================================
# KONFIGURATION - Hier anpassen!
# ============================================================
SELECTED_INTERSECTION = "frankfurter"  # "dieburger", "frankfurter", "pallaswiesen", "bremen"
RUNS_DIR = None  
# ============================================================


def _median(values: list) -> float:
    """Median der Werte."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def _percentile(values: list, p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]

    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return s[-1]
    frac = idx - lo
    return s[lo] + frac * (s[hi] - s[lo])

def _ecdf_on_grid(wait_values: list, x_grid: list) -> list:
    s = sorted(wait_values)
    n = len(s)
    if n == 0:
        return [0.0] * len(x_grid)
    result = []
    j = 0
    for x in x_grid:
        while j < n and s[j] <= x:
            j += 1
        result.append(j / n)
    return result


def aggregate_cdf(intersection_name: str, runs_base_dir: str, suffix: str = "") -> str:
    run_dirs = sorted(
        d for d in glob.glob(os.path.join(runs_base_dir, "run_*"))
        if os.path.isdir(d)
    )
    if not run_dirs:
        return ""

    method_raw = defaultdict(list)

    for run_dir in run_dirs:
        ref_file = os.path.join(run_dir, f"reference_{intersection_name}{suffix}.csv")
        if not os.path.exists(ref_file):
            continue

        ga_raw_override = None
        if suffix == "":
            bc_file = os.path.join(run_dir, f"best_candidates_{intersection_name}.csv")
            if os.path.exists(bc_file):
                with open(bc_file, "r", newline="", encoding="utf-8") as bf:
                    last_row = None
                    for last_row in csv.DictReader(bf, delimiter=";"):
                        pass
                    if last_row and last_row.get("WaitValuesRaw_JSON"):
                        raw = last_row["WaitValuesRaw_JSON"]
                        if raw and raw.strip() not in ("", "[]"):
                            ga_raw_override = json.loads(raw)

        with open(ref_file, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                method = row["Method"]
                if method == "GA" and ga_raw_override is not None:
                    method_raw[method].append(ga_raw_override)
                else:
                    raw = row.get("WaitValuesRaw_JSON", "[]")
                    vals = json.loads(raw) if raw and raw.strip() not in ("", "[]") else []
                    if vals:
                        method_raw[method].append(vals)

    if not method_raw:
        print(f"  Keine WaitValuesRaw_JSON-Daten für CDF-Aggregation gefunden.")
        return ""

    global_max = 0.0
    for runs in method_raw.values():
        for vals in runs:
            if vals:
                global_max = max(global_max, max(vals))
    x_grid = list(range(0, int(global_max) + 2))

    method_order = ["Baseline", "Actuated", "GA"]
    methods_present = [m for m in method_order if m in method_raw]

    columns = {"wait_seconds": x_grid}
    for method in methods_present:
        runs_ecdfs = []
        for vals in method_raw[method]:
            runs_ecdfs.append(_ecdf_on_grid(vals, x_grid))

        n_runs = len(runs_ecdfs)
        median_cdf = []
        p10_cdf = []
        p90_cdf = []
        for i in range(len(x_grid)):
            point_values = [runs_ecdfs[r][i] for r in range(n_runs)]
            median_cdf.append(_median(point_values))
            p10_cdf.append(_percentile(point_values, 10))
            p90_cdf.append(_percentile(point_values, 90))

        m_lower = method.lower()
        columns[f"median_{m_lower}"] = median_cdf
        columns[f"p10_{m_lower}"] = p10_cdf
        columns[f"p90_{m_lower}"] = p90_cdf

        n_tracked_values = [len(vals) for vals in method_raw[method]]
        columns[f"n_tracked_{m_lower}"] = [_median(n_tracked_values)] * len(x_grid)

    out_file = os.path.join(runs_base_dir, f"cdf_{intersection_name}{suffix}.csv")
    col_names = list(columns.keys())
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(col_names)
        for i in range(len(x_grid)):
            writer.writerow([columns[c][i] for c in col_names])

    print(f"CDF-Daten gespeichert: {out_file}")
    return out_file

def aggregate(intersection_name: str, runs_base_dir: str, suffix: str = "") -> str:
    run_dirs = sorted(
        d for d in glob.glob(os.path.join(runs_base_dir, "run_*"))
        if os.path.isdir(d)
    )

    if not run_dirs:
        print(f"Keine run_XX Verzeichnisse in '{runs_base_dir}' gefunden.")
        return ""

    print(f"Aggregiere {len(run_dirs)} Run(s) aus '{runs_base_dir}' ...")

    method_data = defaultdict(lambda: {
        "fitness": [],
        "waiting_time": [],
        "vehicle_count": [],
        "wait_per_vehicle": [],
        "emergency_brakes": [],
        "crash_count": [],
        "wait_distribution": defaultdict(list),
    })

    found_runs = 0
    for run_dir in run_dirs:
        ref_file = os.path.join(run_dir, f"reference_{intersection_name}{suffix}.csv")
        if not os.path.exists(ref_file):
            print(f"  Warnung: '{ref_file}' nicht gefunden, überspringe.")
            continue

        found_runs += 1

        best_candidates_file = os.path.join(run_dir, f"best_candidates_{intersection_name}.csv")
        ga_wait_dist_override = {}
        if suffix == "" and os.path.exists(best_candidates_file):
            with open(best_candidates_file, "r", newline="", encoding="utf-8") as bf:
                last_row = None
                reader_bc = csv.DictReader(bf, delimiter=";")
                for last_row in reader_bc:
                    pass
                if last_row is not None:
                    dist_raw = last_row.get("WaitDistribution_JSON", "{}")
                    ga_wait_dist_override = json.loads(dist_raw) if dist_raw else {}

        with open(ref_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                method = row["Method"]
                d = method_data[method]
                d["fitness"].append(float(row["Fitness"]))
                d["waiting_time"].append(float(row["WaitingTime"]))
                d["vehicle_count"].append(float(row["VehicleCount"]))
                d["wait_per_vehicle"].append(float(row["WaitPerVehicle"]))
                d["emergency_brakes"].append(float(row["EmergencyBrakes"]))
 
                crashes_raw = row.get("Crashes", "[]")
                crashes = json.loads(crashes_raw) if crashes_raw else []
                d["crash_count"].append(float(len(crashes)))

                if method == "GA" and ga_wait_dist_override:
                    wait_dist = ga_wait_dist_override
                else:
                    dist_raw = row.get("WaitDistribution_JSON", "{}")
                    wait_dist = json.loads(dist_raw) if dist_raw else {}
                for bin_label, count in wait_dist.items():
                    d["wait_distribution"][bin_label].append(float(count))

    if found_runs == 0:
        print("Keine gültigen reference_*.csv Dateien gefunden.")
        return ""
    
    bin_order = ["0-10s", "10-30s", "30-60s", "60-120s", "120-180s", ">180s"]

    out_file = os.path.join(runs_base_dir, f"aggregated_reference_{intersection_name}{suffix}.csv")

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")

        # Header
        header = [
            "Method", "Runs",
            "Median_Fitness", "P10_Fitness", "P90_Fitness",
            "Median_WaitingTime", "P10_WaitingTime", "P90_WaitingTime",
            "Median_VehicleCount", "P10_VehicleCount", "P90_VehicleCount",
            "Median_WaitPerVehicle", "P10_WaitPerVehicle", "P90_WaitPerVehicle",
            "Median_EmergencyBrakes", "P10_EmergencyBrakes", "P90_EmergencyBrakes",
            "Median_CrashCount", "P10_CrashCount", "P90_CrashCount",
            "Median_WaitDistribution_JSON", "P10_WaitDistribution_JSON", "P90_WaitDistribution_JSON",
        ]
        writer.writerow(header)

        for method in sorted(method_data.keys()):
            d = method_data[method]
            n = len(d["fitness"])

            median_dist = {}
            p10_dist = {}
            p90_dist = {}
            dist_bins = [b for b in bin_order if b in d["wait_distribution"]]
            for b in d["wait_distribution"]:
                if b not in dist_bins:
                    dist_bins.append(b)

            for bin_label in dist_bins:
                counts = d["wait_distribution"][bin_label]
                median_dist[bin_label] = round(_median(counts), 2)
                p10_dist[bin_label] = round(_percentile(counts, 10), 2)
                p90_dist[bin_label] = round(_percentile(counts, 90), 2)

            writer.writerow([
                method, n,
                f"{_median(d['fitness']):.4f}",
                f"{_percentile(d['fitness'], 10):.4f}",
                f"{_percentile(d['fitness'], 90):.4f}",
                f"{_median(d['waiting_time']):.4f}",
                f"{_percentile(d['waiting_time'], 10):.4f}",
                f"{_percentile(d['waiting_time'], 90):.4f}",
                f"{_median(d['vehicle_count']):.1f}",
                f"{_percentile(d['vehicle_count'], 10):.1f}",
                f"{_percentile(d['vehicle_count'], 90):.1f}",
                f"{_median(d['wait_per_vehicle']):.4f}",
                f"{_percentile(d['wait_per_vehicle'], 10):.4f}",
                f"{_percentile(d['wait_per_vehicle'], 90):.4f}",
                f"{_median(d['emergency_brakes']):.2f}",
                f"{_percentile(d['emergency_brakes'], 10):.2f}",
                f"{_percentile(d['emergency_brakes'], 90):.2f}",
                f"{_median(d['crash_count']):.2f}",
                f"{_percentile(d['crash_count'], 10):.2f}",
                f"{_percentile(d['crash_count'], 90):.2f}",
                json.dumps(median_dist, ensure_ascii=False),
                json.dumps(p10_dist, ensure_ascii=False),
                json.dumps(p90_dist, ensure_ascii=False),
            ])

    print(f"Aggregationsergebnis gespeichert: {out_file}")

    aggregate_cdf(intersection_name, runs_base_dir, suffix)

    level_label = f" | Traffic-Level {suffix.lstrip('_')}%" if suffix else ""
    print(f"\n{'='*70}")
    print(f"=== Aggregation: {intersection_name}{level_label} ({found_runs} Runs) ===")
    print(f"{'='*70}")

    for method in sorted(method_data.keys()):
        d = method_data[method]
        n = len(d["fitness"])
        print(f"\n{method} (n={n}):")
        print(f"  Fitness:           Median {_median(d['fitness']):>10.2f}  [P10: {_percentile(d['fitness'], 10):.2f}, P90: {_percentile(d['fitness'], 90):.2f}]")
        print(f"  Wartezeit:         Median {_median(d['waiting_time']):>10.2f}  [P10: {_percentile(d['waiting_time'], 10):.2f}, P90: {_percentile(d['waiting_time'], 90):.2f}]")
        print(f"  VehicleCount:      Median {_median(d['vehicle_count']):>10.1f}  [P10: {_percentile(d['vehicle_count'], 10):.1f}, P90: {_percentile(d['vehicle_count'], 90):.1f}]")
        print(f"  Warte/Fzg (s):     Median {_median(d['wait_per_vehicle']):>10.2f}  [P10: {_percentile(d['wait_per_vehicle'], 10):.2f}, P90: {_percentile(d['wait_per_vehicle'], 90):.2f}]")
        print(f"  Notbremsungen:     Median {_median(d['emergency_brakes']):>10.2f}  [P10: {_percentile(d['emergency_brakes'], 10):.2f}, P90: {_percentile(d['emergency_brakes'], 90):.2f}]")
        print(f"  Unfälle:           Median {_median(d['crash_count']):>10.2f}  [P10: {_percentile(d['crash_count'], 10):.2f}, P90: {_percentile(d['crash_count'], 90):.2f}]")

        if d["wait_distribution"]:
            print(f"  Wartezeitverteilung (Median Fahrzeuge [P10, P90]):")
            for bin_label in [b for b in bin_order if b in d["wait_distribution"]]:
                counts = d["wait_distribution"][bin_label]
                print(f"    {bin_label:>8s}: Median {_median(counts):7.1f}  [P10: {_percentile(counts, 10):.1f}, P90: {_percentile(counts, 90):.1f}]")

    return out_file


def main():
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _default_log_dir = os.path.join(_script_dir, "logging")

    parser = argparse.ArgumentParser(
        description="Aggregiere Median/P10/P90 aus mehreren GA-Batch-Runs."
    )
    parser.add_argument(
        "--intersection", default=None,
        help="Kreuzungsname (z.B. 'frankfurter', 'dieburger', ...). Standard: SELECTED_INTERSECTION.",
    )
    parser.add_argument(
        "--dir", default=None,
        help=(
            "Pfad zum Verzeichnis mit den run_XX Unterordnern. "
            "Standard: logging/{intersection}/"
        ),
    )
    args = parser.parse_args()

    intersection_name = args.intersection if args.intersection is not None else SELECTED_INTERSECTION
    runs_base_dir = args.dir or RUNS_DIR or os.path.join(_default_log_dir, intersection_name)

    if not os.path.isdir(runs_base_dir):
        print(f"Fehler: Verzeichnis '{runs_base_dir}' nicht gefunden.")
        sys.exit(1)

    aggregate(intersection_name, runs_base_dir)


if __name__ == "__main__":
    main()