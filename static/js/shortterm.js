/**
 * shortterm.js - 7天短线策略前端逻辑（完全独立，不依赖 strategy.js）
 */

// ============ 全局变量 ============
const API_BASE = window.location.origin;

let shorttermConfig = {};
let shorttermSignals = [];

// ============ 工具函数 ============

function showStatus(msg, type = 'info') {
    const el = document.getElementById('status');
    if (!el) return;
    el.textContent = msg;
    el.className = 'status ' + type;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 3000);
}

function closeModal(id) {
    document.getElementById(id)?.classList.remove('show');
}

function formatPct(v) {
    if (v == null) return '--';
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function toggleConfigPanel() {
    const panel = document.getElementById('configPanel');
    if (panel) {
        panel.classList.toggle('collapsed');
        panel.classList.toggle('expanded');
    }
}

// ============ 配置管理 ============

const CONFIG_FIELDS = [
    { key: 'stop_loss_pct', label: '止损线 (%)', hint: '浮亏达到此比例触发止损', default: -10 },
    { key: 'stop_loss_max_pct', label: '最大止损 (%)', hint: '强制止损线', default: -15 },
    { key: 'take_profit_target', label: '目标止盈 (%)', hint: '落袋为安的目标收益', default: 5 },
    { key: 'take_profit_tier1', label: '分批止盈档位1 (%)', hint: '达到后减仓1/3', default: 15 },
    { key: 'take_profit_tier2', label: '分批止盈档位2 (%)', hint: '达到后再减1/3', default: 20 },
    { key: 'trail_stop_pct', label: '回撤止盈触发 (%)', hint: '峰值回撤此比例清仓', default: 5 },
    { key: 'trail_activate_profit', label: '回撤止盈激活 (%)', hint: '盈利超过此值才启用回撤止盈', default: 10 },
    { key: 'first_build_ratio', label: '首次建仓比例', hint: '首次买入占仓位比例', default: 0.30, isRatio: true },
    { key: 'supplement_ratio', label: '补仓比例', hint: '确认后补仓比例', default: 0.20, isRatio: true },
    { key: 'cooldown_days', label: '止损冷却期 (天)', hint: '止损后等待天数', default: 14 },
    { key: 'dip_buy_threshold', label: '回调买入阈值 (%)', hint: '日内跌幅触发买入', default: -2 },
    { key: 'bounce_buy_threshold', label: '反弹买入阈值 (%)', hint: '连跌后反弹触发', default: 0.5 },
];

async function loadConfig() {
    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/config`);
        shorttermConfig = await res.json();
        renderConfig();
    } catch (e) {
        console.error('加载配置失败:', e);
    }
}

function renderConfig() {
    const grid = document.getElementById('configGrid');
    if (!grid) return;

    let html = '';
    for (const field of CONFIG_FIELDS) {
        const value = shorttermConfig[field.key] ?? field.default;
        const displayValue = field.isRatio ? (value * 100).toFixed(0) : value;
        html += `
            <div class="config-item">
                <label>${field.label}</label>
                <input type="number" id="config_${field.key}" value="${displayValue}" step="${field.isRatio ? '5' : '0.5'}">
                <div class="hint">${field.hint}</div>
            </div>
        `;
    }
    grid.innerHTML = html;
}

async function saveConfig() {
    const updates = {};
    for (const field of CONFIG_FIELDS) {
        const input = document.getElementById(`config_${field.key}`);
        if (!input) continue;
        let value = parseFloat(input.value);
        if (field.isRatio) value = value / 100;
        updates[field.key] = value;
    }

    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });
        const data = await res.json();
        if (data.success) {
            shorttermConfig = data.config;
            showStatus('配置已保存', 'success');
        }
    } catch (e) {
        showStatus('保存配置失败: ' + e.message, 'error');
    }
}

async function resetConfig() {
    if (!confirm('确定恢复默认配置？')) return;
    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/config/reset`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            shorttermConfig = data.config;
            renderConfig();
            showStatus('已恢复默认配置', 'success');
        }
    } catch (e) {
        showStatus('重置失败: ' + e.message, 'error');
    }
}

// ============ 添加基金 ============

