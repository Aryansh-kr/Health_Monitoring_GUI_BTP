from flask import Flask, render_template, jsonify, request
import serial.tools.list_ports
import platform
import os
import socket
import numpy as np
from datetime import datetime
import random
import time
from collections import deque
import joblib, os, logging
from scipy.signal import butter, filtfilt, find_peaks, welch
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import MinMaxScaler
from scipy import stats

app = Flask(__name__)

# -------------------------
# Connection configuration
# -------------------------
connection_config = {
    'mode': None,
    'serial_port': None,
    'baud_rate': None,
    'ble_address': None,
    'wifi_ip': None
}

# -------------------------
# Buffers and settings
# -------------------------
# Buffers for general ECG/PPG data
ECG_BUFFER = []
PPG_BUFFERS = {'ir': [], 'red': [], 'green': []}
MAX_BUFFER_SIZE = 70

# Buffers for simulated PPG streaming endpoint (separate sizes if desired)
MAX_SAMPLES = 100
STREAM_PPG_BUFFERS = {
    "ir": [0] * MAX_SAMPLES,
    "red": [0] * MAX_SAMPLES,
    "green": [0] * MAX_SAMPLES,
}

# -------------------------
# Routes - UI pages
# -------------------------
@app.route('/')
def intro():
    # Single landing page; ensure 'intro.html' exists in templates
    return render_template('intro.html')


@app.route('/menu')
def menu():
    return render_template('menu.html')


@app.route("/ppg")
def ppg_page():
    return render_template("ppg.html", title="PPG", icon="💡")


@app.route("/heartrate")
def heartrate_page():
    return render_template("heartrate.html", title="Heartrate", icon="❤️")


@app.route("/ecg")
def ecg_page():
    return render_template("ecg.html", title="ECG", icon="🫀")


@app.route("/spo2")
def spo2_page():
    return render_template("spo2.html", title="SPO2", icon="🌬️")


@app.route("/gas")
def gas_page():
    return render_template("gas.html", title="Gas", icon="🔥",gases=zip(GAS_NAMES, GAS_UNITS, GAS_ICONS, range(6)))


@app.route("/temperatures")
def temperatures_page():
    return render_template("temperature.html", title="Temperatures", icon="🌡️")


@app.route("/master")
def master_dashboard():
    return render_template("dashboard.html", title="Master Dashboard", icon="📊")


@app.route("/bp")
def bp_page():
    return render_template("bp.html", title="Blood Pressure", icon="🩸")


# -------------------------
# API: System / Connectivity
# -------------------------
@app.route('/api/com-ports')
def get_com_ports():
    """Return available COM/serial ports and common baud rates."""
    try:
        ports = [port.device for port in serial.tools.list_ports.comports()]
    except Exception:
        ports = []

    # Add Raspberry Pi typical ports on non-Windows machines
    if platform.system() != 'Windows':
        rpi_ports = ['/dev/ttyUSB0', '/dev/ttyACM0', '/dev/ttyS0', '/dev/ttyAMA0']
        ports += [p for p in rpi_ports if os.path.exists(p)]

    if not ports:
        ports = ['No Ports Available']

    return jsonify({
        'ports': ports,
        'baud_rates': ['9600', '19200', '38400', '57600', '115200']
    })


@app.route('/api/scan-ble', methods=['POST'])
def scan_ble():
    """Scan for BLE devices (placeholder). Replace with bleak.BleakScanner in production."""
    try:
        # Simulated devices for demonstration
        devices = [
            {'name': 'Health Monitor 1', 'address': 'AA:BB:CC:DD:EE:01'},
            {'name': 'Health Monitor 2', 'address': 'AA:BB:CC:DD:EE:02'},
        ]
        return jsonify({'success': True, 'devices': devices, 'message': f'Found {len(devices)} devices'})
    except Exception as e:
        return jsonify({'success': False, 'devices': [], 'message': f'Scan error: {str(e)}'})


