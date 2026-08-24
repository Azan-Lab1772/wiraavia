import pandas as pd
import folium
from folium import plugins
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import io
import re
from datetime import datetime, timedelta, timezone
import streamlit as st
import streamlit.components.v1 as components

# Matikan peringatan SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. KONFIGURASI HALAMAN STREAMLIT
# ==========================================
st.set_page_config(page_title="WiraAvia - DSS Aviation Weather", page_icon="✈️", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 0rem; }
        header { visibility: hidden; }
        footer { visibility: hidden; }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h2 style='text-align: center; color: #2C3E50; margin-bottom: 0;'>✈️ WiraAvia Dashboard</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #7F8C8D; font-style: italic; margin-top: 0;'>Decision Support System untuk Analisis Real-Time Amandemen TAF</p>", unsafe_allow_html=True)

col1, col2, col3 = st.columns([4, 2, 4])
with col2:
    if st.button("🔄 Tarik Data BMKG Terbaru", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ==========================================
# 2. DATA STASIUN BANDARA
# ==========================================
data_csv = """No,ICAO,Nama_Bandara,Lintang,Bujur,WMO
1,WITT,SULTAN ISKANDAR MUDA,5.520251, 95.420983,96011
2,WIMM,KUALANAMU INTERNASIONAL,3.642222, 98.885278,96035
3,WIBB,SULTAN SYARIF KASIM II,0.462222, 101.445278,96109
4,WIEE,MINANGKABAU,-0.788314, 100.286328,96163
5,WIGG,FATMAWATI SOEKARNO,-3.861111, 102.339444,96253
6,WIKK,DEPATI AMIR,-2.162583, 106.138189,96237
7,WIII,SOEKARNO HATTA,-6.126506, 106.661111,96749
8,WIIL,CILACAP/TUNGGUL WULUNG,-7.718061, 109.014129,96805
9,WARR,JUANDA,-7.377480, 112.794322,96935
10,WADD,I GUSTI NGURAH RAI,-8.747500, 115.169167,97230
12,WIOO,SUPADIO,-0.149114, 109.403175,96581
13,WAGI,ISKANDAR,-2.702621, 111.670454,96645
14,WAOO,SYAMSUDIN NOOR,-3.441156, 114.756625,96685
15,WALL,SULTAN AJI MUHAMMAD SULAIMAN,-1.267222, 116.893889,96633
16,WAQQ,JUWATA,3.326879, 117.567216,96509
17,WAFF,MUTIARA SIS AL-JUFRI,-0.916700, 119.910278,97072
18,WAAA,SULTAN HASANUDDIN,-5.058254, 119.554903,97180
19,WATC,FRANSISKUS XAVERIUS SEDA,-8.636989, 122.241190,97300
20,WATT,EL TARI,-10.171544, 123.671823,97372
21,WAMM,SAM RATULANGI,1.543517, 124.922348,97014
22,WAEE,SULTAN BABULLAH,0.831110, 127.380560,97430
23,WAPP,PATTIMURA,-3.706944, 128.088791,97724
24,WASS,DOMINE EDUARD OSOK,-0.894148, 131.287151,97502
25,WAPS,MATHILDA BATLAYERI,-7.988539, 131.304470,97900
26,WABB,FRANS KAISIEPO,-1.189421, 136.106010,97560
27,WAJJ,SENTANI,-2.571812, 140.512298,97690
28,WAVV,WAMENA,-4.097578, 138.952653,97686
29,WAKK,MOPAH,-8.521111, 140.416944,97980"""
df_bandara = pd.read_csv(io.StringIO(data_csv))

# ==========================================
# 3. KONEKSI API & CACHING STREAMLIT
# ==========================================
API_TOKEN = '37da31a5cc6f0732732a7f9c640507b2849e37a3b815b0252af2a54afc7a'
HEADERS = {
    'accept': '*/*', 
    'Authorization': f'Bearer {API_TOKEN}',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
}

session = requests.Session()
session.headers.update(HEADERS)
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)

