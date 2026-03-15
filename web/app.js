/* ═══════════════════════════════════════════════════════════
   OpenNews Impact Terminal — app.js
   ═══════════════════════════════════════════════════════════ */

// ── theme toggle ──────────────────────────────────────────
const $themeToggle = document.getElementById('themeToggle');

function setTheme(light) {
  if (light) {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
  localStorage.setItem('theme', light ? 'light' : 'dark');
}

// init: localStorage > system preference > light (default)
{
  const saved = localStorage.getItem('theme');
  if (saved) {
    setTheme(saved === 'light');
  } else {
    setTheme(!window.matchMedia('(prefers-color-scheme: dark)').matches);
  }
}

$themeToggle.addEventListener('click', () => {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  setTheme(isDark);
});

// ── state ────────────────────────────────────────────────
let allItems = [];          // raw batch items
let filteredItems = [];     // after range filter
let rangeLo = 50;
let rangeHi = 100;
let activeNewsId = null;
let sortMode = 'score'; // 'score' | 'time' | 'avg'
let topicLang = localStorage.getItem('topicLang') || 'zh'; // 'zh' | 'en'

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
const $chartSummary = document.getElementById('chartSummary');

// stats
const $statTotal  = document.getElementById('statTotal');
const $statTopics = document.getElementById('statTopics');
const $statHigh   = document.getElementById('statHigh');
const $statMid    = document.getElementById('statMid');
const $statLow    = document.getElementById('statLow');

// ── helpers ──────────────────────────────────────────────
const getTopicLabel = (topic) => {
  const label = topic?.label;
  if (!label) return 'outlier';
  if (typeof label === 'string') return label;  // 兼容旧数据
  return label[topicLang] || label.zh || label.en || 'outlier';
};

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

// ── auto-refresh ─────────────────────────────────────────
let autoRefreshTimer = null;
const AUTO_REFRESH_INTERVAL = 30_000; // 30 秒

// ── data loading ─────────────────────────────────────────

async function loadData(source) {
  let data;
  try {
    let url;
    if (source.startsWith('hours:')) {
      const h = source.slice(6);
      url = `/api/records?hours=${h}`;
    } else if (source.startsWith('batch:')) {
      url = `/api/batches/${source.slice(6)}`;
    } else {
      url = source;
    }
    const resp = await fetch(url);
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
  if (!Array.isArray(data) || data.length === 0) {
    allItems = [];
    filteredItems = [];
    updateStats();
    drawChart();
    $topicList.innerHTML = '<div class="topics-loading">所选时间范围内无数据</div>';
    return;
  }
  allItems = data.filter(d => d.news && d.report);
  if (allItems.length === 0) {
    filteredItems = [];
    updateStats();
    drawChart();
    $topicList.innerHTML = '<div class="topics-loading">所选时间范围内无有效记录</div>';
    return;
  }

  applyFilter();

  // 自动刷新时：如果详情侧边栏打开，用新数据刷新内容
  if (activeNewsId) {
    const stillExists = allItems.find(d => d.news?.news_id === activeNewsId);
    if (stillExists) {
      showDetail(activeNewsId);
    }
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshTimer = setInterval(async () => {
    const src = document.getElementById('sourceSelect').value;
    await loadData(src);
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

  // update chart summary
  const totalCount = allItems.length;
  const above60 = allItems.filter(d => (d.report?.final_score ?? 0) >= 60).length;
  $chartSummary.textContent = `今天，OPENNEWS 分析了 ${totalCount} 篇新闻文章，其中 ${above60} 篇的评分超过 60 分。`;
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

  // bucket scores into 100 bins (0-1, 1-2, ..., 99-100)
  const binCount = 100;
  const bins = new Array(binCount).fill(0);
  allItems.forEach(d => {
    const s = d.report?.final_score ?? 0;
    const idx = Math.min(binCount - 1, Math.floor(s));
    bins[idx]++;
  });
  const maxBin = Math.max(...bins, 1);

  const padL = 36, padR = 12, padT = 20, padB = 24;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const barGap = 1;
  const barW = (plotW - barGap * (binCount - 1)) / binCount;

  // Y-axis grid lines (dashed)
  const yTicks = 4;
  ctx.lineWidth = 1;
  ctx.font = '500 9px "JetBrains Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= yTicks; i++) {
    const y = padT + plotH - (i / yTicks) * plotH;
    ctx.beginPath();
    ctx.setLineDash([3, 4]);
    ctx.strokeStyle = 'rgba(107,114,128,0.12)';
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
    ctx.stroke();
    ctx.setLineDash([]);
    const label = Math.round((i / yTicks) * maxBin);
    ctx.fillStyle = 'rgba(107,114,128,0.5)';
    ctx.fillText(label, padL - 6, y + 3);
  }

  // draw bars
  bins.forEach((v, i) => {
    const x = padL + i * (barW + barGap);
    const barH = (v / maxBin) * plotH;
    const y = padT + plotH - barH;

    // determine bar color based on score
    const midScore = i + 0.5;
    let barColor;
    if (midScore > 75) barColor = 'rgba(239,68,68,0.75)';
    else if (midScore > 40) barColor = 'rgba(245,158,11,0.75)';
    else barColor = 'rgba(34,197,94,0.75)';

    // dim if outside range
    const inRange = (i + 1) > rangeLo && i < rangeHi;
    if (!inRange) {
      barColor = 'rgba(107,114,128,0.15)';
    }

    ctx.fillStyle = barColor;
    ctx.fillRect(x, y, barW, barH);
  });

  // X-axis labels (every 10)
  ctx.fillStyle = '#6b7280';
  ctx.font = '500 9px "JetBrains Mono", monospace';
  ctx.textAlign = 'center';
  for (let i = 0; i <= 100; i += 10) {
    const x = padL + i * (barW + barGap);
    ctx.fillText(`${i}`, x, padT + plotH + 14);
  }
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
    // handle dot click — snap to integer value
    if (e.target.classList.contains('range-dot')) {
      const snapVal = parseInt(e.target.dataset.val, 10);
      const distLo = Math.abs(snapVal - rangeLo);
      const distHi = Math.abs(snapVal - rangeHi);
      if (distLo <= distHi) {
        rangeLo = Math.min(snapVal, rangeHi - 1);
      } else {
        rangeHi = Math.max(snapVal, rangeLo + 1);
      }
      applyFilter();
      return;
    }
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

  // group by batch_id:topic_id (topic_id alone is not unique across batches)
  const groups = new Map();
  filteredItems.forEach(item => {
    const tid = item.topic?.topic_id ?? -1;
    const bid = item.topic?.batch_id ?? 0;
    const groupKey = `${bid}:${tid}`;
    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        topic_id: groupKey,
        label: getTopicLabel(item.topic),
        items: [],
      });
    }
    groups.get(groupKey).items.push(item);
  });

  // sort groups based on sortMode
  let sorted;
  if (sortMode === 'time') {
    sorted = [...groups.values()].sort((a, b) => {
      const latestA = Math.max(...a.items.map(i => new Date(i.news?.published_at || 0).getTime()));
      const latestB = Math.max(...b.items.map(i => new Date(i.news?.published_at || 0).getTime()));
      return latestB - latestA;
    });
  } else if (sortMode === 'avg') {
    sorted = [...groups.values()].sort((a, b) => {
      const avgA = a.items.reduce((s, i) => s + (i.report?.final_score ?? 0), 0) / a.items.length;
      const avgB = b.items.reduce((s, i) => s + (i.report?.final_score ?? 0), 0) / b.items.length;
      return avgB - avgA;
    });
  } else {
    // default: sort by max score desc
    sorted = [...groups.values()].sort((a, b) => {
      const maxA = Math.max(...a.items.map(i => i.report?.final_score ?? 0));
      const maxB = Math.max(...b.items.map(i => i.report?.final_score ?? 0));
      return maxB - maxA;
    });
  }

  if (sorted.length === 0) {
    $topicList.innerHTML = '<div class="topics-loading">当前范围内无新闻数据</div>';
    return;
  }

  $topicList.innerHTML = sorted.map(g => {
    const scores = g.items.map(i => i.report?.final_score ?? 0);
    const maxScore = Math.max(...scores);
    const avgScore = (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1);

    // sort items by score desc
    g.items.sort((a, b) => (b.report?.final_score ?? 0) - (a.report?.final_score ?? 0));

    // 恢复展开状态
    const isOpen = openTopics.has(String(g.topic_id));

    // 统计来源分布
    const srcCounts = {};
    g.items.forEach(i => {
      const s = sourceName(i.news?.source);
      srcCounts[s] = (srcCounts[s] || 0) + 1;
    });
    const srcText = Object.entries(srcCounts).map(([s, c]) => `${s} +${c}`).join('，');

    // 最新新闻的时间差
    const latestTime = g.items.reduce((latest, i) => {
      const t = i.news?.published_at;
      if (!t) return latest;
      const d = new Date(t);
      return (!latest || d > latest) ? d : latest;
    }, null);
    const timeAgo = latestTime ? fmtTimeAgo(latestTime.toISOString()) : '';

    return `
      <div class="topic-card${isOpen ? ' open' : ''}" data-tid="${escAttr(g.topic_id)}">
        <div class="topic-head" onclick="toggleTopic('${escAttr(g.topic_id)}')">
          <span class="topic-arrow">▶</span>
          <span class="topic-avg-score" style="color:${scoreColor(parseFloat(avgScore))}">${avgScore}</span>
          <span class="topic-label">${escHtml(g.label)}<span class="topic-src-info">（${escHtml(srcText)}）</span></span>
          ${timeAgo ? `<span class="topic-time-ago">${timeAgo}</span>` : ''}
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

const fmtTimeAgo = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 0) return '0m';
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(mins / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) {
    const remH = hours - days * 24;
    return remH > 0 ? `${days}d${remH}h` : `${days}d`;
  }
  if (hours > 0) {
    const remM = mins - hours * 60;
    return remM > 0 ? `${hours}h${remM}m` : `${hours}h`;
  }
  return `${mins}m`;
};

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

  // redraw chart after transition completes (main area resizes)
  setTimeout(() => drawChart(), 380);

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
  // redraw chart after transition completes (main area resizes)
  setTimeout(() => drawChart(), 380);
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
  startAutoRefresh();
});

document.getElementById('sourceLoad').addEventListener('click', () => {
  const src = document.getElementById('sourceSelect').value;
  loadData(src);
  startAutoRefresh();
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
      applyFilter();
    } catch (err) {
      alert('JSON 解析失败: ' + err.message);
    }
  };
  reader.readAsText(file);
});

// ── sort buttons ──────────────────────────────────────────
document.querySelectorAll('.sort-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    sortMode = btn.dataset.sort;
    renderTopics();
  });
});

// ── language switch ───────────────────────────────────────
{
  const $langSwitch = document.getElementById('langSwitch');
  // init active state from stored preference
  $langSwitch.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === topicLang);
  });
  $langSwitch.addEventListener('click', (e) => {
    const btn = e.target.closest('.lang-btn');
    if (!btn) return;
    topicLang = btn.dataset.lang;
    localStorage.setItem('topicLang', topicLang);
    $langSwitch.querySelectorAll('.lang-btn').forEach(b => b.classList.toggle('active', b.dataset.lang === topicLang));
    renderTopics();
  });
}

// ── resize ───────────────────────────────────────────────
window.addEventListener('resize', () => { drawChart(); });

// ── init ─────────────────────────────────────────────────
initRangeSlider();

(async () => {
  const $sel = document.getElementById('sourceSelect');
  await loadData($sel.value);
  startAutoRefresh();
})();