function showAddFundModal() {
    const modal = document.getElementById('addFundModal');
    document.getElementById('addFundCode').value = '';
    document.getElementById('fundPreview').style.display = 'none';
    document.getElementById('confirmAddFundBtn').disabled = true;
    modal.classList.add('show');
    // 聚焦输入框
    setTimeout(() => document.getElementById('addFundCode')?.focus(), 100);
}

async function validateFundCode() {
    const code = document.getElementById('addFundCode').value.trim();
    const preview = document.getElementById('fundPreview');
    const btn = document.getElementById('confirmAddFundBtn');
    const previewCode = document.getElementById('previewCode');
    const previewName = document.getElementById('previewName');

    // 验证6位数字
    if (!/^\d{6}$/.test(code)) {
        preview.style.display = 'none';
        btn.disabled = true;
        return;
    }

    // 检查是否已存在
    if (shorttermSignals.some(s => s.fund_code === code)) {
        preview.style.display = 'block';
        preview.style.background = '#fef2f2';
        previewCode.textContent = code;
        previewName.textContent = '该基金已在列表中';
        btn.disabled = true;
        return;
    }

    // 获取基金名称
    try {
        const res = await fetch(`${API_BASE}/v1/fund/${code}/name`);
        const data = await res.json();
        if (data.name) {
            preview.style.display = 'block';
            preview.style.background = '#f8fafc';
            previewCode.textContent = code;
            previewName.textContent = data.name;
            btn.disabled = false;
        } else {
            preview.style.display = 'block';
            preview.style.background = '#fef2f2';
            previewCode.textContent = code;
            previewName.textContent = '未找到该基金';
            btn.disabled = true;
        }
    } catch (e) {
        preview.style.display = 'none';
        btn.disabled = true;
    }
}

function confirmAddFund() {
    const code = document.getElementById('addFundCode').value.trim();
    const name = document.getElementById('previewName').textContent;

    closeModal('addFundModal');
    addFund(code, name);  // 复用现有函数
}

function debounce(fn, delay) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

async function addFund(fundCode, fundName) {
    closeModal('addFundModal');

    // 打开买入弹窗
    document.getElementById('buyFundCode').value = fundCode;
    document.getElementById('buyFundName').value = fundName;
    document.getElementById('buyModalTitle').textContent = `买入 · ${fundCode} ${fundName}`;
    document.getElementById('buyAmount').value = '';
    document.getElementById('buyNav').value = '';
    document.getElementById('buyNote').value = '短线策略';
    document.getElementById('buyDate').value = new Date().toISOString().slice(0, 10);
    document.getElementById('buyMaxPosition').value = '5000';

    document.getElementById('buyModal').classList.add('show');
}

// ============ 买入/卖出操作 ============

async function submitBuy() {
    const fundCode = document.getElementById('buyFundCode').value;
    const amount = parseFloat(document.getElementById('buyAmount').value) || 0;
    const nav = parseFloat(document.getElementById('buyNav').value) || null;
    const note = document.getElementById('buyNote').value.trim();
    const buyDate = document.getElementById('buyDate').value;
    const maxPosition = parseFloat(document.getElementById('buyMaxPosition').value) || 5000;
    const fundName = document.getElementById('buyFundName').value;

    if (amount <= 0) {
        showStatus('请输入有效金额', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/position/${encodeURIComponent(fundCode)}/buy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                amount, nav, note, buy_date: buyDate,
                max_position: maxPosition, fund_name: fundName
            })
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || '买入失败');
        }
        showStatus(`买入成功: ${fundCode} ${data.batch?.id || ''}`, 'success');
        closeModal('buyModal');
        loadSignalPanel();
    } catch (e) {
        showStatus('买入失败: ' + e.message, 'error');
    }
}

function showSellModal(fundCode, batchId, shares, profitPct) {
    document.getElementById('sellFundCode').value = fundCode;
    document.getElementById('sellBatchId').value = batchId;
    document.getElementById('sellShares').value = shares.toFixed(2);
    document.getElementById('sellNav').value = '';
    document.getElementById('sellDate').value = new Date().toISOString().slice(0, 10);

    document.getElementById('sellModalTitle').textContent = `卖出 · ${fundCode}`;
    document.getElementById('sellHint').textContent = `批次 ${batchId}，当前盈亏 ${formatPct(profitPct)}`;

    document.getElementById('sellModal').classList.add('show');
}