@app.route('/api/test-wifi', methods=['POST'])
def test_wifi():
    """Test TCP connectivity to device IP on port 80 (common HTTP)."""
    data = request.get_json(silent=True) or {}
    ip = (data.get('ip') or '').strip()

    if not ip:
        return jsonify({'success': False, 'message': 'Please enter IP address'})

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, 80))  # Try port 80
        sock.close()

        if result == 0:
            return jsonify({'success': True, 'message': 'Connected!'})
        else:
            return jsonify({'success': False, 'message': 'Connection failed'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})


@app.route('/api/save-config', methods=['POST'])
def save_config():
    """Save connection configuration (in-memory)."""
    global connection_config
    data = request.get_json(silent=True) or {}
    mode = data.get('mode')

    connection_config['mode'] = mode

    # Clear previous values for unused keys to avoid stale state
    if mode != 'serial':
        connection_config['serial_port'] = None
        connection_config['baud_rate'] = None
    if mode != 'ble':
        connection_config['ble_address'] = None
    if mode != 'wifi':
        connection_config['wifi_ip'] = None

    if mode == 'serial':
        connection_config['serial_port'] = data.get('com_port')
        connection_config['baud_rate'] = data.get('baud_rate')
    elif mode == 'ble':
        connection_config['ble_address'] = data.get('ble_address')
    elif mode == 'wifi':
        connection_config['wifi_ip'] = data.get('wifi_ip')

    return jsonify({'success': True, 'message': 'Configuration saved', 'config': connection_config})


@app.route('/api/get-config')
def get_config():
    """Return current connection configuration."""
    return jsonify(connection_config)


# -------------------------
# API: Sensor data
# -------------------------
@app.route('/api/data')
def api_get_data():
    """
    Return a snapshot of simulated sensor data along with internal buffers.
    This is the main API used by dashboards.
    """
    # Use Python native types so jsonify is happy
    heartrate = int(np.random.randint(60, 100))
    spo2 = int(np.random.randint(92, 100))
    ecg_val = float(np.random.uniform(-1.0, 1.0))
    bp_sys = int(np.random.randint(110, 130))
    bp_dia = int(np.random.randint(70, 85))
    temperatures = [
        float(np.random.uniform(36.0, 37.5)),
        float(np.random.uniform(20.0, 25.0)),
        float(np.random.uniform(36.5, 37.5))
    ]
    gas = [
        int(np.random.randint(0, 50)),
        int(np.random.randint(0, 100)),
        int(np.random.randint(0, 150)),
        int(np.random.randint(0, 120)),
        int(np.random.randint(0, 30)),
        float(np.random.uniform(0, 1.0))
    ]
    ppg = [
        int(np.random.randint(100000, 130000)),
        int(np.random.randint(60000, 90000)),
        int(np.random.randint(40000, 60000))
    ]
    timestamp = datetime.now().isoformat()

    data = {
        "heartrate": heartrate,
        "spo2": spo2,
        "ecg": ecg_val,
        "bp": f"{bp_sys}/{bp_dia}",
        "temperatures": temperatures,
        "gas": gas,
        "ppg": ppg,
        "timestamp": timestamp
    }

    # Update buffers (circular)
    global ECG_BUFFER, PPG_BUFFERS
    ECG_BUFFER.append(ecg_val)
    if len(ECG_BUFFER) > MAX_BUFFER_SIZE:
        ECG_BUFFER.pop(0)

    PPG_BUFFERS['ir'].append(ppg[0])
    PPG_BUFFERS['red'].append(ppg[1])
    PPG_BUFFERS['green'].append(ppg[2])

    for key in PPG_BUFFERS:
        if len(PPG_BUFFERS[key]) > MAX_BUFFER_SIZE:
            PPG_BUFFERS[key].pop(0)

    # Attach copies of buffers (to avoid accidental external mutation)
    data['ecg_buffer'] = list(ECG_BUFFER)
    data['ppg_buffers'] = {k: list(v) for k, v in PPG_BUFFERS.items()}

    return jsonify(data)


# Separate endpoint for streaming/simulated PPG data (for charts that poll frequently)
@app.route('/api/ppg-data')
def ppg_data():
    new_data = {
        "ir": random.randint(200, 800),
        "red": random.randint(100, 600),
        "green": random.randint(50, 400),
        "timestamp": int(time.time() * 1000)
    }

    # Update streaming buffers
    for ch in ["ir", "red", "green"]:
        STREAM_PPG_BUFFERS[ch].append(new_data[ch])
        if len(STREAM_PPG_BUFFERS[ch]) > MAX_SAMPLES:
            STREAM_PPG_BUFFERS[ch].pop(0)

    # Return the point (or optionally return the full buffer if desired)
    return jsonify(new_data)

