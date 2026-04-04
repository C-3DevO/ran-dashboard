# 📡 RAN Dashboard (srsRAN-based)

A real-time monitoring dashboard for 5G RAN built using srsRAN.

## 🚀 Features

* Live gNB log parsing
* PRB utilization tracking
* UE throughput visualization
* Scheduler insights (RR / PF ready)
* Extendable to Near-RT RIC

## 🛠 Tech Stack

* Python
* srsRAN
* Flask / Streamlit
* Linux

## 📊 Use Case

Designed for:

* RAN engineers
* AI-RAN experimentation
* Scheduler optimization research

## 🔮 Future Work

* Integrate E2 interface (FlexRIC)
* AI-based PRB allocation
* Anomaly detection (ML)

## ▶️ Run

```bash
python3 dashboard.py
```

## Contributor practice
- Branch used for fork workflow practice: feature/pcchri

## 📡 xApp Fairness Monitoring (KPM-based)

This project has been extended with a Near-RT RIC xApp that monitors per-UE throughput and evaluates fairness in real time.

### 📥 Metrics used
- KPM Service Model (Format 1)
- Actions:
  - `DRB.UEThpDl` (downlink throughput)

### ⚙️ What the xApp computes
- Per-UE throughput (DL)
- Jain’s fairness index (raw)
- Normalized throughput (per UE baseline using EWMA)
- Normalized fairness index
- Weakest and strongest UE detection

### 🧠 Fairness logic
Each UE maintains a baseline throughput using an Exponential Weighted Moving Average (EWMA):

- Baseline adapts to channel conditions
- Current throughput is normalized against baseline
- Fairness is evaluated on normalized values

This allows distinguishing:
- Channel effects (CQI differences)
- Scheduling unfairness

### 📊 Policy output
The xApp identifies:
- Weakest UE (lowest throughput)
- Strongest UE (highest throughput)
- Throughput gap and ratio

Example policy decision:
- Prioritize weaker UEs
- Deprioritize strongest UEs when imbalance is detected

### ⚠️ Notes
- Current testing uses static channel conditions (limited fairness variation)
- Dynamic CQI scenarios are required for full evaluation
- Dashboard integration with xApp metrics is pending

