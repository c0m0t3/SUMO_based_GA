import os
import sys
import platform
import subprocess
import time
import random
import socket
import csv
import json
import copy
from dataclasses import dataclass
from typing import List, Dict, Optional
from multiprocessing import Process, Queue, Event, cpu_count

# ---- OS Erkennung ----
IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

# ---- SUMO PFAD ----
if IS_MAC:
    os.environ["SUMO_HOME"] = "/Applications/SUMO sumo-gui.app/Contents/Resources"
    SUMO_GUI = "/Applications/SUMO sumo-gui.app/Contents/MacOS/SUMO sumo-gui"
    SUMO_CLI = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.25.0/EclipseSUMO/bin/sumo"
elif IS_WIN:
    os.environ["SUMO_HOME"] = r"C:\Program Files (x86)\Eclipse\Sumo"
    SUMO_GUI = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe"
    SUMO_CLI = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
else:
    raise RuntimeError("Unsupported OS")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SIMULATION_SEED: int = 42


def set_simulation_seed(seed: int):
    """Setzt den SUMO- und Python-Seed für alle folgenden Simulationen."""
    global _SIMULATION_SEED
    _SIMULATION_SEED = seed

@dataclass(frozen=True)
class IntersectionConfig:
    """Kreuzungsspezifische Konfiguration."""
    name: str
    sumo_config_path: str
    tls_id: str
    phases: tuple  # z.B. ("rrrrGgrr", "Ggrrrrrr", ...)
    all_red_time: int = 2  # Dauer der Alle-Rot-Phase in Sekunden
    actuated_config_path: str = "" 
    
    @property
    def num_phases(self) -> int:
        return len(self.phases)
    
    @property
    def signal_length(self) -> int:
        return len(self.phases[0]) if self.phases else 0
    
    @property
    def phase_duration(self) -> int:
        """Minimale Phasendauer basierend auf Übergangszeiten: 3s + all_red_time + 1s + Puffer."""
        return 4 + self.all_red_time + 5 


# ---- GA Parameter ----
@dataclass
class GAParams:
    """Parameter für den genetischen Algorithmus."""
    generations: int = 200
    population_size: int = 96
    mutation_rate: float = 0.10
    crossover_rate: float = 0.95
    elitism_count: int = 1
    tournament_size: int = 10
    tournament_probability: float = 0.9
    simulation_duration: int = 900  
    step_length: float = 1.0  

    # Fitness Parameter
    penalty_wait_base: float = 0.3
    waiting_time_exponent: float = 1.005
    penalty_emergency: float = 1000
    emergency_braking_threshold: float = -9
    
    def candidate_length(self, intersection: IntersectionConfig) -> int:
        """Berechne Kandidatenlänge basierend auf Simulationsdauer und Phasendauer."""
        return self.simulation_duration // intersection.phase_duration

INTERSECTIONS: Dict[str, IntersectionConfig] = {
    "dieburger": IntersectionConfig(
        name="dieburger",
        sumo_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Dieburgerstrasse/dieburger.sumocfg"),
        actuated_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Dieburgerstrasse/dieburger.actuated.sumocfg"),
        tls_id="J50",
        phases=(
            "rrrrGgrr",  # 0: West-GRL
            "Ggrrrrrr",  # 1: Ost-GRL
            "GgrrGgrr",  # 2: West-GRL & Ost-GRL
            "rrrrrrGg",  # 3: Nord-GRL
            "rrGgrrrr",  # 4: Sued-GRL
            "rrGgrrGg",  # 5: Nord-GRL & Sued-GRL
        ),
        all_red_time=2,
    ),
    "frankfurter": IntersectionConfig(
        name="frankfurter",
        sumo_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Frankfurterstrasse/frankfurterstrasse.sumocfg"),
        actuated_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Frankfurterstrasse/frankfurterstrasse.actuated.sumocfg"),
        tls_id="clusterJ76_J77_J78_J79_#5more",
        phases=(
            "GGGrGrrrrGGGrGrrrr", # 0: Nord-GR & Sued-GR
            "rrrGrrrrrrrrGrrrrr", # 1: Nord-L & Sued-L
            "rrrrrGGGGrrrrrrrrr", # 2: Ost-GL
            "rrrrrrrrrrrrrrGGGG", # 3: West-GL
            "rrrrrGGrrrrrrrGGrr", # 4: West-G & Ost-G
            "rrrrrrrGGrrrrrrrGG", # 5: West-L & Ost-L
            "GGGGrrrrrrrrrrrrrr", # 6: Nord-GRL
            "rrrrrrrrrGGGGrrrrr", # 7: Sued-GRL
        ),
        all_red_time=3,
    ),
    "pallaswiesen": IntersectionConfig(
        name="pallaswiesen",
        sumo_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Pallaswiesenstrasse/pallaswiesenstrasse.sumocfg"),
        actuated_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Pallaswiesenstrasse/pallaswiesenstrasse.actuated.sumocfg"),
        tls_id="clusterJ3_J6_J7",
        phases=(
            "GGGrrrrrGG", # 0: West-G & Ost-G
            "rrrGGGGGrr", # 1: Sued-RL
        ),
        all_red_time=3,
    ),
    "bremen": IntersectionConfig(
        name="bremen",
        sumo_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Bremen/CN+ Dataset.sumocfg"),
        actuated_config_path=os.path.join(_PROJECT_ROOT, "data/Darmstadt/SUMO/Bremen/CN+ Dataset.actuated.sumocfg"),
        tls_id="25350584",
        phases=(
            "gggrrrGGGGGGGggrrGGG", # 0: West-GRL & Ost-GRL
            "gggrrrrrrrGGGggrrGGG", # 1: Ost-GRL
            "gggrrrGGGGrrrggrrggg", # 2: West-GRL
            "GggGGgrrrrrrrGGGGggg", # 3: Nord-GRL & Sued-GRL
            "GggrrrrrrrrrrGGGGggg", # 4: Nord-GRL
            "GggGGgrrrrrrrGGrrggg", # 5: Sued-GRL
        ),
        all_red_time=3,
    ),
}

