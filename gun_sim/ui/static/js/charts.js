// 2D line charts drawn on a canvas, coloured from the page's CSS variables.

export function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function niceTicks(min, max, count) {
  if (min === max) { max = min + 1; }
  const step0 = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  // Ticks always enclose [min, max], so the axis range never clips the data.
  const ticks = [];
  const end = Math.ceil(max / step - 1e-9) * step;
  for (let v = Math.floor(min / step + 1e-9) * step; v <= end + step * 1e-9; v += step) ticks.push(+v.toPrecision(12));
  return ticks;
}

export function drawChart(canvas, { series, xlabel, ylabel, legendBottom = false }) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  ctx.font = "12px system-ui, sans-serif";
  const text = cssVar("--text"), muted = cssVar("--muted"), grid = cssVar("--grid");
  if (!series.length) {
    ctx.fillStyle = muted; ctx.textAlign = "center";
    ctx.fillText("no data", W / 2, H / 2);
    return;
  }
  let xmin = Infinity, xmax = -Infinity, ymin = 0, ymax = -Infinity;
  for (const s of series) for (let i = 0; i < s.x.length; i++) {
    xmin = Math.min(xmin, s.x[i]); xmax = Math.max(xmax, s.x[i]);
    ymin = Math.min(ymin, s.y[i]); ymax = Math.max(ymax, s.y[i]);
  }
  const xt = niceTicks(xmin, xmax, 6), yt = niceTicks(ymin, ymax, 5);
  xmin = Math.min(xmin, xt[0]); xmax = Math.max(xmax, xt[xt.length - 1]);
  ymin = Math.min(ymin, yt[0]); ymax = Math.max(ymax, yt[yt.length - 1]);
  const L = 54, R = 12, T = 8, B = 38;
  const px = (x) => L + (x - xmin) / (xmax - xmin || 1) * (W - L - R);
  const py = (y) => T + (1 - (y - ymin) / (ymax - ymin || 1)) * (H - T - B);

  ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.fillStyle = muted;
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const x of xt) {
    ctx.beginPath(); ctx.moveTo(px(x), T); ctx.lineTo(px(x), H - B); ctx.stroke();
    ctx.fillText(String(x), px(x), H - B + 4);
  }
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const y of yt) {
    ctx.beginPath(); ctx.moveTo(L, py(y)); ctx.lineTo(W - R, py(y)); ctx.stroke();
    ctx.fillText(String(y), L - 6, py(y));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText(xlabel, L + (W - L - R) / 2, H - 2);
  ctx.save(); ctx.translate(12, T + (H - T - B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = "middle"; ctx.fillText(ylabel, 0, 0); ctx.restore();

  ctx.save();
  ctx.beginPath(); ctx.rect(L, T, W - L - R, H - T - B); ctx.clip();
  for (const s of series) {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.setLineDash(s.dash ? [6, 4] : []);
    ctx.beginPath();
    s.x.forEach((x, i) => (i ? ctx.lineTo(px(x), py(s.y[i])) : ctx.moveTo(px(x), py(s.y[i]))));
    ctx.stroke();
  }
  ctx.restore();

  // Legend, top or bottom right.
  ctx.setLineDash([]); ctx.textAlign = "left"; ctx.textBaseline = "middle";
  const legendW = Math.max(...series.map((s) => ctx.measureText(s.label).width)) + 34;
  const legendH = series.length * 16 + 8;
  const top = legendBottom ? H - B - legendH - 4 : T + 2;
  let ly = top + 8;
  ctx.fillStyle = cssVar("--panel"); ctx.globalAlpha = 0.85;
  ctx.fillRect(W - R - legendW - 6, top, legendW + 4, legendH);
  ctx.globalAlpha = 1;
  for (const s of series) {
    const lx = W - R - legendW;
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.setLineDash(s.dash ? [6, 4] : []);
    ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(lx + 22, ly); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = text; ctx.fillText(s.label, lx + 28, ly);
    ly += 16;
  }
}
