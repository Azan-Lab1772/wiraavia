import pandas as pd
import folium
from folium import plugins
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import io
import re
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. LOAD DATA STASIUN BANDARA
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
# 2. PERSIAPAN KONEKSI API DENGAN ANTI-BLOKIR
# ==========================================
TOKEN = '37da31a5cc6f0732732a7f9c640507b2849e37a3b815b0252af2a54afc7a'
HEADERS = {
    'accept': '*/*', 
    'Authorization': f'Bearer {TOKEN}',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
}

session = requests.Session()
session.headers.update(HEADERS)
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

def get_weather_data(icao, data_type, count=45):
    url = f"https://web-aviation.bmkg.go.id/api/v1/{data_type}/{icao.lower()}"
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, list) and len(data) == 0: return []
                icao_upper = icao.upper()
                if isinstance(data, dict) and icao_upper in data:
                    weather_list = data[icao_upper]
                    if isinstance(weather_list, list) and len(weather_list) > 0:
                        return [w.get('data_text', "") for w in weather_list[:count]]
            except ValueError: pass
    except Exception: pass
    return []

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
        wx_pattern = r'\b([-+]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|IC|PE|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PO|SQ|FC|SS|DS))\b'
        parsed['weather'] = re.findall(wx_pattern, weather_text)
        if 'NSW' in weather_text: parsed['weather'] = []
        vv_match = re.search(r'\bVV(\d{3})\b', weather_text)
        if vv_match: parsed['vertical_vis'] = int(vv_match.group(1)) * 100
        cloud_matches = re.findall(r'\b(FEW|SCT|BKN|OVC|NSC|SKC|CLR)(\d{3})?(?:CB|TCU)?\b', weather_text)
        for amt, hgt in cloud_matches:
            height_ft = int(hgt) * 100 if hgt else 0
            parsed['cloud_layers'].append((amt, height_ft))
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