# Store history for stats
history = {0: [], 1: [], 2: []}
MAX_HISTORY = 100

@app.route("/api/temp-data")
def get_data():
    # Simulate temperatures
    temperatures = [
        round(random.uniform(35, 38), 1),  # Contact
        round(random.uniform(20, 30), 1),  # Ambient
        round(random.uniform(36, 39), 1)  # Core
    ]

    statuses = []
    for i, temp in enumerate(temperatures):
        status = "normal"
        if i == 0 and (temp < 36 or temp > 37.5):
            status = "warning"
        if i == 2 and (temp < 36 or temp > 38.5):
            status = "critical"
        statuses.append(status)

        # Update history
        history[i].append(temp)
        if len(history[i]) > MAX_HISTORY:
            history[i].pop(0)

    stats = []
    for i in range(3):
        if history[i]:
            stats.append({
                "min": min(history[i]),
                "max": max(history[i]),
                "avg": round(sum(history[i]) / len(history[i]), 1)
            })
        else:
            stats.append({"min": None, "max": None, "avg": None})

    return jsonify({
        "temperatures": temperatures,
        "statuses": statuses,
        "stats": stats,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })

@app.route("/api/ecg-data")
def ecg_data():
    # Simulate analog ECG value (1000–3000)
    analog_value = random.randint(1000, 3000)

    # Convert analog (1000–3000) → voltage (-1.5mV to 1.5mV)
    voltage = (analog_value - 1000) / (3000 - 1000) * 3.0 - 1.5

    return jsonify({
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "analog": analog_value,
        "voltage": round(voltage, 3),
        "status": "System Ready"
    })

# Gas info
GAS_NAMES = ["CO", "CH4", "C2H5OH", "H2", "NH3", "NO2"]
GAS_UNITS = ["ppm"] * 6
GAS_ICONS = ["☠️", "🔥", "🍺", "💧", "⚠️", "☁️"]
GAS_THRESHOLDS = [
    (0, 10, 50),   # CO
    (0, 50, 200),  # CH4
    (0, 100, 300), # C2H5OH
    (0, 100, 500), # H2
    (0, 25, 50),   # NH3
    (0, 0.1, 1)    # NO2
]

# Store history (last 30 values for each gas)
HISTORY = [deque(maxlen=30) for _ in range(6)]

@app.route("/api/gas-data")
def get_gas_data():
    gas_values = []
    for i, thr in enumerate(GAS_THRESHOLDS):
        safe, moderate, hazardous = thr
        # Simulate random value around thresholds
        val = round(random.uniform(safe, hazardous * 1.2), 2)
        HISTORY[i].append(val)
        gas_values.append(val)

    return jsonify({
        "gas": gas_values,
        "history": [list(h) for h in HISTORY]
    })

# Session data
session_start_time = time.time()
session_data = {
    'min': float('inf'),
    'max': float('-inf'),
    'total': 0,
    'count': 0
}
graph_data = deque(maxlen=60)  # Store last 60 seconds of data
last_valid_hr = None

@app.route("/update")
def update():
    global session_data, last_valid_hr, graph_data

    # Simulate HR (replace with sensor reading)
    hr = random.choice([random.randint(55, 120), -1])

    if hr == -1:  # No finger
        return jsonify({
            "heartrate": -1,
            "status": "Place finger on sensor",
            "min": "--",
            "max": "--",
            "avg": "--",
            "graph": list(graph_data)
        })

    # Track last valid
    last_valid_hr = hr

    # Update stats
    session_data['min'] = min(session_data['min'], hr)
    session_data['max'] = max(session_data['max'], hr)
    session_data['total'] += hr
    session_data['count'] += 1
    avg = session_data['total'] // session_data['count']

    # Determine status
    if hr > 130:
        status = "HIGH HEART RATE"
    elif hr > 100:
        status = "ELEVATED"
    else:
        status = "NORMAL"

    # Update graph
    elapsed = int(time.time() - session_start_time)
    graph_data.append((elapsed, hr))

    return jsonify({
        "heartrate": hr,
        "status": status,
        "min": session_data['min'],
        "max": session_data['max'],
        "avg": avg,
        "graph": list(graph_data)
    })