_LOG_DIR = os.path.join(_PROJECT_ROOT, "logging")




def _get_reference_file(intersection_name: str, suffix: str = "") -> str:
    """Gibt den Pfad zur Referenz-Log-Datei zurück."""
    return os.path.join(_LOG_DIR, f"reference_{intersection_name}{suffix}.csv")


def init_reference_log(intersection_name: str, suffix: str = ""):
    """Initialisiere das Referenz-Log (GA + Baseline + Actuated)."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    with open(_get_reference_file(intersection_name, suffix), "w", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            "Method",
            "Fitness",
            "WaitingTime",
            "VehicleCount",
            "WaitPerVehicle",
            "WaitDistribution_JSON",
            "Crashes",
            "EmergencyBrakes",
            "WaitValuesRaw_JSON",
        ])


def log_reference(intersection_name: str, method: str, result: dict, suffix: str = ""):
    """Logge einen Referenz-Simulationslauf (GA, Baseline oder Actuated)."""
    with open(_get_reference_file(intersection_name, suffix), "a", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            method,
            f"{result.get('fitness', 0.0):.4f}",
            f"{result.get('waiting_time', 0.0):.4f}",
            result.get("vehicle_count", 0),
            f"{result.get('avg_vehicle_wait', 0.0):.4f}",
            json.dumps(result.get("wait_distribution", {})),
            json.dumps(result.get("crashes", [])),
            result.get("emergency_brakes", 0),
            json.dumps(result.get("wait_values_raw", [])),
        ])

def find_free_port() -> int:
    """Finde einen freien Port für TraCI."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def get_reduced_traffic_configs(intersection: IntersectionConfig) -> dict:
    """Gibt SUMO-Config-Pfade für 75%- und 50%-Verkehrslevel zurück.
    """
    result = {}
    base_cfg = intersection.sumo_config_path
    act_cfg = intersection.actuated_config_path or None

    for factor, tag in [(0.75, "_0.75"), (0.5, "_0.5")]:
        baseline_path = base_cfg.replace(".sumocfg", f"{tag}.sumocfg") if base_cfg else None
        actuated_path = act_cfg.replace(".sumocfg", f"{tag}.sumocfg") if act_cfg else None

        result[factor] = {
            "baseline": baseline_path if baseline_path and os.path.exists(baseline_path) else None,
            "actuated": actuated_path if actuated_path and os.path.exists(actuated_path) else None,
        }

    return result

def generate_candidate(intersection: IntersectionConfig, params: GAParams) -> List[int]:
    """Erzeuge einen zufälligen Kandidaten (Liste von Phasen-Indizes)."""
    length = params.candidate_length(intersection)
    return [random.randint(0, intersection.num_phases - 1) for _ in range(length)]


def create_initial_population(intersection: IntersectionConfig, params: GAParams) -> List[List[int]]:
    """Erzeuge die initiale Population."""
    return [generate_candidate(intersection, params) for _ in range(params.population_size)]

def compute_transition_signal(prev_char: str, curr_char: str, step_in_phase: int, 
                               all_red_time: int) -> str:
    """
    Berechne das Signal für einen bestimmten Schritt innerhalb einer Phase.
    
    Übergangslogik (bei Phasenwechsel):
    - G/g -> r: 3s Gelb (y) -> Rest Rot
    - r -> G/g: 3s Rot -> all_red_time s Rot -> 1s Rot-Gelb (u) -> Rest Grün
    - Gleich: Durchgehend der gleiche Wert
    """
    if prev_char == curr_char:
        return curr_char
    
    # Wechsel von Grün (G/g) zu Rot
    if prev_char in ('G', 'g') and curr_char == 'r':
        return 'y' if step_in_phase < 3 else 'r'
    
    # Wechsel von Rot zu Grün (G/g)
    if prev_char == 'r' and curr_char in ('G', 'g'):
        if step_in_phase < 3:
            return 'r'
        elif step_in_phase < 3 + all_red_time:
            return 'r'
        elif step_in_phase < 3 + all_red_time + 1:
            return 'u'
        else:
            return curr_char
    
    return curr_char