def evaluate_snapshot(curr_metar_str, prev_metar_str, taf_str, eval_dt, has_speci):
    l1_result = {'status': 'Tidak Diketahui', 'color': 'gray', 'reasons': ['Data tidak memadai.']}
    l2_result = {'status': 'Tidak Diketahui', 'color': 'gray', 'reasons': ['Data tidak memadai.']}
    if curr_metar_str == "NIL": return 'gray', l1_result, l2_result, None

    actual = parse_weather_string(curr_metar_str)
    actual_prev = parse_weather_string(prev_metar_str) if prev_metar_str != "NIL" else None
    forecast = get_active_taf_forecast(taf_str, eval_dt)
    if not actual: return 'gray', l1_result, l2_result, None

    l1_reasons = []
    l1_level = 0
    if actual_prev and actual['vis'] is not None and actual_prev['vis'] is not None:
        if abs(actual['vis'] - actual_prev['vis']) >= 1500:
            l1_reasons.append(f"Visibilitas bergeser tajam dari {actual_prev['vis']}m menjadi {actual['vis']}m.")
            l1_level = 1
    if l1_reasons or has_speci:
        l1_level = 1
        l1_result = {'status': 'Terdeteksi Perubahan', 'color': '#D4AC0D', 'reasons': l1_reasons or ["Perubahan parameter terekam pada laporan SPECI."]}
    else:
        l1_result = {'status': 'Stabil (Tidak Ada Lompatan)', 'color': 'green', 'reasons': ['Seluruh parameter stabil terhadap observasi sebelumnya.']}

    l2_reasons = []
    l2_level = 0 
    if forecast:
        if isinstance(actual['wind_dir'], int) and isinstance(forecast['wind_dir'], int):
            dir_diff = abs(actual['wind_dir'] - forecast['wind_dir'])
            if dir_diff > 180: dir_diff = 360 - dir_diff
            if dir_diff >= 60 and ((actual['wind_spd'] or 0) >= 10 or (forecast['wind_spd'] or 0) >= 10):
                l2_reasons.append(f"Wind Shift: Aktual {actual['wind_dir']}° vs TAF {forecast['wind_dir']}° (Selisih >= 60° dengan kecepatan angin >= 10kt).")
                l2_level = 2
        if actual['wind_spd'] is not None and forecast['wind_spd'] is not None:
            if abs(actual['wind_spd'] - forecast['wind_spd']) >= 10:
                l2_reasons.append(f"Wind Speed Dev: Aktual {actual['wind_spd']}kt vs TAF {forecast['wind_spd']}kt (Selisih >= 10kt).")
                l2_level = 2
        act_gst = actual.get('wind_spd_gust') if actual.get('wind_spd_gust') is not None else actual['wind_spd']
        fct_gst = forecast.get('wind_spd_gust') if forecast.get('wind_spd_gust') is not None else forecast['wind_spd']
        if act_gst is not None and fct_gst is not None:
            if abs(act_gst - fct_gst) >= 10 and ((actual['wind_spd'] or 0) >= 15 or (forecast['wind_spd'] or 0) >= 15):
                l2_reasons.append(f"Wind Gust Dev: Selisih hembusan (Gust) mencapai {abs(act_gst - fct_gst)}kt dengan kecepatan dasar >= 15kt.")
                l2_level = 2
        if (actual['wind_spd'] or 0) >= 20:
            l2_reasons.append(f"Wind Operational Threshold: Kecepatan angin aktual ({actual['wind_spd']}kt) melampaui batas aman komparasi.")
            l2_level = max(l2_level, 1)
        vis_thresholds = [150, 350, 600, 800, 1500, 3000, 5000]
        if actual['vis'] is not None and forecast['vis'] is not None:
            for th in vis_thresholds:
                if (actual['vis'] < th <= forecast['vis']) or (forecast['vis'] < th <= actual['vis']):
                    l2_reasons.append(f"Visibilitas melewati threshold {th}m (Aktual: {actual['vis']}m, TAF: {forecast['vis']}m).")
                    l2_level = 2
                    break
        critical_wx_patterns = [r'TS', r'SQ', r'FC', r'FZ', r'DS', r'SS', r'BL', r'DR', r'SH', r'RA', r'DZ', r'FG']
        actual_crit = [wx for W in actual['weather'] for wx in critical_wx_patterns if re.search(wx, W)]
        forecast_crit = [wx for W in forecast['weather'] for wx in critical_wx_patterns if re.search(wx, W)]
        if set(actual_crit) != set(forecast_crit):
            l2_reasons.append(f"Cuaca Signifikan: Aktual '{', '.join(actual_crit) or 'Clear'}' vs TAF '{', '.join(forecast_crit) or 'Clear'}'.")
            l2_level = 2
        cloud_thresholds = [100, 200, 500, 1000, 1500]
        act_ceil = min([h for a, h in actual['cloud_layers'] if a in ['BKN', 'OVC']], default=None)
        fct_ceil = min([h for a, h in forecast['cloud_layers'] if a in ['BKN', 'OVC']], default=None)
        if act_ceil is not None and fct_ceil is not None:
            for th in cloud_thresholds:
                if (act_ceil < th <= fct_ceil) or (fct_ceil < th <= act_ceil):
                    l2_reasons.append(f"Ceiling awan melewati {th}ft (Aktual: {act_ceil}ft, TAF: {fct_ceil}ft).")
                    l2_level = 2
                    break
        act_low_cloud = any([a in ['BKN', 'OVC'] for a, h in actual['cloud_layers'] if h < 1500])
        fct_low_cloud = any([a in ['BKN', 'OVC'] for a, h in forecast['cloud_layers'] if h < 1500])
        if act_low_cloud != fct_low_cloud:
            l2_reasons.append(f"Kategori Awan: Perubahan formasi awan tertutup (BKN/OVC) di bawah 1500ft.")
            l2_level = 2
        if actual['vertical_vis'] is not None and forecast['vertical_vis'] is not None:
            for th in [100, 200, 500, 1000]:
                if (actual['vertical_vis'] < th <= forecast['vertical_vis']) or (forecast['vertical_vis'] < th <= actual['vertical_vis']):
                    l2_reasons.append(f"Vertical Visibility: Nilai aktual {actual['vertical_vis']}ft melewati batas {th}ft.")
                    l2_level = 2
                    break
    if l2_level == 2: l2_result = {'status': 'AMD TAF Recommended', 'color': 'red', 'reasons': l2_reasons}
    elif l2_level == 1: l2_result = {'status': 'Potential TAF Mismatch', 'color': 'orange', 'reasons': l2_reasons}
    else: l2_result = {'status': 'Normal', 'color': 'green', 'reasons': ['Parameter aktual selaras dengan prakiraan dasar TAF.']}
    overall_color = 'red' if l2_level == 2 else ('orange' if l2_level == 1 else ('#D4AC0D' if l1_result['color'] == '#D4AC0D' else 'green'))
    return overall_color, l1_result, l2_result, actual['wind_dir']

