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
import os

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--islands", action="store_true", help="離島も表示")
    ap.add_argument("--interval", type=int, default=500, help="1時間あたりのms")
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