async function submitSell() {
    const fundCode = document.getElementById('sellFundCode').value;
    const batchId = document.getElementById('sellBatchId').value;
    const sellShares = parseFloat(document.getElementById('sellShares').value) || 0;
    const sellNav = parseFloat(document.getElementById('sellNav').value) || null;
    const sellDate = document.getElementById('sellDate').value;

    if (sellShares <= 0) {
        showStatus('请输入有效份额', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/position/${encodeURIComponent(fundCode)}/sell`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                batch_id: batchId, sell_shares: sellShares,
                sell_nav: sellNav, sell_date: sellDate
            })
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || '卖出失败');
        }
        showStatus('卖出成功', 'success');
        closeModal('sellModal');
        loadSignalPanel();
    } catch (e) {
        showStatus('卖出失败: ' + e.message, 'error');
    }
}

async function removeFund(fundCode) {
    if (!confirm(`确定移除 ${fundCode}？这将删除所有持仓记录。`)) return;

    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/position/${encodeURIComponent(fundCode)}`, {
            method: 'DELETE'
        });
        if (!res.ok) throw new Error('移除失败');
        showStatus(`已移除 ${fundCode}`, 'success');
        loadSignalPanel();
    } catch (e) {
        showStatus('移除失败: ' + e.message, 'error');
    }
}

// ============ 信号面板 ============

async function loadSignalPanel() {
    const panel = document.getElementById('signalPanel');
    if (!panel) return;

    panel.innerHTML = '<div style="text-align:center;padding:20px;color:#9ca3af;"><span class="loading"></span>加载信号中...</div>';

    try {
        const res = await fetch(`${API_BASE}/v1/shortterm/signals`);
        const data = await res.json();
        shorttermSignals = data.signals || [];
        shorttermConfig = data.config || shorttermConfig;

        renderSignalPanel(data);
    } catch (e) {
        panel.innerHTML = `<div style="text-align:center;padding:20px;color:#ef4444;">加载失败: ${e.message}</div>`;
    }
}

