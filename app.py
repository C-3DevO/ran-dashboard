from datetime import datetime
from flask import Flask, render_template, jsonify, request
import subprocess
import os
import signal
import pty
import threading
import time
import re
import yaml


app = Flask(__name__)

# ---- CONFIG ----
BASE_DIR = "/home/petros/Spring_Engineering_Project"
CONFIG_PATH = "/home/petros/Spring_Engineering_Project/srsRAN_Project/configs/testmode.yml"

OPEN5GS_SERVICES = [
    "open5gs-amfd",
    "open5gs-smfd",
    "open5gs-upfd",
    "open5gs-nrfd",
    "open5gs-ausfd",
    "open5gs-pcfd",
    "open5gs-bsfd",
    "open5gs-udmd",
    "open5gs-udrd"
]

COMMANDS = {
    "ric": {
        "cmd": ["./nearRT-RIC"],
        "cwd": f"{BASE_DIR}/flexric/build/examples/ric"
    },
    "gnb": {
        "cmd": [
            "./apps/gnb/gnb",
            "-c", "../configs/gnb_custom_cell_properties_with_ric.yaml",
            "-c", "../configs/testmode.yml"
        ],
        "cwd": f"{BASE_DIR}/srsRAN_Project/build"
    },
    "xapp": {
        "cmd": ["./xapp_fairness_moni",
                "-c", "/usr/local/etc/flexric/xapp_kpm.conf"
                ],
        "cwd": f"{BASE_DIR}/flexric/build/examples/xApp/c/monitor"
    }
}

# ---- DEPENDENCIES ----
DEPENDENCIES = {
    "ric": ["open5gs"],
    "gnb": ["open5gs", "ric"],
    "xapp": ["ric", "gnb"]
}

processes = {}


def generate_log_file(prefix):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"/home/petros/Spring_Engineering_Project/logs/{prefix}_{timestamp}.log"


# ---- OPEN5GS CONTROL ----

def start_open5gs():
    results = []
    for svc in OPEN5GS_SERVICES:
        try:
            subprocess.run(["sudo", "systemctl", "start", svc])
            results.append(f"{svc} started")
        except Exception as e:
            results.append(f"{svc} error: {str(e)}")
    return results


def stop_open5gs():
    results = []
    for svc in OPEN5GS_SERVICES:
        try:
            subprocess.run(["sudo", "systemctl", "stop", svc])
            results.append(f"{svc} stopped")
        except Exception as e:
            results.append(f"{svc} error: {str(e)}")
    return results


def is_open5gs_running():
    for svc in OPEN5GS_SERVICES:
        result = subprocess.run(
            ["systemctl", "is-active", svc],
            capture_output=True,
            text=True
        )
        if result.stdout.strip() == "active":
            return True
    return False


# ---- DEPENDENCY CHECK ----

def dependencies_running(name):
    deps = DEPENDENCIES.get(name, [])

    for dep in deps:
        if dep == "open5gs":
            if not is_open5gs_running():
                return False, "open5gs is not running"
        else:
            if dep not in processes:
                return False, f"{dep} is not running"

    return True, "ok"

#--- VISUAL FUNCTIONS ----

def parse_gnb_log():
    log_file = processes.get("gnb_log")
    if not log_file:
        return []

    ue_data = {}

    try:
        with open(log_file, "r") as f:
            lines = f.readlines()

        for line in lines:
            # match full UE line
            match = re.match(
                r"\s*\d+\s+(\d+)\s+\|\s+(\d+)\s+([\d\.]+)\s+(\d+)\s+(\d+\.?\d*)M",
                line
            )

            if match:
                rnti = match.group(1)
                cqi = int(match.group(2))
                ri = float(match.group(3))
                mcs = int(match.group(4))
                throughput = float(match.group(5))

                ue_data[rnti] = {
                    "rnti": rnti,
                    "throughput": throughput,
                    "cqi": cqi,
                    "ri": ri,
                    "mcs": mcs
                }

    except Exception as e:
        print("Parse error:", e)

    return list(ue_data.values())


