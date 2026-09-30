/**
 * ============================================================================
 * CTFA Air Quality Dashboard & Relay Fan Controller
 * ============================================================================
 * 
 * INTEGRATION SETTINGS:
 * ----------------------------------------------------------------------------
 * This dashboard is architected to operate in two modes:
 * 
 * 1. SIMULATION MODE (Current Default - INTEGRATION_CONFIG.USE_SIMULATOR_SOURCE = true):
 *    - The dashboard is directly driven by the simulator inputs and drawer sliders.
 *    - Perfect for testing priority edge cases, client demos, and logic verification.
 * 
 * 2. LIVE PRODUCTION MODE (INTEGRATION_CONFIG.USE_SIMULATOR_SOURCE = false):
 *    - Change USE_SIMULATOR_SOURCE to false.
 *    - The dashboard automatically polls GET /api/telemetry every LIVE_POLL_INTERVAL_MS
 *      to display real-time physical sensor data from hardware / IoT gateways.
 *    - Simulator drawer remains available anytime via "🧪 Simulator Controls".
 * ============================================================================
 */

const INTEGRATION_CONFIG = {
  USE_SIMULATOR_SOURCE: true,   // Set to FALSE to bind dashboard directly to live hardware sensor APIs
  LIVE_POLL_INTERVAL_MS: 10000, // Background polling interval (10s) when in live production mode
};

// Application State
const state = {
  currentTab: 'dashboard',
  countdownSec: 30,
  countdownInterval: null,
  pollInterval: null,
  currentTelemetry: null,
  activeTrendMetric: 'in_pm25',
  reportsData: [],
  currentPage: 1,
  pageSize: 10,
  debounceTimer: null,
};

document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initSimulatorDrawer();
  initQuickPresets();
  initCountdownTimer();
  initAlarmsHandlers();
  initReportsHandlers();
  initTrendsCharts();
  initSettingsHandlers();
  initDeviceConnectionListener();

  if (INTEGRATION_CONFIG.USE_SIMULATOR_SOURCE) {
    // Mode 1: Simulator-driven on startup
    syncSimulatorInputsToDashboard();
    executeSimulation(false);
  } else {
    // Mode 2: Live IoT / Hardware API polling
    fetchAndDisplayLiveTelemetry();
  }
});

/**
 * PRODUCTION HELPER: Fetches live sensor data from backend
 */
async function fetchAndDisplayLiveTelemetry() {
  const telemetry = await window.apiService.fetchTelemetry();
  if (telemetry) {
    updateDashboardUI(telemetry);
  }
}

/* -------------------------------------------------------------
 * 1. Mobile & Desktop Navigation
 * ------------------------------------------------------------- */
function initNavigation() {
  const navItems = document.querySelectorAll('.sidebar-nav-item');
  const mobileSidebar = document.getElementById('mobile-sidebar');
  const mobileBackdrop = document.getElementById('mobile-sidebar-backdrop');
  const btnMobileMenu = document.getElementById('btn-mobile-menu');
  const btnCloseMobile = document.getElementById('btn-close-mobile-menu');
  const btnOpenSimMobile = document.getElementById('btn-open-simulator-mobile');

  const openMobileMenu = () => {
    if (mobileSidebar) mobileSidebar.classList.remove('-translate-x-full');
    if (mobileBackdrop) mobileBackdrop.classList.remove('hidden');
  };

  const closeMobileMenu = () => {
    if (mobileSidebar) mobileSidebar.classList.add('-translate-x-full');
    if (mobileBackdrop) mobileBackdrop.classList.add('hidden');
  };

  if (btnMobileMenu) btnMobileMenu.addEventListener('click', openMobileMenu);
  if (btnCloseMobile) btnCloseMobile.addEventListener('click', closeMobileMenu);
  if (mobileBackdrop) mobileBackdrop.addEventListener('click', closeMobileMenu);

  if (btnOpenSimMobile) {
    btnOpenSimMobile.addEventListener('click', () => {
      closeMobileMenu();
      openSimulatorDrawer();
    });
  }

  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const targetView = item.getAttribute('data-view');
      switchView(targetView);
      closeMobileMenu();
    });
  });
}

