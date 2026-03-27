from datetime import datetime
from flask import Flask, render_template, jsonify
import subprocess
import os
import signal
import pty
import threading
import time
import re


app = Flask(__name__)

# ---- CONFIG ----
BASE_DIR = "/home/cp3-dev0/Simulation"

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
            "-c", "../configs/gnb_custom_cell_2.yml",
            "-c", "../configs/testmode.yml"
        ],
        "cwd": f"{BASE_DIR}/srsRAN_Project/build"
    },
    "xapp": {
        "cmd": ["./xapp_oran_moni"],
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
    return f"/home/cp3-dev0/Simulation/logs/{prefix}_{timestamp}.log"


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
            subprocess.run(["pkill", "-f", "xapp_oran_moni"])

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


# ---- MAIN ----

if __name__ == '__main__':
    threading.Thread(target=monitor_dependencies, daemon=True).start()
    app.run(debug=True)