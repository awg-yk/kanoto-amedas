"""関東アメダス 1時間ごと再生 (気温=色, 風向風速=矢印)

使い方:
    python amedas_player.py                 # 既定フォルダの 時別値_*.csv を全て読み込んで再生
    python amedas_player.py --dir "フォルダ"  # フォルダ指定
    python amedas_player.py --save out.gif  # 画面表示せずGIFに保存
必要: pip install numpy matplotlib pillow(--save gif時)
"""
import argparse
import csv
import glob
import io
import math
import os
import urllib.request

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button, Slider

DEFAULT_DIR = r"C:\Users\山口　孝介\Desktop\ALL\02 自分の研究\風変わり\関東のアメダス"
PATTERN = "時別値_*.csv"
TMIN, TMAX = -10, 35
ISLAND_LAT = 34.9  # これより南(離島)は既定で非表示

for _f in ("Yu Gothic", "Meiryo", "MS Gothic", "IPAexGothic", "Noto Sans CJK JP"):
    matplotlib.rcParams["font.family"] = [_f, "sans-serif"]
    break

# 地点座標 (緯度, 経度)。概算値なので必要に応じて修正してください。
COORDS = {
    "北茨城": (36.8, 140.75),
    "大子": (36.77, 140.35),
    "常陸大宮": (36.55, 140.41),
    "日立": (36.61, 140.65),
    "笠間": (36.37, 140.28),
    "水戸": (36.38, 140.47),
    "古河": (36.2, 139.71),
    "下館": (36.3, 139.98),
    "下妻": (36.19, 139.97),
    "鉾田": (36.16, 140.51),
    "つくば（館野）": (36.06, 140.13),
    "土浦": (36.11, 140.21),
    "鹿嶋": (35.97, 140.64),
    "龍ケ崎": (35.92, 140.19),
    "那須高原": (37.02, 139.95),
    "五十里": (36.9, 139.7),
    "黒磯": (36.97, 140.06),
    "土呂部": (36.79, 139.81),
    "大田原": (36.87, 140.02),
    "奥日光（日光）": (36.73, 139.49),
    "日光東町": (36.75, 139.6),
    "塩谷": (36.71, 139.86),
    "那須烏山": (36.65, 140.12),
    "鹿沼": (36.57, 139.74),
    "宇都宮": (36.55, 139.87),
    "真岡": (36.43, 140.02),
    "佐野": (36.32, 139.58),
    "小山": (36.31, 139.8),
    "藤原": (36.85, 139.7),
    "みなかみ": (36.77, 138.96),
    "草津": (36.62, 138.6),
    "沼田": (36.64, 139.05),
    "中之条": (36.59, 138.84),
    "田代": (36.72, 138.68),
    "前橋": (36.41, 139.06),
    "桐生": (36.4, 139.33),
    "上里見": (36.42, 138.87),
    "伊勢崎": (36.32, 139.2),
    "西野牧": (36.2, 138.6),
    "館林": (36.25, 139.54),
    "神流": (36.1, 138.82),
    "寄居": (36.12, 139.19),
    "熊谷": (36.15, 139.38),
    "久喜": (36.1, 139.68),
    "秩父": (35.99, 139.07),
    "鳩山": (35.99, 139.34),
    "さいたま": (35.87, 139.6),
    "越谷": (35.9, 139.79),
    "所沢": (35.79, 139.47),
    "小河内": (35.8, 139.02),
    "青梅": (35.79, 139.26),
    "練馬": (35.74, 139.6),
    "八王子": (35.66, 139.33),
    "府中": (35.68, 139.48),
    "東京": (35.69, 139.75),
    "江戸川臨海": (35.65, 139.86),
    "羽田": (35.55, 139.78),
    "大島": (34.75, 139.36),
    "大島北ノ山": (34.78, 139.39),
    "新島": (34.37, 139.26),
    "神津島": (34.22, 139.14),
    "三宅島": (34.08, 139.53),
    "三宅坪田": (34.06, 139.55),
    "八重見ヶ原": (33.12, 139.8),
    "八丈島": (33.11, 139.79),
    "我孫子": (35.87, 140.03),
    "香取": (35.9, 140.5),
    "船橋": (35.72, 140.0),
    "佐倉": (35.72, 140.23),
    "成田": (35.77, 140.32),
    "銚子": (35.74, 140.86),
    "横芝光": (35.66, 140.5),
    "千葉": (35.6, 140.1),
    "茂原": (35.43, 140.3),
    "木更津": (35.37, 139.92),
    "牛久": (35.3, 140.1),
    "坂畑": (35.2, 140.03),
    "鴨川": (35.11, 140.1),
    "勝浦": (35.15, 140.32),
    "館山": (34.99, 139.86),
    "海老名": (35.45, 139.39),
    "横浜": (35.44, 139.65),
    "辻堂": (35.33, 139.46),
    "小田原": (35.28, 139.16),
    "三浦": (35.16, 139.63),
}