@app.route("/clear", methods=["POST"])
def clear():
    global session_start_time, session_data, graph_data, last_valid_hr
    session_start_time = time.time()
    session_data = {'min': float('inf'), 'max': float('-inf'), 'total': 0, 'count': 0}
    graph_data.clear()
    last_valid_hr = None
    return jsonify({"message": "Session cleared"})


# Session data
session_start = None
session_data = {"spo2": [], "pulse": []}
thresholds = {
    "spo2": {"low": 90, "critical_low": 85},
    "pulse": {"low": 50, "high": 120, "critical_low": 40, "critical_high": 150},
}

paused = False
@app.route("/api/spo2-data")
def get_spo2_data():
    global session_start, paused

    if paused:
        return jsonify({"spo2": None, "pulse": None, "duration": get_duration()})

    # simulate sensor data (replace with real sensor input)
    spo2_val = random.randint(85, 99)
    pulse_val = random.randint(45, 140)

    session_data["spo2"].append(spo2_val)
    session_data["pulse"].append(pulse_val)

    return jsonify({
        "spo2": spo2_val,
        "pulse": pulse_val,
        "spo2_status": get_spo2_status(spo2_val),
        "pulse_status": get_pulse_status(pulse_val),
        "stats": get_stats(),
        "duration": get_duration()
    })

@app.route("/toggle_pause", methods=["POST"])
def toggle_pause():
    global paused
    paused = not paused
    return jsonify({"paused": paused})

@app.route("/settings", methods=["POST"])
def update_settings():
    global thresholds
    data = request.json
    thresholds = data
    return jsonify({"message": "Thresholds updated", "thresholds": thresholds})

def get_spo2_status(value):
    if value >= 95:
        return {"status": "Normal", "color": "green", "icon": "✅"}
    elif 90 <= value < 95:
        return {"status": "Low", "color": "yellow", "icon": "⚠️"}
    else:
        return {"status": "Critical", "color": "red", "icon": "❌"}

def get_pulse_status(value):
    if 60 <= value <= 100:
        return {"status": "Normal", "color": "green", "icon": "✅"}
    elif 50 <= value < 60 or 100 < value <= 120:
        return {"status": "Abnormal", "color": "yellow", "icon": "⚠️"}
    else:
        return {"status": "Critical", "color": "red", "icon": "❌"}

def get_stats():
    spo2_vals = session_data["spo2"]
    pulse_vals = session_data["pulse"]

    spo2_stats = {"avg": "--", "min": "--", "max": "--"}
    pulse_stats = {"avg": "--", "min": "--", "max": "--"}

    if spo2_vals:
        spo2_stats = {
            "avg": sum(spo2_vals)//len(spo2_vals),
            "min": min(spo2_vals),
            "max": max(spo2_vals),
        }
    if pulse_vals:
        pulse_stats = {
            "avg": sum(pulse_vals)//len(pulse_vals),
            "min": min(pulse_vals),
            "max": max(pulse_vals),
        }

    return {"spo2": spo2_stats, "pulse": pulse_stats}

def get_duration():
    global session_start
    if session_start is None:
        session_start = time.time()
    elapsed = int(time.time() - session_start)
    return f"{elapsed//60:02d}:{elapsed%60:02d}"


# Load models
current_dir = os.path.dirname(os.path.abspath(__file__))
try:
    model_sbp = joblib.load(os.path.join(current_dir, "sys.joblib"))
    model_dbp = joblib.load(os.path.join(current_dir, "dys.joblib"))
    logging.info("BP models loaded successfully")
except Exception as e:
    logging.error(f"Error loading models: {e}")
    model_sbp = None
    model_dbp = None

# ---------- Signal Processing ----------
def butter_bandpass_filter(data, lowcut=0.5, highcut=8.0, fs=100, order=3):
    nyq = 0.5 * fs
    low, high = lowcut/nyq, highcut/nyq
    b, a = butter(order, [low, high], btype="band")
    return filtfilt(b, a, data)

