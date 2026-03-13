/* ═══════════════════════════════════════════════════════════
   OpenNews Impact Terminal — app.js
   ═══════════════════════════════════════════════════════════ */

// ── state ────────────────────────────────────────────────
let allItems = [];          // raw batch items
let filteredItems = [];     // after range filter
let rangeLo = 0;
let rangeHi = 100;
let activeNewsId = null;

// ── DOM refs ─────────────────────────────────────────────
const $topicList   = document.getElementById('topicList');
const $distChart   = document.getElementById('distChart');
const $rangeText   = document.getElementById('rangeText');
const $rangeFill   = document.getElementById('rangeFill');
const $thumbLo     = document.getElementById('thumbLo');
const $thumbHi     = document.getElementById('thumbHi');
const $rangeTrack  = document.getElementById('rangeTrack');
const $detailPanel = document.getElementById('detailPanel');
const $detailBody  = document.getElementById('detailBody');
const $detailClose = document.getElementById('detailClose');

// stats
const $statTotal  = document.getElementById('statTotal');
const $statTopics = document.getElementById('statTopics');
const $statHigh   = document.getElementById('statHigh');
const $statMid    = document.getElementById('statMid');
const $statLow    = document.getElementById('statLow');

// ── helpers ──────────────────────────────────────────────
const levelClass = (level) => {
  if (level === '高') return 'high';
  if (level === '中') return 'mid';
  return 'low';
};

const levelColor = (level) => {
  if (level === '高') return '#ef4444';
  if (level === '中') return '#f59e0b';
  return '#22c55e';
};

const scoreColor = (score) => {
  if (score > 75) return '#ef4444';
  if (score > 40) return '#f59e0b';
  return '#22c55e';
};

const catLabel = {
  financial_market:  'FINANCIAL',
  policy_regulation: 'POLICY',
  company_event:     'COMPANY',
  macro_economy:     'MACRO',
  industry_trend:    'INDUSTRY',
};

const catColor = {
  financial_market:  '#3b82f6',
  policy_regulation: '#a855f7',
  company_event:     '#f59e0b',
  macro_economy:     '#06b6d4',
  industry_trend:    '#10b981',
};

const sourceName = (src) => {
  if (!src) return '—';
  if (src.includes('wallstreetcn')) return '华尔街见闻';
  if (src.includes('cls'))     return '财联社';
  if (src.includes('caixin'))  return '财新';
  if (src.includes('reuters')) return 'Reuters';
  if (src.includes('weibo'))   return '微博';
  if (src.includes('seed'))    return 'Seed';
  return src;
};

const fmtTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
};

// 将 UTC 时间戳 YYYYMMDD_HHMMSS 转为本地时间显示
const fmtBatchTs = (ts) => {
  const m = ts.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!m) return ts;
  const utcDate = new Date(Date.UTC(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]));
  return utcDate.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
};

// ── auto-refresh ─────────────────────────────────────────
let autoRefreshTimer = null;
const AUTO_REFRESH_INTERVAL = 30_000; // 30 秒

// ── data loading ─────────────────────────────────────────

async function fetchBatchList() {
  try {
    const resp = await fetch('/api/batches');
    if (!resp.ok) return [];
    return resp.json();
  } catch { return []; }
}

async function loadData(source, { preserveState = false } = {}) {
  let data;
  if (source === 'latest') {
    try {
      const resp = await fetch('/api/batches/latest');
      if (!resp.ok) throw new Error('no data');
      data = await resp.json();
    } catch {
      allItems = [];
      filteredItems = [];
      updateStats();
      drawChart();
      $topicList.innerHTML = '<div class="topics-loading">暂无数据 — 请先运行后端流水线产出批次数据</div>';
      return;
    }
  } else if (source.startsWith('batch:')) {
    const id = source.slice(6);
    const resp = await fetch(`/api/batches/${id}`);
    data = await resp.json();
  } else {
    data = await (await fetch(source)).json();
  }
  if (!Array.isArray(data) || data.length === 0) {
    allItems = [];
    filteredItems = [];
    updateStats();
    drawChart();
    $topicList.innerHTML = '<div class="topics-loading">该批次无数据</div>';
    return;
  }
  allItems = data.filter(d => d.news && d.report);
  if (allItems.length === 0) {
    filteredItems = [];
    updateStats();
    drawChart();
    $topicList.innerHTML = '<div class="topics-loading">该批次数据中无有效记录（缺少 news 或 report 字段）</div>';
    return;
  }

  if (!preserveState) {
    rangeLo = 0;
    rangeHi = 100;
  }
  applyFilter();

  // 自动刷新时：如果详情侧边栏打开，用新数据刷新内容
  if (preserveState && activeNewsId) {
    const stillExists = allItems.find(d => d.news?.news_id === activeNewsId);
    if (stillExists) {
      showDetail(activeNewsId);
    }
  }
}

