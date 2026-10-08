"""関東アメダス 1時間ごと再生 (気温=等温線と色, 風向風速=矢印)

バージョン: v3.20 (変更時は VERSION 定数も更新)

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
import functools
import concurrent.futures
import datetime
import glob
import io
import json
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
from matplotlib.widgets import Button, TextBox

DEFAULT_DIR = os.path.dirname(os.path.abspath(__file__))  # 既定: このスクリプトのあるフォルダ(サブフォルダも検索)
VERSION = "v3.21"
PATTERN = "時別値_*.csv"
FNAME_RE = re.compile(r"時別値_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})")
TMIN, TMAX = -10, 35
ISLANDS = {"大島", "大島北ノ山", "新島", "神津島", "三宅島", "三宅坪田", "八重見ヶ原", "八丈島"}  # --islands を付けたときだけ表示

from matplotlib import font_manager

for _f in ("Yu Gothic", "Meiryo", "MS Gothic", "IPAexGothic", "IPAGothic", "Noto Sans CJK JP", "TakaoGothic"):
    try:  # 実際に入っている最初の日本語フォントを使う
        font_manager.findfont(_f, fallback_to_default=False)
    except ValueError:
        continue
    matplotlib.rcParams["font.family"] = [_f, "sans-serif"]
    break

COORDS = {}  # 地点名 -> (緯度, 経度, 標高m)。実行時に stations.json(観測所一覧)から作る

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


@functools.lru_cache(maxsize=4096)
def parse_time(t):
    """'2000/1/7 12:00:00' でも '2000/1/7 12:00'(Excelで保存し直したCSV)でも読めるようにする"""
    for f in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.datetime.strptime(t, f)
        except ValueError:
            pass
    raise ValueError(f"時刻を解釈できません: {t}")


def scan_months(folder):
    """folder以下のCSVのファイル名から、データのある (年, 月) の集合を返す"""
    out = set()
    for f in glob.glob(os.path.join(folder, "**", PATTERN), recursive=True):
        m = FNAME_RE.search(os.path.basename(f))
        if not m:
            continue
        d0, d1 = (datetime.date.fromisoformat(x) for x in m.groups())
        k = d0.year * 12 + d0.month - 1
        while k <= d1.year * 12 + d1.month - 1:
            out.add((k // 12, k % 12 + 1))
            k += 1
    return out


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
    stations = []  # 年や地域によって地点が違っても対応できるよう和集合をとる
    for p in parts:
        stations += [s for s in p[0] if s not in stations]
    col = {s: k for k, s in enumerate(stations)}
    # start 0:00 〜 end翌日0:00 を含めて絞る。CSVが「1:00〜24:00(翌0:00)」形式でも
    # 「0:00〜23:00」形式でも、その日のデータを取りこぼさない。
    lo = datetime.datetime.combine(start, datetime.time(0, 0))
    hi = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time(0, 0))
    rows = {}  # 時刻 -> [気温, 風速, 風向] (地点ごとの配列)。同じ時刻は複数ファイルの値を合体する
    for st, t, tp, w, d in parts:
        cols = [col[s] for s in st]
        for r, ts in enumerate(t):
            dt = parse_time(ts)
            if not (lo <= dt <= hi):
                continue
            if dt not in rows:
                rows[dt] = [np.full(len(stations), np.nan) for _ in range(3)] + [ts]
            for k, src in enumerate((tp, w, d)):
                vals = src[r]
                ok = ~np.isnan(vals)
                rows[dt][k][np.array(cols)[ok]] = vals[ok]
    order = sorted(rows)
    TP = np.array([rows[k][0] for k in order]).reshape(len(order), len(stations))
    W = np.array([rows[k][1] for k in order]).reshape(len(order), len(stations))
    D = np.array([rows[k][2] for k in order]).reshape(len(order), len(stations))
    return stations, [rows[k][3] for k in order], TP, W, D


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
    nx = int(min(3000, max(900, (lon1 - lon0) * 350)))  # 約0.003度刻み(広域は上限3000)
    ny = int(nx * (lat1 - lat0) / ((lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))))
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
    G = {"gray": [], "flat": []}

    base = np.zeros(elev.shape + (3,))
    base[~land] = sea
    flat = base.copy()
    flat[land] = (0.95, 0.94, 0.90)  # 標高を消したときに見える、無地の陸と海
    G["flat"].append(ax.imshow(flat, extent=extent, origin="upper", zorder=-0.1, aspect="auto"))
    if show_elev:
        shade = LightSource(azdeg=315, altdeg=45).hillshade(e, vert_exag=8, dx=1, dy=1)
        g = np.clip((0.97 - 0.30 * np.clip(e / 2500.0, 0, 1)) * (0.6 + 0.4 * shade), 0, 1)
        gr = base.copy()
        gr[land] = np.stack([g, g, g], axis=-1)[land]
        G["gray"].append(ax.imshow(gr, extent=extent, origin="upper", zorder=0, aspect="auto"))
        cs = ax.contour(lons, lats, np.nan_to_num(elev, nan=-1), levels=[200, 500, 1000, 1500, 2000],
                        colors="#5a4632", linewidths=0.9, zorder=0.5)  # 濃い茶色(黒の等温線と区別)
        G["gray"] += [cs, *cs.clabel(fmt="%dm", fontsize=8, inline=True)]

    G["coast"] = [ax.contour(lons, lats, land.astype(float), levels=[0.5], colors="#444", linewidths=0.8, zorder=2.5)]
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


DEFAULT_VIEW = (138.0, 141.2, 33.0, 37.7)  # 既定の地図の範囲(経度0, 経度1, 緯度0, 緯度1)
REF_POINT = (36.0, 139.7)  # 同名の地点が複数あるとき、この点(関東の中心)に最も近いものを採用する
TABLE = {}  # 観測所一覧CSVの地点名 -> [(緯度, 経度, 標高, 都道府県), ...]


def load_station_table(folders):
    """「観測所一覧*.csv」(列: 地点名, 緯度, 経度, 標高(m), 都道府県 など)があれば読み込む。
    他の地域のデータを足すときは、この表に行を足すだけで座標が使える。"""
    seen = set()
    for folder in folders:  # 全国の観測所一覧(stations.json: 現役 stations と廃止 discontinuedStations)
        for f in (glob.glob(os.path.join(folder, "stations.json")) + glob.glob(os.path.join(folder, "観測所一覧*.json"))
                  + glob.glob(os.path.join(folder, "data", "stations_all.json"))):
            f = os.path.abspath(f)
            if f in seen:
                continue
            seen.add(f)
            try:
                with open(f, encoding="utf-8") as fh:
                    js = json.load(fh)
                items = (js.get("stations", []) + js.get("discontinuedStations", [])) if isinstance(js, dict) else []
            except (ValueError, OSError):
                continue
            n = 0
            for it in items:
                try:
                    d_from = datetime.date.fromisoformat(it["observedFrom"]) if it.get("observedFrom") else None
                    d_to = datetime.date.fromisoformat(it["observedTo"]) if it.get("observedTo") else None
                    TABLE.setdefault(it["name"].strip(), []).append(
                        (float(it["lat"]), float(it["lon"]), int(it.get("alt") or 0), it.get("prefecture", ""),
                         d_from, d_to, not it.get("discontinued", False)))
                    n += 1
                except (KeyError, ValueError, TypeError, AttributeError):
                    continue
            if n:
                print(f"観測所一覧: {n} 地点を読み込み ({os.path.basename(f)})")
        for f in glob.glob(os.path.join(folder, "**", "観測所一覧*.csv"), recursive=True):
            f = os.path.abspath(f)
            if f in seen:
                continue
            seen.add(f)
            for enc in ("utf-8-sig", "cp932"):
                try:
                    with open(f, encoding=enc, newline="") as fh:
                        rows = list(csv.reader(fh))
                    break
                except UnicodeDecodeError:
                    continue
            else:
                continue
            head = rows[0]
            find = lambda key: next((i for i, h in enumerate(head) if h.startswith(key)), None)
            ci, cla, clo, cel, cpr = find("地点名"), find("緯度"), find("経度"), find("標高"), find("都道府県")
            if None in (ci, cla, clo):
                print("観測所一覧の列が見つかりません(地点名/緯度/経度):", f)
                continue
            n = 0
            for r in rows[1:]:
                try:
                    TABLE.setdefault(r[ci].strip(), []).append(
                        (float(r[cla]), float(r[clo]), int(float(r[cel])) if cel is not None and r[cel] else 0,
                         r[cpr] if cpr is not None else "", None, None, True))
                    n += 1
                except (ValueError, IndexError):
                    continue
            print(f"観測所一覧: {n} 地点を読み込み ({os.path.basename(f)})")


def resolve_coord(name, when=None, verbose=False):
    """CSVの地点名から (緯度, 経度, 標高) を探す。「つくば（館野）」のような括弧付きは括弧を除いた名前でも探す。
    同じ名前が複数あるとき:
      1) まず関東の中心(REF_POINT)に最も近い場所を選び、その場所と同じ所(約15km以内=移転前後の旧地点)だけに絞る
         (例: 伏木は富山県。大分県にあった同名の廃止地点は、遠いので選ばない)
      2) その中で、データの日付(when)に観測していた旧地点があればそれを、なければ現役の地点を選ぶ"""
    base = re.sub(r"[（(].*?[）)]", "", name).strip()
    ref_lat, ref_lon = REF_POINT
    dist = lambda p, q: math.hypot(p[0] - q[0], (p[1] - q[1]) * 0.82)
    for key in (name, base):
        if key not in TABLE:
            continue
        cands = TABLE[key]
        if len(cands) > 1:
            nearest = min(cands, key=lambda v: dist(v, (ref_lat, ref_lon)))
            pool = [c for c in cands if dist(c, nearest) <= 0.15]  # 同じ場所(移転前後)
            if when is not None and len(pool) > 1:
                cover = [c for c in pool if (c[4] is None or c[4] <= when) and (c[5] is None or when <= c[5])]
                pool = [c for c in cover if not c[6]] or [c for c in cover if c[6]] or pool
            if verbose and len(pool) < len(cands):
                print(f"  同名の地点が複数あります({key}): {nearest[3]} を使います")
            c = min(pool, key=lambda v: dist(v, (ref_lat, ref_lon)))
        else:
            c = cands[0]
        return c[:3]
    return None


def scan_station_names(folder):
    """全CSVの「地点名の行」だけを読んで、データ全体に出てくる地点名の一覧を作る(年によって地点が違うため)。"""
    names, seen = [], set()
    n_files = 0
    for f in sorted(glob.glob(os.path.join(folder, "**", PATTERN), recursive=True)):
        if not FNAME_RE.search(os.path.basename(f)):
            continue
        n_files += 1
        try:
            with open(f, encoding="utf-8-sig", errors="replace") as fh:
                for _ in range(8):
                    cells = fh.readline().rstrip("\r\n").split(",")
                    if len(cells) > 8 and cells[0] == "" and cells[1] != "":
                        for n in cells[1:]:
                            n = n.strip()
                            if n and n not in seen:
                                seen.add(n); names.append(n)
                        break
        except OSError:
            continue
    return names, n_files


# 気象庁の地上天気図: 東経140度を中心とした極ステレオ投影。枠の幅Wを1とした座標で表す。
#   rho = CHART_S * tan((90-緯度)/2),  u = U0 + rho*sin(経度-140),  v = V0 + rho*cos(経度-140)
#   (u,v)は枠の左上が原点。2000年1月1日00Zと2025年12月31日12Zの図の経緯線(20-50N, 120-160E)から決めた値。
CHART_U0, CHART_V0, CHART_S = 0.5906, -0.495, 2.117
CHART_RE = re.compile(r"(?<!\d)(\d{4})[-_./]?(\d{2})[-_./]?(\d{2})[-_./ T]?(\d{2})(?:UTC|utc|[zZ])?(?!\d)")
CHART_EXT = (".png", ".gif", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def index_charts(folder):
    """天気図フォルダ(サブフォルダ含む)のファイル名から 時刻(UTC) -> ファイル の対応表を作る。
    ファイル名に 年月日+時(例: 2000010100 / 2000-01-01_00z / 2000.01.01.00UTC)が入っていれば読める。"""
    idx = {}
    if not os.path.isdir(folder):
        return idx
    for root, _, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(CHART_EXT):
                continue
            m = None
            for cand in (fn, os.path.join(os.path.relpath(root, folder), fn)):
                m = CHART_RE.search(cand)
                if m:
                    break
            if not m:
                continue
            try:
                key = datetime.datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]))
            except ValueError:
                continue
            path = os.path.join(root, fn)
            if key not in idx or fn.lower().endswith(".png"):
                idx[key] = path
    return idx


def chart_frame(arr):
    """画像から天気図の枠(黒い長方形)を見つける。戻り値 (左, 右, 上, 下) の画素位置。"""
    dark = arr.min(axis=2) < 110
    cc, rc = dark.sum(axis=0), dark.sum(axis=1)
    cols = np.where(cc > 0.6 * cc.max())[0]
    rows = np.where(rc > 0.6 * rc.max())[0]
    return cols.min(), cols.max(), rows.min(), rows.max()


_chart_geo = {}  # (枠, 画像サイズ, 範囲) -> 変換の座標と重み。天気図ごとに作り直さない


def chart_overlay(path, extent, alpha):
    """天気図を緯度経度の格子(extent=(経度0,経度1,緯度0,緯度1))に変形し、白を透明にしたRGBAを返す。"""
    from PIL import Image
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    xl, xr, yt, yb = chart_frame(arr)
    key = (int(xl), int(xr), int(yt), int(yb), arr.shape, tuple(extent))
    geo = _chart_geo.get(key)
    if geo is None:
        W = float(xr - xl)
        lon0, lon1, lat0, lat1 = extent
        nx = int(min(1100, max(600, (lon1 - lon0) * 300)))
        ny = int(nx * (lat1 - lat0) / ((lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))))
        LO, LA = np.meshgrid(np.linspace(lon0, lon1, nx), np.linspace(lat1, lat0, ny))
        rho = CHART_S * np.tan(np.radians((90 - LA) / 2))
        dl = np.radians(LO - 140.0)
        px = xl + (CHART_U0 + rho * np.sin(dl)) * W
        py = yt + (CHART_V0 + rho * np.cos(dl)) * W
        inside = (px >= xl) & (px <= xr) & (py >= yt) & (py <= yb)
        x0 = np.clip(np.floor(px).astype(int), 0, arr.shape[1] - 2)
        y0 = np.clip(np.floor(py).astype(int), 0, arr.shape[0] - 2)
        fx, fy = (px - x0).astype(np.float32), (py - y0).astype(np.float32)
        geo = (x0, y0, fx, fy, inside)
        _chart_geo.clear()
        _chart_geo[key] = geo
    x0, y0, fx, fy, inside = geo
    m = arr.min(axis=2)  # 白さ(白=255)だけを先に双一次補間(色は後で)
    w00, w10, w01, w11 = (1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy
    def samp(a2):
        return a2[y0, x0] * w00 + a2[y0, x0 + 1] * w10 + a2[y0 + 1, x0] * w01 + a2[y0 + 1, x0 + 1] * w11
    rgb = np.dstack([samp(arr[..., c]) for c in range(3)])
    dark = 1.0 - samp(m) / 255.0  # 白=0(透明) 線=濃いほど不透明
    a = np.clip(dark * 1.6, 0, 1) * alpha * inside
    return np.dstack([rgb / 255.0, a]).astype(np.float32)


# ---- ウィンドプロファイラ (BUFR電文。1ファイル=複数局×直近1時間(10分おき6時刻)×高さ別の風) ----
WP_RE = re.compile(r"(IUP[A-Z]\d{2})(?:_?[A-Z]{4}_?)?(\d{2})(\d{2})(\d{2})")
WP_HEIGHTS = [500, 1000, 1500, 2000, 3000, 4000, 5000]  # 表示する高さ(m, 局の標高からの高さ)
_wp = {"decoder": None, "failed": False, "days": {}, "files": {}}


def find_wp_dir(base):
    """スクリプトと同じ階層から、名前に「プロファイラ」を含むフォルダを探す
    (「ウィンド」「ウインド」など表記の違いがあっても見つかるようにする)"""
    try:
        for name in sorted(os.listdir(base)):
            if "プロファイラ" in name and os.path.isdir(os.path.join(base, name)):
                return os.path.join(base, name)
    except OSError:
        pass
    return os.path.join(base, "ウィンドプロファイラー")


def wp_decoder():
    """pybufrkit(BUFRの純Python解読ライブラリ)を必要になったときだけ読み込む"""
    if _wp["decoder"] is None and not _wp["failed"]:
        try:
            import logging
            logging.getLogger("pybufrkit").setLevel(logging.ERROR)
            from pybufrkit.decoder import Decoder
            _wp["decoder"] = Decoder()
        except ImportError:
            _wp["failed"] = True
            print("ウィンドプロファイラの表示には pybufrkit が必要です: py -m pip install pybufrkit")
    return _wp["decoder"]


def wp_list_day(folder, day):
    """folder/年/月/日/ にあるファイルを (ファイル名の時刻[UTC], 種別, パス) の一覧にする"""
    if (folder, day) in _wp["days"]:
        return _wp["days"][(folder, day)]
    out = []
    for sub in (f"{day.year:04d}/{day.month:02d}/{day.day:02d}", f"{day.year}/{day.month}/{day.day}"):
        d = os.path.join(folder, *sub.split("/"))
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                m = WP_RE.search(fn)
                if not m:
                    continue
                dd, hh, mm = int(m[2]), int(m[3]), int(m[4])
                for off in (0, -1, 1):  # ファイル名の日(dd)は、フォルダの日の前後のこともある
                    base = day + datetime.timedelta(days=off)
                    if base.day == dd:
                        try:
                            out.append((datetime.datetime(base.year, base.month, base.day, hh, mm), m[1],
                                        os.path.join(root, fn)))
                        except ValueError:
                            pass
                        break
        break
    _wp["days"][(folder, day)] = out
    return out


def wp_decode(path):
    """1ファイルを解読して局ごとのデータにする。
    戻り値: [{"id","lat","lon","obs":{観測時刻(UTC): [(高さ, 東西風u, 南北風v), ...]}}, ...]"""
    if path in _wp["files"]:
        return _wp["files"][path]
    dec = wp_decoder()
    stations = []
    if dec is not None:
        data = open(path, "rb").read()
        pos = 0
        while True:
            i = data.find(b"BUFR", pos)
            if i < 0:
                break
            n = int.from_bytes(data[i + 4:i + 7], "big")
            try:
                msg = dec.process(data[i:i + n])
                td = msg.template_data.value
                for descs, vals in zip(td.decoded_descriptors_all_subsets, td.decoded_values_all_subsets):
                    st, tp, obs, lev = {"obs": {}}, {}, None, None
                    for d, v in zip(descs, vals):
                        k = str(d.id).lstrip("0")
                        if k == "1001":
                            blk = v
                        elif k == "1002":
                            st["id"] = f"{blk:02d}{v:03d}" if v is not None and blk is not None else "?"
                        elif k in ("5001", "5002"):
                            st["lat"] = v
                        elif k in ("6001", "6002"):
                            st["lon"] = v
                        elif k in ("4001", "4002", "4003", "4004"):
                            tp[k] = v
                        elif k == "4005":  # 分 = 1つの観測時刻の始まり
                            try:  # 24:00(翌日0:00)と書かれていても読めるよう、日付に時間・分を足して作る
                                t = (datetime.datetime(tp["4001"], tp["4002"], tp["4003"])
                                     + datetime.timedelta(hours=tp["4004"], minutes=v))
                                obs = st["obs"].setdefault(t, [])
                            except (KeyError, TypeError, ValueError):
                                obs = None
                        elif k == "7006" and obs is not None:  # 局からの高さ = 新しい層
                            lev = [v, None, None]
                            obs.append(lev)
                        elif k == "11003" and lev is not None:
                            lev[1] = v
                        elif k == "11004" and lev is not None:
                            lev[2] = v
                    if st.get("lat") is not None and st.get("lon") is not None:
                        stations.append(st)
            except Exception:
                pass
            pos = i + max(n, 4)
    _wp["files"][path] = stations
    return stations


def wp_winds(folder, utc, extent, height):
    """時刻utc(きっかり)の、extent内の局の「heightメートルに最も近い層」の風。[(lon, lat, u, v), ...]"""
    cands = []
    for off in (-1, 0, 1):  # 日付の境目(0:00)のファイルは、前後の日のフォルダにあることもある
        day = utc.date() + datetime.timedelta(days=off)
        cands += [c for c in wp_list_day(folder, day) if utc <= c[0] <= utc + datetime.timedelta(minutes=50)]
    out, seen = [], set()
    lon0, lon1, lat0, lat1 = extent
    if _wp.get("debug"):  # --wp-debug: どのファイルを見て、どの時刻の観測が入っていたかを表示
        print(f"[wp] {utc:%Y-%m-%d %H:%M}UTC 候補ファイル {len(cands)} 個")
        for ft, ty, path in sorted(cands):
            sts = wp_decode(path)
            ts = sorted({t for st in sts for t in st["obs"]})
            print(f"[wp]   {os.path.basename(path)}  局{len(sts)}  観測 {ts[0]:%d %H:%M}〜{ts[-1]:%d %H:%M}" if ts else
                  f"[wp]   {os.path.basename(path)}  局{len(sts)}  観測時刻なし")
    for _, _, path in sorted(cands):
        for st in wp_decode(path):
            if st["id"] in seen or not (lon0 <= st["lon"] <= lon1 and lat0 <= st["lat"] <= lat1):
                continue
            levels = [l for l in st["obs"].get(utc, []) if None not in l]
            if not levels:
                continue
            h, u, v = min(levels, key=lambda l: abs(l[0] - height))
            if abs(h - height) <= 200:
                out.append((st["lon"], st["lat"], u, v))
                seen.add(st["id"])
    return out


def chart_thumbnail(path, width=520):
    """元の天気図から枠の内側だけを切り出して縮小した画像(右上の小さな表示用)"""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    xl, xr, yt, yb = chart_frame(np.asarray(img))
    img = img.crop((int(xl), int(yt), int(xr) + 1, int(yb) + 1))
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)), Image.LANCZOS)
    return np.asarray(img)


def month_range(y, m):
    first = datetime.date(y, m, 1)
    last = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    return first, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR, help="「時別値」フォルダの親(サブフォルダも検索)")
    ap.add_argument("--start", default=None, help="再生開始日 YYYY-MM-DD (省略時はフォルダ内で最も古いファイルの開始日)")
    ap.add_argument("--end", default=None, help="再生終了日 YYYY-MM-DD (省略時は開始日の月末)")
    ap.add_argument("--islands", action="store_true", help="(既定でオンのため不要) 離島も表示")
    ap.add_argument("--no-islands", action="store_true", help="離島(大島・三宅島・八丈島など)を表示しない")
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
    ap.add_argument("--reach", type=float, default=1.0,
                    help="観測地点からこの距離(度, 約1度=100km)より遠い所は気温を塗らない。0で無効")
    ap.add_argument("--chart-dir", default=None, help="天気図フォルダ(省略時はスクリプトと同じ場所の「天気図」)")
    ap.add_argument("--chart-alpha", type=float, default=0.5, help="天気図の不透明度(0-1)。既定0.5")
    ap.add_argument("--no-chart", action="store_true", help="天気図を重ねない")
    ap.add_argument("--wp-dir", default=None, help="ウィンドプロファイラのフォルダ(省略時はスクリプトと同じ場所の、名前に「プロファイラ」を含むフォルダ)")
    ap.add_argument("--no-wp", action="store_true", help="ウィンドプロファイラを重ねない")
    ap.add_argument("--wp-debug", action="store_true", help="ウィンドプロファイラの読み込み状況を表示(原因調べ用)")
    ap.add_argument("--extent", type=float, nargs=4, metavar=("経度0", "経度1", "緯度0", "緯度1"),
                    help="地図に描く範囲(度)。省略時は関東地方を中心にした範囲(東北南部・中部東部の一部を含む)")
    ap.add_argument("--all-area", action="store_true", help="範囲を決めず、読み込んだ地点が全部入る範囲で描く")
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
    load_station_table([a.dir, os.path.dirname(os.path.abspath(__file__))])
    if not TABLE:
        raise SystemExit("観測所一覧(stations.json)が見つかりません。amedas_player.py と同じフォルダに置いてください。")
    try:
        first = load(a.dir, start, end)
    except FileNotFoundError as e:
        raise SystemExit(str(e))
    all_names, n_files = scan_station_names(a.dir)  # 全期間に出てくる地点(年が違っても地図の地点を固定できる)
    all_names += [n for n in first[0] if n not in all_names]
    print(f"地点名: {len(all_names)} 件 (CSV {n_files} ファイルから)")
    unresolved = []
    for st_name in all_names:
        c = resolve_coord(st_name, start, verbose=True)
        if c:
            COORDS[st_name] = c
        else:
            unresolved.append(st_name)
    if unresolved:
        print(f"座標未登録(地図に出しません) {len(unresolved)} 地点: " + "、".join(unresolved))
        todo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "観測所一覧_不足.csv")
        with open(todo, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["地点名", "緯度", "経度", "標高(m)", "都道府県"])
            for n in unresolved:
                w.writerow([n, "", "", "", ""])
        print(f"→ {os.path.basename(todo)} に地点名を書き出しました。緯度・経度を入れて「観測所一覧.csv」に足してください")
    names = [n for n in all_names if n in COORDS and (not a.no_islands or n not in ISLANDS)]
    # 地図に描く四角い範囲: 既定は関東地方を中心に、東北南部(福島県など)・中部東部(新潟・長野・山梨・静岡)の一部が入る範囲
    if a.extent:
        view = tuple(a.extent)
    elif a.all_area:
        view = (min(COORDS[n][1] for n in names) - 0.15, max(COORDS[n][1] for n in names) + 0.15,
                min(COORDS[n][0] for n in names) - 0.15, max(COORDS[n][0] for n in names) + 0.15)
    else:
        view = (DEFAULT_VIEW[0], DEFAULT_VIEW[1], DEFAULT_VIEW[2] if not a.no_islands else 34.8, DEFAULT_VIEW[3])
    # 範囲の外側に少し離れた地点も補間には使う(範囲の端でも気温の分布が途切れないように)。表示は範囲の中だけ。
    mg = 0.6
    names = [n for n in names if view[0] - mg <= COORDS[n][1] <= view[1] + mg and view[2] - mg <= COORDS[n][0] <= view[3] + mg]
    print(f"地図の範囲: 東経{view[0]:.1f}〜{view[1]:.1f}度, 北緯{view[2]:.1f}〜{view[3]:.1f}度  (地点 {len(names)} 件)")
    lat = np.array([COORDS[n][0] for n in names])
    lon = np.array([COORDS[n][1] for n in names])
    first_used = {}
    pos_hooks = []  # 月が変わったとき、地点の位置を更新する関数(あとで登録)
    S = {}  # 現在表示中のデータ: times, temp, wind, wdir

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    month_cache = {}  # (月初, 月末) -> 読み込み(予約)結果。前後の月を先に裏で読んでおく

    def fetch(d0, d1):
        if (d0, d1) not in month_cache:
            if len(month_cache) >= 4:
                month_cache.pop(next(iter(month_cache)))
            month_cache[(d0, d1)] = pool.submit(load, a.dir, d0, d1)
        return month_cache[(d0, d1)]

    def prefetch(d0):
        for k in (1, -1):  # 次の月、前の月
            y, m = divmod(d0.year * 12 + d0.month - 1 + k, 12)
            try:
                r = month_range(y, m + 1)
            except ValueError:
                continue
            if find_files(a.dir, *r):
                fetch(*r)

    def read(d0, d1):
        if (d0, d1) == (start, end) and "used" not in first_used:
            stations, times, temp, wind, wdir = first
        else:
            stations, times, temp, wind, wdir = fetch(d0, d1).result()
        first_used["used"] = True
        if not times:
            raise FileNotFoundError(f"{d0}〜{d1} のデータ行がありません")
        if a.despike > 0:
            temp = despike(temp, a.despike, stations, times)
        idx = [stations.index(n) if n in stations else -1 for n in names]
        pick = lambda arr: np.stack([arr[:, k] if k >= 0 else np.full(len(times), np.nan) for k in idx], axis=1)
        S.update(times=times, temp=pick(temp), wind=pick(wind), wdir=pick(wdir), start=d0, end=d1)
        for fn in pos_hooks:
            fn(d0)
        print(f"{d0} 〜 {d1}: {len(times)} 時刻")
        prefetch(d0)

    try:
        read(start, end)
    except FileNotFoundError as e:
        raise SystemExit(str(e))

    fig, ax = plt.subplots(figsize=(12, 8))
    # 軽量化: 地形・文字などは1回だけ描き、気温の色分け・矢印・地点名・天気図など動く部分だけを描き直す(blitting)。
    # 動画保存(--save)や対応しない環境では使わず、毎回全体を描く。
    use_blit = (not a.save) and getattr(fig.canvas, "supports_blit", False)
    persist_arts, frame_arts = [], []  # 動く部品: 常に存在するもの / コマごとに作り直すもの
    blit = {"bg": None, "ready": False}
    ctl = {}

    def animate(arts):
        """動く部品に登録する(通常の全体描画からは除かれ、コマごとに描き直される)"""
        flat = []
        for art in arts:
            if hasattr(art, "collections") and not hasattr(art, "set_animated"):
                flat += list(art.collections)  # 古いmatplotlibのContourSet
            else:
                flat.append(art)
        if use_blit:
            for art in flat:
                art.set_animated(True)
        return flat

    dims = {}  # 凡例ごとの「オフのとき薄くするカバー」

    def make_dim(axx, x, y, w, h, transform=None):
        r = matplotlib.patches.Rectangle((x, y), w, h, transform=transform or axx.transAxes, fc="white", ec="none",
                                         alpha=0.75, zorder=20, clip_on=False)
        axx.add_artist(r)
        r.set_visible(False)
        return r

    def draw_dynamic():
        for art in sorted(persist_arts + frame_arts, key=lambda x: x.get_zorder()):
            ax.draw_artist(art)

    def on_full_draw(_event):
        if use_blit and blit["ready"]:
            blit["bg"] = fig.canvas.copy_from_bbox(fig.bbox)
            draw_dynamic()

    fig.canvas.mpl_connect("draw_event", on_full_draw)

    def refresh(full=False):
        """full=True: 全体を描き直す(ボタンの文字が変わったとき等)。False: 動く部品だけ描き直す"""
        if not (use_blit and blit["ready"]) or full or blit["bg"] is None:
            fig.canvas.draw_idle()
            return
        fig.canvas.restore_region(blit["bg"])
        draw_dynamic()
        fig.canvas.blit(fig.bbox)
        fig.canvas.flush_events()

    plt.subplots_adjust(left=0.27, right=0.70, top=0.94, bottom=0.2)  # 左: 元の天気図 / 中央: 地図 / 右: 凡例(上から 気温・風速・標高)
    bg = {"gray": [], "coast": [], "flat": []}
    if not a.no_terrain:
        m = 0.15
        box = (view[0] - m, view[1] + m, view[2] - m, view[3] + m)
        try:
            z = a.zoom
            while z > 4:  # 広域ではタイルが多すぎるので、60枚以下になるまでズームを下げる
                x0, y1 = _tile_xy(box[0], box[2], z)
                x1, y0 = _tile_xy(box[1], box[3], z)
                if (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1) <= 60:
                    break
                z -= 1
            if z != a.zoom:
                print(f"範囲が広いので標高タイルのズームを {a.zoom} → {z} に下げました")
            elev, ext = load_terrain(*box, z, os.path.dirname(os.path.abspath(__file__)))
            if a.relief:
                draw_terrain(ax, elev, ext)
            else:
                bg = draw_coast(ax, elev, ext, show_elev=not a.no_elev)
                persist_arts.extend(animate(bg.get("coast", [])))  # 海岸線は気温の色の上に重ねる
        except Exception as e:
            print("地形の取得に失敗したため地形なしで続行:", e)
    ax.set_xlim(view[0], view[1])
    ax.set_ylim(view[2], view[3])
    geo_aspect = 1 / np.cos(np.radians((view[2] + view[3]) / 2))  # 緯度経度を実際の距離の比に合わせる
    ax.set_aspect(geo_aspect)
    ax.grid(alpha=0.3)
    ax.set_xlabel("経度"); ax.set_ylabel("緯度")
    # 表示のON/OFF (画面下のチェックボックス)。気温・風をOFFにすると標高(灰色)だけ見える。
    show = {"temp": True, "wind": True, "pts": True, "val": False, "chart": True, "wp": True, "elev": True}
    wp_dir = a.wp_dir or find_wp_dir(os.path.dirname(os.path.abspath(__file__)))
    use_wp = (not a.no_wp) and os.path.isdir(wp_dir)
    if not a.no_wp:
        print("ウィンドプロファイラ:", wp_dir if use_wp else f"フォルダがありません(重ねません): {wp_dir}")
    wp_state = {"height": 1000, "q": None, "mk": None}
    _wp["debug"] = a.wp_debug

    # ---- 天気図: 00Z/12Z (日本時間の9:00/21:00)の時刻にだけ、緯度経度に変形して半透明で重ねる ----
    chart_dir = a.chart_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "天気図")
    chart_idx = {} if a.no_chart else index_charts(chart_dir)
    if not a.no_chart:
        if chart_idx:
            print(f"天気図: {len(chart_idx)} 枚 ({min(chart_idx):%Y-%m-%d} 〜 {max(chart_idx):%Y-%m-%d}) {chart_dir}")
        else:
            print(f"天気図が見つかりません(重ねません): {chart_dir}  ※ファイル名に年月日+時(例 2000010100)が必要です")
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    chart_im = ax.imshow(np.zeros((2, 2, 4)), extent=(xlim[0], xlim[1], ylim[0], ylim[1]), origin="upper",
                         zorder=2.2, aspect=geo_aspect)  # "auto" にすると地図が横に伸びる
    chart_im.set_visible(False)
    ax.set_xlim(xlim); ax.set_ylim(ylim)
    ax.set_aspect(geo_aspect)
    persist_arts.extend(animate([chart_im]))
    # 右上: 拡大していない元の天気図(小さく)。天気図のある時刻だけ表示する
    iax = fig.add_axes([0.02, 0.63, 0.22, 0.31])  # 左上: 拡大していない元の天気図(地図の上端にそろえる)
    im_in = iax.imshow(np.zeros((2, 2, 3)), aspect="equal")
    im_in.set_visible(False)
    iax.set_xticks([]); iax.set_yticks([])
    for sp in iax.spines.values():  # 点線の枠(画像が出ていなくても、クリックする場所が分かるように)
        sp.set_linestyle("--"); sp.set_edgecolor("0.65")
    ph = iax.text(0.5, 0.5, "天気図", transform=iax.transAxes, ha="center", va="center", fontsize=10, color="0.45")
    dims["chart"] = make_dim(iax, 0, 0, 1, 1)
    persist_arts.extend(animate([im_in, ph]))
    inset_state = {"path": None}
    chart_cache = {}
    dots = ax.scatter(lon, lat, s=6, c="k", zorder=2.6)
    pts_arts = [dots]
    name_arts = []
    for n, x, y in zip(names, lon, lat):
        name_arts.append(ax.annotate(n, (x, y), xytext=(8, -3), textcoords="offset points", fontsize=7))
    missing = np.zeros(len(names), bool)  # 気温も風も空欄の地点(地点名を出さない)
    persist_arts.extend(animate([dots] + name_arts))

    # ---- 気温: 補間した等温線(線+数値)と等温帯(色)。右側に凡例 ----
    cmap = plt.get_cmap("RdYlBu_r")
    # 色は絶対値で固定 (期間や月を変えても同じ気温は同じ色)。--tmin/--tmax で変更可。
    tmin = np.floor((a.tmin if a.tmin is not None else -15.0) / a.step) * a.step
    tmax = np.ceil((a.tmax if a.tmax is not None else 40.0) / a.step) * a.step
    st = {"levels": np.arange(tmin, tmax + a.step / 2, a.step)}
    st["norm"] = matplotlib.colors.BoundaryNorm(st["levels"], cmap.N, extend="both")
    cax = fig.add_axes([0.76, 0.52, 0.02, 0.42])  # 右の列(1番目): 気温のカラーバー
    dims["temp"] = make_dim(cax, -1.0, -0.04, 8.0, 1.08)  # カラーバーと目盛り・見出しを覆う
    fig.colorbar(matplotlib.cm.ScalarMappable(norm=st["norm"], cmap=cmap), cax=cax,
                 label="気温 (℃)", ticks=st["levels"][::max(1, int(round(5 / a.step)))])
    contours, labels = [], []

    # 平滑化用の格子 (約0.02度刻み)
    gstep = max(0.0125, max(view[1] - view[0], view[3] - view[2]) / 700)  # 度/格子
    gx = np.linspace(view[0] - 0.1, view[1] + 0.1, int((view[1] - view[0] + 0.2) / gstep) + 1)
    gy = np.linspace(view[2] - 0.1, view[3] + 0.1, int((view[3] - view[2] + 0.2) / gstep) + 1)
    GX, GY = np.meshgrid(gx, gy)
    sig = max(a.smooth, 0.1) * 0.011 / gstep  # 関東(0.011度/格子)と同じ強さになるよう度に換算
    kk = int(3 * sig) + 1
    kern = np.exp(-0.5 * (np.arange(-kk, kk + 1) / sig) ** 2)
    kern /= kern.sum()

    def update_positions(when):
        """移転した観測所は、データの日付に合う地点の位置に直す(stations.jsonの観測期間を使う)"""
        moved = 0
        for k, n in enumerate(names):
            c = resolve_coord(n, when)
            if c and (abs(c[0] - lat[k]) > 1e-6 or abs(c[1] - lon[k]) > 1e-6):
                lat[k], lon[k] = c[0], c[1]
                moved += 1
        if moved:
            dots.set_offsets(np.column_stack([lon, lat]))
            for art, x, y in zip(name_arts, lon, lat):
                art.xy = (x, y)
            interp_cache.clear()
            print(f"{when:%Y-%m}: 移転・廃止前の地点位置に {moved} 地点を更新")

    def conv_axis(arr, axis):
        """ガウスカーネルとの畳み込み(端は0埋め)。ずらして足し合わせるだけなので速い"""
        out = np.zeros_like(arr)
        n = arr.shape[axis]
        for k, w in zip(range(-kk, kk + 1), kern):
            if w < 1e-6 or abs(k) >= n:
                continue
            src, dst = [slice(None)] * 2, [slice(None)] * 2
            if k >= 0:
                src[axis], dst[axis] = slice(k, n), slice(0, n - k)
            else:
                src[axis], dst[axis] = slice(0, n + k), slice(-k, n)
            out[tuple(dst)] += w * arr[tuple(src)]
        return out

    interp_cache = {}  # 気温がある地点の組み合わせごとに、補間の重み・マスク・平滑化の分母を保存
    pos_hooks.append(update_positions)

    def interp_geom(ok):
        key = ok.tobytes()
        g = interp_cache.get(key)
        if g is None:
            if len(interp_cache) >= 12:
                interp_cache.clear()
            lo, la = lon[ok], lat[ok]
            tri = matplotlib.tri.Triangulation(lo, la)
            idx = tri.get_trifinder()(GX, GY)
            inside = idx >= 0
            tris = tri.triangles[idx[inside]]
            x, y = lo[tris], la[tris]
            px, py = GX[inside], GY[inside]
            det = (y[:, 1] - y[:, 2]) * (x[:, 0] - x[:, 2]) + (x[:, 2] - x[:, 1]) * (y[:, 0] - y[:, 2])
            det = np.where(det == 0, 1.0, det)
            l1 = ((y[:, 1] - y[:, 2]) * (px - x[:, 2]) + (x[:, 2] - x[:, 1]) * (py - y[:, 2])) / det
            l2 = ((y[:, 2] - y[:, 0]) * (px - x[:, 2]) + (x[:, 0] - x[:, 2]) * (py - y[:, 2])) / det
            bary = np.stack([l1, l2, 1 - l1 - l2], axis=1)  # 重心座標(観測値の範囲を超えない補間)
            mask = ~inside
            if a.reach > 0:  # 最も近い観測地点から遠い格子は塗らない
                coslat = np.cos(np.radians((view[2] + view[3]) / 2))
                d2 = np.full(GX.shape, np.inf)
                wx, wy = int(a.reach / (gstep * coslat)) + 2, int(a.reach / gstep) + 2
                for x0, y0 in zip(lo, la):
                    ix, iy = int((x0 - gx[0]) / gstep), int((y0 - gy[0]) / gstep)
                    sx = slice(max(ix - wx, 0), ix + wx + 1)
                    sy = slice(max(iy - wy, 0), iy + wy + 1)
                    d2[sy, sx] = np.minimum(d2[sy, sx], ((GX[sy, sx] - x0) * coslat) ** 2 + (GY[sy, sx] - y0) ** 2)
                mask = mask | (d2 > a.reach ** 2)
            den = None
            if a.smooth > 0:
                den = conv_axis(conv_axis((~mask).astype(float), 1), 0)
                mask = mask | (den < 1e-3)
            g = (inside, tris, bary, mask, den)
            interp_cache[key] = g
        return g

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
            inside, tris, bary, mask, den = interp_geom(ok)
            z = np.zeros(GX.shape)
            z[inside] = (bary * t[ok][tris]).sum(axis=1)  # 観測値の範囲を超えない線形補間
            if den is not None:  # 平滑化(欠測・範囲外を無視した正規化ガウス)
                z = conv_axis(conv_axis(np.where(mask, 0.0, z), 1), 0) / np.maximum(den, 1e-3)
            z = np.ma.masked_array(z, mask=mask)
            lv, nm = st["levels"], st["norm"]
            cf = ax.contourf(GX, GY, z, levels=lv, cmap=cmap, norm=nm, extend="both", alpha=0.6, zorder=1)
            cl = ax.contour(GX, GY, z, levels=lv, colors="k", linewidths=0.5, alpha=0.7, zorder=2)
            contours.extend([cf, cl])
            labels.extend(cl.clabel(fmt="%g", fontsize=7, inline=True, inline_spacing=3))
            frame_arts.extend(animate([cf, cl] + labels))
        except Exception as e:
            print("等温線を描けませんでした:", e)

    # ---- 風: 矢印 ----
    qh = {"q": None}  # 矢印は毎回、風が有効な地点だけで作り直す(長さ0の矢印が点として残るのを防ぐ)

    def draw_wind(i):
        if qh["q"] is not None:
            qh["q"].remove()
            qh["q"] = None
        w, d = S["wind"][i], S["wdir"][i]
        ang = np.radians(d * 22.5 + 180)  # 風が吹いていく向き
        u, v = w * np.sin(ang), w * np.cos(ang)
        ok = ~(np.isnan(u) | np.isnan(v) | (d < 0))  # 欠測・静穏は矢印を描かない
        if ok.any():
            qh["q"] = ax.quiver(lon[ok], lat[ok], u[ok], v[ok], angles="xy",
                                scale_units="xy", scale=25, width=0.003, zorder=3)
            frame_arts.extend(animate([qh["q"]]))

    # ---- 風速の凡例: 右側(カラーバーの下)。本体の矢印と同じ長さ(ピクセル)で描く ----
    lax = fig.add_axes([0.75, 0.29, 0.23, 0.21])  # 右の列(2番目): 風速の凡例
    lax.axis("off")
    legend_state = {"px": None}

    def draw_wind_legend(_=None):
        p0 = ax.transData.transform((view[0], view[2]))
        p1 = ax.transData.transform((view[0] + 1.0, view[2]))
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
        y_wp = bb.height - 40 - 32 * 3  # 高層風(紫)の行
        lax.scatter([14], [y_wp], marker="^", s=40, color="#7b1fa2")
        lax.quiver([28], [y_wp], [5 / 25 * px_deg], [0], angles="xy", scale_units="xy", scale=1,
                   units="dots", width=width_px * 1.3, color="#7b1fa2")
        lax.text(28 + 5 / 25 * px_deg + 8, y_wp, "高層風(プロファイラ)", fontsize=9, va="center", color="#7b1fa2")
        split = y_wp + 16  # これより上=地上の風、下=高層風 (クリックで切り替える範囲)
        legend_state["split"] = split
        dims["wind"] = make_dim(lax, 0, split, bb.width, bb.height - split, transform=lax.transData)
        dims["wp"] = make_dim(lax, 0, 0, bb.width, split, transform=lax.transData)
        dims["wind"].set_visible(not show["wind"]); dims["wp"].set_visible(not show["wp"])
        fig.canvas.draw_idle()

    eax = None
    if bg["gray"] and not a.relief:
        eax = fig.add_axes([0.76, 0.22, 0.17, 0.015])  # 右の列(3番目): 標高の凡例
        eax.imshow(np.linspace(0.97, 0.67, 100)[None, :].repeat(2, 0), cmap="gray", vmin=0, vmax=1,
                   aspect="auto", extent=(0, 2500, 0, 1))
        eax.set_yticks([]); eax.set_xticks([0, 500, 1000, 1500, 2000, 2500])
        eax.tick_params(labelsize=7)
        eax.set_xlabel("標高 (m)", fontsize=8)
        dims["elev"] = make_dim(eax, -0.06, -5.0, 1.12, 7.0)

    def apply_view():
        """チェックボックスの状態を表示に反映する"""
        set_visible(pts_arts, show["pts"])
        for k, art in enumerate(name_arts):
            art.set_visible(show["pts"] and not missing[k])
        rgba = np.zeros((len(names), 4))
        rgba[:, 3] = np.where(missing, 0.0, 1.0)  # 観測値が空欄の地点は黒点も消す
        dots.set_facecolor(rgba)
        dots.set_edgecolor(rgba)
        if qh["q"] is not None:
            qh["q"].set_visible(show["wind"])
        for key, d in dims.items():  # オフの凡例は薄くする
            d.set_visible(not show[key])
        set_visible(bg["gray"], show["elev"])  # 標高(灰色の陰影と等高線)のオン/オフ

    fig.canvas.mpl_connect("draw_event", draw_wind_legend)
    title = ax.set_title("", fontsize=18, fontweight="bold")
    persist_arts.extend(animate([title]))

    on_time = []  # 時刻が変わったときに呼ぶ関数(日のプルダウンの同期など)

    def update(i, full=False):
        frame_arts.clear()
        draw_temp(S["temp"][i])
        draw_wind(i)
        missing[:] = np.isnan(S["temp"][i]) & np.isnan(S["wind"][i])
        for k, (n, art) in enumerate(zip(names, name_arts)):  # 「数値」ON: 観測気温を地点名に併記
            tv, wv = S["temp"][i][k], S["wind"][i][k]
            if show["val"]:  # 「数値」ON: 地点名の下に気温、その下に風速を改行して併記
                vals = []
                if not np.isnan(tv):
                    vals.append(f"{tv:.1f}℃")
                if not np.isnan(wv):
                    vals.append(f"{wv:g}m/s")
                art.set_text("\n".join([n] + vals))  # 地点名 / 気温 / 風速 の3行
            else:
                art.set_text(n)
        apply_view()
        for fn in on_time:
            fn(i)
        chart_note = ""
        utc = parse_time(S["times"][i]) - datetime.timedelta(hours=9)  # 日本時間 -> UTC
        if wp_state["q"] is not None:
            wp_state["q"].remove(); wp_state["q"] = None
        if wp_state["mk"] is not None:
            wp_state["mk"].remove(); wp_state["mk"] = None
        if use_wp and show["wp"]:
            ws = wp_winds(wp_dir, utc, (xlim[0], xlim[1], ylim[0], ylim[1]), wp_state["height"])
            if ws:
                wl, wa, wu, wv = (np.array(c) for c in zip(*ws))
                wp_state["q"] = ax.quiver(wl, wa, wu, wv, angles="xy", scale_units="xy", scale=25, width=0.004,
                                          color="#7b1fa2", zorder=3.2)
                wp_state["mk"] = ax.scatter(wl, wa, marker="^", s=28, color="#7b1fa2", zorder=3.3)
                frame_arts.extend(animate([wp_state["q"], wp_state["mk"]]))
                chart_note += f"   プロファイラ {wp_state['height']}m"
        path = chart_idx.get(utc)
        if path and show["chart"]:
            if path not in chart_cache:
                chart_cache.clear()  # 直前の1枚だけ保持
                chart_cache[path] = chart_overlay(path, (xlim[0], xlim[1], ylim[0], ylim[1]), a.chart_alpha)
            chart_im.set_data(chart_cache[path])
            chart_im.set_visible(True)
            if inset_state["path"] != path:  # 元の天気図(枠の内側だけ・縮小)
                inset_state["path"] = path
                thumb = chart_thumbnail(path)
                im_in.set_data(thumb)
                th, tw = thumb.shape[:2]
                im_in.set_extent((-0.5, tw - 0.5, th - 0.5, -0.5))  # 画像の大きさに合わせる(最初の仮の画像の大きさのままだと点になる)
                iax.set_xlim(-0.5, tw - 0.5)
                iax.set_ylim(th - 0.5, -0.5)
            im_in.set_visible(True)
            pass  # 天気図の時刻は図の中に書かれているので、タイトルには出さない
        else:
            chart_im.set_visible(False)
            im_in.set_visible(False)
        ph.set_visible(not im_in.get_visible())  # 画像が出ていないとき、理由を枠の中に書く
        ph.set_text("天気図\n(クリックで表示)" if not show["chart"] else "天気図なし\n(この時刻は\n9時・21時のみ)")
        title.set_text(f"{S['times'][i]}{chart_note}   [{VERSION.split()[0]}]")
        refresh(full)

    if a.save:
        anim = FuncAnimation(fig, lambda i: update(i), frames=len(S["times"]), interval=a.interval)
        anim.save(a.save, dpi=100)
        print("保存:", a.save)
        return

    # ---- 操作部 ----
    # 下段: [-1年 -1月 -1日 -12時間 -1時間] 再生/停止 [+1時間 +12時間 +1日 +1月 +1年]
    # その上の段: 表示の切り替えボタン(オンのとき色が変わる)
    state = {"i": 0, "playing": False}
    ON_COLOR, OFF_COLOR = "#8ec3e6", "0.85"

    def set_index(i):
        state["i"] = int(i)
        update(state["i"])

    btn = Button(plt.axes([0.455, 0.03, 0.09, 0.05]), "再生/停止", color=OFF_COLOR, hovercolor=OFF_COLOR)
    steps = [("-1年", "y", -1), ("-1月", "m", -1), ("-1日", "h", -24), ("-12時間", "h", -12), ("-1時間", "h", -1),
             ("+1時間", "h", 1), ("+12時間", "h", 12), ("+1日", "h", 24), ("+1月", "m", 1), ("+1年", "y", 1)]
    step_btns = []
    for k, (label, kind, amount) in enumerate(steps):
        x0 = 0.08 + 0.072 * k if k < 5 else 0.565 + 0.072 * (k - 5)
        bt = Button(plt.axes([x0, 0.03, 0.068, 0.05]), label, hovercolor="0.85")
        bt.label.set_fontsize(8)
        step_btns.append((bt, kind, amount))
    avail = scan_months(a.dir)
    ym = {"cy": None, "cm": None, "cd": None, "ch": None}
    use_tk = False
    try:  # TkAgg(Windowsの標準)なら、ウィンドウ上部に年・月のプルダウンを付ける
        import tkinter as tk
        from tkinter import ttk
        win = fig.canvas.manager.window
        use_tk = isinstance(win, tk.Misc)
    except Exception:
        use_tk = False
    tb = None
    if not use_tk:  # プルダウンが使えない環境では、これまでどおり入力欄
        tb = TextBox(plt.axes([0.80, 0.10, 0.09, 0.05]), "年月 ", initial=f"{S['start'].year}-{S['start'].month:02d}")
    msg = fig.text(0.08, 0.165, "", fontsize=9, color="crimson")

    def load_month(y, m, target=None):
        """指定の年月を読み込んで表示を切り替える。CSVが無い場合は元の表示のまま。
        target(日時)があれば、その時刻に最も近いコマを表示する。"""
        try:
            d0, d1 = month_range(y, m)
        except ValueError:
            msg.set_text("年月は YYYY-MM の形式で入力してください"); fig.canvas.draw_idle(); return
        if (d0, d1) not in month_cache or not month_cache[(d0, d1)].done():
            msg.set_text(f"{y}-{m:02d} を読み込み中 ..."); fig.canvas.draw()
        old = dict(S)
        try:
            read(d0, d1)
        except FileNotFoundError:
            S.update(old); msg.set_text(f"{y}-{m:02d} のCSVがありません")
            sync_ym(S["start"].year, S["start"].month); fig.canvas.draw_idle(); return
        msg.set_text("")
        state["playing"] = False
        state["i"] = nearest_index(target) if target else 0
        sync_ym(y, m)
        update(state["i"], full=True)

    def nearest_index(dt):
        ts = [parse_time(t) for t in S["times"]]
        return int(np.argmin([abs((t - dt).total_seconds()) for t in ts]))

    def current_time():
        return parse_time(S["times"][state["i"]])

    def go_to(dt):
        """dt へ移動。読み込み済みの月の外なら、その月のCSVを読み込む。"""
        if S["start"] <= dt.date() <= S["end"]:
            state["playing"] = False
            set_index(nearest_index(dt))
        else:
            load_month(dt.year, dt.month, target=dt)

    def move(kind, amount):
        cur = current_time()
        if kind in ("y", "m"):  # 同じ日・時刻のまま月/年を動かす(月末は日を詰める)
            k = cur.year * 12 + cur.month - 1 + (amount * 12 if kind == "y" else amount)
            y, m = k // 12, k % 12 + 1
            day = min(cur.day, calendar.monthrange(y, m)[1])
            go_to(cur.replace(year=y, month=m, day=day))
        else:
            go_to(cur + datetime.timedelta(hours=amount))

    for bt, kind, amount in step_btns:
        bt.on_clicked(lambda e, kind=kind, amount=amount: move(kind, amount))

    def on_submit(text):
        try:
            y, m = (int(x) for x in text.strip().replace("/", "-").split("-")[:2])
        except ValueError:
            msg.set_text("年月は YYYY-MM の形式で入力してください"); fig.canvas.draw_idle(); return
        if (y, m) != (S["start"].year, S["start"].month):
            load_month(y, m)

    def sync_ym(y, m):
        """表示中の年月を、プルダウン(または入力欄)に反映する"""
        if ym["cy"] is not None:
            years = sorted({yy for yy, _ in avail} | {y})
            ym["cy"].configure(values=years)
            ym["cy"].set(str(y))
            ym["cm"].configure(values=sorted({mm for yy, mm in avail if yy == y} | {m}))
            ym["cm"].set(str(m))
        elif tb is not None:
            tb.set_val(f"{y}-{m:02d}")

    if use_tk:
        tkfont = ("Yu Gothic UI", 13)  # ②日時を大きく
        win.option_add("*TCombobox*Listbox.font", tkfont)
        frame = ttk.Frame(win)
        frame.pack(side=tk.TOP, fill=tk.X, before=fig.canvas.get_tk_widget())

        def pull(key, width, unit, pad=(10, 0)):
            """プルダウンの後ろに単位(年・月・日・時)を付ける"""
            ym[key] = ttk.Combobox(frame, width=width, state="readonly", font=tkfont)
            ym[key].pack(side=tk.LEFT, padx=pad)
            ttk.Label(frame, text=unit, font=tkfont).pack(side=tk.LEFT, padx=(2, 6))

        pull("cy", 6, "年")
        pull("cm", 4, "月")
        pull("cd", 4, "日")
        pull("ch", 4, "時")

        def on_hour(_=None):
            cur = current_time()
            go_to(cur.replace(hour=int(ym["ch"].get()), minute=0))

        ym["ch"].configure(values=list(range(24)))
        ym["ch"].bind("<<ComboboxSelected>>", on_hour)

        def on_day(_=None):
            cur = current_time()
            go_to(datetime.datetime(S["start"].year, S["start"].month, int(ym["cd"].get()), cur.hour, 0))

        ym["cd"].bind("<<ComboboxSelected>>", on_day)

        def sync_day(i):
            """表示中の時刻の「日」をプルダウンに反映する(月末の翌0:00は月の最終日として扱う)"""
            d = min(max(parse_time(S["times"][i]).date(), S["start"]), S["end"])
            ym["cd"].configure(values=list(range(1, S["end"].day + 1)))
            ym["cd"].set(str(d.day))
            ym["ch"].set(str(parse_time(S["times"][i]).hour))

        on_time.append(sync_day)

        if use_wp:
            ttk.Label(frame, text="プロファイラの高さ", font=tkfont).pack(side=tk.LEFT, padx=(20, 2))
            ch = ttk.Combobox(frame, width=8, state="readonly", font=tkfont, values=[f"{h} m" for h in WP_HEIGHTS])
            ch.set(f"{wp_state['height']} m")
            ch.pack(side=tk.LEFT)

            def on_height(_=None):
                wp_state["height"] = int(ch.get().split()[0])
                update(state["i"])

            ch.bind("<<ComboboxSelected>>", on_height)

        def on_year(_=None):
            y = int(ym["cy"].get())
            months = sorted(mm for yy, mm in avail if yy == y)
            m = int(ym["cm"].get()) if ym["cm"].get() and int(ym["cm"].get()) in months else (months[0] if months else 1)
            load_month(y, m)

        def on_month(_=None):
            load_month(int(ym["cy"].get()), int(ym["cm"].get()))

        ym["cy"].bind("<<ComboboxSelected>>", on_year)
        ym["cm"].bind("<<ComboboxSelected>>", on_month)
        sync_ym(S["start"].year, S["start"].month)
    else:
        tb.on_submit(on_submit)

    # 表示の切り替えボタン: オンのとき色が変わる (チェックボックスの代わり)
    toggles = {}
    for k, (key, label) in enumerate((("pts", "地点"), ("val", "数値"))):
        tg = Button(plt.axes([0.08 + 0.08 * k, 0.10, 0.075, 0.05]), label, color=ON_COLOR, hovercolor=ON_COLOR)
        tg.label.set_fontsize(9)
        toggles[key] = tg

    def refresh_toggle(key):
        c = ON_COLOR if show[key] else OFF_COLOR
        tg = toggles[key]
        tg.color = tg.hovercolor = c
        tg.ax.set_facecolor(c)

    def make_toggle_cb(key):
        def cb(_):
            show[key] = not show[key]
            refresh_toggle(key)
            update(state["i"], full=True)
        return cb

    for key in toggles:
        refresh_toggle(key)
        toggles[key].on_clicked(make_toggle_cb(key))
    fig.text(0.26, 0.118, "凡例(右の列・左上の天気図)をクリックすると、その表示のオン/オフを切り替えられます",
             fontsize=9, color="0.4")

    def on_legend_click(ev):
        """凡例をクリックして、対応する表示のオン/オフを切り替える"""
        if ev.button != 1 or ev.inaxes is None:
            return
        axx, key = ev.inaxes, None
        if axx is cax:
            key = "temp"
        elif axx is iax:
            key = "chart"
        elif eax is not None and axx is eax:
            key = "elev"
        elif axx is lax:
            key = "wp" if (ev.ydata is not None and ev.ydata < legend_state.get("split", 0)) else "wind"
        if key is not None:
            show[key] = not show[key]
            update(state["i"], full=True)

    fig.canvas.mpl_connect("button_press_event", on_legend_click)

    def tick(_):
        if state["playing"]:
            set_index((state["i"] + 1) % len(S["times"]))

    def on_play(_):
        state["playing"] = not state["playing"]
        c = ON_COLOR if state["playing"] else OFF_COLOR
        btn.color = btn.hovercolor = c
        btn.ax.set_facecolor(c)
        fig.canvas.draw_idle()

    btn.on_clicked(on_play)
    if use_blit:  # 保存時の画像にも動く部品が入るように、保存の間だけ通常描画に戻す
        _orig_savefig = fig.savefig

        def savefig(*args, **kw):
            arts = persist_arts + frame_arts
            for x in arts:
                x.set_animated(False)
            try:
                return _orig_savefig(*args, **kw)
            finally:
                for x in arts:
                    x.set_animated(True)
        fig.savefig = savefig
    play_timer = fig.canvas.new_timer(interval=a.interval)
    play_timer.add_callback(lambda: tick(None))
    play_timer.start()
    blit["ready"] = True
    update(0, full=True)
    plt.show()


if __name__ == "__main__":
    main()