def create_dynamic_webgis(df):
    m = folium.Map(location=[-2.5, 118.0], zoom_start=5, tiles='cartodbdark_matter')

    folium.TileLayer('openstreetmap', name='Standard Maps (Minimal)').add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri, Maxar, Earthstar Geographics',
        name='Satellite Imagery (Satelit Esri)'
    ).add_to(m)

    folium.LayerControl().add_to(m)
    
    # UI Judul WiraAvia - Auto updated timestamp
    update_time_str = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    
    m.get_root().html.add_child(folium.Element(f'''
    <div align="center" style="position: absolute; z-index: 9999; top: 15px; left: 50%; transform: translateX(-50%);
    background-color: rgba(44, 62, 80, 0.95); padding: 10px 25px; border-radius: 8px; 
    box-shadow: 0px 4px 6px rgba(0,0,0,0.5); border: 1px solid #34495E; font-family: Arial; text-align: center;">
        <h3 style="font-size:22px; font-weight:bold; color: #ECF0F1; margin: 0; padding: 0;">WiraAvia</h3>
        <p style="font-size:12px; font-style: italic; color: #BDC3C7; margin: 4px 0 0 0; padding: 0;">
            (Web-gis Interface for Rapid Assessment of Aviation Weather)
        </p>
        <p style="font-size:10px; color: #7F8C8D; margin: 5px 0 0 0; padding: 0;">Last Auto-Update: {update_time_str}</p>
    </div>
    '''))
    
    m.get_root().html.add_child(folium.Element('''
    <div style="position: fixed; bottom: 80px; left: 30px; width: 270px; 
    background-color: rgba(44, 62, 80, 0.95); color: #ECF0F1; z-index:9999; font-size:13px; font-family: Arial;
    border: 1px solid #34495E; border-radius: 8px; padding: 15px; box-shadow: 0px 4px 6px rgba(0,0,0,0.5);">
    <h4 style="margin-top:0; font-weight:bold; font-size:14px; text-align:center;">🚦 Hierarki Peringatan Dini</h4><hr style="margin:5px 0; border-top: 1px solid #7F8C8D;">
    <span style="color:green; font-size:16px;">●</span> <b>Hijau:</b> Normal<br>
    <span style="color:#F1C40F; font-size:16px;">●</span> <b style="color:#F1C40F;">Kuning:</b> Rapid Weather Change<br>
    <span style="color:orange; font-size:16px;">●</span> <b style="color:orange;">Orange:</b> Potential TAF Mismatch<br>
    <span style="color:red; font-size:16px;">●</span> <b style="color:red;">Merah:</b> AMD TAF Recommended<br>
    </div>
    '''))

    features = []
    now = datetime.now(timezone.utc)
    minute_grid = 30 if now.minute >= 30 else 0
    latest_grid = now.replace(minute=minute_grid, second=0, microsecond=0)
    grid_times = [latest_grid - timedelta(minutes=30 * i) for i in range(3)]
    grid_times.reverse() 

    for index, row in df.iterrows():
        icao = row['ICAO']
        metars = get_weather_data(icao, 'metar', count=45)
        specis = get_weather_data(icao, 'speci', count=20)
        tafs = get_weather_data(icao, 'taf', count=1)
        taf_str = tafs[0] if len(tafs) > 0 else "NIL"
        
        if len(metars) == 0: continue
            
        parsed_metars = []
        for metar_text_raw in metars:
            dt_comp = extract_time_components(metar_text_raw)
            if dt_comp: parsed_metars.append((dt_comp, metar_text_raw))
            
        parsed_specis = []
        for speci_text_raw in specis:
            dt_comp = extract_time_components(speci_text_raw)
            if dt_comp: parsed_specis.append((dt_comp, speci_text_raw))
            
        for grid_time in grid_times:
            curr_metar = find_closest_data_by_grid_logic(grid_time, parsed_metars)
            prev_metar = find_closest_data_by_grid_logic(grid_time - timedelta(minutes=30), parsed_metars)
            target_hhmm = grid_time.strftime("%H%M")
            has_speci = False
            speci_alert_str = "NIL (Tidak ada laporan SPECI baru pada jam ini)"
            for comp, s_str in parsed_specis:
                if comp['string_key'] == target_hhmm:
                    has_speci = True
                    speci_alert_str = s_str
                    break
            
            color, l1_res, l2_res, wind_dir_int = evaluate_snapshot(curr_metar, prev_metar, taf_str, grid_time, has_speci)
            
            l1_html = "".join([f"<li>{r}</li>" for r in l1_res['reasons']])
            l2_html = "".join([f"<li>{r}</li>" for r in l2_res['reasons']])
            waktu_lokal_str = grid_time.strftime("%d %b %Y, %H:%M UTC")

            popup_html = f"""
            <div style="width: 450px; font-family: Arial, sans-serif;">
                <div style="background-color: {color if color != '#D4AC0D' else '#D4AC0D'}; color: {'black' if color == '#D4AC0D' else 'white'}; padding: 10px; border-radius: 5px 5px 0 0; text-align: center;">
                    <h4 style="margin: 0; font-weight: bold;">{icao} <span style="font-size:12px; font-weight:normal;">({waktu_lokal_str})</span></h4>
                    <p style="margin: 5px 0 0 0; font-size: 12px;">{row['Nama_Bandara']}</p>
                </div>
                <div style="padding: 15px; background-color: #f8f9fa; border: 1px solid #ddd; border-top: none;">
                    <div style="margin-bottom: 12px; border-left: 4px solid {l1_res['color']}; padding-left: 10px;">
                        <span style="font-size: 11px; font-weight: bold; color: #555;">OBSERVASI (METAR)</span><br>
                        <span style="font-size: 14px; font-weight: bold; color: {l1_res['color'] if l1_res['color'] != '#D4AC0D' else '#9A7D0A'};">{l1_res['status']}</span>
                        <ul style="margin: 5px 0 0 0; padding-left: 15px; font-size: 11px; color: #333;">{l1_html}</ul>
                    </div>
                    <div style="margin-bottom: 15px; border-left: 4px solid {l2_res['color']}; padding-left: 10px;">
                        <span style="font-size: 11px; font-weight: bold; color: #555;">EVALUASI TAF</span><br>
                        <span style="font-size: 14px; font-weight: bold; color: {l2_res['color']};">{l2_res['status']}</span>
                        <ul style="margin: 5px 0 0 0; padding-left: 15px; font-size: 11px; color: #333;">{l2_html}</ul>
                    </div>
                    <hr style="border: 0; border-top: 1px solid #ccc; margin: 10px 0;">
                    <div style="max-height: 160px; overflow-y: auto; font-size: 11px;">
                        <p style="margin: 0 0 5px 0; color: #004085; font-weight:bold;">[ DATA METAR AKTUAL ]</p>
                        <div style="background: #e9ecef; padding: 6px; border-radius: 4px; font-family: monospace; margin-bottom: 10px;">{curr_metar}</div>
                        <p style="margin: 0 0 5px 0; color: #856404; font-weight:bold;">[ LAPORAN SPECI ]</p>
                        <div style="background: #fff3cd; padding: 6px; border-radius: 4px; font-family: monospace; margin-bottom: 10px;">{speci_alert_str}</div>
                        <p style="margin: 0 0 5px 0; color: #155724; font-weight:bold;">[ PRAKIRAAN TAF TERBARU ]</p>
                        <div style="background: #d4edda; padding: 6px; border-radius: 4px; font-family: monospace;">{taf_str}</div>
                    </div>
                </div>
            </div>
            """
            
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [row['Bujur'], row['Lintang']]
                },
                'properties': {
                    'time': grid_time.isoformat(),
                    'popup': popup_html,
                    'icon': 'circle',
                    'iconstyle': {
                        'fillColor': color if color != '#D4AC0D' else '#F1C40F',
                        'fillOpacity': 0.85,
                        'stroke': 'true',
                        'color': 'white', 
                        'weight': 1.5,
                        'radius': 9
                    }
                }
            }
            features.append(feature)

    plugins.TimestampedGeoJson(
        {'type': 'FeatureCollection', 'features': features},
        period='PT30M', add_last_point=True, auto_play=False, loop=False,
        max_speed=1, time_slider_drag_update=True, duration='PT30M' 
    ).add_to(m)
    
    return m

# ==========================================
# 6. RUN ENGINE & SAVE TO HTML (UNTUK GITHUB ACTIONS)
# ==========================================
if __name__ == "__main__":
    print("Memulai proses penarikan data BMKG dan generasi Peta WiraAvia...")
    dashboard_map = create_dynamic_webgis(df_bandara)
    # Menyimpan output dengan nama 'index.html' agar langsung menjadi beranda GitHub Pages
    dashboard_map.save("index.html")
    print("Selesai! File 'index.html' berhasil diperbarui.")