DIRS = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
        "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]


def _num(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return np.nan


def parse_csv(path):
    """気象庁形式CSV。1地点8列: 気温,品質,均質,風速,品質,風向,品質,均質"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    name_row = next(i for i, r in enumerate(rows) if r and r[0] == "" and len(r) > 8)
    names = rows[name_row]
    starts, stations = [], []
    for i in range(1, len(names)):
        if names[i] and names[i] != names[i - 1]:
            starts.append(i)
            stations.append(names[i].strip())
    times, temp, wind, wdir = [], [], [], []
    for r in rows[name_row + 1:]:
        if not r or "/" not in r[0]:
            continue
        times.append(r[0].strip())
        temp.append([_num(r[s]) for s in starts])
        wind.append([_num(r[s + 3]) for s in starts])
        d = []
        for s in starts:
            v = r[s + 5].strip() if s + 5 < len(r) else ""
            d.append(-1 if v == "静穏" else (DIRS.index(v) if v in DIRS else np.nan))
        wdir.append(d)
    return stations, times, np.array(temp), np.array(wind), np.array(wdir)


def load(folder):
    files = sorted(glob.glob(os.path.join(folder, PATTERN)))
    if not files:
        raise SystemExit(f"CSVが見つかりません: {os.path.join(folder, PATTERN)}")
    parts = [parse_csv(f) for f in files]
    stations = parts[0][0]
    T, TP, W, D = [], [], [], []
    for st, t, tp, w, d in parts:
        idx = [st.index(s) if s in st else -1 for s in stations]
        pick = lambda a: np.array([[a[r][k] if k >= 0 else np.nan for k in idx] for r in range(len(t))])
        T += t; TP.append(pick(tp)); W.append(pick(w)); D.append(pick(d))
    return stations, T, np.vstack(TP), np.vstack(W), np.vstack(D)


DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"  # 国土地理院 標高タイル


def _tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def load_terrain(lon0, lon1, lat0, lat1, z, cache_dir):
    """国土地理院DEMタイルを取得して (標高[m], extent) を返す。取得済みはキャッシュ。"""
    from PIL import Image
    cache = os.path.join(cache_dir, f"terrain_z{z}_{lon0:.2f}_{lon1:.2f}_{lat0:.2f}_{lat1:.2f}.npz")
    if os.path.exists(cache):
        d = np.load(cache)
        return d["elev"], tuple(d["extent"])
    x0, y1 = _tile_xy(lon0, lat0, z)
    x1, y0 = _tile_xy(lon1, lat1, z)
    tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    mosaic = np.full((H, W), np.nan)
    print(f"標高タイルを取得中 ({(tx1 - tx0 + 1) * (ty1 - ty0 + 1)} 枚, z={z}) ...")
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            try:
                with urllib.request.urlopen(DEM_URL.format(z=z, x=tx, y=ty), timeout=30) as r:
                    im = np.array(Image.open(io.BytesIO(r.read())).convert("RGB")).astype(np.int64)
            except Exception as e:  # 海上などタイルが無い場合は海扱い
                print("  タイルなし/失敗:", tx, ty, e)
                continue
            v = im[..., 0] * 65536 + im[..., 1] * 256 + im[..., 2]
            v = np.where(v == 2 ** 23, np.nan, np.where(v > 2 ** 23, v - 2 ** 24, v) / 100.0)  # 2^23=無効
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = v
    # メルカトル画素 -> 緯度経度の等間隔格子に再サンプリング
    nx, ny = 900, int(900 * (lat1 - lat0) / ((lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))))
    lons = np.linspace(lon0, lon1, nx)
    lats = np.linspace(lat1, lat0, ny)
    px = np.clip(((lons + 180) / 360 * 2 ** z - tx0) * 256, 0, W - 1).astype(int)
    py = np.clip(((1 - np.arcsinh(np.tan(np.radians(lats))) / math.pi) / 2 * 2 ** z - ty0) * 256, 0, H - 1).astype(int)
    elev = mosaic[np.ix_(py, px)]
    extent = (lon0, lon1, lat0, lat1)
    np.savez_compressed(cache, elev=elev, extent=np.array(extent))
    return elev, extent


def draw_terrain(ax, elev, extent):
    from matplotlib.colors import LightSource
    e = np.nan_to_num(elev, nan=0.0)
    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(e, vert_exag=8, dx=1, dy=1)
    rgb = plt.cm.terrain(np.clip(e, 0, 2500) / 2500 * 0.85 + 0.15)[..., :3] * (0.55 + 0.45 * shade[..., None])
    rgb[np.isnan(elev)] = (0.75, 0.85, 0.95)  # 海
    ax.imshow(rgb, extent=extent, origin="upper", zorder=0, aspect="auto")


def draw_coast(ax, elev, extent):
    """標高データが無い(=海・湖)所を水色、陸を薄い色にして、境界を海岸線として描く。"""
    land = ~np.isnan(elev)
    rgb = np.where(land[..., None], np.array([0.95, 0.94, 0.90]), np.array([0.80, 0.88, 0.95]))
    ax.imshow(rgb, extent=extent, origin="upper", zorder=0, aspect="auto")
    lon0, lon1, lat0, lat1 = extent
    lons = np.linspace(lon0, lon1, elev.shape[1])
    lats = np.linspace(lat1, lat0, elev.shape[0])
    ax.contour(lons, lats, land.astype(float), levels=[0.5], colors="#444", linewidths=0.8, zorder=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--islands", action="store_true", help="離島も表示")
    ap.add_argument("--interval", type=int, default=500, help="1時間あたりのms")
    ap.add_argument("--no-terrain", action="store_true", help="海岸線・地形を表示しない")
    ap.add_argument("--relief", action="store_true", help="海岸線でなく標高の陰影図にする")
    ap.add_argument("--zoom", type=int, default=9, help="標高タイルのズーム(8-11、大きいほど細かい)")
    ap.add_argument("--save", help="GIF/MP4で保存")
    a = ap.parse_args()

    stations, times, temp, wind, wdir = load(a.dir)
    keep = [i for i, s in enumerate(stations)
            if s in COORDS and (a.islands or COORDS[s][0] >= ISLAND_LAT)]
    for s in stations:
        if s not in COORDS:
            print("座標未登録(スキップ):", s)
    names = [stations[i] for i in keep]
    lat = np.array([COORDS[n][0] for n in names])
    lon = np.array([COORDS[n][1] for n in names])
    temp, wind, wdir = temp[:, keep], wind[:, keep], wdir[:, keep]

    fig, ax = plt.subplots(figsize=(11, 8))
    plt.subplots_adjust(bottom=0.15)
    ax.set_aspect(1 / np.cos(np.radians(lat.mean())))
    if not a.no_terrain:
        m = 0.15
        box = (lon.min() - m, lon.max() + m, lat.min() - m, lat.max() + m)
        try:
            elev, ext = load_terrain(*box, a.zoom, a.dir)
            (draw_terrain if a.relief else draw_coast)(ax, elev, ext)
        except Exception as e:
            print("地形の取得に失敗したため地形なしで続行:", e)
    ax.set_xlim(lon.min() - 0.15, lon.max() + 0.15)
    ax.set_ylim(lat.min() - 0.15, lat.max() + 0.15)
    ax.grid(alpha=0.3)
    ax.set_xlabel("経度"); ax.set_ylabel("緯度")
    sc = ax.scatter(lon, lat, c=temp[0], cmap="RdYlBu_r", vmin=TMIN, vmax=TMAX,
                    s=260, edgecolors="k", linewidths=0.4, zorder=2)
    fig.colorbar(sc, ax=ax, label="気温 (℃)", shrink=0.7)
    for n, x, y in zip(names, lon, lat):
        ax.annotate(n, (x, y), xytext=(8, -3), textcoords="offset points", fontsize=7)
    q = ax.quiver(lon, lat, np.zeros(len(lon)), np.zeros(len(lon)), angles="xy",
                  scale_units="xy", scale=25, width=0.003, zorder=3)
    title = ax.set_title("")

    def update(i):
        sc.set_array(np.ma.masked_invalid(temp[i]))
        ang = np.radians(wdir[i] * 22.5 + 180)  # 風が吹いていく向き
        u, v = wind[i] * np.sin(ang), wind[i] * np.cos(ang)
        bad = np.isnan(u) | (wdir[i] < 0)  # 欠測・静穏は矢印なし
        q.set_UVC(np.where(bad, 0, u), np.where(bad, 0, v))
        title.set_text(f"{times[i]}   (矢印: 風の向き, 長さ=風速)")
        fig.canvas.draw_idle()

    if a.save:
        anim = FuncAnimation(fig, lambda i: update(i), frames=len(times), interval=a.interval)
        anim.save(a.save, dpi=100)
        print("保存:", a.save)
        return

    state = {"i": 0, "playing": False}
    sax = plt.axes([0.15, 0.04, 0.6, 0.03])
    slider = Slider(sax, "時刻", 0, len(times) - 1, valinit=0, valstep=1)
    bax = plt.axes([0.8, 0.03, 0.08, 0.05])
    btn = Button(bax, "▶ / ⏸")

    def on_slide(v):
        state["i"] = int(v); update(state["i"])

    def tick(_):
        if state["playing"]:
            slider.set_val((state["i"] + 1) % len(times))

    slider.on_changed(on_slide)
    btn.on_clicked(lambda e: state.update(playing=not state["playing"]))
    anim = FuncAnimation(fig, tick, interval=a.interval, cache_frame_data=False)
    update(0)
    plt.show()


if __name__ == "__main__":
    main()
