import argparse
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "src"))

import simulation as sim
from simulation import (
    INTERSECTIONS,
    GAParams,
    run_single_experiment,
)
from aggregate_results import aggregate


# ============================================================
# KONFIGURATION - Hier anpassen!
# ============================================================
SELECTED_INTERSECTION = "bremen"  # "dieburger", "frankfurter", "pallaswiesen", "bremen"
NUM_RUNS = 1                          # Anzahl sequenzieller Durchläufe
USE_GUI = False                         # True für SUMO GUI, False für headless
SEED_BASE = 42                          # Basis-Seed; Run i nutzt Seed (SEED_BASE + i)
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Batch-Ausführung des GA: N sequenzielle Durchläufe mit automatischer Aggregation."
        )
    )
    parser.add_argument(
        "--intersection", default=None,
        choices=list(INTERSECTIONS.keys()),
        help="Kreuzungsname (z.B. 'frankfurter', 'dieburger', 'pallaswiesen', 'bremen').",
    )
    parser.add_argument(
        "--runs", type=int, default=None,
        help="Anzahl der sequenziellen Durchläufe.",
    )
    parser.add_argument(
        "--gui", action="store_true", default=None,
    )
    parser.add_argument(
        "--seed-base", type=int, default=None,
    )
    args = parser.parse_args()

    intersection_name = args.intersection if args.intersection is not None else SELECTED_INTERSECTION
    num_runs = args.runs if args.runs is not None else NUM_RUNS
    use_gui = args.gui if args.gui else USE_GUI
    seed_base = args.seed_base if args.seed_base is not None else SEED_BASE

    intersection = INTERSECTIONS[intersection_name]
    params = GAParams()

    base_log_dir = sim._LOG_DIR
    intersection_log_dir = os.path.join(base_log_dir, intersection_name)
    os.makedirs(intersection_log_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"=== Batch-Start: {intersection_name} | {num_runs} Run(s) ===")
    print(f"=== Seed-Basis: {seed_base} ===")
    print(f"{'='*60}")

    total_start = time.time()

    for i in range(num_runs):
        seed = seed_base + i
        run_dir = os.path.join(intersection_log_dir, f"run_{i:02d}")
        os.makedirs(run_dir, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"=== Run {i + 1}/{num_runs} | Seed: {seed} | Verzeichnis: run_{i:02d} ===")
        print(f"{'='*60}")

        run_start = time.time()

        sim._LOG_DIR = run_dir

        run_single_experiment(
            intersection, params,
            use_gui=use_gui,
            seed=seed,
        )

        run_elapsed = time.time() - run_start
        run_min, run_sec = divmod(int(run_elapsed), 60)

        total_elapsed = time.time() - total_start
        remaining = num_runs - (i + 1)
        eta = (total_elapsed / (i + 1)) * remaining if remaining > 0 else 0
        eta_min, eta_sec = divmod(int(eta), 60)

        print(
            f"\nRun {i + 1} abgeschlossen in {run_min}m {run_sec}s"
            + (f" | ETA: {eta_min}m {eta_sec}s ({remaining} Run(s) verbleibend)" if remaining > 0 else "")
        )

    sim._LOG_DIR = os.path.join(sim._PROJECT_ROOT, "logging")

    print(f"\n{'='*60}")
    print(f"=== Starte Aggregation ===")
    print(f"{'='*60}")
    aggregate(intersection_name, intersection_log_dir)

    for lvl_suffix in ["_75", "_50"]:
        lvl_label = lvl_suffix.lstrip("_") + "%"
        lvl_file = os.path.join(
            intersection_log_dir, "run_00",
            f"reference_{intersection_name}{lvl_suffix}.csv",
        )
        if os.path.exists(lvl_file):
            print(f"\n{'='*60}")
            print(f"=== Aggregation Traffic-Level {lvl_label} ===")
            print(f"{'='*60}")
            aggregate(intersection_name, intersection_log_dir, suffix=lvl_suffix)
        else:
            print(f"[Traffic-Level {lvl_label}] Keine Ergebnisse zum Aggregieren gefunden, überspringe.")

    total_elapsed = time.time() - total_start
    total_min, total_sec = divmod(int(total_elapsed), 60)
    print(f"\nBatch abgeschlossen: {num_runs} Run(s) in {total_min}m {total_sec}s")
    print(f"Ergebnisse: {intersection_log_dir}")


if __name__ == "__main__":
    main()