async function refreshBatchSelect() {
  const $sel = document.getElementById('sourceSelect');
  const batches = await fetchBatchList();

  const curVal = $sel.value;

  $sel.innerHTML = '';

  // 固定选项：最新批次
  const optLatest = document.createElement('option');
  optLatest.value = 'latest';
  optLatest.textContent = '最新批次 (自动刷新)';
  $sel.appendChild(optLatest);

  // 动态批次列表
  batches.forEach(b => {
    const opt = document.createElement('option');
    opt.value = `batch:${b.batch_id}`;
    opt.textContent = `${fmtBatchTs(b.batch_ts)} (${b.record_count} 条)`;
    $sel.appendChild(opt);
  });

  if ([...($sel.options)].some(o => o.value === curVal)) {
    $sel.value = curVal;
  } else {
    $sel.value = 'latest';
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshTimer = setInterval(async () => {
    const $sel = document.getElementById('sourceSelect');
    if ($sel.value === 'latest') {
      await loadData('latest', { preserveState: true });
      await refreshBatchSelect();
    }
  }, AUTO_REFRESH_INTERVAL);
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

function applyFilter() {
  filteredItems = allItems.filter(d => {
    const s = d.report?.final_score ?? 0;
    return s >= rangeLo && s <= rangeHi;
  });
  updateStats();
  drawChart();
  renderTopics();
  updateRangeUI();
}

// ── stats ────────────────────────────────────────────────
function updateStats() {
  $statTotal.textContent = filteredItems.length;
  const topics = new Set(filteredItems.map(d => d.topic?.topic_id));
  $statTopics.textContent = topics.size;
  const levels = { '高': 0, '中': 0, '低': 0 };
  filteredItems.forEach(d => { levels[d.report?.impact_level] = (levels[d.report?.impact_level] || 0) + 1; });
  $statHigh.textContent = `高 ${levels['高']}`;
  $statMid.textContent  = `中 ${levels['中']}`;
  $statLow.textContent  = `低 ${levels['低']}`;
}

// ── chart ────────────────────────────────────────────────
function drawChart() {
  const canvas = $distChart;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const W = rect.width;
  const H = rect.height;
  ctx.clearRect(0, 0, W, H);

  // bucket scores into 20 bins (0-5, 5-10, ..., 95-100)
  const bins = new Array(20).fill(0);
  allItems.forEach(d => {
    const s = d.report?.final_score ?? 0;
    const idx = Math.min(19, Math.floor(s / 5));
    bins[idx]++;
  });
  const maxBin = Math.max(...bins, 1);

  const padL = 4, padR = 4, padT = 16, padB = 4;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  // draw area + line
  const points = bins.map((v, i) => ({
    x: padL + (i + 0.5) / 20 * plotW,
    y: padT + plotH - (v / maxBin) * plotH,
  }));

  // area fill
  ctx.beginPath();
  ctx.moveTo(padL, padT + plotH);
  points.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(padL + plotW, padT + plotH);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
  grad.addColorStop(0, 'rgba(59,130,246,0.25)');
  grad.addColorStop(1, 'rgba(59,130,246,0.02)');
  ctx.fillStyle = grad;
  ctx.fill();

  // line
  ctx.beginPath();
  points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // dots
  points.forEach((p, i) => {
    if (bins[i] === 0) return;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#3b82f6';
    ctx.fill();
  });

  // highlight range
  const loX = padL + (rangeLo / 100) * plotW;
  const hiX = padL + (rangeHi / 100) * plotW;
  ctx.fillStyle = 'rgba(59,130,246,0.08)';
  ctx.fillRect(loX, padT, hiX - loX, plotH);

  // bin labels for non-zero
  ctx.font = '500 9px "Geist Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillStyle = '#6b7280';
  points.forEach((p, i) => {
    if (bins[i] > 0) {
      ctx.fillText(bins[i], p.x, p.y - 6);
    }
  });
}

// ── range slider ─────────────────────────────────────────
function updateRangeUI() {
  const loPct = rangeLo / 100 * 100;
  const hiPct = rangeHi / 100 * 100;
  $thumbLo.style.left = loPct + '%';
  $thumbHi.style.left = hiPct + '%';
  $rangeFill.style.left = loPct + '%';
  $rangeFill.style.width = (hiPct - loPct) + '%';
  $rangeText.textContent = `${rangeLo.toFixed(1)} — ${rangeHi.toFixed(1)}`;
}

function initRangeSlider() {
  let dragging = null;

  const getVal = (e) => {
    const rect = $rangeTrack.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    return Math.max(0, Math.min(100, x / rect.width * 100));
  };

  const onMove = (e) => {
    if (!dragging) return;
    e.preventDefault();
    const val = Math.round(getVal(e) * 10) / 10;
    if (dragging === 'lo') {
      rangeLo = Math.min(val, rangeHi - 1);
    } else {
      rangeHi = Math.max(val, rangeLo + 1);
    }
    applyFilter();
  };

  const onUp = () => { dragging = null; };

  $thumbLo.addEventListener('mousedown', () => dragging = 'lo');
  $thumbHi.addEventListener('mousedown', () => dragging = 'hi');
  $thumbLo.addEventListener('touchstart', () => dragging = 'lo', { passive: true });
  $thumbHi.addEventListener('touchstart', () => dragging = 'hi', { passive: true });

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
  document.addEventListener('touchmove', onMove, { passive: false });
  document.addEventListener('touchend', onUp);

  // click on track
  $rangeTrack.addEventListener('click', (e) => {
    if (e.target.classList.contains('range-thumb')) return;
    const val = Math.round(getVal(e) * 10) / 10;
    const distLo = Math.abs(val - rangeLo);
    const distHi = Math.abs(val - rangeHi);
    if (distLo < distHi) {
      rangeLo = Math.min(val, rangeHi - 1);
    } else {
      rangeHi = Math.max(val, rangeLo + 1);
    }
    applyFilter();
  });
}

// ── render topics ────────────────────────────────────────
function renderTopics() {
  // 记录当前展开的 topic
  const openTopics = new Set();
  document.querySelectorAll('.topic-card.open').forEach(el => {
    openTopics.add(el.dataset.tid);
  });

  // group by topic_id
  const groups = new Map();
  filteredItems.forEach(item => {
    const tid = item.topic?.topic_id ?? -1;
    if (!groups.has(tid)) {
      groups.set(tid, {
        topic_id: tid,
        label: item.topic?.label || 'outlier',
        items: [],
      });
    }
    groups.get(tid).items.push(item);
  });

  // sort groups by max score desc
  const sorted = [...groups.values()].sort((a, b) => {
    const maxA = Math.max(...a.items.map(i => i.report?.final_score ?? 0));
    const maxB = Math.max(...b.items.map(i => i.report?.final_score ?? 0));
    return maxB - maxA;
  });

  if (sorted.length === 0) {
    $topicList.innerHTML = '<div class="topics-loading">当前范围内无新闻数据</div>';
    return;
  }

  $topicList.innerHTML = sorted.map(g => {
    const scores = g.items.map(i => i.report?.final_score ?? 0);
    const maxScore = Math.max(...scores);
    const avgScore = (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1);
    const levels = { '高': 0, '中': 0, '低': 0 };
    g.items.forEach(i => { levels[i.report?.impact_level] = (levels[i.report?.impact_level] || 0) + 1; });

    // sort items by score desc
    g.items.sort((a, b) => (b.report?.final_score ?? 0) - (a.report?.final_score ?? 0));

    // 恢复展开状态
    const isOpen = openTopics.has(String(g.topic_id));

    return `
      <div class="topic-card${isOpen ? ' open' : ''}" data-tid="${g.topic_id}">
        <div class="topic-head" onclick="toggleTopic(${g.topic_id})">
          <span class="topic-arrow">▶</span>
          <span class="topic-id">T${g.topic_id}</span>
          <span class="topic-label">${escHtml(g.label)}</span>
          <span class="topic-count">${g.items.length} 条</span>
          <div class="topic-score-bar">
            ${levels['高'] ? `<span class="topic-score-pill" style="background:var(--high-bg);color:var(--high)">高 ${levels['高']}</span>` : ''}
            ${levels['中'] ? `<span class="topic-score-pill" style="background:var(--mid-bg);color:var(--mid)">中 ${levels['中']}</span>` : ''}
            ${levels['低'] ? `<span class="topic-score-pill" style="background:var(--low-bg);color:var(--low)">低 ${levels['低']}</span>` : ''}
            <span class="topic-score-pill" style="background:var(--border);color:var(--text-dim)">avg ${avgScore}</span>
          </div>
        </div>
        <div class="topic-body">
          <div class="news-list">
            ${g.items.map(item => renderNewsItem(item)).join('')}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderNewsItem(item) {
  const score = item.report?.final_score ?? 0;
  const level = item.report?.impact_level ?? '低';
  const cat = item.classification?.category ?? 'unknown';
  const nid = item.news?.news_id ?? '';
  const title = item.news?.title ?? '';
  const time = fmtTime(item.news?.published_at);
  const src = sourceName(item.news?.source);

  return `
    <div class="news-item ${nid === activeNewsId ? 'active' : ''}" data-nid="${escAttr(nid)}" onclick="showDetail('${escAttr(nid)}')">
      <span class="news-score ${levelClass(level)}">${score.toFixed(1)}</span>
      <span class="news-level ${levelClass(level)}">${level}</span>
      <span class="news-cat" data-cat="${cat}">${catLabel[cat] || cat.toUpperCase()}</span>
      <span class="news-title">${escHtml(title)}</span>
      <span class="news-source">${escHtml(src)}</span>
      <span class="news-time">${time}</span>
    </div>
  `;
}

function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s) { return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

const isValidUrl = (url) => url && (url.startsWith('http://') || url.startsWith('https://'));

// ── topic toggle ─────────────────────────────────────────
window.toggleTopic = function(tid) {
  const card = document.querySelector(`.topic-card[data-tid="${tid}"]`);
  if (card) card.classList.toggle('open');
};

// ── detail panel ─────────────────────────────────────────
window.showDetail = function(nid) {
  const item = allItems.find(d => d.news?.news_id === nid);
  if (!item) return;

  activeNewsId = nid;
  // update active state
  document.querySelectorAll('.news-item').forEach(el => {
    el.classList.toggle('active', el.dataset.nid === nid);
  });

  const news = item.news || {};
  const clf = item.classification || {};
  const feat = item.features || {};
  const report = item.report || {};
  const entities = item.entities || [];
  const dkScores = report.dk_cot_scores || {};
  const level = report.impact_level || '低';
  const score = report.final_score ?? 0;

  // DK-CoT dimensions
  const dims = [
    { key: 'stock_relevance',  label: '股价相关性', weight: '40%' },
    { key: 'market_sentiment', label: '市场情绪',   weight: '20%' },
    { key: 'policy_risk',      label: '政策风险',   weight: '20%' },
    { key: 'spread_breadth',   label: '传播广度',   weight: '20%' },
  ];

  // feature keys
  const featKeys = [
    { key: 'market_impact',    label: 'MKT IMP' },
    { key: 'price_signal',     label: 'PRICE SIG' },
    { key: 'regulatory_risk',  label: 'REG RISK' },
    { key: 'timeliness',       label: 'TIMELY' },
    { key: 'impact',           label: 'IMPACT' },
    { key: 'controversy',      label: 'CONTROV' },
    { key: 'generalizability', label: 'GENERAL' },
    { key: 'impact_score',     label: 'TOTAL' },
  ];

  // classification all_scores
  const clfScores = Object.entries(clf.all_scores || {}).sort((a, b) => b[1] - a[1]);

  $detailBody.innerHTML = `
    <div class="d-title">${escHtml(news.title || '')}</div>
    <div class="d-meta">
      <span class="d-tag score ${levelClass(level)}">${score.toFixed(1)} · ${level}</span>
      <span class="d-tag" style="color:${catColor[clf.category] || '#6b7280'}">${catLabel[clf.category] || clf.category || '—'}</span>
      <span class="d-tag">${sourceName(news.source)}</span>
      <span class="d-tag">${fmtTime(news.published_at)}</span>
    </div>

    <div class="d-section">
      <div class="d-section-title">DK-COT 四维评分</div>
      <div class="d-scores">
        ${dims.map(d => {
          const v = dkScores[d.key] ?? 0;
          return `
            <div class="d-score-row">
              <span class="d-score-label">${d.label} <span style="color:var(--text-dim);font-size:9px">${d.weight}</span></span>
              <div class="d-score-track">
                <div class="d-score-fill" style="width:${v}%;background:${scoreColor(v)}"></div>
              </div>
              <span class="d-score-val" style="color:${scoreColor(v)}">${v.toFixed(1)}</span>
            </div>
          `;
        }).join('')}
        <div class="d-score-row" style="margin-top:4px;padding-top:6px;border-top:1px solid var(--border)">
          <span class="d-score-label" style="font-weight:700;color:var(--text-bright)">加权总分</span>
          <div class="d-score-track">
            <div class="d-score-fill" style="width:${score}%;background:${scoreColor(score)}"></div>
          </div>
          <span class="d-score-val" style="font-weight:700;color:${scoreColor(score)}">${score.toFixed(1)}</span>
        </div>
      </div>
    </div>

    <div class="d-section">
      <div class="d-section-title">7 维特征 (1-5)</div>
      <div class="d-features">
        ${featKeys.map(f => {
          const v = feat[f.key] ?? 0;
          return `
            <div class="d-feat">
              <div class="d-feat-val">${v.toFixed(2)}</div>
              <div class="d-feat-name">${f.label}</div>
            </div>
          `;
        }).join('')}
      </div>
    </div>

    <div class="d-section">
      <div class="d-section-title">分类置信度</div>
      <div class="d-clf-scores">
        ${clfScores.map(([cat, pct]) => `
          <div class="d-clf-row">
            <span class="d-clf-label" style="color:${catColor[cat] || '#6b7280'}">${catLabel[cat] || cat}</span>
            <div class="d-clf-bar">
              <div class="d-clf-fill" style="width:${pct * 100}%;background:${catColor[cat] || '#6b7280'}"></div>
            </div>
            <span class="d-clf-pct">${(pct * 100).toFixed(1)}%</span>
          </div>
        `).join('')}
      </div>
    </div>

    ${entities.length ? `
      <div class="d-section">
        <div class="d-section-title">识别实体</div>
        <div class="d-entities">
          ${entities.map(e => `
            <span class="d-entity">${escHtml(e.name)}<span class="d-entity-type">${e.type}</span></span>
          `).join('')}
        </div>
      </div>
    ` : ''}

    ${report.reasoning ? `
      <div class="d-section">
        <details class="d-reasoning-toggle">
          <summary class="d-section-title" style="cursor:pointer;user-select:none">DK-COT 推理过程 <span style="font-size:10px;color:var(--text-dim);font-weight:400">▶ 展开</span></summary>
          <div class="d-reasoning">${escHtml(report.reasoning)}</div>
        </details>
      </div>
    ` : ''}

    <div class="d-section">
      <div class="d-section-title">原文摘要</div>
      <p style="font-size:13px;line-height:1.7;color:var(--text)">${escHtml(news.content || '—')}</p>
      ${isValidUrl(news.url) ? `<a href="${escAttr(news.url)}" target="_blank" rel="noopener noreferrer" style="font-family:var(--font-mono);font-size:11px;color:var(--accent);margin-top:8px;display:inline-block">查看原文 →</a>` : ''}
    </div>
  `;

  $detailPanel.classList.add('open');

  // animate score bars
  requestAnimationFrame(() => {
    $detailBody.querySelectorAll('.d-score-fill, .d-clf-fill').forEach(el => {
      el.style.width = el.style.width; // trigger reflow
    });
  });
};

// details 展开/折叠提示文字切换
$detailBody.addEventListener('toggle', (e) => {
  if (e.target.tagName !== 'DETAILS') return;
  const hint = e.target.querySelector('summary span');
  if (hint) hint.textContent = e.target.open ? '▼ 折叠' : '▶ 展开';
}, true);

$detailClose.addEventListener('click', () => {
  $detailPanel.classList.remove('open');
  activeNewsId = null;
  document.querySelectorAll('.news-item.active').forEach(el => el.classList.remove('active'));
});

// close on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $detailPanel.classList.contains('open')) {
    $detailClose.click();
  }
});

// ── source bar ───────────────────────────────────────────
document.getElementById('sourceSelect').addEventListener('change', () => {
  const src = document.getElementById('sourceSelect').value;
  loadData(src);
  if (src === 'latest') startAutoRefresh();
  else stopAutoRefresh();
});

document.getElementById('sourceLoad').addEventListener('click', () => {
  const src = document.getElementById('sourceSelect').value;
  loadData(src);
  if (src === 'latest') startAutoRefresh();
  else stopAutoRefresh();
});

document.getElementById('fileBtn').addEventListener('click', () => {
  document.getElementById('fileInput').click();
});

document.getElementById('fileInput').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      allItems = JSON.parse(reader.result).filter(d => d.news && d.report);
      rangeLo = 0;
      rangeHi = 100;
      applyFilter();
    } catch (err) {
      alert('JSON 解析失败: ' + err.message);
    }
  };
  reader.readAsText(file);
});

// ── resize ───────────────────────────────────────────────
window.addEventListener('resize', () => { drawChart(); });

// ── init ─────────────────────────────────────────────────
initRangeSlider();

(async () => {
  await refreshBatchSelect();
  document.getElementById('sourceSelect').value = 'latest';
  await loadData('latest');
  startAutoRefresh();
})();
