/* 公共JS - 低频网格工具 */

// API基础路径
const API_BASE = '';

// 全局估值数据缓存
let valuations = {};

// ============ 状态提示 ============
function showStatus(msg, type = 'info') {
    const el = document.getElementById('status');
    if (!el) return;
    el.textContent = msg;
    el.className = `status show ${type}`;
    setTimeout(() => el.classList.remove('show'), 2500);
}

// ============ 弹窗控制 ============
function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('show');
}

// ============ 净值历史弹窗 ============
async function showNavHistory(fundCode) {
    const modal = document.getElementById('navHistoryModal');
    const title = document.getElementById('navHistoryTitle');
    const body = document.getElementById('navHistoryBody');

    if (!modal || !title || !body) {
        console.warn('净值历史弹窗元素不存在');
        return;
    }

    const val = valuations[fundCode];
    const name = val?.fund_name || fundCode;
    title.textContent = `${name}（${fundCode}）近期涨跌`;
    body.innerHTML = '<p style="text-align:center;color:#9ca3af;padding:20px;"><span class="loading"></span>加载中...</p>';
    modal.classList.add('show');

    try {
        const res = await fetch(`${API_BASE}/v1/fund/${fundCode}/nav-history?days=20`);
        const data = await res.json();
        const history = data.history || [];

        if (history.length === 0) {
            body.innerHTML = '<p style="text-align:center;color:#9ca3af;padding:20px;">暂无数据</p>';
            return;
        }

        // 找最大绝对值用于柱状图比例
        const maxAbs = Math.max(...history.map(h => Math.abs(h.change || 0)), 0.01);

        let html = `<table class="nav-history-table">
            <thead><tr>
                <th>日期</th>
                <th>净值</th>
                <th style="text-align:right">涨跌幅</th>
                <th style="width:80px"></th>
            </tr></thead><tbody>`;

        history.forEach(h => {
            const change = h.change;
            const cls = change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
            const changeStr = change != null ? ((change >= 0 ? '+' : '') + change.toFixed(2) + '%') : '--';
            const navStr = h.nav != null ? h.nav.toFixed(4) : '--';

            // 迷你柱状图
            const barWidth = change != null ? Math.round(Math.abs(change) / maxAbs * 60) : 0;
            const barColor = change > 0 ? '#fca5a5' : change < 0 ? '#86efac' : '#e5e7eb';
            const barHtml = barWidth > 0 ? `<span class="mini-bar" style="width:${barWidth}px;background:${barColor}"></span>` : '';

            html += `<tr>
                <td>${h.date || '--'}</td>
                <td>${navStr}</td>
                <td style="text-align:right" class="${cls}">${changeStr}</td>
                <td>${barHtml}</td>
            </tr>`;
        });

        html += '</tbody></table>';

        // 累计统计（复利计算）
        const validChanges = history.filter(h => h.change != null).map(h => h.change);
        if (validChanges.length >= 2) {
            const compoundReturn = (arr) => {
                let product = 1;
                for (const c of arr) product *= (1 + c / 100);
                return (product - 1) * 100;
            };
            const sum5 = compoundReturn(validChanges.slice(0, 5));
            const sum10 = compoundReturn(validChanges.slice(0, 10));
            const upDays = validChanges.filter(c => c > 0).length;
            const downDays = validChanges.filter(c => c < 0).length;
            html += `<div style="padding:8px 0;font-size:11px;color:#6b7280;display:flex;gap:16px;flex-wrap:wrap;">
                <span>近5日累计: <b style="color:${sum5>=0?'#dc2626':'#16a34a'}">${sum5>=0?'+':''}${sum5.toFixed(2)}%</b></span>
                <span>近10日累计: <b style="color:${sum10>=0?'#dc2626':'#16a34a'}">${sum10>=0?'+':''}${sum10.toFixed(2)}%</b></span>
                <span>涨${upDays}天 跌${downDays}天</span>
            </div>`;
        }

        body.innerHTML = html;
    } catch (e) {
        body.innerHTML = `<p style="text-align:center;color:#ef4444;padding:20px;">加载失败: ${e.message}</p>`;
    }
}

// ============ 获取基金名称 ============
async function getFundName(code) {
    try {
        const res = await fetch(`${API_BASE}/v1/fund/${code}/name`);
        const data = await res.json();
        return data.name || '';
    } catch {
        return '';
    }
}

// ============ 自动刷新（交易时段感知） ============
let autoRefreshTimer = null;
let displayTimer = null;
let lastRefreshTime = null;

function isTradeTime() {
    const now = new Date();
    const day = now.getDay();
    if (day === 0 || day === 6) return false;
    const hhmm = now.getHours() * 100 + now.getMinutes();
    // 9:15~11:35 和 12:55~15:05（留缓冲）
    return (hhmm >= 915 && hhmm <= 1135) || (hhmm >= 1255 && hhmm <= 1505);
}

function startAutoRefresh(refreshCallback) {
    stopAutoRefresh();  // 先清理旧定时器

    function scheduleNextRefresh() {
        if (autoRefreshTimer) clearTimeout(autoRefreshTimer);
        const interval = isTradeTime() ? 30000 : 300000; // 交易时段30s，非交易5min
        autoRefreshTimer = setTimeout(() => {
            if (refreshCallback) refreshCallback();
            scheduleNextRefresh();
        }, interval);
    }

    scheduleNextRefresh();
    updateRefreshTimer();
}

function updateRefreshTimer() {
    const el = document.getElementById('refreshTimer');
    const dot = document.querySelector('.refresh-status .dot');
    if (!el) return;

    const trading = isTradeTime();

    if (trading) {
        if (dot) dot.style.background = '#10b981';
        if (lastRefreshTime) {
            const ago = Math.floor((Date.now() - lastRefreshTime) / 1000);
            el.textContent = `${ago}s前更新 · 30s刷新`;
        } else {
            el.textContent = '🟢 30s自动刷新中';
        }
    } else {
        if (dot) dot.style.background = '#9ca3af';
        if (lastRefreshTime) {
            const ago = Math.floor((Date.now() - lastRefreshTime) / 1000);
            const agoText = ago < 60 ? `${ago}s` : `${Math.floor(ago/60)}m`;
            el.textContent = `⏸ 非交易时段 · ${agoText}前更新`;
        } else {
            el.textContent = '⏸ 非交易时段';
        }
    }
    if (displayTimer) clearTimeout(displayTimer);
    displayTimer = setTimeout(updateRefreshTimer, 1000);
}

function setLastRefreshTime(time) {
    lastRefreshTime = time;
}

function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearTimeout(autoRefreshTimer);
        autoRefreshTimer = null;
    }
    if (displayTimer) {
        clearTimeout(displayTimer);
        displayTimer = null;
    }
}