@st.cache_data(ttl=600) # Cache 10 menit agar aman dari blokir
def get_weather_data(icao, data_type, count=45):
    url = f"https://web-aviation.bmkg.go.id/api/v1/{data_type}/{icao.lower()}"
    try:
        res = session.get(url, timeout=10, verify=False)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) == 0: return []
            if isinstance(data, dict) and icao.upper() in data:
                w_list = data[icao.upper()]
                if isinstance(w_list, list) and len(w_list) > 0:
                    return [w.get('data_text', "") for w in w_list[:count]]
    except Exception: pass
    return []

# ==========================================
# 4. ENGINE ASISTEN NWP & DIRECTIONAL PARSER
# ==========================================
def terjemah_wx(kode):
    if kode in [95, 96, 99]: return "TSRA ⚡"
    elif kode in [61, 63, 65, 66, 67]: return "RA 🌧️"
    elif kode in [45, 48]: return "FG 🌫️"
    elif kode in [51, 53, 55]: return "DZ 💧"
    elif kode in [0, 1, 2, 3]: return "NSW ⛅"
    else: return f"Kode {kode}"

@st.cache_data(ttl=1800) # Model NWP cache 30 menit
def get_nwp_forecast(lat, lon, status_color, l2_reasons):
    url = (f"https://api.open-meteo.com/v1/forecast?"
           f"latitude={lat}&longitude={lon}&"
           f"hourly=pressure_msl,weather_code,wind_speed_10m,wind_direction_10m&"
           f"models=ecmwf_ifs025,gfs_seamless,icon_global&timezone=UTC&wind_speed_unit=kn")
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, verify=False)
        if res.status_code == 200:
            data = res.json()
            hourly = data.get('hourly', {})
            waktu_full = hourly.get('time', [])
            if not waktu_full: return ""
            
            now_utc = datetime.now(timezone.utc)
            current_hour_str = now_utc.strftime("%Y-%m-%dT%H:00")
            start_idx = next((i for i, t in enumerate(waktu_full) if t >= current_hour_str), 0)
            
            waktu = waktu_full[start_idx : start_idx+3]
            null_array = [None] * len(waktu_full)

            qnh_ec, qnh_gf, qnh_ic = hourly.get('pressure_msl_ecmwf_ifs025', null_array)[start_idx:start_idx+3], hourly.get('pressure_msl_gfs_seamless', null_array)[start_idx:start_idx+3], hourly.get('pressure_msl_icon_global', null_array)[start_idx:start_idx+3]
            wx_ec, wx_gf, wx_ic = hourly.get('weather_code_ecmwf_ifs025', null_array)[start_idx:start_idx+3], hourly.get('weather_code_gfs_seamless', null_array)[start_idx:start_idx+3], hourly.get('weather_code_icon_global', null_array)[start_idx:start_idx+3]
            ws_ec, ws_gf, ws_ic = hourly.get('wind_speed_10m_ecmwf_ifs025', null_array)[start_idx:start_idx+3], hourly.get('wind_speed_10m_gfs_seamless', null_array)[start_idx:start_idx+3], hourly.get('wind_speed_10m_icon_global', null_array)[start_idx:start_idx+3]
            wd_ec, wd_gf, wd_ic = hourly.get('wind_direction_10m_ecmwf_ifs025', null_array)[start_idx:start_idx+3], hourly.get('wind_direction_10m_gfs_seamless', null_array)[start_idx:start_idx+3], hourly.get('wind_direction_10m_icon_global', null_array)[start_idx:start_idx+3]

            html_out, trend_cuaca = "", []
            
            for i in range(len(waktu)):
                jam = waktu[i][-5:]
                def get_val(arr, fmt, is_wx=False): return terjemah_wx(arr[i]) if is_wx and arr[i] is not None else (f"{arr[i]:{fmt}}" if arr[i] is not None else "N/A")
                def get_wind(wd_arr, ws_arr): return f"{wd_arr[i]:03.0f}/{ws_arr[i]:.0f}KT" if wd_arr[i] is not None and ws_arr[i] is not None else "N/A"

                q_e, q_u, q_i = get_val(qnh_ec, '.1f'), get_val(qnh_gf, '.1f'), get_val(qnh_ic, '.1f')
                w_e, w_u, w_i = get_val(wx_ec, '', True), get_val(wx_gf, '', True), get_val(wx_ic, '', True)
                wind_e, wind_u, wind_i = get_wind(wd_ec, ws_ec), get_wind(wd_gf, ws_gf), get_wind(wd_ic, ws_ic)

                bad_votes, total_votes = 0, 0
                for wx_arr, ws_arr in [(wx_ec, ws_ec), (wx_gf, ws_gf), (wx_ic, ws_ic)]:
                    if i < len(wx_arr) and wx_arr[i] is not None:
                        total_votes += 1
                        if wx_arr[i] >= 45 or (ws_arr[i] is not None and ws_arr[i] >= 15): bad_votes += 1
                
                trend_cuaca.append("BAD" if total_votes > 0 and bad_votes > (total_votes / 2) else "GOOD")

                html_out += f"<span style='color:#0056b3; font-weight:bold;'>{jam} UTC</span><br>"
                html_out += f"🇪🇺 ECMWF : {wind_e} | QNH {q_e} | {w_e}<br>"
                html_out += f"🇺🇸 GFS&nbsp;&nbsp;&nbsp;: {wind_u} | QNH {q_u} | {w_u}<br>"
                html_out += f"🇩🇪 ICON&nbsp;&nbsp;: {wind_i} | QNH {q_i} | {w_i}<br>"
                if i < len(waktu) - 1: html_out += "<br>"

            rekomendasi_html = ""
            if len(trend_cuaca) == 3:
                jam_teks = [waktu[0][-5:], waktu[1][-5:], waktu[2][-5:]]
                is_wind = any("Angin" in r or "Wind" in r for r in l2_reasons)
                is_vis_or_ceil = any("Visibilitas" in r or "Awan" in r or "Ceiling" in r for r in l2_reasons)
                is_wx = any("Cuaca Signifikan" in r for r in l2_reasons)

                is_improving, is_worsening = False, False
                for r in l2_reasons:
                    if "Visibilitas" in r:
                        match = re.search(r'Aktual: (\d+)m, TAF: (\d+)m', r)
                        if match and int(match.group(1)) > int(match.group(2)): is_improving = True
                        else: is_worsening = True
                    elif "Cuaca Signifikan" in r:
                        if "Aktual 'Clear'" in r or "Aktual 'NSW'" in r: is_improving = True
                        else: is_worsening = True
                    elif "Ceiling" in r:
                        match = re.search(r'Aktual: (\d+|None)ft, TAF: (\d+|None)ft', r)
                        if match:
                            a_val = 99999 if match.group(1) == 'None' else int(match.group(1))
                            f_val = 99999 if match.group(2) == 'None' else int(match.group(2))
                            if a_val > f_val: is_improving = True
                            else: is_worsening = True
                    elif "Kecepatan Angin" in r:
                        match = re.search(r'Aktual (\d+)kt vs TAF (\d+)kt', r)
                        if match and int(match.group(1)) < int(match.group(2)): is_improving = True
                        else: is_worsening = True
                    else: is_worsening = True

                if all(t == "GOOD" for t in trend_cuaca): teks_trend = "kondisi diprediksi stabil dan aman (cerah/berawan/nsw) ke depannya."
                elif all(t == "BAD" for t in trend_cuaca): teks_trend = "kondisi perburukan parameter diprediksi persisten bertahan."
                elif trend_cuaca[0] == "BAD" and "GOOD" in trend_cuaca: teks_trend = f"kondisi diprediksi berangsur mereda/membaik pada pukul {jam_teks[trend_cuaca.index('GOOD')]} UTC."
                elif trend_cuaca[0] == "GOOD" and "BAD" in trend_cuaca: teks_trend = f"potensi perburukan lebih lanjut mulai pukul {jam_teks[trend_cuaca.index('BAD')]} UTC."
                else: teks_trend = "kondisi parameter diprediksi akan berfluktuasi."

                if status_color == 'green': 
                    kesimpulan = f"METAR Aktual terpantau Normal. {teks_trend}"
                    saran = "Tidak ada indikasi untuk Amandemen TAF saat ini. Lanjutkan pemantauan."
                elif status_color == '#D4AC0D': 
                    kesimpulan = f"Terdapat fluktuasi cuaca (Laporan SPECI). {teks_trend}"
                    saran = "Tingkatkan kewaspadaan observasi. Jadikan model NWP sebagai panduan durasi jika merilis AMD TAF."
                else: 
                    if is_improving and not is_worsening:
                        kesimpulan = f"Kriteria AMD TAF terpenuhi karena kondisi aktual <b>LEBIH BAIK</b> dari TAF (<i>Over-forecast</i>). Konsensus NWP: {teks_trend}"
                        skenario_a = "Jika cuaca dipastikan membaik permanen, segera rilis AMD TAF untuk <b>MENGHAPUS</b> prediksi cuaca buruk tersebut."
                        skenario_b = "Jika radar mendeteksi cuaca buruk bisa kembali masuk (<i>delayed</i>), ubah ke sisipan <b>TEMPO</b>."
                    else:
                        kesimpulan = f"Kriteria AMD TAF terpenuhi akibat perburukan aktual! Konsensus NWP 3 jam ke depan: {teks_trend}"
                        if is_wind and not (is_vis_or_ceil or is_wx):
                            skenario_a = "Jika efek lokal sesaat (outflow awan), gunakan sisipan <b>TEMPO</b> singkat."
                            skenario_b = "Jika perubahan pola sinoptik persisten, amankan dengan <b>FM</b> atau sesuaikan <i>Base Group</i>."
                        elif is_vis_or_ceil and not is_wx:
                            skenario_a = "Jika fenomena tipis lokal (kabut cepat pudar), gunakan <b>TEMPO</b> atau <b>FM</b> singkat."
                            skenario_b = "Jika stratus/kelembapan tebal meluas, pertahankan di <i>Base Group</i> atau gunakan <b>BECMG</b>."
                        else:
                            skenario_a = "Jika radar mendeteksi awan sel tunggal (CB) bergerak cepat, abaikan model, gunakan <b>TEMPO</b>."
                            skenario_b = "Jika sistem hujan meluas di radar, ikuti <i>timeline</i> model. Gunakan <b>FM/BECMG</b>."
                    saran = f"Pantau Citra Radar terkini, lalu pilih skenario:<br><ul style='padding-left:15px; margin-top:5px;'><li style='margin-bottom:5px;'><b>Skenario A (Lokal/Singkat/Aman):</b> {skenario_a}</li><li><b>Skenario B (Meluas/Persisten/Delay):</b> {skenario_b}</li></ul>"

                rekomendasi_html = f"<div style='margin-top: 10px; background-color: #e9f7fd; border-left: 4px solid #17a2b8; color: #0c5460; padding: 10px; border-radius: 4px; white-space: normal;'>💡 <b>AI Konsensus Forecaster:</b><br>{kesimpulan}<br><br><b>🎯 Saran Taktis:</b><br>{saran}</div>"
            return html_out + "<br>" + rekomendasi_html
    except Exception: pass
    return ""

