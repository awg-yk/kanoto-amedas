"""関東アメダス 1時間ごと再生 (気温=等温線と色, 風向風速=矢印)

バージョン: v2.7 (変更時は VERSION 定数も更新)

使い方:
    python amedas_player.py                                   # 2000-01 (開始日の月末まで)
    python amedas_player.py --start 2010-07-01 --end 2010-07-31
    python amedas_player.py --dir "フォルダ"                    # 時別値フォルダの親を指定
    python amedas_player.py --save out.gif  # 画面表示せずGIFに保存
必要: pip install numpy matplotlib pillow(--save gif時)
"""
import argparse
import calendar
import csv
import datetime
import glob
import io
import math
import os
import re
import ssl
import urllib.error
import urllib.request

import matplotlib
import matplotlib.cm
import matplotlib.patches
import matplotlib.colors
import matplotlib.tri
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button, Slider, TextBox

DEFAULT_DIR = r"C:\Users\山口　孝介\Desktop\ALL\02 自分の研究\風変わり\関東のアメダス"
VERSION = "v2.7 (空欄地点の黒点も非表示)"
PATTERN = "時別値_*.csv"
FNAME_RE = re.compile(r"時別値_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})")
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
    name_row = next(i for i, r in enumerate(rows) if len(r) > 8 and r[0] == "" and r[1] != "")  # 地点名の行(空行は飛ばす)
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


def parse_time(t):
    """'2000/1/7 12:00:00' でも '2000/1/7 12:00'(Excelで保存し直したCSV)でも読めるようにする"""
    for f in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.datetime.strptime(t, f)
        except ValueError:
            pass
    raise ValueError(f"時刻を解釈できません: {t}")


def find_files(folder, start, end):
    """folder以下(サブフォルダ含む)の 時別値_開始日_終了日.csv のうち、start〜end と重なるものを返す。"""
    out = []
    for f in glob.glob(os.path.join(folder, "**", PATTERN), recursive=True):
        m = FNAME_RE.search(os.path.basename(f))
        if not m:
            continue
        d0, d1 = (datetime.date.fromisoformat(x) for x in m.groups())
        if d1 >= start and d0 <= end:
            out.append((d0, f))
    return [f for _, f in sorted(out)]


def load(folder, start, end):
    files = find_files(folder, start, end)
    if not files:
        raise FileNotFoundError(f"{start}〜{end} のCSVが見つかりません: {folder}\\{PATTERN}")
    print(f"{len(files)} ファイルを読み込み中 ...")
    parts = [parse_csv(f) for f in files]
    stations = []  # 年によって地点数が違っても対応できるよう和集合をとる
    for p in parts:
        stations += [s for s in p[0] if s not in stations]
    T, TP, W, D = [], [], [], []
    for st, t, tp, w, d in parts:
        idx = [st.index(s) if s in st else -1 for s in stations]
        pick = lambda a: np.array([[a[r][k] if k >= 0 else np.nan for k in idx] for r in range(len(t))])
        T += t; TP.append(pick(tp)); W.append(pick(w)); D.append(pick(d))
    TP, W, D = np.vstack(TP), np.vstack(W), np.vstack(D)
    # start 0:00 〜 end翌日0:00 を含めて絞る。CSVが「1:00〜24:00(翌0:00)」形式でも
    # 「0:00〜23:00」形式でも、その日のデータを取りこぼさない。
    lo = datetime.datetime.combine(start, datetime.time(0, 0))
    hi = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time(0, 0))
    keep = [i for i, t in enumerate(T) if lo <= parse_time(t) <= hi]
    return stations, [T[i] for i in keep], TP[keep], W[keep], D[keep]


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
    # Python 3.13 は証明書の検証が厳格化され、セキュリティソフト等が挟む証明書で
    # 「Missing Authority Key Identifier」となることがある。厳格フラグだけ外す(検証自体は行う)。
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    failed = 0
    print(f"標高タイルを取得中 ({(tx1 - tx0 + 1) * (ty1 - ty0 + 1)} 枚, z={z}) ...")
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            try:
                with urllib.request.urlopen(DEM_URL.format(z=z, x=tx, y=ty), timeout=30, context=ctx) as r:
                    im = np.array(Image.open(io.BytesIO(r.read())).convert("RGB")).astype(np.int64)
            except urllib.error.HTTPError as e:
                if e.code != 404:  # 404 は海上などタイル無し=海扱い
                    failed += 1
                    print("  取得失敗:", tx, ty, e)
                continue
            except Exception as e:
                failed += 1
                print("  取得失敗:", tx, ty, e)
                continue
            v = im[..., 0] * 65536 + im[..., 1] * 256 + im[..., 2]
            v = np.where(v == 2 ** 23, np.nan, np.where(v > 2 ** 23, v - 2 ** 24, v) / 100.0)  # 2^23=無効
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = v
    if failed:
        raise RuntimeError(f"{failed} 枚の取得に失敗しました(ネットワーク/証明書を確認)")
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


