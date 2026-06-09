/* 估值页面JS - 低频网格工具 */

// 状态管理
let state = { version: 1, sectors: [] };
let autoRefreshTimer = null;
let isRefreshing = false;
let lastRefreshTime = null;

// ============ API 调用 ============
async function loadState() {
    try {
        const res = await fetch(`${API_BASE}/v1/state`);
        state = await res.json();
        render();
    } catch (e) {
        showStatus('加载失败: ' + e.message, 'error');
    }
}

async function saveState() {
    try {
        await fetch(`${API_BASE}/v1/state`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(state)
        });
    } catch (e) {
        showStatus('保存失败', 'error');
    }
}

async function refreshAll() {
    if (isRefreshing) return;
    if (state.sectors.length === 0) return;

    const allCodes = [];
    state.sectors.forEach(s => s.funds.forEach(f => { if (f.code) allCodes.push(f.code); }));
    if (allCodes.length === 0) return;

    isRefreshing = true;
    const btn = document.getElementById('refreshBtn');
    if (btn) {
        btn.innerHTML = '<span class="loading"></span>刷新中';
        btn.disabled = true;
    }

    try {
        const res = await fetch(`${API_BASE}/v1/valuation/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fund_codes: allCodes })
        });

        if (!res.ok) throw new Error('请求失败');

        const data = await res.json();
        valuations = {};
        (data.items || []).forEach(item => {
            if (item?.fund_code) valuations[item.fund_code] = item;
        });

        render();
        lastRefreshTime = new Date();
        document.getElementById('updateTime').textContent =
            `更新于 ${lastRefreshTime.toLocaleTimeString()}`;
    } catch (e) {
        showStatus('刷新失败: ' + e.message, 'error');
    } finally {
        isRefreshing = false;
        if (btn) {
            btn.innerHTML = '🔄 刷新';
            btn.disabled = false;
        }
    }
}

// ============ 板块操作 ============
function showAddSectorModal() {
    document.getElementById('newSectorName').value = '';
    document.getElementById('addSectorModal').classList.add('show');
    document.getElementById('newSectorName').focus();
}

function addSector() {
    const name = document.getElementById('newSectorName').value.trim();
    if (!name) return;

    state.sectors.push({ name, funds: [] });
    saveState();
    render();
    closeModal('addSectorModal');
}

async function deleteSector(sectorIndex) {
    const sector = state.sectors[sectorIndex];
    if (!confirm(`确定删除板块「${sector.name}」及其所有基金？`)) return;
    state.sectors.splice(sectorIndex, 1);
    saveState();
    render();
}

// ============ 基金操作 ============
async function addFund(sectorIndex) {
    const form = document.querySelector(`#sector-${sectorIndex} .add-row`);
    const codeInput = form.querySelector('input[name="code"]');
    const aliasInput = form.querySelector('input[name="alias"]');
    const code = codeInput.value.trim();
    let alias = aliasInput.value.trim();

    if (!code || !/^\d{6}$/.test(code)) {
        showStatus('请输入6位基金代码', 'error');
        return;
    }

    // 检查重复
    const exists = state.sectors[sectorIndex].funds.some(f => f.code === code);
    if (exists) {
        showStatus('该基金已存在', 'error');
        return;
    }

    // 自动获取基金名称
    if (!alias) {
        const btn = form.querySelector('button');
        btn.innerHTML = '<span class="loading"></span>';
        btn.disabled = true;
        alias = await getFundName(code);
        btn.innerHTML = '添加';
        btn.disabled = false;
    }

    state.sectors[sectorIndex].funds.push({ code, alias });
    saveState();
    render();

    codeInput.value = '';
    aliasInput.value = '';

    // 添加后立即刷新估值
    refreshAll();
}

function deleteFund(sectorIndex, fundIndex) {
    state.sectors[sectorIndex].funds.splice(fundIndex, 1);
    saveState();
    render();
}

function showMoveFundModal(sectorIndex, fundIndex) {
    const fund = state.sectors[sectorIndex].funds[fundIndex];
    if (!fund) return;
    const displayName = valuations[fund.code]?.fund_name || fund.alias || fund.code;
    document.getElementById('moveFundTitle').textContent = `移动 ${fund.code} ${displayName}`;

    let html = '';
    state.sectors.forEach((sector, si) => {
        const isCurrent = si === sectorIndex;
        html += `<div style="padding:8px 10px;border-bottom:1px solid #f1f5f9;cursor:${isCurrent ? 'default' : 'pointer'};border-radius:4px;${isCurrent ? 'background:#eff6ff;' : ''}" ${isCurrent ? '' : `onclick="moveFund(${sectorIndex},${fundIndex},${si})"`}>
            <span style="font-size:12px;color:#374151;">📁 ${sector.name}</span>
            <span style="font-size:11px;color:#9ca3af;margin-left:8px;">${sector.funds.length}只基金</span>
            ${isCurrent ? '<span style="float:right;color:#4f46e5;font-size:11px;">✓ 当前</span>' : ''}
        </div>`;
    });
    document.getElementById('moveFundList').innerHTML = html;
    document.getElementById('moveFundModal').classList.add('show');
}

function moveFund(fromSector, fundIndex, toSector) {
    if (fromSector === toSector) return;
    const fund = state.sectors[fromSector].funds[fundIndex];
    if (!fund) return;
    // 检查目标板块是否已有同代码基金
    if (state.sectors[toSector].funds.some(f => f.code === fund.code)) {
        showStatus('目标板块已存在该基金', 'error');
        return;
    }
    state.sectors[fromSector].funds.splice(fundIndex, 1);
    state.sectors[toSector].funds.push(fund);
    saveState();
    closeModal('moveFundModal');
    render();
    showStatus(`已移动到「${state.sectors[toSector].name}」`, 'success');
}

// ============ ETF映射设置 ============
function showEtfLinkModal(linkCode) {
    document.getElementById('etfLinkCode').value = linkCode;
    document.getElementById('etfTargetCode').value = '';
    document.getElementById('etfLinkModal').classList.add('show');
    document.getElementById('etfTargetCode').focus();
}

async function saveEtfLink() {
    const linkCode = document.getElementById('etfLinkCode').value.trim();
    const etfCode = document.getElementById('etfTargetCode').value.trim();

    if (!etfCode || !/^\d{6}$/.test(etfCode)) {
        showStatus('请输入6位ETF代码', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/v1/etf-link`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ link_code: linkCode, etf_code: etfCode })
        });

        if (!res.ok) throw new Error('设置失败');

        showStatus(`已设置 ${linkCode} -> ${etfCode}`, 'success');
        closeModal('etfLinkModal');

        // 刷新估值
        await refreshAll();
    } catch (e) {
        showStatus('设置失败: ' + e.message, 'error');
    }
}

async function clearEtfLink() {
    const linkCode = document.getElementById('etfLinkCode').value.trim();

    try {
        await fetch(`${API_BASE}/v1/etf-link/${linkCode}`, { method: 'DELETE' });
        showStatus(`已清除 ${linkCode} 的映射`, 'success');
        closeModal('etfLinkModal');
        await refreshAll();
    } catch (e) {
        showStatus('清除失败', 'error');
    }
}

// ============ 自动刷新（交易时段感知） ============
function isTradeTime() {
    const now = new Date();
    const day = now.getDay();
    if (day === 0 || day === 6) return false;
    const hhmm = now.getHours() * 100 + now.getMinutes();
    // 9:15~11:35 和 12:55~15:05（留缓冲）
    return (hhmm >= 915 && hhmm <= 1135) || (hhmm >= 1255 && hhmm <= 1505);
}

function startAutoRefresh() {
    if (autoRefreshTimer) return;
    _scheduleNextRefresh();
    updateRefreshTimer();
}

function _scheduleNextRefresh() {
    if (autoRefreshTimer) clearTimeout(autoRefreshTimer);
    const interval = isTradeTime() ? 30000 : 300000; // 交易时段30s，非交易5min
    autoRefreshTimer = setTimeout(() => {
        if (state.sectors.some(s => s.funds.length > 0)) {
            refreshAll();
        }
        _scheduleNextRefresh();
    }, interval);
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
    setTimeout(updateRefreshTimer, 1000);
}

// ============ 渲染界面（估值看板） ============
function render() {
    const container = document.getElementById('sectors');

    if (state.sectors.length === 0) {
        container.innerHTML = `
            <div class="empty">
                <div class="empty-icon">📁</div>
                <p>点击"新建板块"开始</p>
            </div>
        `;
        return;
    }

    container.innerHTML = state.sectors.map((sector, si) => {
        // 按涨跌幅排序（由高到低）
        const sortedFunds = [...sector.funds].sort((a, b) => {
            const valA = valuations[a.code];
            const valB = valuations[b.code];
            const changeA = valA?.estimation_change ?? -999;
            const changeB = valB?.estimation_change ?? -999;
            return changeB - changeA;
        });

        return `
        <div class="sector" id="sector-${si}">
            <div class="sector-header">
                <span class="sector-name">${sector.name}</span>
                <div style="display:flex;gap:4px;">
                    <button class="btn-export" onclick="exportSectorImage(${si})" title="导出图片">📷</button>
                    <button class="btn-export" onclick="deleteSector(${si})" title="删除板块" style="color:#ef4444;">🗑</button>
                </div>
            </div>
            ${sector.funds.length === 0 ?
                '<div style="padding:20px;text-align:center;color:#9ca3af;font-size:12px;">暂无基金</div>' :
                `<table class="fund-table">
                    <thead>
                        <tr>
                            <th>代码</th>
                            <th>名称</th>
                            <th style="text-align:right">涨跌幅</th>
                            <th style="text-align:right">近5日</th>
                            <th style="text-align:right">近20日</th>
                            <th style="text-align:right">置信度</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${sortedFunds.map((fund) => {
                            const fi = sector.funds.findIndex(f => f.code === fund.code);
                            return renderFundRow(fund, si, fi);
                        }).join('')}
                    </tbody>
                </table>`
            }
            <div class="add-row">
                <input type="text" name="code" placeholder="代码" maxlength="6">
                <input type="text" name="alias" placeholder="名称（自动获取）">
                <button class="btn-primary" onclick="addFund(${si})">添加</button>
            </div>
        </div>
    `}).join('');
}

function renderFundRow(fund, sectorIndex, fundIndex) {
    const val = valuations[fund.code];
    let changeText = '--';
    let changeClass = 'flat';
    let confidence = '--';
    let weekText = '--';
    let weekClass = 'flat';
    let monthText = '--';
    let monthClass = 'flat';
    let displayName = fund.alias || '';
    let needsEtfLink = false;
    let isNav = false;

    if (val) {
        if (val.estimation_change !== null && val.estimation_change !== undefined) {
            const change = val.estimation_change;
            changeText = (change >= 0 ? '+' : '') + change.toFixed(2) + '%';
            changeClass = change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
            if (val._source === 'nav') isNav = true;
        }
        if (val.week_change !== null && val.week_change !== undefined) {
            const wc = val.week_change;
            weekText = (wc >= 0 ? '+' : '') + wc.toFixed(2) + '%';
            weekClass = wc > 0 ? 'up' : wc < 0 ? 'down' : 'flat';
        }
        if (val.month_change !== null && val.month_change !== undefined) {
            const mc = val.month_change;
            monthText = (mc >= 0 ? '+' : '') + mc.toFixed(2) + '%';
            monthClass = mc > 0 ? 'up' : mc < 0 ? 'down' : 'flat';
        }
        confidence = ((val.calibrated_confidence ?? val.confidence) * 100).toFixed(0) + '%';
        if (!displayName && val.fund_name) {
            displayName = val.fund_name;
        }
        if ((val.calibrated_confidence ?? val.confidence) < 0.15) {
            needsEtfLink = true;
        }
    }

    // ✓ 标记作为小号内联元素
    let navMark = '';
    if (isNav) {
        const navDate = val?._nav_date;
        const todayStr = new Date().toISOString().slice(0, 10);
        if (navDate && navDate !== todayStr) {
            const md = navDate.slice(5).replace(/^0/, '').replace(/-0?/, '/');
            navMark = `<span style="font-size:9px;margin-left:2px;color:#f59e0b;font-weight:400;" title="${navDate}净值">${md}</span>`;
        } else {
            navMark = '<span style="font-size:10px;margin-left:2px;color:#10b981;font-weight:400;">✓</span>';
        }
    }

    const etfBtn = needsEtfLink ?
        `<button onclick="showEtfLinkModal('${fund.code}')" title="设置ETF穿透" style="color:#f59e0b;">⚙</button>` : '';

    return `
        <tr>
            <td class="td-code" onclick="showNavHistory('${fund.code}')" title="点击查看近期涨跌">${fund.code}</td>
            <td class="td-name" title="${displayName}">${displayName}</td>
            <td class="td-change ${changeClass}" style="white-space:nowrap;">${changeText}${navMark}</td>
            <td class="td-change ${weekClass}">${weekText}</td>
            <td class="td-change ${monthClass}">${monthText}</td>
            <td class="td-confidence">${confidence}</td>
            <td class="td-action" style="white-space:nowrap;">
                ${etfBtn}
                <button onclick="addToStrategy('${fund.code}')" title="加入低频网格" style="color:#10b981;">📌</button>
                <button onclick="showMoveFundModal(${sectorIndex}, ${fundIndex})" title="移动到其他板块" style="color:#6366f1;">↗</button>
                <button onclick="deleteFund(${sectorIndex}, ${fundIndex})" title="删除">×</button>
            </td>
        </tr>
    `;
}

// ============ 加入策略持仓（跳转到策略页面） ============
async function addToStrategy(fundCode) {
    // 跳转到策略页面并带上参数
    window.location.href = `strategy.html?addFund=${fundCode}`;
}

// ============ 导出图片（实时估值板块） ============
async function exportSectorImage(sectorIndex) {
    const sector = state.sectors[sectorIndex];
    if (!sector || sector.funds.length === 0) {
        showStatus('板块为空，无法导出', 'error');
        return;
    }

    const sortedFunds = [...sector.funds]
        .filter(f => {
            const v = valuations[f.code];
            if (!v) return false;
            // 净值来源无视置信度判断，直接输出
            if (v._source === 'nav') return true;
            // 盘中估值：校准后置信度低于50%不输出
            return (v.calibrated_confidence ?? v.confidence) >= 0.50;
        })
        .sort((a, b) => {
        const valA = valuations[a.code];
        const valB = valuations[b.code];
        return (valB?.estimation_change ?? -999) - (valA?.estimation_change ?? -999);
    });

    if (sortedFunds.length === 0) {
        showStatus('没有置信度足够的基金可导出', 'error');
        return;
    }

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    const P = 16, rowH = 26, headH = 36, thH = 22, W = 560;
    const H = headH + thH + sortedFunds.length * rowH + P;

    // 列位置（右对齐基准点）
    const colCodeL = P;
    const colNameL = P + 58;
    const colChangeR = W - P - 155;  // 估值涨幅右边界
    const col5dayR = W - P - 78;     // 近5日右边界
    const col20dayR = W - P;          // 近20日右边界

    canvas.width = W * 2;
    canvas.height = H * 2;
    ctx.scale(2, 2);

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);

    // 标题
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 14px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.fillText(sector.name, P, P + 14);

    ctx.fillStyle = '#9ca3af';
    ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
    const timeStr = new Date().toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
    ctx.fillText(timeStr, W - P - ctx.measureText(timeStr).width, P + 14);

    // 表头
    ctx.fillStyle = '#f1f5f9';
    ctx.fillRect(0, headH, W, thH);
    ctx.fillStyle = '#64748b';
    ctx.font = '10px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.fillText('代码', colCodeL, headH + 15);
    ctx.fillText('基金名称', colNameL, headH + 15);
    let tw;
    tw = ctx.measureText('估值涨幅').width;
    ctx.fillText('估值涨幅', colChangeR - tw, headH + 15);
    tw = ctx.measureText('近5日').width;
    ctx.fillText('近5日', col5dayR - tw, headH + 15);
    tw = ctx.measureText('近20日').width;
    ctx.fillText('近20日', col20dayR - tw, headH + 15);

    // 数据行
    sortedFunds.forEach((fund, i) => {
        const y = headH + thH + i * rowH;
        const val = valuations[fund.code];
        const textY = y + 17;

        if (i % 2 === 1) { ctx.fillStyle = '#f8fafc'; ctx.fillRect(0, y, W, rowH); }

        // 代码
        ctx.fillStyle = '#6366f1';
        ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.fillText(fund.code, colCodeL, textY);

        // 名称
        ctx.fillStyle = '#334155';
        ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
        let name = fund.alias || val?.fund_name || '';
        if (name.length > 14) name = name.slice(0, 14) + '...';
        ctx.fillText(name, colNameL, textY);

        // 估值涨幅（右对齐）
        let chgTxt = '--', chgClr = '#64748b';
        if (val?.estimation_change != null) {
            const c = val.estimation_change;
            chgTxt = (c >= 0 ? '+' : '') + c.toFixed(2) + '%';
            chgClr = c > 0 ? '#ef4444' : c < 0 ? '#22c55e' : '#64748b';
        }
        ctx.fillStyle = chgClr;
        ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.fillText(chgTxt, colChangeR - ctx.measureText(chgTxt).width, textY);

        // 净值日期标注
        if (val?._source === 'nav' && val?._nav_date) {
            const todayCheck = new Date().toISOString().slice(0, 10);
            if (val._nav_date !== todayCheck) {
                const md = val._nav_date.slice(5).replace(/^0/, '').replace(/-0?/, '/');
                ctx.fillStyle = '#f59e0b';
                ctx.font = '9px -apple-system, BlinkMacSystemFont, sans-serif';
                ctx.fillText(md, colChangeR + 2, textY);
            }
        }

        // 近5日（右对齐）
        let wTxt = '--', wClr = '#64748b';
        if (val?.week_change != null) {
            const w = val.week_change;
            wTxt = (w >= 0 ? '+' : '') + w.toFixed(2) + '%';
            wClr = w > 0 ? '#ef4444' : w < 0 ? '#22c55e' : '#64748b';
        }
        ctx.fillStyle = wClr;
        ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.fillText(wTxt, col5dayR - ctx.measureText(wTxt).width, textY);

        // 近20日（右对齐）
        let mTxt = '--', mClr = '#64748b';
        if (val?.month_change != null) {
            const m = val.month_change;
            mTxt = (m >= 0 ? '+' : '') + m.toFixed(2) + '%';
            mClr = m > 0 ? '#ef4444' : m < 0 ? '#22c55e' : '#64748b';
        }
        ctx.fillStyle = mClr;
        ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.fillText(mTxt, col20dayR - ctx.measureText(mTxt).width, textY);
    });

    const link = document.createElement('a');
    link.download = `${sector.name}_${timeStr.replace(/[\/\s:]/g, '')}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
    showStatus('图片已导出', 'success');
}

async function exportAllSectorImages() {
    if (!state.sectors || state.sectors.length === 0) {
        showStatus('没有板块可导出', 'error');
        return;
    }
    let exported = 0;
    for (let i = 0; i < state.sectors.length; i++) {
        const sector = state.sectors[i];
        if (sector.funds.length === 0) continue;
        // 复用单板块导出，加延迟避免浏览器吞下载
        await exportSectorImage(i);
        exported++;
        if (i < state.sectors.length - 1) {
            await new Promise(r => setTimeout(r, 500));
        }
    }
    if (exported > 0) {
        showStatus(`已导出 ${exported} 个板块图片`, 'success');
    } else {
        showStatus('没有可导出的板块', 'error');
    }
}

// ============ 初始化 ============
window.onload = async () => {
    await loadState();
    if (state.sectors.some(s => s.funds.length > 0)) {
        await refreshAll();
    }
    startAutoRefresh();
};

// 回车/ESC 键处理
document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && document.getElementById('addSectorModal')?.classList.contains('show')) {
        addSector();
    }
    if (e.key === 'Enter' && document.getElementById('etfLinkModal')?.classList.contains('show')) {
        saveEtfLink();
    }
    if (e.key === 'Escape') {
        closeModal('addSectorModal');
        closeModal('etfLinkModal');
        closeModal('navHistoryModal');
        closeModal('moveFundModal');
    }
});