# ==========================================
# 5. PARSER & EVALUATOR METAR/TAF
# ==========================================
def extract_time_components(weather_str):
    if not weather_str or any(kw in weather_str for kw in ["NIL", "Error", "Gagal"]): return None
    match = re.search(r'\b(\d{2})(\d{2})(\d{2})Z\b', weather_str)
    if match: return {'day': int(match.group(1)), 'hour': int(match.group(2)), 'minute': int(match.group(3)), 'string_key': match.group(2) + match.group(3)}
    return None

def find_closest_data_by_grid_logic(target_dt, parsed_data_list):
    target_hhmm = target_dt.strftime("%H%M")
    for comp, text in parsed_data_list:
        if comp['string_key'] == target_hhmm: return text
    best_match = "NIL"
    min_diff = float('inf')
    for comp, text in parsed_data_list:
        rel_data_mins = comp['hour'] * 60 + comp['minute']
        rel_target_mins = target_dt.hour * 60 + target_dt.minute
        diff = abs(rel_data_mins - rel_target_mins)
        if diff > 720: diff = 1440 - diff
        if diff <= 25:
            if diff < min_diff:
                min_diff = diff
                best_match = text
    return best_match

def parse_weather_string(weather_text):
    if not weather_text or weather_text == "NIL": return None
    parsed = {'wind_dir': None, 'wind_spd': None, 'wind_spd_gust': None, 'vis': None, 'weather': [], 'vertical_vis': None, 'cloud_layers': []}
    wind_match = re.search(r'\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)\b', weather_text)
    if wind_match:
        dir_str = wind_match.group(1)
        parsed['wind_dir'] = int(dir_str) if dir_str != 'VRB' else None
        parsed['wind_spd'] = int(wind_match.group(2))
        if wind_match.group(3): parsed['wind_spd_gust'] = int(wind_match.group(3))
    if 'CAVOK' in weather_text:
        parsed['vis'] = 9999
        parsed['cloud_layers'] = [('NSC', 9999)]
    else:
        vis_match = re.search(r'(?:\s|^)(\d{4})(?=\s|$)', weather_text)
        if vis_match: parsed['vis'] = int(vis_match.group(1))
        parsed['weather'] = re.findall(r'\b([-+]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|IC|PE|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PO|SQ|FC|SS|DS))\b', weather_text)
        if 'NSW' in weather_text: parsed['weather'] = []
        vv_match = re.search(r'\bVV(\d{3})\b', weather_text)
        if vv_match: parsed['vertical_vis'] = int(vv_match.group(1)) * 100
        for amt, hgt in re.findall(r'\b(FEW|SCT|BKN|OVC|NSC|SKC|CLR)(\d{3})?(?:CB|TCU)?\b', weather_text):
            parsed['cloud_layers'].append((amt, int(hgt) * 100 if hgt else 0))
    return parsed