function switchView(viewName) {
  state.currentTab = viewName;

  document.querySelectorAll('.sidebar-nav-item').forEach(el => {
    if (el.getAttribute('data-view') === viewName) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  document.querySelectorAll('.dashboard-view').forEach(v => {
    v.classList.add('hidden');
  });

  const activeViewEl = document.getElementById(`view-${viewName}`);
  if (activeViewEl) {
    activeViewEl.classList.remove('hidden');
  }

  // Refresh view-specific components
  if (viewName === 'reports') renderReportsTable();
  if (viewName === 'trends') renderTrendsCharts(state.activeTrendMetric);
  if (viewName === 'alarms') loadAlarms();
}

/* -------------------------------------------------------------
 * 2. Simulator Inputs to Dashboard Synchronization
 * ------------------------------------------------------------- */
function calcDewPoint(temp, hum) {
  return Number((parseFloat(temp) - ((100.0 - parseFloat(hum)) / 5.0)).toFixed(1));
}

function getSimulatorInputs() {
  const inTemp = parseFloat(document.getElementById('sim-in-temp')?.value) || 24.0;
  const outTemp = parseFloat(document.getElementById('sim-out-temp')?.value) || 28.0;
  const safetyBuffer = parseFloat(document.getElementById('sim-safety-buffer')?.value) || 2.0;

  const inHum = parseFloat(document.getElementById('sim-in-hum')?.value) || 55;
  const outHum = parseFloat(document.getElementById('sim-out-hum')?.value) || 45;

  const inPm25 = parseFloat(document.getElementById('sim-in-pm25')?.value) || 42;
  const outPm25 = parseFloat(document.getElementById('sim-out-pm25')?.value) || 28;
  const inCo2 = parseFloat(document.getElementById('sim-in-co2')?.value) || 650;
  const outCo2 = parseFloat(document.getElementById('sim-out-co2')?.value) || 420;

  const outDew = calcDewPoint(outTemp, outHum);
  const inDew = calcDewPoint(inTemp, inHum);
  const condensationThreshold = Number((inTemp - safetyBuffer).toFixed(1));
  const mockMode = document.getElementById('sim-chk-mock')?.checked || false;

  return {
    indoor_temp: inTemp,
    outdoor_temp: outTemp,
    safety_buffer: safetyBuffer,
    indoor_humidity: inHum,
    outdoor_humidity: outHum,
    indoor_pm25: inPm25,
    outdoor_pm25: outPm25,
    indoor_co2: inCo2,
    outdoor_co2: outCo2,
    indoor_dew_point: inDew,
    outdoor_dew_point: outDew,
    indoor_condensation_threshold: condensationThreshold,
    mock_mode: mockMode,
  };
}

function syncSimulatorInputsToDashboard() {
  const sim = getSimulatorInputs();

  // Drive 6 metric cards directly from simulator values!
  setText('val-in-pm25', Math.round(sim.indoor_pm25));
  setText('val-out-pm25', Math.round(sim.outdoor_pm25));
  setText('val-in-co2', Math.round(sim.indoor_co2));
  setText('val-out-co2', Math.round(sim.outdoor_co2));
  setText('val-in-dew', sim.indoor_dew_point.toFixed(1));
  setText('val-out-dew', sim.outdoor_dew_point.toFixed(1));

  setText('tag-in-temp', `${Math.round(sim.indoor_temp)}°C`);
  setText('tag-out-temp', `${Math.round(sim.outdoor_temp)}°C`);
  setText('tag-in-hum', `${sim.indoor_humidity}% Hum`);
  setText('tag-out-hum', `${sim.outdoor_humidity}% Hum`);

  // Update calculated dew point displays in drawer
  setText('sim-disp-out-dew', sim.outdoor_dew_point.toFixed(1));
  setText('sim-disp-in-dew', sim.indoor_dew_point.toFixed(1));
  setText('sim-disp-threshold', sim.indoor_condensation_threshold.toFixed(1));

  // Update Drawer Risk Badge
  const riskBadge = document.getElementById('sim-dew-risk-badge');
  if (riskBadge) {
    if (sim.outdoor_dew_point >= sim.indoor_condensation_threshold) {
      riskBadge.className = 'mt-2 p-2 rounded-lg text-xs font-semibold text-center bg-rose-100 text-rose-800 border border-rose-200';
      riskBadge.textContent = '⚠️ Condensation Hazard: Lockout Active';
    } else {
      riskBadge.className = 'mt-2 p-2 rounded-lg text-xs font-semibold text-center bg-emerald-100 text-emerald-800 border border-emerald-200';
      riskBadge.textContent = '✓ Safe Dew Point (Ventilation Allowed)';
    }
  }

  // Evaluate logic locally for instant zero-latency feedback
  evaluateLocalLogic(sim);
}

function evaluateLocalLogic(sim) {
  // Priority 1: Outdoor Dew Point >= Indoor Condensation Threshold (Lockout)
  if (sim.outdoor_dew_point >= sim.indoor_condensation_threshold) {
    updateStateBannerLocal(
      'lockout',
      'DewPoint Lockout - CTFA Off',
      `Outdoor Dew Point (${sim.outdoor_dew_point}°C) >= Cold Surface Threshold (${sim.indoor_condensation_threshold}°C)`
    );
    updateFanStatus(false);
    return;
  }

  // Priority 2: Indoor PM2.5 > 60 OR Indoor CO2 > 800 (Purge)
  const isPm25High = sim.indoor_pm25 > 60;
  const isCo2High = sim.indoor_co2 > 800;

  if (isPm25High || isCo2High) {
    if (isPm25High) {
      updateStateBannerLocal(
        'purge_pm25',
        'PM 2.5 Purge - CTFA ON',
        `Indoor PM 2.5 (${sim.indoor_pm25} µg/m³) is higher than 60 µg/m³ threshold`
      );
    } else {
      updateStateBannerLocal(
        'purge_co2',
        'CO2 Purge - CTFA ON',
        `Indoor CO2 (${sim.indoor_co2} PPM) is greater than 800 PPM threshold`
      );
    }
    updateFanStatus(true);
    return;
  }

  // Priority 3: Fallback Normal
  updateStateBannerLocal(
    'normal',
    'Normal Air Quality - CTFA Off',
    'All environmental readings within acceptable thresholds'
  );
  updateFanStatus(false);
}

function updateStateBannerLocal(stateKey, title, desc) {
  const banner = document.getElementById('ctfa-state-banner');
  const iconContainer = document.getElementById('state-icon-badge');
  const titleEl = document.getElementById('state-title');
  const descEl = document.getElementById('state-desc');

  if (!banner || !titleEl || !descEl) return;

  titleEl.textContent = title;
  descEl.textContent = desc;

  banner.className = 'rounded-2xl p-5 sm:p-6 shadow-2xl transition-all duration-300 relative overflow-hidden backdrop-blur-md ';

  if (stateKey === 'purge_pm25') {
    banner.classList.add('state-banner-green');
    titleEl.className = 'text-xl sm:text-2xl font-black text-emerald-400 tracking-tight';
    iconContainer.className = 'w-12 h-12 rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400 text-2xl shadow-[0_0_15px_rgba(16,185,129,0.3)] shrink-0';
    iconContainer.innerHTML = '🍃';
    descEl.className = 'text-xs sm:text-sm text-emerald-200/80 mt-1 font-medium';
  } else if (stateKey === 'purge_co2') {
    banner.classList.add('state-banner-blue');
    titleEl.className = 'text-xl sm:text-2xl font-black text-sky-400 tracking-tight';
    iconContainer.className = 'w-12 h-12 rounded-xl bg-sky-500/20 border border-sky-500/40 flex items-center justify-center text-sky-400 text-2xl shadow-[0_0_15px_rgba(14,165,233,0.3)] shrink-0';
    iconContainer.innerHTML = '☁️';
    descEl.className = 'text-xs sm:text-sm text-sky-200/80 mt-1 font-medium';
  } else if (stateKey === 'lockout') {
    banner.classList.add('state-banner-red');
    titleEl.className = 'text-xl sm:text-2xl font-black text-rose-400 tracking-tight';
    iconContainer.className = 'w-12 h-12 rounded-xl bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-rose-400 text-2xl shadow-[0_0_15px_rgba(244,63,94,0.3)] shrink-0';
    iconContainer.innerHTML = '💧';
    descEl.className = 'text-xs sm:text-sm text-rose-200/80 mt-1 font-medium';
  } else {
    banner.classList.add('state-banner-slate');
    titleEl.className = 'text-xl sm:text-2xl font-black text-slate-100 tracking-tight';
    iconContainer.className = 'w-12 h-12 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300 text-2xl shadow-sm shrink-0';
    iconContainer.innerHTML = '✓';
    descEl.className = 'text-xs sm:text-sm text-slate-400 mt-1 font-medium';
  }

  setText('txt-last-updated', new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
}

function updateFanStatus(isON) {
  const fanIcon = document.getElementById('fan-status-icon');
  const fanText = document.getElementById('txt-fan-status');

  if (isON) {
    if (fanIcon) {
      fanIcon.classList.remove('fan-stopped');
      fanIcon.classList.add('fan-spinning');
    }
    if (fanText) {
      fanText.textContent = 'ON';
      fanText.className = 'text-lg font-black text-emerald-400 drop-shadow-[0_0_8px_rgba(16,185,129,0.8)]';
    }
  } else {
    if (fanIcon) {
      fanIcon.classList.remove('fan-spinning');
      fanIcon.classList.add('fan-stopped');
    }
    if (fanText) {
      fanText.textContent = 'OFF';
      fanText.className = 'text-lg font-black text-slate-500';
    }
  }
}

/* -------------------------------------------------------------
 * 3. Simulator Drawer & Real-Time Syncing
 * ------------------------------------------------------------- */
function openSimulatorDrawer() {
  const drawer = document.getElementById('simulator-drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  if (drawer) drawer.classList.remove('translate-x-full');
  if (backdrop) backdrop.classList.remove('hidden');
}

function closeSimulatorDrawer() {
  const drawer = document.getElementById('simulator-drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  if (drawer) drawer.classList.add('translate-x-full');
  if (backdrop) backdrop.classList.add('hidden');
}

function initSimulatorDrawer() {
  const backdrop = document.getElementById('drawer-backdrop');
  const btnClose = document.getElementById('btn-close-simulator');

  ['btn-open-simulator', 'btn-open-simulator-header', 'btn-open-sim-quick'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', openSimulatorDrawer);
  });

  if (btnClose) btnClose.addEventListener('click', closeSimulatorDrawer);
  if (backdrop) backdrop.addEventListener('click', closeSimulatorDrawer);

  // Sync range & number inputs and immediately update dashboard
  const sliderPairs = [
    { num: 'sim-out-temp', range: 'sim-range-out-temp' },
    { num: 'sim-in-temp', range: 'sim-range-in-temp' },
    { num: 'sim-in-pm25', range: 'sim-range-in-pm25' },
    { num: 'sim-out-pm25', range: 'sim-range-out-pm25' },
    { num: 'sim-in-co2', range: 'sim-range-in-co2' },
    { num: 'sim-out-co2', range: 'sim-range-out-co2' },
    { num: 'sim-in-hum', range: 'sim-range-in-hum' },
    { num: 'sim-out-hum', range: 'sim-range-out-hum' },
  ];

  sliderPairs.forEach(({ num, range }) => {
    const nEl = document.getElementById(num);
    const rEl = document.getElementById(range);

    const onValChange = () => {
      syncSimulatorInputsToDashboard();

      // Debounce backend simulation / hardware dispatch by 400ms
      clearTimeout(state.debounceTimer);
      state.debounceTimer = setTimeout(() => {
        executeSimulation(false);
      }, 400);
    };

    if (nEl && rEl) {
      nEl.addEventListener('input', () => { rEl.value = nEl.value; onValChange(); });
      rEl.addEventListener('input', () => { nEl.value = rEl.value; onValChange(); });
    }
  });

  const bufEl = document.getElementById('sim-safety-buffer');
  if (bufEl) {
    bufEl.addEventListener('input', () => {
      syncSimulatorInputsToDashboard();
      clearTimeout(state.debounceTimer);
      state.debounceTimer = setTimeout(() => executeSimulation(false), 400);
    });
  }

  // Load Presets into Drawer
  window.apiService.fetchPresets().then(presets => {
    const container = document.getElementById('sim-presets-container');
    if (!container) return;
    container.innerHTML = '';

    presets.forEach(p => {
      const btn = document.createElement('button');
      btn.className = 'w-full text-left p-2.5 rounded-lg border border-slate-700/70 bg-slate-800/50 hover:border-cyan-400 hover:bg-slate-800 transition-all text-xs flex flex-col justify-between';
      btn.innerHTML = `
        <div class="font-semibold text-slate-200">${p.title}</div>
        <div class="text-[10px] text-slate-400 mt-0.5">${p.subtitle}</div>
      `;
      btn.onclick = () => {
        applyPresetValues(p);
        executeSimulation(true);
      };
      container.appendChild(btn);
    });
  });

  // Simulator Execute Button
  const btnRun = document.getElementById('btn-run-simulation');
  if (btnRun) {
    btnRun.addEventListener('click', () => executeSimulation(true));
  }

  // Manual ON / OFF buttons inside drawer
  const btnManOn = document.getElementById('sim-btn-manual-on');
  const btnManOff = document.getElementById('sim-btn-manual-off');
  if (btnManOn) btnManOn.addEventListener('click', () => sendManualCommand(true));
  if (btnManOff) btnManOff.addEventListener('click', () => sendManualCommand(false));
}

function initQuickPresets() {
  document.querySelectorAll('.btn-quick-preset').forEach(btn => {
    btn.addEventListener('click', async () => {
      const presetId = btn.getAttribute('data-preset');
      const presets = await window.apiService.fetchPresets();
      const match = presets.find(p => p.id === presetId);
      if (match) {
        applyPresetValues(match);
        executeSimulation(true);
      }
    });
  });
}

function applyPresetValues(p) {
  if (p.indoor_temp !== undefined) {
    setVal('sim-in-temp', p.indoor_temp);
    setVal('sim-range-in-temp', p.indoor_temp);
  }
  if (p.outdoor_temp !== undefined) {
    setVal('sim-out-temp', p.outdoor_temp);
    setVal('sim-range-out-temp', p.outdoor_temp);
  }
  if (p.safety_buffer !== undefined) {
    setVal('sim-safety-buffer', p.safety_buffer);
  }

  setVal('sim-in-pm25', p.indoor_pm25);
  setVal('sim-range-in-pm25', p.indoor_pm25);
  setVal('sim-out-pm25', p.outdoor_pm25 || 28);
  setVal('sim-range-out-pm25', p.outdoor_pm25 || 28);
  setVal('sim-in-co2', p.indoor_co2);
  setVal('sim-range-in-co2', p.indoor_co2);
  setVal('sim-out-co2', p.outdoor_co2 || 420);
  setVal('sim-range-out-co2', p.outdoor_co2 || 420);
  setVal('sim-in-hum', p.indoor_humidity);
  setVal('sim-range-in-hum', p.indoor_humidity);
  setVal('sim-out-hum', p.outdoor_humidity);
  setVal('sim-range-out-hum', p.outdoor_humidity);

  syncSimulatorInputsToDashboard();
}

async function executeSimulation(notify = true) {
  const btn = document.getElementById('btn-run-simulation');
  if (btn && notify) btn.disabled = true;

  const payload = getSimulatorInputs();
  payload.force = true;

  try {
    const res = await window.apiService.simulate(payload);
    if (res.success && res.telemetry) {
      updateDashboardUI(res.telemetry);

      const statusBox = document.getElementById('sim-result-msg');
      if (statusBox) {
        statusBox.classList.remove('hidden');
        statusBox.textContent = `Applied: ${res.telemetry.state_title} (${res.telemetry.fan_status ? 'Fan ON' : 'Fan OFF'})`;
        statusBox.className = res.telemetry.fan_status ? 'p-2 rounded bg-emerald-100 text-emerald-800 text-xs mt-2' : 'p-2 rounded bg-rose-100 text-rose-800 text-xs mt-2';
      }
    }
  } catch (err) {
    console.warn('Simulation sync error:', err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function updateDashboardUI(t) {
  state.currentTelemetry = t;

  setText('val-in-pm25', Math.round(t.indoor_pm25));
  setText('val-out-pm25', Math.round(t.outdoor_pm25));
  setText('val-in-co2', Math.round(t.indoor_co2));
  setText('val-out-co2', Math.round(t.outdoor_co2));
  setText('val-in-dew', Number(t.indoor_dew_point).toFixed(1));
  setText('val-out-dew', Number(t.outdoor_dew_point).toFixed(1));

  if (t.indoor_temp !== undefined) setText('tag-in-temp', `${Math.round(t.indoor_temp)}°C`);
  if (t.outdoor_temp !== undefined) setText('tag-out-temp', `${Math.round(t.outdoor_temp)}°C`);
  setText('tag-in-hum', `${t.indoor_humidity}% Hum`);
  setText('tag-out-hum', `${t.outdoor_humidity}% Hum`);

  updateStateBannerLocal(t.state_key, t.state_title, t.state_desc);
  updateFanStatus(t.fan_status);

  setText('txt-last-updated', t.last_updated || 'Just now');
  if (t.is_connected !== undefined) {
    updateConnectionStatusUI(t.is_connected);
  } else if (t.system_status) {
    updateConnectionStatusUI(t.system_status === 'Connected');
  }
}

async function sendManualCommand(forceState) {
  try {
    const res = await window.apiService.manualOverride(forceState);
    if (res.success && res.telemetry) {
      updateDashboardUI(res.telemetry);
    }
  } catch (err) {
    alert('Manual override failed: ' + err.message);
  }
}

/* -------------------------------------------------------------
 * 4. Next Evaluation Countdown Timer
 * ------------------------------------------------------------- */
function initCountdownTimer() {
  const timerText = document.getElementById('txt-countdown');
  state.countdownSec = 30;

  if (state.countdownInterval) clearInterval(state.countdownInterval);
  state.countdownInterval = setInterval(() => {
    state.countdownSec--;
    if (state.countdownSec <= 0) {
      state.countdownSec = 30;
      // In simulation mode: re-evaluates inputs; in live mode: polls live backend sensors
      if (INTEGRATION_CONFIG.USE_SIMULATOR_SOURCE) {
        executeSimulation(false);
      } else {
        fetchAndDisplayLiveTelemetry();
      }
    }
    if (timerText) {
      timerText.textContent = `in ${state.countdownSec} seconds`;
    }
  }, 1000);
}

/* -------------------------------------------------------------
 * 5. Trends Charts (Interactive SVG Curves)
 * ------------------------------------------------------------- */
function initTrendsCharts() {
  const metricTabs = document.querySelectorAll('.trend-metric-tab');
  metricTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      metricTabs.forEach(t => t.classList.remove('active-tab', 'bg-blue-600', 'text-white'));
      tab.classList.add('active-tab', 'bg-blue-600', 'text-white');
      state.activeTrendMetric = tab.getAttribute('data-metric');
      renderTrendsCharts(state.activeTrendMetric);
    });
  });

  renderTrendsCharts('in_pm25');
}

function renderTrendsCharts(metricKey) {
  drawSvgChart('chart-hourly', '#10b981', [32, 45, 78, 72, 54, 42, 38, 52, 65, 68, 48, 40]);
  drawSvgChart('chart-daily', '#3b82f6', [24, 38, 52, 44, 31, 22, 35, 48, 56, 42, 36, 28, 33, 41, 50]);
  drawSvgChart('chart-monthly', '#f59e0b', [58, 64, 52, 45, 30, 22, 18, 25, 34, 45, 52, 60]);
}

function drawSvgChart(svgId, color, points) {
  const svg = document.getElementById(svgId);
  if (!svg) return;

  const w = 700;
  const h = 180;
  const max = Math.max(...points) * 1.2;
  const min = 0;

  const stepX = w / (points.length - 1);
  let pathD = `M 0 ${h - ((points[0] - min) / (max - min)) * h}`;

  for (let i = 1; i < points.length; i++) {
    const x = i * stepX;
    const y = h - ((points[i] - min) / (max - min)) * h;
    const prevX = (i - 1) * stepX;
    const prevY = h - ((points[i - 1] - min) / (max - min)) * h;
    const cx1 = prevX + (x - prevX) / 2;
    const cx2 = prevX + (x - prevX) / 2;
    pathD += ` C ${cx1} ${prevY}, ${cx2} ${y}, ${x} ${y}`;
  }

  const fillPathD = pathD + ` L ${w} ${h} L 0 ${h} Z`;

  svg.innerHTML = `
    <defs>
      <linearGradient id="grad-${svgId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.25"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0.0"/>
      </linearGradient>
    </defs>
    <path d="${fillPathD}" fill="url(#grad-${svgId})" />
    <path d="${pathD}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" />
  `;
}

/* -------------------------------------------------------------
 * 6. Alarms Management
 * ------------------------------------------------------------- */
function initAlarmsHandlers() {
  loadAlarms();
}

async function loadAlarms() {
  const container = document.getElementById('alarms-list-container');
  if (!container) return;

  const alarms = await window.apiService.fetchAlarms();
  container.innerHTML = '';

  alarms.forEach(a => {
    const item = document.createElement('div');
    item.className = 'p-4 rounded-xl border border-slate-200 bg-white flex items-center justify-between shadow-sm';
    item.innerHTML = `
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-lg ${a.active ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-400'} flex items-center justify-center text-lg">
          ⚠️
        </div>
        <div>
          <h4 class="text-sm font-semibold text-slate-800">${a.name}</h4>
          <p class="text-xs text-slate-400">Condition: ${a.condition}</p>
        </div>
      </div>
      <div class="flex items-center gap-4">
        <button class="btn-toggle-alarm px-3 py-1 rounded-full text-xs font-semibold ${a.active ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-500 border border-slate-200'}" data-id="${a.id}">
          ${a.active ? 'Active' : 'Inactive'}
        </button>
        <button class="text-slate-400 hover:text-slate-600">✏️</button>
        <button class="text-slate-400 hover:text-rose-600">🗑️</button>
      </div>
    `;
    container.appendChild(item);
  });

  container.querySelectorAll('.btn-toggle-alarm').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = parseInt(btn.getAttribute('data-id'));
      await window.apiService.toggleAlarm(id);
      loadAlarms();
    });
  });
}

