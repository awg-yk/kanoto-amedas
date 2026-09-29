'use strict';
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const { parseAmedasCsv, mergeParsed } = require('./parser');

function loadData(ctx) {
  const cfg = vscode.workspace.getConfiguration('kantoAmedas').get('dataDir');
  const dir = cfg || path.join(ctx.extensionPath, 'data');
  const files = fs.readdirSync(dir).filter((f) => f.toLowerCase().endsWith('.csv')).sort();
  if (!files.length) throw new Error(`CSVが見つかりません: ${dir}`);
  const data = mergeParsed(files.map((f) => parseAmedasCsv(fs.readFileSync(path.join(dir, f), 'utf8'))));
  const stations = JSON.parse(fs.readFileSync(path.join(ctx.extensionPath, 'data', 'stations.json'), 'utf8'));
  data.coords = data.stations.map((s) => stations[s] || null);
  return data;
}

function activate(ctx) {
  ctx.subscriptions.push(vscode.commands.registerCommand('kantoAmedas.open', () => {
    const panel = vscode.window.createWebviewPanel('kantoAmedas', '関東アメダス', vscode.ViewColumn.One,
      { enableScripts: true, localResourceRoots: [vscode.Uri.file(path.join(ctx.extensionPath, 'media'))] });
    const uri = (f) => panel.webview.asWebviewUri(vscode.Uri.file(path.join(ctx.extensionPath, 'media', f)));
    const nonce = Math.random().toString(36).slice(2);
    panel.webview.html = `<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${panel.webview.cspSource}; script-src 'nonce-${nonce}' ${panel.webview.cspSource};">
<link rel="stylesheet" href="${uri('player.css')}"></head><body>
<div id="bar">
 <button id="play">▶</button><button id="prev">◀</button><button id="next">▶|</button>
 <input id="slider" type="range" min="0" value="0"><span id="time"></span>
 <select id="mode"><option value="both">気温+風</option><option value="temp">気温のみ</option><option value="wind">風のみ</option></select>
 <select id="speed"><option value="1000">1秒/時</option><option value="500" selected>0.5秒/時</option><option value="200">0.2秒/時</option></select>
 <label><input type="checkbox" id="labels" checked>地点名</label>
 <label><input type="checkbox" id="islands">離島</label>
</div>
<canvas id="map"></canvas><div id="legend"></div><div id="tip"></div>
<script nonce="${nonce}" src="${uri('player.js')}"></script></body></html>`;
    try {
      panel.webview.postMessage({ type: 'data', data: loadData(ctx) });
    } catch (e) {
      vscode.window.showErrorMessage('アメダスデータの読込に失敗: ' + e.message);
    }
  }));
}

module.exports = { activate, deactivate() {} };