def build_signal_state(intersection: IntersectionConfig, params: GAParams,
                       candidate: List[int], phase_idx: int, step_in_phase: int) -> str:
    """Baue den Signal-State-String für einen bestimmten Zeitpunkt."""
    curr_phase = intersection.phases[candidate[phase_idx]]
    prev_phase = curr_phase if phase_idx == 0 else intersection.phases[candidate[phase_idx - 1]]
    
    state = []
    for i in range(intersection.signal_length):
        signal = compute_transition_signal(
            prev_phase[i], curr_phase[i], step_in_phase, intersection.all_red_time
        )
        state.append(signal)
    
    return ''.join(state)


def tournament_selection(population: List[List[int]], fitnesses: List[float],
                         tournament_size: int, tournament_prob: float) -> List[int]:
    """Probabilistische Tournament-Selektion."""
    n = len(population)
    if n == 0:
        raise ValueError("Leere Population")
    if n == 1:
        return population[0]
    
    k = max(2, min(tournament_size, n))
    
    # Wähle k zufällige Kandidaten
    indices = [random.randrange(n) for _ in range(k)]
    
    # Sortiere nach Fitness 
    indices.sort(key=lambda i: fitnesses[i], reverse=True)
    
    # Auswahl
    for idx in indices:
        if random.random() < tournament_prob:
            return population[idx]
    
    # Fallback, falls keiner gefunden
    return population[indices[0]]

def mutate(candidate: List[int], intersection: IntersectionConfig, params: GAParams) -> List[int]:
    """Mutation: Mit mutation_rate wird jeder Phaseneintrag zufällig geändert."""
    new_candidate = []
    for phase_idx in candidate:
        if random.random() < params.mutation_rate:
            new_candidate.append(random.randint(0, intersection.num_phases - 1))
        else:
            new_candidate.append(phase_idx)
    return new_candidate

def crossover(parent1: List[int], parent2: List[int], params: GAParams) -> List[int]:
    """Wählt zwei zufällige Schnittpunkte und tauscht den mittleren Abschnitt.
    Bewahrt gute Phasenblöcke am Anfang/Ende und erlaubt Austausch in der Mitte.
    """
    if random.random() > params.crossover_rate:
        return copy.deepcopy(random.choice([parent1, parent2]))
    
    n = min(len(parent1), len(parent2))
    if n < 3:
        return copy.deepcopy(random.choice([parent1, parent2]))
    
    cut1, cut2 = sorted(random.sample(range(1, n), 2))
    return parent1[:cut1] + parent2[cut1:cut2] + parent1[cut2:]


# ---- Worker Pool für parallele Simulation ----
_worker_procs: List[Process] = []
_task_queue: Optional[Queue] = None
_result_queue: Optional[Queue] = None
_quit_event: Optional[Event] = None