def get_active_taf_forecast(taf_str, eval_dt):
    if not taf_str or taf_str == "NIL": return None
    current_rel = eval_dt.day * 24 + eval_dt.hour 
    parts = re.split(r'(?=TEMPO |BECMG |FM\d{6}|PROB\d{2} )', taf_str)
    if len(parts) == 0: return None
    active_forecast = parse_weather_string(parts[0])
    if not active_forecast: return None
    for part in parts[1:]:
        part = part.strip()
        time_match = re.search(r'\b(\d{2})(\d{2})/(\d{2})(\d{2})\b', part)
        if time_match:
            start_rel = int(time_match.group(1)) * 24 + int(time_match.group(2))
            end_rel = int(time_match.group(3)) * 24 + int(time_match.group(4))
            if end_rel < start_rel: end_rel += 31 * 24
            apply_trend = False
            if part.startswith('TEMPO') and start_rel <= current_rel <= end_rel: apply_trend = True
            elif part.startswith('BECMG') and current_rel >= start_rel: apply_trend = True 
            if apply_trend:
                trend_data = parse_weather_string(part)
                if trend_data['wind_dir'] is not None: active_forecast['wind_dir'] = trend_data['wind_dir']
                if trend_data['wind_spd'] is not None: active_forecast['wind_spd'] = trend_data['wind_spd']
                if trend_data.get('wind_spd_gust') is not None: active_forecast['wind_spd_gust'] = trend_data['wind_spd_gust']
                if trend_data['vis'] is not None: active_forecast['vis'] = trend_data['vis']
                if trend_data['vertical_vis'] is not None: active_forecast['vertical_vis'] = trend_data['vertical_vis']
                if trend_data['cloud_layers']: active_forecast['cloud_layers'] = trend_data['cloud_layers']
                if 'NSW' in part: active_forecast['weather'] = []
                elif trend_data['weather']: active_forecast['weather'] = trend_data['weather']
    return active_forecast