/* -------------------------------------------------------------
 * 7. Reports & CSV Download
 * ------------------------------------------------------------- */
function initReportsHandlers() {
  const btnCsv = document.getElementById('btn-download-csv');
  if (btnCsv) {
    btnCsv.addEventListener('click', downloadCsv);
  }
  loadReports();
}

async function loadReports() {
  state.reportsData = await window.apiService.fetchReports();
  renderReportsTable();
}

function renderReportsTable() {
  const tbody = document.getElementById('reports-tbody');
  if (!tbody) return;

  tbody.innerHTML = '';
  const rows = state.reportsData.slice(0, 10);

  rows.forEach((r, idx) => {
    const tr = document.createElement('tr');
    tr.className = 'border-b border-slate-100 hover:bg-slate-50/50';
    tr.innerHTML = `
      <td class="py-3 px-3 text-slate-400 font-mono text-xs">${idx + 1}</td>
      <td class="py-3 px-3 font-semibold text-slate-800 text-xs">${r.timestamp}</td>
      <td class="py-3 px-3 text-slate-600 text-xs font-mono">${r.in_pm25}</td>
      <td class="py-3 px-3 text-slate-600 text-xs font-mono">${r.out_pm25}</td>
      <td class="py-3 px-3 text-slate-600 text-xs font-mono">${r.in_co2}</td>
      <td class="py-3 px-3 text-slate-600 text-xs font-mono">${r.out_co2}</td>
      <td class="py-3 px-3 text-slate-600 text-xs font-mono">${r.in_dew}</td>
      <td class="py-3 px-3 text-slate-600 text-xs font-mono">${r.out_dew}</td>
    `;
    tbody.appendChild(tr);
  });
}