function renderSignalPanel(data) {
    const panel = document.getElementById('signalPanel');

    // 工具栏
    let html = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <span style="font-size:12px;color:#6b7280;">共 ${shorttermSignals.length} 只基金</span>
            <div style="display:flex;gap:6px;">
                <button class="btn-success" onclick="showAddFundModal()" style="padding:4px 12px;font-size:11px;">➕ 添加基金</button>
                <button class="btn-primary" onclick="loadSignalPanel()" style="padding:4px 12px;font-size:11px;">🔄 刷新信号</button>
            </div>
        </div>
    `;

    if (shorttermSignals.length === 0) {
        html += `
            <div class="empty">
                <div class="empty-icon">⚡</div>
                <p>暂无基金</p>
                <p style="font-size:11px;color:#9ca3af;margin-top:8px;">点击"添加基金"从板块选择</p>
            </div>
        `;
        panel.innerHTML = html;
        return;
    }

    // 分类
    const withSignal = shorttermSignals.filter(s => s.action !== 'hold');
    const noSignal = shorttermSignals.filter(s => s.action === 'hold');

    // 有信号的卡片
    for (const sig of withSignal) {
        html += renderSignalCard(sig);
    }

    // 无信号的卡片（折叠）
    if (noSignal.length > 0) {
        html += `<div style="font-size:12px;color:#9ca3af;padding:8px 0;">观望中 (${noSignal.length}只)</div>`;
        for (const sig of noSignal.slice(0, 5)) {
            html += renderSignalCard(sig, true);
        }
        if (noSignal.length > 5) {
            html += `<div style="font-size:11px;color:#9ca3af;padding:4px 0;">... 还有 ${noSignal.length - 5} 只</div>`;
        }
    }

    panel.innerHTML = html;

    // 更新时间
    document.getElementById('updateTime').textContent = `更新于 ${data.generated_at || ''}`;
}

function renderSignalCard(sig, compact = false) {
    const ma = sig.market_analysis || {};
    const isSell = sig.action === 'sell';
    const isStopLoss = sig.is_stop_loss;

    let cardClass = sig.action;
    if (isStopLoss) cardClass = 'stop-loss';
    else if (sig.signal_name?.includes('止盈')) cardClass = 'take-profit';

    const profitPct = sig.profit_pct ?? ma.total_profit_pct ?? 0;
    const profitColor = profitPct >= 0 ? 'up' : 'down';

    let html = `<div class="signal-card ${cardClass}">
        <div class="signal-card-header">
            <div class="fund-info">
                <span class="code">${sig.fund_code}</span>
                ${sig.fund_name ? `<span class="name">${sig.fund_name}</span>` : ''}
            </div>
            <span class="signal-badge ${sig.action}">${sig.signal_name}</span>
        </div>
        <div class="signal-card-body">`;

    // 指标
    html += `<div class="signal-metrics">
        <div class="metric"><span class="label">今日:</span><span class="value ${ma.today_change > 0 ? 'up' : ma.today_change < 0 ? 'down' : ''}">${formatPct(ma.today_change)}</span></div>
        <div class="metric"><span class="label">浮盈:</span><span class="value ${profitColor}">${formatPct(profitPct)}</span></div>
        <div class="metric"><span class="label">趋势:</span><span class="value">${ma.trend || '震荡'}</span></div>
    </div>`;

    // 原因
    const reasonClass = isStopLoss ? 'danger' : sig.signal_name?.includes('止盈') ? 'warning' : '';
    html += `<div class="signal-reason ${reasonClass}">${sig.reason || ''}</div>`;

    // 买入/卖出金额
    if (sig.action === 'buy' && sig.amount) {
        html += `<div class="signal-amount">建议买入: ¥${sig.amount.toFixed(0)}</div>`;
    } else if (isSell && sig.sell_pct) {
        html += `<div class="signal-amount sell">建议卖出: ${sig.sell_pct}%${sig.target_batch_id ? ` (${sig.target_batch_id})` : ''}</div>`;
    }

    // 操作按钮
    html += `<div class="signal-actions">`;
    if (sig.action === 'buy' && sig.amount) {
        html += `<button class="buy-btn" onclick="quickBuy('${sig.fund_code}', ${sig.amount}, '${(sig.fund_name || '').replace(/'/g, "\\'")}')">一键买入</button>`;
    } else if (isSell && sig.target_batch_id) {
        html += `<button class="sell-btn" onclick="showSellModal('${sig.fund_code}', '${sig.target_batch_id}', ${sig.sell_shares || 0}, ${profitPct})">执行卖出</button>`;
    }
    html += `<button onclick="removeFund('${sig.fund_code}')" style="color:#9ca3af;">移除</button>`;
    html += `</div>`;

    html += `</div></div>`;
    return html;
}

function quickBuy(fundCode, amount, fundName) {
    document.getElementById('buyFundCode').value = fundCode;
    document.getElementById('buyFundName').value = fundName;
    document.getElementById('buyModalTitle').textContent = `买入 · ${fundCode} ${fundName}`;
    document.getElementById('buyAmount').value = amount.toFixed(0);
    document.getElementById('buyNav').value = '';
    document.getElementById('buyNote').value = '短线策略';
    document.getElementById('buyDate').value = new Date().toISOString().slice(0, 10);
    document.getElementById('buyMaxPosition').value = '5000';

    document.getElementById('buyModal').classList.add('show');
}

// ============ 初始化 ============

async function init() {
    // 添加基金代码输入框事件监听
    const addFundInput = document.getElementById('addFundCode');
    if (addFundInput) {
        addFundInput.addEventListener('input', debounce(validateFundCode, 300));
    }

    await loadConfig();
    await loadSignalPanel();
}

// 键盘事件
document.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        if (document.getElementById('buyModal')?.classList.contains('show')) {
            submitBuy();
        } else if (document.getElementById('sellModal')?.classList.contains('show')) {
            submitSell();
        }
    }
    if (e.key === 'Escape') {
        closeModal('buyModal');
        closeModal('sellModal');
        closeModal('addFundModal');
    }
});

// 页面加载完成后初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