def set_visible(arts, flag):
    """描画物(ContourSetは古いmatplotlibだとArtistでない)の表示/非表示をまとめて切り替える"""
    for art in arts:
        if hasattr(art, "collections") and not hasattr(art, "set_visible"):
            for c in art.collections:
                c.set_visible(flag)
        else:
            art.set_visible(flag)


def draw_coast(ax, elev, extent, show_elev=True):
    """海岸線(標高データが無い所=海・湖との境界)と、灰色の標高(陰影+等高線)を描く。
    戻り値は表示切替用の描画物。気温の色を邪魔しないよう標高は無彩色。"""
    from matplotlib.colors import LightSource
    land = ~np.isnan(elev)
    lon0, lon1, lat0, lat1 = extent
    lons = np.linspace(lon0, lon1, elev.shape[1])
    lats = np.linspace(lat1, lat0, elev.shape[0])
    e = np.nan_to_num(elev, nan=0.0)
    sea = np.array([0.80, 0.88, 0.95])
    G = {"gray": []}

    base = np.zeros(elev.shape + (3,))
    base[~land] = sea
    if not show_elev:
        base[land] = (0.95, 0.94, 0.90)
        G["gray"].append(ax.imshow(base, extent=extent, origin="upper", zorder=0, aspect="auto"))
    else:
        shade = LightSource(azdeg=315, altdeg=45).hillshade(e, vert_exag=8, dx=1, dy=1)
        g = np.clip((0.97 - 0.30 * np.clip(e / 2500.0, 0, 1)) * (0.6 + 0.4 * shade), 0, 1)
        gr = base.copy()
        gr[land] = np.stack([g, g, g], axis=-1)[land]
        G["gray"].append(ax.imshow(gr, extent=extent, origin="upper", zorder=0, aspect="auto"))
        cs = ax.contour(lons, lats, np.nan_to_num(elev, nan=-1), levels=[200, 500, 1000, 1500, 2000],
                        colors="#5a4632", linewidths=0.9, zorder=0.5)  # 濃い茶色(黒の等温線と区別)
        G["gray"] += [cs, *cs.clabel(fmt="%dm", fontsize=8, inline=True)]

    ax.contour(lons, lats, land.astype(float), levels=[0.5], colors="#444", linewidths=0.8, zorder=2.5)
    return G


def despike(temp, thr, stations, times):
    """1時間だけ前後から大きく外れた気温(前の時刻と次の時刻は近い)を欠測(NaN)にする"""
    out = temp.copy()
    prev, mid, nxt = temp[:-2], temp[1:-1], temp[2:]
    with np.errstate(invalid="ignore"):
        bad = (np.abs(mid - (prev + nxt) / 2) > thr) & (np.abs(prev - nxt) <= thr / 2)
    for h, k in zip(*np.where(bad)):
        print(f"  異常値として除外: {times[h + 1]} {stations[k]} {temp[h + 1, k]}℃ (前後 {temp[h, k]}, {temp[h + 2, k]})")
    out[1:-1][bad] = np.nan
    return out