def parse_fairness_alert():
    log_file = processes.get("gnb_log")
    if not log_file or not os.path.exists(log_file):
        return {
            "status": "UNKNOWN",
            "raw_jain": None,
            "norm_jain": None,
            "rolling_mu": None,
            "rolling_var": None,
            "delta": None,
            "weakest_raw_ue": None,
            "strongest_raw_ue": None,
            "weakest_norm_ue": None,
            "strongest_norm_ue": None,
            "target_ue": None,
            "action": None,
        }

    latest_fairness = None
    latest_policy_raw = None
    latest_policy_norm = None
    latest_policy_status = None

    fairness_re = re.compile(
        r"KPM FAIRNESS DL: n=(\d+) raw_jain=([-\d\.]+) norm_jain=([-\d\.]+) "
        r"rolling_mu=([-\d\.]+) rolling_var=([-\d\.]+) delta=([-\d\.]+)"
    )

    policy_raw_re = re.compile(
        r"KPM POLICY DL: weakest_raw_ue=(\d+) weakest_raw=([-\d\.]+) "
        r"strongest_raw_ue=(\d+) strongest_raw=([-\d\.]+)"
    )

    policy_norm_re = re.compile(
        r"KPM POLICY DL: weakest_norm_ue=(\d+) weakest_norm=([-\d\.]+) "
        r"strongest_norm_ue=(\d+) strongest_norm=([-\d\.]+)"
    )

    policy_status_re = re.compile(
        r"KPM POLICY DL: status=([A-Z_]+) action=([a-z_]+) target_ue=(\d+)(?: .*?)?$"
    )

    try:
        with open(log_file, "r") as f:
            for line in f:
                m = fairness_re.search(line)
                if m:
                    latest_fairness = {
                        "n": int(m.group(1)),
                        "raw_jain": float(m.group(2)),
                        "norm_jain": float(m.group(3)),
                        "rolling_mu": float(m.group(4)),
                        "rolling_var": float(m.group(5)),
                        "delta": float(m.group(6)),
                    }

                m = policy_raw_re.search(line)
                if m:
                    latest_policy_raw = {
                        "weakest_raw_ue": int(m.group(1)),
                        "weakest_raw": float(m.group(2)),
                        "strongest_raw_ue": int(m.group(3)),
                        "strongest_raw": float(m.group(4)),
                    }

                m = policy_norm_re.search(line)
                if m:
                    latest_policy_norm = {
                        "weakest_norm_ue": int(m.group(1)),
                        "weakest_norm": float(m.group(2)),
                        "strongest_norm_ue": int(m.group(3)),
                        "strongest_norm": float(m.group(4)),
                    }

                m = policy_status_re.search(line)
                if m:
                    latest_policy_status = {
                        "status": m.group(1),
                        "action": m.group(2),
                        "target_ue": int(m.group(3)),
                    }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

    result = {
        "status": "UNKNOWN",
        "raw_jain": None,
        "norm_jain": None,
        "rolling_mu": None,
        "rolling_var": None,
        "delta": None,
        "weakest_raw_ue": None,
        "strongest_raw_ue": None,
        "weakest_norm_ue": None,
        "strongest_norm_ue": None,
        "target_ue": None,
        "action": None,
    }

    if latest_fairness:
        result.update(latest_fairness)
    if latest_policy_raw:
        result.update(latest_policy_raw)
    if latest_policy_norm:
        result.update(latest_policy_norm)
    if latest_policy_status:
        result.update(latest_policy_status)

    return result



# ---- CORE FUNCTIONS ----