def _worker_main(task_q: Queue, result_q: Queue, quit_e: Event, 
                 worker_id: int, intersection_dict: dict, params_dict: dict, use_gui: bool = False):
    import traci
    import traci.constants as tc
    
    intersection = IntersectionConfig(**intersection_dict)
    seed = params_dict.get("seed", 42)
    ga_params_dict = {k: v for k, v in params_dict.items() if k != "seed"}
    params = GAParams(**ga_params_dict)
    random.seed(seed + worker_id)

    sumo_bin = SUMO_GUI if use_gui else SUMO_CLI
    port = find_free_port()
    sumo_cmd = [
        sumo_bin,
        "-c", intersection.sumo_config_path,
        "--remote-port", str(port),
        "--start",
        "--step-length", str(params.step_length),
        "--seed", str(seed),
        "--no-step-log",
        "--no-duration-log",
        "--xml-validation", "never",
    ]
    
    sumo_proc = subprocess.Popen(sumo_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    connected = False
    for _ in range(200):
        try:
            time.sleep(0.05)
            traci.init(port)
            connected = True
            break
        except Exception:
            time.sleep(0.01)
    
    if not connected:
        try:
            sumo_proc.kill()
        except Exception:
            pass
        return
    
    try:
        while not quit_e.is_set():
            try:
                task = task_q.get(timeout=0.5)
            except Exception:
                continue
            
            if task is None:
                break
            
            candidate_index, candidate = task
            
            try:
                traci.load(["-c", intersection.sumo_config_path, 
                           "--step-length", str(params.step_length)])
            except Exception:
                try:
                    traci.close()
                except Exception:
                    pass
                try:
                    traci.init(port)
                except Exception:
                    result_q.put(None)
                    continue
            
            fitness = 0.0
            emergency_brakes = 0
            total_vehicle_count = 0
            vehicle_accum_wait = {}
            
            total_steps = int(params.simulation_duration / params.step_length)
            steps_per_phase = int(intersection.phase_duration / params.step_length)
            candidate_len = len(candidate)
            penalty_base = params.penalty_wait_base
            waiting_time_exponent = params.waiting_time_exponent
            brake_threshold = params.emergency_braking_threshold
            tls_id = intersection.tls_id
            _getArrivedNumber = traci.simulation.getArrivedNumber
            _getDeparted = traci.simulation.getDepartedIDList
            _getAllSubResults = traci.vehicle.getAllSubscriptionResults
            _subscribe = traci.vehicle.subscribe
            _SUBSCRIBE_VARS = [tc.VAR_ACCUMULATED_WAITING_TIME, tc.VAR_ACCEL]
            
            # Übergangszeit: maximale Dauer in der sich der State ändern kann
            transition_steps = int((3 + intersection.all_red_time + 1) / params.step_length)
            last_state = None
            
            for step in range(total_steps):
                traci.simulationStep()
                
                phase_idx = step // steps_per_phase
                if phase_idx >= candidate_len:
                    phase_idx = candidate_len - 1
                step_in_phase = step % steps_per_phase
                
                # Signal nur setzen wenn sich etwas ändern könnte
                if step_in_phase <= transition_steps or step_in_phase == 0 or last_state is None:
                    state = build_signal_state(intersection, params, candidate, phase_idx, step_in_phase)
                    if state != last_state:
                        try:
                            traci.trafficlight.setRedYellowGreenState(tls_id, state)
                        except Exception:
                            pass
                        last_state = state
                
                # Neu eingefahrene Fahrzeuge einmalig abonnieren
                for v in _getDeparted():
                    _subscribe(v, _SUBSCRIBE_VARS)
                
                # Alle Fahrzeugdaten als Batch lesen (1 Call statt N)
                for v, data in _getAllSubResults().items():
                    vehicle_accum_wait[v] = data[tc.VAR_ACCUMULATED_WAITING_TIME]
                    if data[tc.VAR_ACCEL] <= brake_threshold:
                        emergency_brakes += 1
                
                # Fahrzeugzählung: abgeschlossene Fahrten
                total_vehicle_count += _getArrivedNumber()
            
            wait_values = list(vehicle_accum_wait.values())
            total_wait = sum(wait_values)
            for wt in wait_values:
                fitness -= penalty_base * (wt ** waiting_time_exponent)
            fitness -= params.penalty_emergency * emergency_brakes
            crashes = traci.simulation.getCollidingVehiclesIDList()
            
            bins = [0, 10, 30, 60, 120, 180, float('inf')]
            bin_labels = ["0-10s", "10-30s", "30-60s", "60-120s", "120-180s", ">180s"]
            wait_distribution = {label: 0 for label in bin_labels}
            for wt in wait_values:
                for i in range(len(bins) - 1):
                    if bins[i] <= wt < bins[i + 1]:
                        wait_distribution[bin_labels[i]] += 1
                        break

            result_q.put({
                "candidate": candidate_index,
                "fitness": fitness,
                "waiting_time": total_wait,
                "emergency_brakes": emergency_brakes,
                "crashes": list(crashes) if crashes else [],
                "vehicle_count": total_vehicle_count,
                "avg_vehicle_wait": total_wait / total_vehicle_count if total_vehicle_count > 0 else 0.0,
                "max_vehicle_wait": max(wait_values) if wait_values else 0.0,
                "wait_distribution": wait_distribution,
                "wait_values_raw": sorted(wait_values),
                "total_vehicles_tracked": len(wait_values),
            })
    
    finally:
        try:
            traci.close()
        except Exception:
            pass
        try:
            sumo_proc.kill()
        except Exception:
            pass


def start_worker_pool(intersection: IntersectionConfig, params: GAParams,
                      num_workers: int = None, use_gui: bool = False):
    """Starte den Worker-Pool für parallele Simulationen."""
    global _worker_procs, _task_queue, _result_queue, _quit_event
    
    if _worker_procs:
        return
    
    if num_workers is None:
        num_workers = min(16, cpu_count() or 16, params.population_size)
    
    _task_queue = Queue()
    _result_queue = Queue()
    _quit_event = Event()
    
    intersection_dict = {
        "name": intersection.name,
        "sumo_config_path": intersection.sumo_config_path,
        "tls_id": intersection.tls_id,
        "phases": intersection.phases,
        "all_red_time": intersection.all_red_time,
    }
    params_dict = {
        "generations": params.generations,
        "population_size": params.population_size,
        "mutation_rate": params.mutation_rate,
        "crossover_rate": params.crossover_rate,
        "elitism_count": params.elitism_count,
        "tournament_size": params.tournament_size,
        "tournament_probability": params.tournament_probability,
        "simulation_duration": params.simulation_duration,
        "step_length": params.step_length,
        "penalty_wait_base": params.penalty_wait_base,
        "waiting_time_exponent": params.waiting_time_exponent,
        "penalty_emergency": params.penalty_emergency,
        "emergency_braking_threshold": params.emergency_braking_threshold,
        "seed": _SIMULATION_SEED,
    }
    
    for i in range(num_workers):
        p = Process(
            target=_worker_main,
            args=(_task_queue, _result_queue, _quit_event, i, intersection_dict, params_dict, use_gui),
            daemon=True
        )
        p.start()
        _worker_procs.append(p)


def stop_worker_pool():
    global _worker_procs, _task_queue, _result_queue, _quit_event
    
    if not _worker_procs:
        return
    
    for _ in _worker_procs:
        _task_queue.put(None)
    _quit_event.set()
    
    for p in _worker_procs:
        p.join(timeout=5)
        if p.is_alive():
            p.terminate()
    
    _worker_procs = []
    _task_queue = None
    _result_queue = None
    _quit_event = None


def evaluate_population(population: List[List[int]], intersection: IntersectionConfig,
                        params: GAParams, use_gui: bool = False) -> List[dict]:
    global _task_queue, _result_queue
    
    if not _worker_procs:
        start_worker_pool(intersection, params, use_gui=use_gui)
    
    for i, candidate in enumerate(population):
        _task_queue.put((i, candidate))
    
    results = []
    responses_received = 0
    while responses_received < len(population):
        res = _result_queue.get()
        if res is not None:
            results.append(res)
        responses_received += 1
    
    results.sort(key=lambda x: x["candidate"])
    return results


# ---- Evolutionary Algorithm ----
def run_evolution(intersection: IntersectionConfig, params: GAParams, use_gui: bool = False):
    print(f"\n=== Starte Evolution für '{intersection.name}' ===")
    print(f"Phasen: {intersection.num_phases}, Signallänge: {intersection.signal_length}")
    print(f"Kandidatenlänge: {params.candidate_length(intersection)} Phaseneinträge")
    print(f"Population: {params.population_size}, Generationen: {params.generations}")
    print(f"Mutation: {params.mutation_rate}, Crossover: {params.crossover_rate}")
    print(f"Elitismus: {params.elitism_count}, Tournament-Größe: {params.tournament_size}")
    
    init_log(intersection.name)
    init_best_log(intersection.name)
    
    population = create_initial_population(intersection, params)
    best_overall_fitness = float("-inf")
    best_overall_candidate = None
    best_overall_result = {}
    
    start_worker_pool(intersection, params, use_gui=use_gui)
    
    try:
        evolution_start_time = time.time()
        gen_start_time = time.time()
        
        for gen in range(params.generations):
            is_last_gen = (gen == params.generations - 1)
            print(f"\n=== Generation {gen} ===")

            results = evaluate_population(population, intersection, params, use_gui=use_gui)
            fitnesses = [r["fitness"] for r in results]
            
            avg_fit = sum(fitnesses) / len(fitnesses)
            best_fit = max(fitnesses)
            best_idx = fitnesses.index(best_fit)
            best_result = results[best_idx]
            
            # Zeitprognose
            gen_end_time = time.time()
            gen_duration = gen_end_time - gen_start_time
            remaining_gens = params.generations - (gen + 1)
            eta_seconds = gen_duration * remaining_gens
            eta_min, eta_sec = divmod(int(eta_seconds), 60)
            elapsed_total = gen_end_time - evolution_start_time if gen > 0 else gen_duration
            avg_per_gen = elapsed_total / (gen + 1)
            
            print(f"Durchschnittliche Fitness: {avg_fit:.4f}")
            print(f"Beste Fitness: {best_fit:.4f}")
            print(f"Gen-Dauer: {gen_duration:.1f}s | Ø {avg_per_gen:.1f}s/Gen | Verbleibend: {eta_min}m {eta_sec}s ({remaining_gens} Gen)")
            
            gen_start_time = time.time()
            
            if best_fit > best_overall_fitness:
                best_overall_fitness = best_fit
                best_overall_candidate = copy.deepcopy(population[best_idx])
                best_overall_result = copy.deepcopy(best_result)
            
            log_best_candidate(
                intersection.name, gen, best_idx,
                best_result["fitness"], best_result["waiting_time"],
                best_result.get("vehicle_count", 0),
                best_result.get("avg_vehicle_wait", 0.0),
                best_result.get("wait_distribution", {}),
                best_result["emergency_brakes"], best_result["crashes"],
                population[best_idx],
                wait_values_raw=best_result.get("wait_values_raw"),
            )
            
            avg_wait = sum(r["waiting_time"] for r in results) / len(results)
            avg_brakes = sum(r["emergency_brakes"] for r in results) / len(results)
            avg_vehicles = sum(r.get("vehicle_count", 0) for r in results) / len(results)
            avg_wait_per_vehicle = sum(r.get("avg_vehicle_wait", 0.0) for r in results) / len(results)
            avg_crashes = sum(len(r.get("crashes", [])) for r in results) / len(results)
            
            # Detaillierte Statistiken in der letzten Generation ausgeben
            if is_last_gen:
                print(f"\n--- Detaillierte Wartezeit-Statistiken (Bester Kandidat) ---")
                print(f"Max. Wartezeit (einzelnes Fzg): {best_result.get('max_vehicle_wait', 0):.1f}s")
                print(f"Ø Wartezeit pro Fzg: {best_result.get('avg_vehicle_wait', 0):.1f}s")
                dist = best_result.get('wait_distribution', {})
                n_tracked = best_result.get('total_vehicles_tracked', 0)
                if dist and n_tracked > 0:
                    print(f"Wartezeit-Verteilung ({n_tracked} Fzg):")
                    for label, count in dist.items():
                        pct = count / n_tracked * 100
                        bar = '█' * int(pct / 2)
                        print(f"  {label:>8s}: {count:4d} Fzg ({pct:5.1f}%) {bar}")
            
            log_generation(intersection.name, gen, avg_fit, best_fit, best_overall_fitness,
                           avg_wait, avg_vehicles, avg_wait_per_vehicle, avg_crashes, avg_brakes,
                           params.mutation_rate)
            
            if gen == params.generations - 1:
                break
            
            new_population = []
            elite_indices = sorted(range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True)[:params.elitism_count]
            for idx in elite_indices:
                new_population.append(copy.deepcopy(population[idx]))
            
            while len(new_population) < params.population_size:
                parent1 = tournament_selection(population, fitnesses, params.tournament_size, params.tournament_probability)
                parent2 = tournament_selection(population, fitnesses, params.tournament_size, params.tournament_probability)
                child = crossover(parent1, parent2, params)
                child = mutate(child, intersection, params)
                new_population.append(child)
            
            population = new_population
    finally:
        stop_worker_pool()
    
    print(f"\n=== Evolution abgeschlossen ===")
    total_time = time.time() - evolution_start_time
    total_min, total_sec = divmod(int(total_time), 60)
    print(f"Beste Gesamtfitness: {best_overall_fitness:.4f}")
    print(f"Gesamtdauer: {total_min}m {total_sec}s")
    
    return best_overall_candidate, best_overall_fitness, best_overall_result



def run_single_simulation(
    intersection: IntersectionConfig,
    params: GAParams,
    candidate: Optional[List[int]] = None,
    config_path: str = None,
    label: str = "",
    use_gui: bool = False,
) -> dict:
    """Führt eine einzelne SUMO-Simulation durch und gibt das Ergebnis-Dict zurück.

    Im GA-Modus (candidate gegeben) steuert die Funktion die Ampelphasen über
    build_signal_state. Im Referenz-Modus (candidate=None) übernimmt SUMO die
    eingebaute Steuerlogik (Baseline / Actuated).
    """
    import traci
    import traci.constants as tc

    if config_path is None:
        config_path = intersection.sumo_config_path

    print(f"\n=== {label}-Simulation für \'{intersection.name}\' ===")

    sumo_bin = SUMO_GUI if use_gui else SUMO_CLI
    port = find_free_port()
    cmd = [
        sumo_bin, "-c", config_path,
        "--remote-port", str(port), "--start",
        "--step-length", str(params.step_length),
        "--seed", str(_SIMULATION_SEED),
        "--no-step-log",
        "--no-duration-log",
        "--xml-validation", "never",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        for _ in range(200):
            try:
                time.sleep(0.05)
                traci.init(port)
                break
            except Exception:
                time.sleep(0.01)
        else:
            proc.kill()
            raise RuntimeError("Konnte keine Verbindung zu SUMO herstellen")

        fitness = 0.0
        emergency_brakes = 0
        total_vehicle_count = 0
        vehicle_accum_wait: dict = {}

        total_steps = int(params.simulation_duration / params.step_length)
        penalty_base = params.penalty_wait_base
        exponent = params.waiting_time_exponent
        brake_threshold = params.emergency_braking_threshold

        _getArrivedNumber = traci.simulation.getArrivedNumber
        _getDeparted = traci.simulation.getDepartedIDList
        _getAllSubResults = traci.vehicle.getAllSubscriptionResults
        _subscribe = traci.vehicle.subscribe
        _SUBSCRIBE_VARS = [tc.VAR_ACCUMULATED_WAITING_TIME, tc.VAR_ACCEL]

        # GA-Modus: Phasensteuerung vorbereiten
        if candidate is not None:
            steps_per_phase = int(intersection.phase_duration / params.step_length)
            candidate_len = len(candidate)
            transition_steps = int((3 + intersection.all_red_time + 1) / params.step_length)
            tls_id = intersection.tls_id
            last_state = None

        for step in range(total_steps):
            traci.simulationStep()

            # GA-Modus: Ampelsteuerung je Simulationsschritt
            if candidate is not None:
                phase_idx = min(step // steps_per_phase, candidate_len - 1)
                step_in_phase = step % steps_per_phase
                if step_in_phase <= transition_steps or last_state is None:
                    state = build_signal_state(intersection, params, candidate, phase_idx, step_in_phase)
                    if state != last_state:
                        try:
                            traci.trafficlight.setRedYellowGreenState(tls_id, state)
                        except Exception:
                            pass
                        last_state = state

            for v in _getDeparted():
                _subscribe(v, _SUBSCRIBE_VARS)

            for v, data in _getAllSubResults().items():
                vehicle_accum_wait[v] = data[tc.VAR_ACCUMULATED_WAITING_TIME]
                if data[tc.VAR_ACCEL] <= brake_threshold:
                    emergency_brakes += 1

            total_vehicle_count += _getArrivedNumber()

        wait_values = list(vehicle_accum_wait.values())
        total_wait = sum(wait_values)
        for wt in wait_values:
            fitness -= penalty_base * (wt ** exponent)
        fitness -= params.penalty_emergency * emergency_brakes
        crashes = traci.simulation.getCollidingVehiclesIDList()

        avg_wait = total_wait / total_vehicle_count if total_vehicle_count > 0 else 0.0
        max_wait = max(wait_values) if wait_values else 0.0

        bins = [0, 10, 30, 60, 120, 180, float('inf')]
        bin_labels = ["0-10s", "10-30s", "30-60s", "60-120s", "120-180s", ">180s"]
        wait_distribution = {lbl: 0 for lbl in bin_labels}
        for wt in wait_values:
            for i in range(len(bins) - 1):
                if bins[i] <= wt < bins[i + 1]:
                    wait_distribution[bin_labels[i]] += 1
                    break

        print(f"  Fitness:     {fitness:.2f}")
        print(f"  Wartezeit:   {total_wait:.2f}s  |  Ø {avg_wait:.2f}s/Fzg  |  Max {max_wait:.1f}s")
        print(f"  Fahrzeuge:   {total_vehicle_count}  |  Notbremsungen: {emergency_brakes}")
        for cat, count in wait_distribution.items():
            pct = count / len(wait_values) * 100 if wait_values else 0
            print(f"    {cat:>8s}: {count:4d} ({pct:5.1f}%)")

        return {
            "fitness": fitness,
            "waiting_time": total_wait,
            "emergency_brakes": emergency_brakes,
            "crashes": list(crashes) if crashes else [],
            "vehicle_count": total_vehicle_count,
            "max_vehicle_wait": max_wait,
            "avg_vehicle_wait": avg_wait,
            "wait_distribution": wait_distribution,
            "wait_values_raw": sorted(wait_values),
            "total_vehicles_tracked": len(wait_values),
        }

    finally:
        try:
            traci.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass


def run_traffic_level_tests(
    intersection: IntersectionConfig,
    params: GAParams,
    candidate: List[int],
    use_gui: bool = False,
) -> dict:
    """Testet GA-Kandidat, Baseline und Actuated auf 75%- und 50%-Verkehrslevel.

    Für jedes Level wird eine eigene reference-CSV im _LOG_DIR angelegt.
    Traffic-Level ohne vorhandene SUMO-Config werden stillschweigend übersprungen.
    """
    configs = get_reduced_traffic_configs(intersection)
    all_results = {}

    for factor in [0.75, 0.5]:
        level_configs = configs[factor]
        pct = int(factor * 100)
        suffix = f"_{pct}"

        if level_configs["baseline"] is None:
            print(f"\n[Traffic-Level {pct}%] Keine Config für '{intersection.name}' gefunden, überspringe.")
            continue

        print(f"\n{'='*60}")
        print(f"=== Traffic-Level {pct}% Test: {intersection.name} ===")
        print(f"{'='*60}")

        ga_result = run_single_simulation(
            intersection, params, candidate=candidate,
            config_path=level_configs["baseline"],
            label=f"GA ({pct}%)",
            use_gui=use_gui,
        )

        baseline_result = run_single_simulation(
            intersection, params,
            config_path=level_configs["baseline"],
            label=f"Baseline ({pct}%)",
            use_gui=use_gui,
        )

        actuated_result = None
        if level_configs["actuated"]:
            actuated_result = run_single_simulation(
                intersection, params,
                config_path=level_configs["actuated"],
                label=f"Actuated ({pct}%)",
                use_gui=use_gui,
            )

        init_reference_log(intersection.name, suffix=suffix)
        log_reference(intersection.name, "GA", ga_result, suffix=suffix)
        log_reference(intersection.name, "Baseline", baseline_result, suffix=suffix)
        if actuated_result:
            log_reference(intersection.name, "Actuated", actuated_result, suffix=suffix)

        level_results = {"ga": ga_result, "baseline": baseline_result}
        if actuated_result:
            level_results["actuated"] = actuated_result
        all_results[factor] = level_results

    return all_results


# ============================================================
# KONFIGURATION - Hier anpassen!
# ============================================================
SELECTED_INTERSECTION = "pallaswiesen"  # "dieburger", "frankfurter", "pallaswiesen", "bremen"
USE_GUI = False 
BASELINE_ONLY = False


# ---- Single Experiment ----
def run_single_experiment(intersection: IntersectionConfig, params: GAParams,
                           use_gui: bool = False, baseline_only: bool = False,
                           seed: int = 42, test_traffic_levels: bool = False) -> dict:
    """Führt ein vollständiges Experiment durch (GA-Evolution + Baseline + Actuated).

    Mit test_traffic_levels=True wird der beste GA-Kandidat zusätzlich auf
    reduzierten Verkehrsdichten getestet (75%, 50%), sofern SUMO-Configs vorhanden.
    """
    random.seed(seed)
    set_simulation_seed(seed)

    results = {}

    if baseline_only:
        baseline = run_single_simulation(intersection, params, label="Baseline", use_gui=use_gui)
        actuated = None
        if intersection.actuated_config_path:
            actuated = run_single_simulation(
                intersection, params,
                config_path=intersection.actuated_config_path,
                label="Actuated",
                use_gui=use_gui,
            )
        init_reference_log(intersection.name)
        log_reference(intersection.name, "Baseline", baseline)
        if actuated:
            log_reference(intersection.name, "Actuated", actuated)
        results["baseline"] = baseline
        if actuated:
            results["actuated"] = actuated
    else:
        best_candidate, best_fitness, best_ga_result = run_evolution(intersection, params, use_gui=use_gui)
        print(f"\nBester Kandidat: {best_candidate}")

        baseline = run_single_simulation(intersection, params, label="Baseline", use_gui=use_gui)

        actuated = None
        if intersection.actuated_config_path:
            actuated = run_single_simulation(
                intersection, params,
                config_path=intersection.actuated_config_path,
                label="Actuated",
                use_gui=use_gui,
            )

        init_reference_log(intersection.name)
        log_reference(intersection.name, "GA", best_ga_result)
        log_reference(intersection.name, "Baseline", baseline)
        if actuated:
            log_reference(intersection.name, "Actuated", actuated)

        print(f"\n{'='*50}")
        print(f"=== Vergleich für '{intersection.name}' ===")
        print(f"{'='*50}")
        print(f"{'Methode':<12s} {'Fitness':>12s} {'Wartezeit':>12s} {'Notbr.':>8s} {'Max.Warte':>10s} {'Ø Warte':>10s}")
        print(f"{'-'*64}")

        if baseline["fitness"] != 0:
            ga_vs_baseline = ((baseline["fitness"] - best_fitness) / abs(baseline["fitness"])) * 100
        else:
            ga_vs_baseline = 0.0

        print(f"{'GA':.<12s} {best_fitness:>12.2f} {'':>12s} {'':>8s} {'':>10s} {'':>10s}")
        print(f"{'Baseline':.<12s} {baseline['fitness']:>12.2f} {baseline['waiting_time']:>12.2f} {baseline['emergency_brakes']:>8d} {baseline.get('max_vehicle_wait',0):>9.1f}s {baseline.get('avg_vehicle_wait',0):>9.1f}s")

        if actuated:
            print(f"{'Actuated':.<12s} {actuated['fitness']:>12.2f} {actuated['waiting_time']:>12.2f} {actuated['emergency_brakes']:>8d} {actuated.get('max_vehicle_wait',0):>9.1f}s {actuated.get('avg_vehicle_wait',0):>9.1f}s")

        print(f"\nGA vs Baseline: {ga_vs_baseline:+.2f}%")
        if actuated and actuated["fitness"] != 0:
            ga_vs_actuated = ((actuated["fitness"] - best_fitness) / abs(actuated["fitness"])) * 100
            print(f"GA vs Actuated: {ga_vs_actuated:+.2f}%")

        results["ga"] = best_ga_result
        results["baseline"] = baseline
        if actuated:
            results["actuated"] = actuated

        if test_traffic_levels:
            level_results = run_traffic_level_tests(intersection, params, best_candidate, use_gui=use_gui)
            if level_results:
                results["traffic_levels"] = level_results

    return results

def _get_log_file(intersection_name: str) -> str:
    """Gibt den Pfad zur Generations-Log-Datei für die jeweilige Kreuzung zurück."""
    return os.path.join(_LOG_DIR, f"ga_log_{intersection_name}.csv")

def _get_best_file(intersection_name: str) -> str:
    """Gibt den Pfad zur Best-Kandidaten-Log-Datei für die jeweilige Kreuzung zurück."""
    return os.path.join(_LOG_DIR, f"best_candidates_{intersection_name}.csv")

def init_log(intersection_name: str):
    """Initialisiere das Generations-Log."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    with open(_get_log_file(intersection_name), "w", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            "Generation",
            "AverageFitness",
            "BestFitness",
            "BestOverallFitness",
            "AverageWaitingTime",
            "AverageVehicleCount",
            "AverageWaitPerVehicle",
            "AverageCrashes",
            "AverageEmergencyBrakes",
            "MutationRate",
        ])


def init_best_log(intersection_name: str):
    """Initialisiere das Best-Kandidaten-Log."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    with open(_get_best_file(intersection_name), "w", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            "Generation",
            "CandidateIndex",
            "Fitness",
            "WaitingTime",
            "VehicleCount",
            "WaitPerVehicle",
            "WaitDistribution_JSON",
            "Crashes",
            "EmergencyBrakes",
            "Candidate_JSON",
            "WaitValuesRaw_JSON",
        ])


def log_generation(intersection_name: str, gen: int, avg_fit: float, best_fit: float, best_overall: float,
                   avg_waiting_time: float, avg_vehicle_count: float, avg_wait_per_vehicle: float,
                   avg_crashes: float, avg_brakes: float, mutation_rate: float):
    """Logge Generationsstatistiken."""
    with open(_get_log_file(intersection_name), "a", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            gen,
            f"{avg_fit:.4f}",
            f"{best_fit:.4f}",
            f"{best_overall:.4f}",
            f"{avg_waiting_time:.4f}",
            f"{avg_vehicle_count:.0f}",
            f"{avg_wait_per_vehicle:.4f}",
            f"{avg_crashes:.4f}",
            f"{avg_brakes:.4f}",
            f"{mutation_rate:.4f}",
        ])


def log_best_candidate(intersection_name: str, gen: int, idx: int, fitness: float, waiting_time: float,
                       vehicle_count: int, wait_per_vehicle: float, wait_distribution: dict,
                       brakes: int, crashes: list, candidate: List[int],
                       wait_values_raw: list = None):
    """Logge den besten Kandidaten einer Generation."""
    with open(_get_best_file(intersection_name), "a", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            gen,
            idx,
            f"{fitness:.4f}",
            f"{waiting_time:.4f}",
            vehicle_count,
            f"{wait_per_vehicle:.4f}",
            json.dumps(wait_distribution),
            json.dumps(crashes),
            brakes,
            json.dumps(candidate),
            json.dumps(wait_values_raw if wait_values_raw is not None else []),
        ])
# ---- Main ----
def main():
    intersection = INTERSECTIONS[SELECTED_INTERSECTION]
    params = GAParams()
    run_single_experiment(intersection, params, use_gui=USE_GUI, baseline_only=BASELINE_ONLY)


if __name__ == "__main__":
    main()