def evaluate_snapshot(curr_metar_str, taf_str, eval_dt, has_speci):
    l2_result = {'status': 'Tidak Diketahui', 'color': 'gray', 'reasons': ['Data tidak memadai.']}
    if curr_metar_str == "NIL": return 'gray', l2_result, None

    actual = parse_weather_string(curr_metar_str)
    forecast = get_active_taf_forecast(taf_str, eval_dt)
    if not actual: return 'gray', l2_result, None

    l2_reasons, l2_level = [], 0 
    if has_speci:
        l2_reasons.append("Laporan SPECI baru diterbitkan (Fluktuasi cuaca).")
        l2_level = 1

    if forecast:
        if isinstance(actual['wind_dir'], int) and isinstance(forecast['wind_dir'], int):
            dir_diff = abs(actual['wind_dir'] - forecast['wind_dir'])
            if dir_diff > 180: dir_diff = 360 - dir_diff
            if dir_diff >= 60 and ((actual['wind_spd'] or 0) >= 10 or (forecast['wind_spd'] or 0) >= 10):
                l2_reasons.append(f"Pergeseran Arah Angin: Aktual {actual['wind_dir']}° vs TAF {forecast['wind_dir']}° (Selisih ≥ 60° dengan kecepatan ≥ 10kt).")
                l2_level = 2
        if actual['wind_spd'] is not None and forecast['wind_spd'] is not None and abs(actual['wind_spd'] - forecast['wind_spd']) >= 10:
            l2_reasons.append(f"Kecepatan Angin: Aktual {actual['wind_spd']}kt vs TAF {forecast['wind_spd']}kt (Selisih ≥ 10kt).")
            l2_level = 2
        act_gst = actual.get('wind_spd_gust') or actual['wind_spd']
        fct_gst = forecast.get('wind_spd_gust') or forecast['wind_spd']
        if act_gst is not None and fct_gst is not None and abs(act_gst - fct_gst) >= 10 and ((actual['wind_spd'] or 0) >= 15 or (forecast['wind_spd'] or 0) >= 15):
            l2_reasons.append(f"Wind Gust Dev: Selisih hembusan (Gust) mencapai {abs(act_gst - fct_gst)}kt dengan kecepatan dasar ≥ 15kt.")
            l2_level = 2
        if (actual['wind_spd'] or 0) >= 20:
            l2_reasons.append(f"Wind Operational Threshold: Kecepatan angin aktual ({actual['wind_spd']}kt) melampaui batas aman.")
            l2_level = max(l2_level, 1)
        if actual['vis'] is not None and forecast['vis'] is not None:
            for th in [150, 350, 600, 800, 1500, 3000, 5000]:
                if (actual['vis'] < th <= forecast['vis']) or (forecast['vis'] < th <= actual['vis']):
                    l2_reasons.append(f"Visibilitas melewati threshold {th}m (Aktual: {actual['vis']}m, TAF: {forecast['vis']}m).")
                    l2_level = 2
                    break
        actual_crit = [wx for W in actual['weather'] for wx in [r'TS', r'SQ', r'FC', r'FZ', r'DS', r'SS', r'BL', r'DR', r'SH', r'RA', r'DZ', r'FG'] if re.search(wx, W)]
        forecast_crit = [wx for W in forecast['weather'] for wx in [r'TS', r'SQ', r'FC', r'FZ', r'DS', r'SS', r'BL', r'DR', r'SH', r'RA', r'DZ', r'FG'] if re.search(wx, W)]
        if set(actual_crit) != set(forecast_crit):
            l2_reasons.append(f"Cuaca Signifikan: Aktual '{', '.join(actual_crit) or 'Clear'}' vs TAF '{', '.join(forecast_crit) or 'Clear'}'.")
            l2_level = 2
        act_ceil = min([h for a, h in actual['cloud_layers'] if a in ['BKN', 'OVC']], default=None)
        fct_ceil = min([h for a, h in forecast['cloud_layers'] if a in ['BKN', 'OVC']], default=None)
        if act_ceil is not None and fct_ceil is not None:
            for th in [100, 200, 500, 1000, 1500]:
                if (act_ceil < th <= fct_ceil) or (fct_ceil < th <= act_ceil):
                    l2_reasons.append(f"Ceiling awan melewati {th}ft (Aktual: {act_ceil}ft, TAF: {fct_ceil}ft).")
                    l2_level = 2
                    break

    if l2_level == 2: l2_result = {'status': 'REKOMENDASI AMD TAF', 'color': 'red', 'reasons': l2_reasons}
    elif l2_level == 1: l2_result = {'status': 'POTENSI AMANDEMEN TAF', 'color': '#D4AC0D', 'reasons': l2_reasons}
    else: l2_result = {'status': 'Normal', 'color': 'green', 'reasons': ['Parameter aktual selaras dengan prakiraan dasar TAF.']}
    return 'red' if l2_level == 2 else ('#D4AC0D' if l2_level == 1 else 'green'), l2_result, actual['wind_dir']

