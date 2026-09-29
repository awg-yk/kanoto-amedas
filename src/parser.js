'use strict';
// アメダスCSV(気象庁 過去データ ダウンロード形式)のパーサ。
// 1地点あたり8列: 気温, 品質, 均質, 風速, 品質, 風向, 品質, 均質

const DIRS = ['北', '北北東', '北東', '東北東', '東', '東南東', '南東', '南南東',
  '南', '南南西', '南西', '西南西', '西', '西北西', '北西', '北北西'];

function splitCsvLine(line) {
  return line.split(',').map((s) => s.trim());
}

function num(s) {
  if (s === undefined || s === '') return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
}

// "2000/1/1 1:00:00" -> "2000-01-01T01:00" (24時表記の 00:00 は翌日そのまま)
function toIso(s) {
  const m = /^(\d{4})\/(\d{1,2})\/(\d{1,2}) (\d{1,2}):(\d{2})/.exec(s);
  if (!m) return null;
  const p = (x) => String(x).padStart(2, '0');
  return `${m[1]}-${p(m[2])}-${p(m[3])}T${p(m[4])}:${m[5]}`;
}

// 戻り値: { stations: string[], times: string[], temp: (number|null)[][],
//          wind: (number|null)[][], dir: (number|null)[][] }
// dir は 0..15 (北=0, 時計回り)、静穏は -1、欠測は null。配列は [時刻][地点]。
function parseAmedasCsv(text) {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/);
  const nameRow = lines.findIndex((l) => l.startsWith(',') && l.length > 10);
  if (nameRow < 0) throw new Error('地点名の行が見つかりません');
  const names = splitCsvLine(lines[nameRow]);
  const stations = [];
  const startCol = [];
  names.forEach((n, i) => {
    if (i > 0 && n && n !== names[i - 1]) { stations.push(n); startCol.push(i); }
  });
  const out = { stations, times: [], temp: [], wind: [], dir: [] };
  for (let i = nameRow + 1; i < lines.length; i++) {
    const c = splitCsvLine(lines[i]);
    const t = toIso(c[0]);
    if (!t) continue;
    out.times.push(t);
    out.temp.push(startCol.map((s) => num(c[s])));
    out.wind.push(startCol.map((s) => num(c[s + 3])));
    out.dir.push(startCol.map((s) => {
      const d = c[s + 5];
      if (d === '静穏') return -1;
      const k = DIRS.indexOf(d);
      return k < 0 ? null : k;
    }));
  }
  return out;
}

// 複数ファイルを時刻順に結合(地点は名前で揃える)
function mergeParsed(list) {
  const stations = [];
  for (const p of list) for (const s of p.stations) if (!stations.includes(s)) stations.push(s);
  const rows = [];
  for (const p of list) {
    const idx = stations.map((s) => p.stations.indexOf(s));
    p.times.forEach((t, r) => {
      const pick = (a) => idx.map((k) => (k < 0 ? null : a[r][k]));
      rows.push({ t, temp: pick(p.temp), wind: pick(p.wind), dir: pick(p.dir) });
    });
  }
  rows.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  return {
    stations,
    times: rows.map((r) => r.t),
    temp: rows.map((r) => r.temp),
    wind: rows.map((r) => r.wind),
    dir: rows.map((r) => r.dir),
  };
}

module.exports = { parseAmedasCsv, mergeParsed, DIRS };