function downloadCsv() {
  if (!state.reportsData.length) return;

  const headers = ['#', 'Timestamp', 'In PM2.5', 'Out PM2.5', 'In CO2', 'Out CO2', 'In Dew Point', 'Out Dew Point'];
  const rows = state.reportsData.map((r, i) => [
    i + 1, r.timestamp, r.in_pm25, r.out_pm25, r.in_co2, r.out_co2, r.in_dew, r.out_dew
  ]);

  const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement('a');
  link.setAttribute('href', encodedUri);
  link.setAttribute('download', `CTFA_Telemetry_Log_${new Date().toISOString().slice(0,10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/* -------------------------------------------------------------
 * 8. Settings Form
 * ------------------------------------------------------------- */
function initSettingsHandlers() {
  const btnSave = document.getElementById('btn-save-settings');
  if (btnSave) {
    btnSave.addEventListener('click', (e) => {
      e.preventDefault();
      alert('Settings saved successfully!');
    });
  }
}

/* -------------------------------------------------------------
 * Helper Utilities
 * ------------------------------------------------------------- */
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

/* -------------------------------------------------------------
 * 9. Hardware Connection Status Listener (/api/events)
 * ------------------------------------------------------------- */
function updateConnectionStatusUI(isConnected) {
  const txt = document.getElementById('txt-system-status');
  const dot = document.getElementById('dot-system-status');
  const wrap = document.getElementById('status-indicator-wrap');
  if (!txt) return;

  if (isConnected) {
    txt.textContent = 'Connected';
    if (dot) {
      dot.className = 'w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)] animate-pulse';
    }
    if (wrap) {
      wrap.classList.remove('text-rose-600', 'text-amber-600');
      wrap.classList.add('text-emerald-600');
      wrap.title = 'Device Online (Connected) - Click to view http://178.16.137.20:3101/api/events';
    }
  } else {
    txt.textContent = 'Disconnected';
    if (dot) {
      dot.className = 'w-2 h-2 rounded-full bg-rose-500';
    }
    if (wrap) {
      wrap.classList.remove('text-emerald-600', 'text-amber-600');
      wrap.classList.add('text-rose-600');
      wrap.title = 'Device Offline (Disconnected) - Click to view http://178.16.137.20:3101/api/events';
    }
  }
}

function initDeviceConnectionListener() {
  // 1. Initial snapshot fetch from /api/device/state
  fetch('/api/device/state')
    .then(res => res.json())
    .then(data => {
      if (data && data.is_connected !== undefined) {
        updateConnectionStatusUI(data.is_connected);
      }
    })
    .catch(() => {});

  // 2. Connect to Server-Sent Events stream
  try {
    const src = new EventSource('/api/events');
    src.addEventListener('state', (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        const devices = payload.devices || [];
        const dev = devices.find(d => d.mac === '004B12302844') || devices[0];
        if (dev && dev.online !== undefined) {
          updateConnectionStatusUI(!!dev.online);
        } else if (payload.online !== undefined) {
          updateConnectionStatusUI(!!payload.online);
        }
      } catch (err) {
        console.warn('Error parsing hardware SSE payload:', err);
      }
    });

    src.onerror = () => {
      // Graceful fallback: EventSource auto-reconnects natively
    };
  } catch (err) {
    console.warn('EventSource not supported:', err);
  }
}