# ==========================================
# 6. PEMBANGUNAN PETA & INJEKSI WEB
# ==========================================
def build_wiraavia_map(df):
    m = folium.Map(location=[-2.5, 118.0], zoom_start=5, tiles='cartodbdark_matter')
    folium.TileLayer('openstreetmap', name='Standard Maps').add_to(m)
    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satellite').add_to(m)
    folium.LayerControl().add_to(m)
    
    m.get_root().html.add_child(folium.Element('''
    <div style="position: fixed; bottom: 80px; left: 30px; width: 280px; background-color: rgba(44, 62, 80, 0.95); color: #ECF0F1; z-index:9999; font-size:13px; font-family: Arial; border: 1px solid #34495E; border-radius: 8px; padding: 15px;">
    <h4 style="margin-top:0; font-weight:bold; font-size:14px; text-align:center;">🚦 Hierarki Peringatan Dini</h4><hr style="margin:5px 0; border-top: 1px solid #7F8C8D;">
    <span style="color:green; font-size:16px;">●</span> <b>Hijau:</b> Normal<br>
    <span style="color:#F1C40F; font-size:16px;">●</span> <b style="color:#F1C40F;">Kuning:</b> SPECI & Potensi AMD TAF<br>
    <span style="color:red; font-size:16px;">●</span> <b style="color:red;">Merah:</b> Rekomendasi AMD TAF<br>
    </div>
    '''))

    features = []
    now = datetime.now(timezone.utc)
    minute_grid = 30 if now.minute >= 30 else 0
    latest_grid = now.replace(minute=minute_grid, second=0, microsecond=0)
    grid_times = [latest_grid - timedelta(minutes=30 * i) for i in range(2)]
    grid_times.reverse() 

    for index, row in df.iterrows():
        icao = row['ICAO']
        metars = get_weather_data(icao, 'metar', 45)
        specis = get_weather_data(icao, 'speci', 20)
        tafs = get_weather_data(icao, 'taf', 1)
        taf_str = tafs[0] if len(tafs) > 0 else "NIL"
        
        if not metars: continue
            
        parsed_metars = [ (extract_time_components(m), m) for m in metars if extract_time_components(m) ]
        parsed_specis = [ (extract_time_components(s), s) for s in specis if extract_time_components(s) ]

        final_color, final_reasons = 'green', []
        for grid_time in grid_times:
            curr_metar = find_closest_data_by_grid_logic(grid_time, parsed_metars)
            has_speci = any(0 <= (grid_time.hour * 60 + grid_time.minute) - (comp['hour'] * 60 + comp['minute']) <= 30 for comp, _ in parsed_specis if comp)
            c, l2_res, _ = evaluate_snapshot(curr_metar, taf_str, grid_time, has_speci)
            if grid_time == grid_times[-1]: final_color, final_reasons = c, l2_res['reasons']

        nwp_html = get_nwp_forecast(row['Lintang'], row['Bujur'], final_color, final_reasons)
        
        nwp_section = ""
        if nwp_html:
            nwp_section = f"""
            <details style="margin-top: 15px; margin-bottom: 10px; background: #ffffff; border: 1px solid #17a2b8; border-radius: 5px;">
                <summary style="padding: 8px 10px; font-size: 11px; font-weight: bold; color: #0c5460; background-color: #d1ecf1; cursor: pointer; outline: none; border-radius: 4px;">
                    📊 PERTIMBANGAN MODEL NWP (Klik untuk buka)
                </summary>
                <div style="padding: 10px; font-size: 10px; line-height: 1.5; white-space: nowrap; overflow-x: auto;">
                    {nwp_html}
                </div>
            </details>
            """

        for grid_time in grid_times:
            curr_metar = find_closest_data_by_grid_logic(grid_time, parsed_metars)
            
            target_mins = grid_time.hour * 60 + grid_time.minute
            speci_alert_str, has_speci = "NIL (Tidak ada SPECI)", False
            for comp, s_str in parsed_specis:
                data_mins = comp['hour'] * 60 + comp['minute']
                diff = target_mins - data_mins
                if diff < -720: diff += 1440
                elif diff > 720: diff -= 1440
                if 0 <= diff <= 30:
                    has_speci, speci_alert_str = True, s_str
                    break
            
            color, l2_res, wind_dir_int = evaluate_snapshot(curr_metar, taf_str, grid_time, has_speci)
            l2_html = "".join([f"<li>{r}</li>" for r in l2_res['reasons']])
            curr_comp = extract_time_components(curr_metar)
            jam_label = f"{curr_comp['hour']:02d}:{curr_comp['minute']:02d} UTC" if curr_comp else grid_time.strftime("%H:%M UTC")
            
            popup_html = f"""
            <div style="max-width: 380px; min-width: 250px; width: max-content; font-family: Arial, sans-serif;">
                <div style="background-color: {color if color != '#D4AC0D' else '#D4AC0D'}; color: {'black' if color == '#D4AC0D' else 'white'}; padding: 10px; border-radius: 5px 5px 0 0; text-align: center;">
                    <h4 style="margin: 0; font-weight: bold;">{icao} <span style="font-size:12px; font-weight:normal;">({jam_label})</span></h4>
                    <p style="margin: 5px 0 0 0; font-size: 12px;">{row['Nama_Bandara']}</p>
                </div>
                <div style="padding: 15px; background-color: #f8f9fa; border: 1px solid #ddd; border-top: none;">
                    <div style="margin-bottom: 10px; border-left: 4px solid {l2_res['color']}; padding-left: 10px;">
                        <span style="font-size: 11px; font-weight: bold; color: #555;">EVALUASI TAF AKTUAL</span><br>
                        <span style="font-size: 14px; font-weight: bold; color: {l2_res['color']};">{l2_res['status']}</span>
                        <ul style="margin: 5px 0 0 0; padding-left: 15px; font-size: 11px; color: #333;">{l2_html}</ul>
                    </div>
                    <hr style="border: 0; border-top: 1px solid #ccc; margin: 10px 0;">
                    <div style="max-height: 160px; overflow-y: auto; font-size: 11px;">
                        <p style="margin: 0 0 5px 0; color: #004085; font-weight:bold;">[ METAR ]</p>
                        <div style="background: #e9ecef; padding: 6px; border-radius: 4px; font-family: monospace; margin-bottom: 10px;">{curr_metar}</div>
                        <p style="margin: 0 0 5px 0; color: #856404; font-weight:bold;">[ SPECI ]</p>
                        <div style="background: #fff3cd; padding: 6px; border-radius: 4px; font-family: monospace; margin-bottom: 10px;">{speci_alert_str}</div>
                        <p style="margin: 0 0 5px 0; color: #155724; font-weight:bold;">[ TAF ]</p>
                        <div style="background: #d4edda; padding: 6px; border-radius: 4px; font-family: monospace; margin-bottom: 10px;">{taf_str}</div>
                    </div>
                    {nwp_section if grid_time == grid_times[-1] else ""}
                </div>
            </div>
            """
            
            features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [row['Bujur'], row['Lintang']]},
                'properties': {'time': grid_time.isoformat(), 'popup': popup_html, 'icon': 'circle',
                'iconstyle': {'fillColor': color if color != '#D4AC0D' else '#F1C40F', 'fillOpacity': 0.85, 'stroke': 'true', 'color': 'white', 'weight': 1.5, 'radius': 9}}})
            
    if not features: return None
    plugins.TimestampedGeoJson({'type': 'FeatureCollection', 'features': features}, period='PT30M', add_last_point=True, auto_play=False, loop=False, max_speed=1, time_slider_drag_update=True, duration='PT30M').add_to(m)
    return m

# ==========================================
# 7. RENDER STREAMLIT
# ==========================================
with st.spinner("⏳ Menembus jaringan BMKG & Merender Peta WiraAvia..."):
    folium_map = build_wiraavia_map(df_bandara)
    if folium_map is None:
        st.error("❌ **Data Kosong!** Silakan klik tombol 'Force Refresh' di atas.")
    else:
        map_html = folium_map.get_root().render()
        components.html(map_html, height=750, scrolling=False)