def start_process(name):
    if name in processes:
        return f"{name} already running"

    if name == "open5gs":
        return "\n".join(start_open5gs())

    ok, msg = dependencies_running(name)
    if not ok:
        return f"Cannot start {name}: {msg}"

    config = COMMANDS.get(name)
    if not config:
        return f"{name} not defined"

    try:
        # Handling for gNB logging

        if name == "gnb":
            log_file = generate_log_file("gnb")
            log_f = open(log_file, "w")

            master_fd, slave_fd = pty.openpty()

            proc = subprocess.Popen(
                config["cmd"],
                cwd=config["cwd"],
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=log_f,
                stderr=log_f,
                text=True
            )

            processes[name] = proc
            processes[f"{name}_log"] = log_file

            # writing
            os.write(master_fd, b"t\n")

            return f"{name} started (PID {proc.pid}) → log: {log_file}"

        #Default processes
        proc = subprocess.Popen(
            config["cmd"],
            cwd=config["cwd"],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        processes[name] = proc
        return f"{name} started (PID {proc.pid})"

    except Exception as e:
        return f"Error starting {name}: {str(e)}"


# def stop_process(name):
#     if name not in processes:
#         return f"{name} not running"
#
#     try:
#         proc = processes[name]
#         os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
#         del processes[name]
#         return f"{name} stopped"
#
#     except Exception as e:
#         return f"Error stopping {name}: {str(e)}"

def stop_process(name):
    if name not in processes:
        return f"{name} not running"

    try:
        proc = processes[name]

        # 1. Graceful shutdown
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        time.sleep(1)

        # 2. Force kill if still alive
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

        # 3. Fallback cleanup
        if name == "gnb":
            subprocess.run(["pkill", "-f", "./apps/gnb/gnb"])

        elif name == "ric":
            subprocess.run(["pkill", "-f", "nearRT-RIC"])

        elif name == "xapp":
            subprocess.run(["pkill", "-f", "xapp_fairness_moni"])

        del processes[name]
        return f"{name} stopped"

    except Exception as e:
        return f"Error stopping {name}: {str(e)}"



def stop_all():
    order = ["xapp", "gnb", "ric"]
    results = []

    for name in order:
        if name in processes:
            results.append(stop_process(name))

    results.extend(stop_open5gs())

    return results


def get_status():
    status = {}

    for name in ["open5gs", "ric", "gnb", "xapp"]:
        if name == "open5gs":
            status[name] = "running" if is_open5gs_running() else "stopped"
        else:
            status[name] = "running" if name in processes else "stopped"

    return status


# ---- MONITOR THREAD ----
def monitor_dependencies():
    while True:
        time.sleep(3)

        # Open5GS failure then we stop everything
        if not is_open5gs_running():
            if len(processes) > 0:
                stop_all()
            continue

        # RIC failure then we stop gNB + xApp
        if "ric" not in processes:
            for svc in ["gnb", "xapp"]:
                if svc in processes:
                    stop_process(svc)
            continue

        # gNB failure then we stop xApp
        if "gnb" not in processes:
            if "xapp" in processes:
                stop_process("xapp")


# Function to update the configs from terminal
def update_testmode_config(nof_ues, ri):
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)

    config['test_mode']['test_ue']['nof_ues'] = int(nof_ues)
    config['test_mode']['test_ue']['ri'] = int(ri)

    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f)

    # restart gNB
    stop_process("gnb")
    time.sleep(1)
    start_process("gnb")

    return "Config updated & gNB restarted"


# ---- ROUTES ----

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start/<name>')
def start(name):
    msg = start_process(name)
    return jsonify({"msg": msg, "status": get_status()})


@app.route('/stop/<name>')
def stop(name):
    if name == "open5gs":
        results = stop_all()
        return jsonify({"msg": results, "status": get_status()})

    msg = stop_process(name)
    return jsonify({"msg": msg, "status": get_status()})


@app.route('/stop_all')
def stop_all_route():
    results = stop_all()
    return jsonify({"msg": results, "status": get_status()})


@app.route('/status')
def status():
    return jsonify(get_status())


@app.route('/metrics')
def metrics():
    data = parse_gnb_log()
    return jsonify(data)

@app.route('/update_config', methods=['POST'])
def update_config_route():
    data = request.json

    try:
        msg = update_testmode_config(
            data['nof_ues'],
            data['ri']
        )
        return jsonify({"msg": msg})

    except Exception as e:
        return jsonify({"msg": f"Error: {str(e)}"})

@app.route('/fairness_alert')
def fairness_alert():
    return jsonify(parse_fairness_alert())


# ---- MAIN ----

if __name__ == '__main__':
    threading.Thread(target=monitor_dependencies, daemon=True).start()
    app.run(debug=True)