def month_range(y, m):
    first = datetime.date(y, m, 1)
    last = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    return first, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR, help="「時別値」フォルダの親(サブフォルダも検索)")
    ap.add_argument("--start", default=None, help="再生開始日 YYYY-MM-DD (省略時はフォルダ内で最も古いファイルの開始日)")
    ap.add_argument("--end", default=None, help="再生終了日 YYYY-MM-DD (省略時は開始日の月末)")
    ap.add_argument("--islands", action="store_true", help="離島も表示")
    ap.add_argument("--interval", type=int, default=500, help="1時間あたりのms")
    ap.add_argument("--no-terrain", action="store_true", help="海岸線・地形を表示しない")
    ap.add_argument("--relief", action="store_true", help="海岸線でなく標高の陰影図にする")
    ap.add_argument("--no-elev", action="store_true", help="標高(灰色の陰影・等高線)を描かず海岸線だけにする")
    ap.add_argument("--zoom", type=int, default=9, help="標高タイルのズーム(8-11、大きいほど細かい)")
    ap.add_argument("--tmin", type=float, help="色の下限(℃)。省略時は -15")
    ap.add_argument("--tmax", type=float, help="色の上限(℃)。省略時は 40")
    ap.add_argument("--smooth", type=float, default=4.0, help="等温線の平滑化の強さ(格子数、0で無し)")
    ap.add_argument("--despike", type=float, default=0.0,
                    help="気温の突発的な異常値を除く。前後の時刻の平均から この値(℃)以上ずれ、前後の値どうしは近い点を欠測にする(0で無効)")
    ap.add_argument("--step", type=float, default=2.0, help="等温線の間隔(℃)")
    ap.add_argument("--save", help="GIF/MP4で保存")
    a = ap.parse_args()

    print("amedas_player", VERSION, "/", os.path.abspath(__file__))
    if a.start:
        start = datetime.date.fromisoformat(a.start)
    else:
        firsts = [FNAME_RE.search(os.path.basename(f)) for f in
                  glob.glob(os.path.join(a.dir, "**", PATTERN), recursive=True)]
        firsts = [datetime.date.fromisoformat(m.group(1)) for m in firsts if m]
        if not firsts:
            raise SystemExit(f"CSVが見つかりません: {os.path.join(a.dir, '**', PATTERN)}")
        start = min(firsts)
        print("開始日を最も古いファイルに合わせました:", start)
    end = (datetime.date.fromisoformat(a.end) if a.end else month_range(start.year, start.month)[1])

    # 表示する地点は座標表(COORDS)で固定し、CSV側に無い地点は欠測(NaN)にする。
    # これで年月を切り替えても地点・地図の枠は変わらない。
    names = [n for n in COORDS if a.islands or COORDS[n][0] >= ISLAND_LAT]
    lat = np.array([COORDS[n][0] for n in names])
    lon = np.array([COORDS[n][1] for n in names])
    S = {}  # 現在表示中のデータ: times, temp, wind, wdir

    def read(d0, d1):
        stations, times, temp, wind, wdir = load(a.dir, d0, d1)
        if not times:
            raise FileNotFoundError(f"{d0}〜{d1} のデータ行がありません")
        for st in stations:
            if st not in COORDS:
                print("座標未登録(スキップ):", st)
        if a.despike > 0:
            temp = despike(temp, a.despike, stations, times)
        idx = [stations.index(n) if n in stations else -1 for n in names]
        pick = lambda arr: np.stack([arr[:, k] if k >= 0 else np.full(len(times), np.nan) for k in idx], axis=1)
        S.update(times=times, temp=pick(temp), wind=pick(wind), wdir=pick(wdir), start=d0, end=d1)
        print(f"{d0} 〜 {d1}: {len(times)} 時刻")

    try:
        read(start, end)
    except FileNotFoundError as e:
        raise SystemExit(str(e))

    fig, ax = plt.subplots(figsize=(12, 8))
    plt.subplots_adjust(left=0.07, right=0.78, top=0.94, bottom=0.2)
    bg = {"gray": []}
    if not a.no_terrain:
        m = 0.15
        box = (lon.min() - m, lon.max() + m, lat.min() - m, lat.max() + m)
        try:
            elev, ext = load_terrain(*box, a.zoom, os.path.dirname(os.path.abspath(__file__)))
            if a.relief:
                draw_terrain(ax, elev, ext)
            else:
                bg = draw_coast(ax, elev, ext, show_elev=not a.no_elev)
        except Exception as e:
            print("地形の取得に失敗したため地形なしで続行:", e)
    ax.set_xlim(lon.min() - 0.15, lon.max() + 0.15)
    ax.set_ylim(lat.min() - 0.15, lat.max() + 0.15)
    ax.set_aspect(1 / np.cos(np.radians(lat.mean())))
    ax.grid(alpha=0.3)
    ax.set_xlabel("経度"); ax.set_ylabel("緯度")
    # 表示のON/OFF (画面下のチェックボックス)。気温・風をOFFにすると標高(灰色)だけ見える。
    show = {"temp": True, "wind": True, "pts": True, "val": False}
    dots = ax.scatter(lon, lat, s=6, c="k", zorder=2.6)
    pts_arts = [dots]
    name_arts = []
    for n, x, y in zip(names, lon, lat):
        name_arts.append(ax.annotate(n, (x, y), xytext=(8, -3), textcoords="offset points", fontsize=7))
    missing = np.zeros(len(names), bool)  # 気温も風も空欄の地点(地点名を出さない)

    # ---- 気温: 補間した等温線(線+数値)と等温帯(色)。右側に凡例 ----
    cmap = plt.get_cmap("RdYlBu_r")
    # 色は絶対値で固定 (期間や月を変えても同じ気温は同じ色)。--tmin/--tmax で変更可。
    tmin = np.floor((a.tmin if a.tmin is not None else -15.0) / a.step) * a.step
    tmax = np.ceil((a.tmax if a.tmax is not None else 40.0) / a.step) * a.step
    st = {"levels": np.arange(tmin, tmax + a.step / 2, a.step)}
    st["norm"] = matplotlib.colors.BoundaryNorm(st["levels"], cmap.N, extend="both")
    cax = fig.add_axes([0.82, 0.52, 0.02, 0.38])
    fig.colorbar(matplotlib.cm.ScalarMappable(norm=st["norm"], cmap=cmap), cax=cax,
                 label="気温 (℃)", ticks=st["levels"][::max(1, int(round(5 / a.step)))])
    contours, labels = [], []

    # 平滑化用の格子 (約0.02度刻み)
    gx = np.linspace(lon.min() - 0.1, lon.max() + 0.1, 220)
    gy = np.linspace(lat.min() - 0.1, lat.max() + 0.1, 200)
    GX, GY = np.meshgrid(gx, gy)
    kern = np.exp(-0.5 * (np.arange(-18, 19) / max(a.smooth, 0.1)) ** 2)
    kern /= kern.sum()

    def smooth(field):
        """欠測(マスク)を無視した正規化ガウス平滑化"""
        valid = ~np.ma.getmaskarray(field)
        v = np.where(valid, np.ma.filled(field, 0.0), 0.0)

        def conv(mm):
            mm = np.apply_along_axis(lambda r: np.convolve(r, kern, mode="same"), 1, mm)
            return np.apply_along_axis(lambda c: np.convolve(c, kern, mode="same"), 0, mm)
        num, den = conv(v), conv(valid.astype(float))
        return np.ma.masked_where(~valid | (den < 1e-3), num / np.maximum(den, 1e-3))

    def clear_temp():
        for c in contours:
            try:
                c.remove()
            except Exception:
                for coll in c.collections:
                    coll.remove()
        for t in labels:
            try:
                t.remove()
            except Exception:
                pass
        contours.clear(); labels.clear()

    def draw_temp(t):
        clear_temp()
        if not show["temp"]:
            return
        ok = ~np.isnan(t)
        if ok.sum() < 4:
            return
        try:
            tri = matplotlib.tri.Triangulation(lon[ok], lat[ok])
            z = matplotlib.tri.LinearTriInterpolator(tri, t[ok])(GX, GY)  # 観測値の範囲を超えない
            if a.smooth > 0:
                z = smooth(z)
            lv, nm = st["levels"], st["norm"]
            contours.append(ax.contourf(GX, GY, z, levels=lv, cmap=cmap, norm=nm,
                                        extend="both", alpha=0.6, zorder=1))
            cl = ax.contour(GX, GY, z, levels=lv, colors="k", linewidths=0.5, alpha=0.7, zorder=2)
            contours.append(cl)
            labels.extend(cl.clabel(fmt="%g", fontsize=7, inline=True, inline_spacing=3))
        except Exception as e:
            print("等温線を描けませんでした:", e)

    # ---- 風: 矢印 ----
    q = ax.quiver(lon, lat, np.zeros(len(lon)), np.zeros(len(lon)), angles="xy",
                  scale_units="xy", scale=25, width=0.003, zorder=3)

    # ---- 風速の凡例: 右側(カラーバーの下)。本体の矢印と同じ長さ(ピクセル)で描く ----
    lax = fig.add_axes([0.80, 0.22, 0.19, 0.24])
    lax.axis("off")
    legend_state = {"px": None}

    def draw_wind_legend(_=None):
        p0 = ax.transData.transform((lon.min(), lat.min()))
        p1 = ax.transData.transform((lon.min() + 1.0, lat.min()))
        px_deg = p1[0] - p0[0]  # 経度1度あたりのピクセル数
        if legend_state["px"] is not None and abs(legend_state["px"] - px_deg) < 0.5:
            return
        legend_state["px"] = px_deg
        lax.clear(); lax.axis("off")
        bb = lax.get_window_extent()
        lax.set_xlim(0, bb.width); lax.set_ylim(0, bb.height)
        lax.text(2, bb.height - 12, "風速の凡例 (矢印の長さ)", fontsize=9, va="center")
        width_px = 0.003 * ax.get_window_extent().width
        for k, v in enumerate((1, 5, 10)):
            y = bb.height - 40 - 32 * k
            lax.quiver([8], [y], [v / 25 * px_deg], [0], angles="xy", scale_units="xy", scale=1,
                       units="dots", width=width_px, color="k")
            lax.text(8 + v / 25 * px_deg + 8, y, f"{v} m/s", fontsize=9, va="center")
        lax.text(2, 8, "矢印は風の吹く向き", fontsize=8, va="center", color="0.3")
        fig.canvas.draw_idle()

    if bg["gray"] and not a.relief:
        eax = fig.add_axes([0.82, 0.16, 0.14, 0.015])
        eax.imshow(np.linspace(0.97, 0.67, 100)[None, :].repeat(2, 0), cmap="gray", vmin=0, vmax=1,
                   aspect="auto", extent=(0, 2500, 0, 1))
        eax.set_yticks([]); eax.set_xticks([0, 500, 1000, 1500, 2000, 2500])
        eax.tick_params(labelsize=7)
        eax.set_xlabel("標高 (m)", fontsize=8)

    def apply_view():
        """チェックボックスの状態を表示に反映する"""
        set_visible(pts_arts, show["pts"])
        for k, art in enumerate(name_arts):
            art.set_visible(show["pts"] and not missing[k])
        rgba = np.zeros((len(names), 4))
        rgba[:, 3] = np.where(missing, 0.0, 1.0)  # 観測値が空欄の地点は黒点も消す
        dots.set_facecolor(rgba)
        dots.set_edgecolor(rgba)
        q.set_visible(show["wind"])
        lax.set_visible(show["wind"])
        cax.set_visible(show["temp"])

    fig.canvas.mpl_connect("draw_event", draw_wind_legend)
    title = ax.set_title("")

    def update(i):
        draw_temp(S["temp"][i])
        w, d = S["wind"][i], S["wdir"][i]
        ang = np.radians(d * 22.5 + 180)  # 風が吹いていく向き
        u, v = w * np.sin(ang), w * np.cos(ang)
        bad = np.isnan(u) | (d < 0)  # 欠測・静穏は矢印なし
        q.set_UVC(np.where(bad, 0, u), np.where(bad, 0, v))
        missing[:] = np.isnan(S["temp"][i]) & np.isnan(S["wind"][i])
        for k, (n, art) in enumerate(zip(names, name_arts)):  # 「数値」ON: 観測気温を地点名に併記
            tv = S["temp"][i][k]
            art.set_text(f"{n} {tv:.1f}" if show["val"] and not np.isnan(tv) else n)
        apply_view()
        title.set_text(f"{S['times'][i]}   [{VERSION.split()[0]}]")
        fig.canvas.draw_idle()

    if a.save:
        anim = FuncAnimation(fig, lambda i: update(i), frames=len(S["times"]), interval=a.interval)
        anim.save(a.save, dpi=100)
        print("保存:", a.save)
        return

    # ---- 操作部 ----
    # 下段: [-1年 -1月 -1日 -1時間] 時刻スライダー [+1時間 +1日 +1月 +1年] 再生/停止
    state = {"i": 0, "playing": False}
    slider = Slider(plt.axes([0.26, 0.04, 0.29, 0.03]), "時刻", 0, len(S["times"]) - 1, valinit=0, valstep=1)
    btn = Button(plt.axes([0.81, 0.03, 0.09, 0.05]), "再生/停止")
    steps = [("年", 0.010, -12), ("月", 0.062, -1), ("日", 0.114, -24), ("時間", 0.166, -1),
             ("時間", 0.585, 1), ("日", 0.637, 24), ("月", 0.689, 1), ("年", 0.741, 12)]
    step_btns = []
    for unit, x0, d in steps:
        bt = Button(plt.axes([x0, 0.03, 0.05, 0.05]), f"{'+' if d > 0 else '-'}1{unit}")
        bt.label.set_fontsize(8)
        step_btns.append((bt, unit, d))
    tb = TextBox(plt.axes([0.30, 0.10, 0.09, 0.05]), "年月 ", initial=f"{S['start'].year}-{S['start'].month:02d}")
    msg = fig.text(0.15, 0.165, "", fontsize=9, color="crimson")

    # 表示のON/OFF: ☑/☐ のトグルボタン (CheckButtonsの×印の代わり)
    toggles = {}
    for k, (key, label) in enumerate((("temp", "気温"), ("wind", "風"), ("pts", "地点"), ("val", "数値"))):
        tg = Button(plt.axes([0.715, 0.185 - 0.03 * k, 0.085, 0.026]), "", color="white", hovercolor="0.92")
        tg.label.set_fontsize(10)
        toggles[key] = (tg, label)

    def refresh_toggle(key):
        tg, label = toggles[key]
        tg.label.set_text(("☑ " if show[key] else "☐ ") + label)

    def make_toggle_cb(key):
        def cb(_):
            show[key] = not show[key]
            refresh_toggle(key)
            update(state["i"])
        return cb

    for key in toggles:
        refresh_toggle(key)
        toggles[key][0].on_clicked(make_toggle_cb(key))

    def load_month(y, m, target=None):
        """指定の年月を読み込んで表示を切り替える。CSVが無い場合は元の表示のまま。
        target(日時)があれば、その時刻に最も近いコマを表示する。"""
        try:
            d0, d1 = month_range(y, m)
        except ValueError:
            msg.set_text("年月は YYYY-MM の形式で入力してください"); fig.canvas.draw_idle(); return
        msg.set_text(f"{y}-{m:02d} を読み込み中 ..."); fig.canvas.draw()
        old = dict(S)
        try:
            read(d0, d1)
        except FileNotFoundError:
            S.update(old); msg.set_text(f"{y}-{m:02d} のCSVがありません"); fig.canvas.draw_idle(); return
        msg.set_text("")
        state["playing"] = False
        slider.valmax = len(S["times"]) - 1
        slider.ax.set_xlim(slider.valmin, slider.valmax)
        state["i"] = nearest_index(target) if target else 0
        slider.set_val(state["i"])
        tb.set_val(f"{y}-{m:02d}")
        update(state["i"])

    def nearest_index(dt):
        ts = [parse_time(t) for t in S["times"]]
        return int(np.argmin([abs((t - dt).total_seconds()) for t in ts]))

    def current_time():
        return parse_time(S["times"][state["i"]])

    def go_to(dt):
        """dt へ移動。読み込み済みの月の外なら、その月のCSVを読み込む。"""
        if S["start"] <= dt.date() <= S["end"]:
            state["playing"] = False
            slider.set_val(nearest_index(dt))
        else:
            load_month(dt.year, dt.month, target=dt)

    def move(unit, d):
        cur = current_time()
        if unit in ("年", "月"):  # 同じ日・時刻のまま月/年を動かす(月末は日を詰める)
            k = cur.year * 12 + cur.month - 1 + (d if unit == "月" else d)
            y, m = k // 12, k % 12 + 1
            day = min(cur.day, calendar.monthrange(y, m)[1])
            go_to(cur.replace(year=y, month=m, day=day))
        else:
            go_to(cur + datetime.timedelta(hours=d))

    for bt, unit, d in step_btns:
        bt.on_clicked(lambda e, unit=unit, d=d: move(unit, d))

    def on_submit(text):
        try:
            y, m = (int(x) for x in text.strip().replace("/", "-").split("-")[:2])
        except ValueError:
            msg.set_text("年月は YYYY-MM の形式で入力してください"); fig.canvas.draw_idle(); return
        if (y, m) != (S["start"].year, S["start"].month):
            load_month(y, m)

    tb.on_submit(on_submit)

    def on_slide(v):
        state["i"] = int(v); update(state["i"])

    def tick(_):
        if state["playing"]:
            slider.set_val((state["i"] + 1) % len(S["times"]))

    slider.on_changed(on_slide)
    btn.on_clicked(lambda e: state.update(playing=not state["playing"]))
    anim = FuncAnimation(fig, tick, interval=a.interval, cache_frame_data=False)
    update(0)
    plt.show()


if __name__ == "__main__":
    main()
