
# Genetischer Algorithmus zur Optimierung von Ampelschaltungen

Dieses Repository enthält den genetischen Algorithmus, der im Rahmen der Bachelorarbeit zur Optimierung von Ampelschaltungen entwickelt wurde.

## Inhalt

- **Automatisierte Optimierung** von Ampelsteuerungen an vier Darmstädter Kreuzungen mittels SUMO-Simulation und genetischem Algorithmus.
- **Reproduzierbare Ergebnisse**: Durch die Verwendung von festen Seeds für Python und SUMO können die Resultate exakt nachvollzogen werden.
- **Batch-Ausführung**: Die Datei `batch_run.py` ermöglicht automatisierte Mehrfachläufe und aggregiert die Ergebnisse.

## Nutzung

1. **Voraussetzungen**
	- Python 3.x
	- SUMO (Simulation of Urban MObility)

2. **Batch-Ausführung starten**
	```
	python batch_run.py --intersection <name> --runs <anzahl>
	```
	Beispiel:
	```
	python batch_run.py --intersection frankfurter --runs 10
	```

3. **Ergebnisse**
	- Ergebnisse werden in Unterordnern wie `logging/run_XX/` gespeichert.
	- Die Datei `aggregate_results.py` fasst die Resultate zusammen.

## Reproduzierbarkeit

Für die Bachelorarbeit wurde für jede der vier Kreuzungen (`dieburger`, `frankfurter`, `pallaswiesen`, `bremen`) jeweils ein Batchlauf mit 10 Wiederholungen durchgeführt. Die Seeds sorgen dafür, dass die Ergebnisse exakt replizierbar sind.
Der in der Thesis verwendete Startseed ist 42.

die genannten Laufzeiten kommen von meinem Apple M3 Max 16-Kern Prozessor
### Geschätzte Laufzeiten

Die tatsächliche Laufzeit hängt stark von der Hardware ab. Die folgenden Werte dienen als grobe Orientierung und wurden auf einem Apple M3 Max (16-Kern Prozessor) gemessen:

| Kreuzung       | Geschätzte Laufzeit|
| -------------- | ------------------ |
| bremen         | ca. 1h 28min       |
| dieburger      | TBA                |
| frankfurter    | TBA                |
| pallaswiesen   | ca. 1h 51min       |

*Hinweis: Die Werte sind Schätzungen und können je nach System und Einstellungen variieren.*

## Struktur

- `batch_run.py`: Startet mehrere Durchläufe und aggregiert die Ergebnisse.
- `aggregate_results.py`: Fasst die Resultate zusammen.
- `src/simulation.py`: Enthält die Simulationslogik und GA-Parameter.
- `data/`: Enthält die SUMO-Konfigurationsdateien und die Berechnungen der Referenzmethoden
- `logging/`: Speichert die Logdateien und Ergebnisse.