# ---------- Feature Extraction ----------
def extract_time_domain_features(sig):
    m = np.mean(sig, axis=1)
    sd = np.std(sig, axis=1)
    mx = np.max(sig, axis=1)
    mn = np.min(sig, axis=1)
    rng = mx - mn
    sk = stats.skew(sig, axis=1)
    kt = stats.kurtosis(sig, axis=1)
    ent = np.apply_along_axis(lambda x: stats.entropy(np.abs(x)+1e-8), 1, sig)
    return np.column_stack((m, sd, mx, mn, rng, sk, kt, ent))

def extract_frequency_domain_features(sig, fs=100):
    f, psd = welch(sig, fs=fs, nperseg=min(256, sig.shape[1]), axis=1)
    domf = f[np.argmax(psd, axis=1)]
    power = np.sum(psd, axis=1)
    return np.column_stack((domf, power))

def extract_ppg_specific_features(sig, fs=100):
    intervals, amps = [], []
    for s in sig:
        pks, _ = find_peaks(s, distance=int(fs*0.5))
        if len(pks) > 1:
            intervals.append(np.mean(np.diff(pks))/fs)
            amps.append(np.mean(s[pks]))
        else:
            intervals.append(np.nan)
            amps.append(np.nan)
    return np.column_stack((intervals, amps))

def extract_ppg_features(ppg_array, fs=100):
    features = []
    for sig in ppg_array:
        sig = (sig - np.min(sig)) / (np.max(sig) - np.min(sig) + 1e-8)
        peaks, _ = find_peaks(sig, distance=50)
        valleys, _ = find_peaks(-sig, distance=50)
        if len(peaks) < 2 or len(valleys) < 2:
            features.append([np.nan]*9)
            continue
        Pp, Pv = sig[peaks[0]], sig[valleys[0]]
        T1 = peaks[0] - valleys[0]
        T2 = valleys[1] - peaks[0] if len(valleys) > 1 else T1
        T3 = peaks[1] - valleys[1] if len(peaks) > 1 and len(valleys) > 1 else T1
        T4, T5 = valleys[0] - peaks[0], peaks[0] - valleys[0]
        ETR = (T4+T5)/(T1+T2+T3) if (T1+T2+T3)!=0 else np.nan
        BD = T1+T2+T3
        HR = BD/60
        SVC = (Pp-Pv)/T1 if T1!=0 else np.nan
        DVC = (Pp-Pv)/T2 if T2!=0 else np.nan
        d = np.diff(sig)
        SMVC, DMVC = np.max(d), np.min(d)
        PWIR = Pp/Pv if Pv!=0 else np.nan
        PWAT = T1/fs
        features.append([ETR, BD, HR, SVC, DVC, SMVC, DMVC, PWIR, PWAT])
    return np.array(features)

def extract_features(ppg_signal):
    arr = np.asarray(ppg_signal).reshape(1, -1)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(arr.T).reshape(1, -1)
    tf = extract_time_domain_features(scaled)
    ff = extract_frequency_domain_features(scaled)
    pf = extract_ppg_specific_features(scaled)
    wf = extract_ppg_features(scaled)
    feats = np.hstack((tf, ff, pf, wf))
    return SimpleImputer(strategy="mean").fit_transform(feats)



@app.route("/predict", methods=["POST"])
def predict():
    data = request.json.get("ppg", [])
    fs = request.json.get("fs", 100)

    if not data or model_sbp is None or model_dbp is None:
        return jsonify({"error": "Invalid input or models not loaded"}), 400

    try:
        data = np.array(data, dtype=float)
        filt = butter_bandpass_filter(data, fs=fs)
        X = extract_features(filt)
        sbp = float(model_sbp.predict(X)[0])
        dbp = float(model_dbp.predict(X)[0])
        return jsonify({"sbp": round(sbp,1), "dbp": round(dbp,1), "filtered": filt.tolist()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# Run app
# -------------------------
if __name__ == '__main__':
    # For production: remove debug=True, use a WSGI server like Gunicorn or uWSGI
    app.run(debug=True, host='0.0.0.0', port=5000)
