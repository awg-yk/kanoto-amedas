(function () {
  const $ = (id) => document.getElementById(id);
  const cv = $('map'), ctx = cv.getContext('2d');
  const TMIN = -10, TMAX = 35, ISLAND_LAT = 34.9;
  let D = null, idx = 0, timer = null, pts = [];

  // 気温→色 (青→水色→緑→黄→赤)
  const STOPS = [[0, [49, 54, 149]], [.2, [69, 117, 180]], [.4, [116, 173, 209]], [.5, [166, 217, 106]],
    [.65, [254, 224, 144]], [.8, [244, 109, 67]], [1, [165, 0, 38]]];
  function tempColor(t) {
    if (t == null) return null;
    const x = Math.min(1, Math.max(0, (t - TMIN) / (TMAX - TMIN)));
    for (let i = 1; i < STOPS.length; i++) {
      if (x <= STOPS[i][0]) {
        const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], f = (x - a) / (b - a);
        return `rgb(${ca.map((v, k) => Math.round(v + (cb[k] - v) * f)).join(',')})`;
      }
    }
  }

  function buildLegend() {
    const c = document.createElement('canvas'); c.width = 160; c.height = 10;
    const g = c.getContext('2d');
    for (let x = 0; x < 160; x++) { g.fillStyle = tempColor(TMIN + (TMAX - TMIN) * x / 159); g.fillRect(x, 0, 1, 10); }
    $('legend').innerHTML = '';
    $('legend').append(c);
    const s = document.createElement('div'); s.style.cssText = 'display:flex;justify-content:space-between';
    s.innerHTML = `<span>${TMIN}℃</span><span>${TMAX}℃</span>`;
    $('legend').append(s, '矢印: 風の吹く向き / 長さ=風速');
  }

  function layout() {
    const dpr = window.devicePixelRatio || 1;
    cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!D) return;
    const show = D.coords.map((c) => c && ($('islands').checked || c.lat >= ISLAND_LAT));
    const cs = D.coords.filter((c, i) => show[i]);
    const lat0 = Math.min(...cs.map((c) => c.lat)), lat1 = Math.max(...cs.map((c) => c.lat));
    const lon0 = Math.min(...cs.map((c) => c.lon)), lon1 = Math.max(...cs.map((c) => c.lon));
    const W = cv.clientWidth, H = cv.clientHeight, m = 40;
    const kx = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180); // 経度の縮み
    const s = Math.min((W - 2 * m) / ((lon1 - lon0) * kx), (H - 2 * m) / (lat1 - lat0));
    const ox = (W - (lon1 - lon0) * kx * s) / 2, oy = (H - (lat1 - lat0) * s) / 2;
    pts = D.coords.map((c, i) => show[i] ? { x: ox + (c.lon - lon0) * kx * s, y: oy + (lat1 - c.lat) * s } : null);
    layout.grid = { lat0, lat1, lon0, lon1, kx, s, ox, oy };
    draw();
  }

  function arrow(x, y, dirIdx, spd) {
    // dirIdx は風が吹いてくる方位。矢印は吹いていく向き(+180°)。
    const ang = (dirIdx * 22.5 + 180) * Math.PI / 180;
    const len = 8 + Math.min(spd, 15) * 2.2;
    const dx = Math.sin(ang), dy = -Math.cos(ang);
    const x0 = x - dx * len / 2, y0 = y - dy * len / 2, x1 = x + dx * len / 2, y1 = y + dy * len / 2;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
    const h = 5, a = 0.5;
    ctx.moveTo(x1, y1); ctx.lineTo(x1 - h * Math.sin(ang - a), y1 + h * Math.cos(ang - a));
    ctx.moveTo(x1, y1); ctx.lineTo(x1 - h * Math.sin(ang + a), y1 + h * Math.cos(ang + a));
    ctx.stroke();
  }

  function draw() {
    const W = cv.clientWidth, H = cv.clientHeight;
    ctx.clearRect(0, 0, W, H);
    if (!D) return;
    const g = layout.grid, fg = getComputedStyle(document.body).color;
    ctx.strokeStyle = 'rgba(128,128,128,.25)'; ctx.fillStyle = 'rgba(128,128,128,.8)'; ctx.font = '10px sans-serif'; ctx.lineWidth = 1;
    for (let lo = Math.ceil(g.lon0); lo <= g.lon1; lo++) {
      const x = g.ox + (lo - g.lon0) * g.kx * g.s; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); ctx.fillText(lo + '°E', x + 2, H - 4);
    }
    for (let la = Math.ceil(g.lat0); la <= g.lat1; la++) {
      const y = g.oy + (g.lat1 - la) * g.s; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); ctx.fillText(la + '°N', 2, y - 2);
    }
    const mode = $('mode').value;
    D.stations.forEach((name, i) => {
      const p = pts[i]; if (!p) return;
      const t = D.temp[idx][i], w = D.wind[idx][i], d = D.dir[idx][i];
      if (mode !== 'wind') {
        const col = tempColor(t);
        ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, 7);
        if (col) { ctx.fillStyle = col; ctx.fill(); } else { ctx.strokeStyle = 'gray'; ctx.setLineDash([2, 2]); ctx.stroke(); ctx.setLineDash([]); }
      }
      if (mode !== 'temp') {
        ctx.lineWidth = 1.6; ctx.strokeStyle = mode === 'wind' ? fg : '#111';
        if (d === -1 || (w === 0)) { ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, 7); ctx.stroke(); }
        else if (d != null && w != null) arrow(p.x, p.y, d, w);
        ctx.lineWidth = 1;
      }
      if ($('labels').checked) { ctx.fillStyle = fg; ctx.font = '10px sans-serif'; ctx.fillText(name, p.x + 11, p.y + 3); }
    });
    $('time').textContent = D.times[idx].replace('T', ' ');
    $('slider').value = idx;
  }

  function step(n) { idx = (idx + n + D.times.length) % D.times.length; draw(); }
  function toggle(on) {
    clearInterval(timer); timer = null;
    if (on === undefined) on = !$('play').dataset.on;
    $('play').dataset.on = on ? '1' : ''; $('play').textContent = on ? '⏸' : '▶';
    if (on) timer = setInterval(() => step(1), +$('speed').value);
  }

  $('play').onclick = () => toggle();
  $('prev').onclick = () => { toggle(false); step(-1); };
  $('next').onclick = () => { toggle(false); step(1); };
  $('slider').oninput = (e) => { idx = +e.target.value; draw(); };
  $('speed').onchange = () => { if ($('play').dataset.on) toggle(true); };
  $('mode').onchange = $('labels').onchange = draw;
  $('islands').onchange = layout;
  window.addEventListener('resize', layout);
  cv.addEventListener('mousemove', (e) => {
    if (!D) return;
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    let best = -1, bd = 144;
    pts.forEach((p, i) => { if (p) { const d = (p.x - x) ** 2 + (p.y - y) ** 2; if (d < bd) { bd = d; best = i; } } });
    const tip = $('tip');
    if (best < 0) { tip.style.display = 'none'; return; }
    const N = ['北','北北東','北東','東北東','東','東南東','南東','南南東','南','南南西','南西','西南西','西','西北西','北西','北北西'];
    const t = D.temp[idx][best], w = D.wind[idx][best], d = D.dir[idx][best];
    tip.textContent = `${D.stations[best]}\n気温 ${t ?? '欠測'}℃\n風 ${d === -1 ? '静穏' : d == null ? '欠測' : N[d]} ${w ?? '-'} m/s`;
    tip.style.display = 'block'; tip.style.left = e.clientX + 12 + 'px'; tip.style.top = e.clientY + 12 + 'px';
  });
  cv.addEventListener('mouseleave', () => { $('tip').style.display = 'none'; });

  window.addEventListener('message', (e) => {
    if (e.data.type !== 'data') return;
    D = e.data.data; idx = 0;
    $('slider').max = D.times.length - 1;
    buildLegend(); layout();
  });
})();
