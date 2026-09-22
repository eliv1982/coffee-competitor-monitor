// Запросы на тот же хост, с которого открыта страница (для desktop — порт 8765; для браузера — порт из URL).
const API_BASE = (typeof window !== 'undefined' && window.location && window.location.origin && window.location.protocol !== 'file:')
  ? window.location.origin
  : 'http://127.0.0.1:8000';

function show(el, visible) {
  el.classList.toggle('hidden', !visible);
}

function setPlaceholder(visible) {
  document.getElementById('result-placeholder').classList.toggle('hidden', !visible);
}

function setResultContent(visible, html = '') {
  const el = document.getElementById('result-content');
  el.innerHTML = html;
  el.classList.toggle('hidden', !visible);
}

function setError(msg) {
  const el = document.getElementById('result-error');
  el.textContent = msg || '';
  el.classList.toggle('hidden', !msg);
}

function renderTextAnalysis(analysis) {
  if (!analysis || typeof analysis !== 'object') return '';
  const parts = [];
  if (analysis.summary) {
    parts.push('<h3>Резюме</h3><p>' + escapeHtml(analysis.summary) + '</p>');
  }
  if (analysis.content_quality != null && analysis.content_quality > 0) {
    parts.push('<h3>Качество контента</h3><p>' + escapeHtml(String(analysis.content_quality)) + ' / 10</p>');
  }
  if (analysis.price_category) {
    parts.push('<h3>Ценовая категория</h3><p>' + escapeHtml(String(analysis.price_category)) + '</p>');
  }
  if (Array.isArray(analysis.strengths) && analysis.strengths.length) {
    parts.push('<h3>Сильные стороны</h3><ul>' + analysis.strengths.map(s => '<li>' + escapeHtml(String(s)) + '</li>').join('') + '</ul>');
  }
  if (Array.isArray(analysis.weaknesses) && analysis.weaknesses.length) {
    parts.push('<h3>Слабые стороны</h3><ul>' + analysis.weaknesses.map(s => '<li>' + escapeHtml(String(s)) + '</li>').join('') + '</ul>');
  }
  if (Array.isArray(analysis.unique_offers) && analysis.unique_offers.length) {
    parts.push('<h3>Уникальные предложения</h3><ul>' + analysis.unique_offers.map(s => '<li>' + escapeHtml(String(s)) + '</li>').join('') + '</ul>');
  }
  if (Array.isArray(analysis.unique_selling_points) && analysis.unique_selling_points.length) {
    parts.push('<h3>Уникальные торговые предложения</h3><ul>' + analysis.unique_selling_points.map(s => '<li>' + escapeHtml(String(s)) + '</li>').join('') + '</ul>');
  }
  if (Array.isArray(analysis.recommendations) && analysis.recommendations.length) {
    parts.push('<h3>Рекомендации</h3><ul>' + analysis.recommendations.map(s => '<li>' + escapeHtml(String(s)) + '</li>').join('') + '</ul>');
  }
  return parts.join('');
}

function renderImageAnalysis(analysis) {
  if (!analysis) return '';
  const parts = [];
  if (analysis.description) {
    parts.push('<h3>Описание</h3><p>' + escapeHtml(analysis.description) + '</p>');
  }
  if (analysis.design_score != null) {
    parts.push('<h3>Дизайн</h3><p>' + escapeHtml(String(analysis.design_score)) + ' / 10</p>');
  }
  if (analysis.brand_style) {
    parts.push('<h3>Стиль бренда</h3><p>' + escapeHtml(analysis.brand_style) + '</p>');
  }
  if (analysis.animation_potential != null) {
    parts.push('<p><strong>Анимация/интерактив:</strong> ' + (analysis.animation_potential ? 'есть' : 'нет') + '</p>');
  }
  if (analysis.menu_visibility != null) {
    parts.push('<p><strong>Видимость меню:</strong> ' + escapeHtml(String(analysis.menu_visibility)) + ' / 10</p>');
  }
  if (analysis.usability_score != null) {
    parts.push('<p><strong>Удобство:</strong> ' + escapeHtml(String(analysis.usability_score)) + ' / 10</p>');
  }
  if (analysis.content_quality != null) {
    parts.push('<p><strong>Качество контента:</strong> ' + escapeHtml(String(analysis.content_quality)) + ' / 10</p>');
  }
  if (analysis.visual_style_score != null) {
    parts.push('<h3>Визуальный стиль</h3><p>' + escapeHtml(String(analysis.visual_style_score)) + ' / 10</p>');
  }
  if (analysis.visual_style_analysis) {
    parts.push('<p>' + escapeHtml(analysis.visual_style_analysis) + '</p>');
  }
  if (analysis.marketing_insights?.length) {
    parts.push('<h3>Маркетинговые инсайты</h3><ul>' + analysis.marketing_insights.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
  }
  if (analysis.recommendations?.length) {
    parts.push('<h3>Рекомендации</h3><ul>' + analysis.recommendations.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
  }
  return parts.join('');
}

function renderParseDemo(payload) {
  if (!payload || typeof payload !== 'object') {
    return '<p class="placeholder">Нет данных для отображения.</p>';
  }
  const parts = [];
  if (payload.error) {
    parts.push('<p class="error">' + escapeHtml(payload.error) + '</p>');
  }
  if (payload.title) parts.push('<p><strong>Title:</strong> ' + escapeHtml(payload.title) + '</p>');
  if (payload.h1) parts.push('<p><strong>H1:</strong> ' + escapeHtml(payload.h1) + '</p>');
  if (payload.first_paragraph) parts.push('<p><strong>Первый абзац:</strong> ' + escapeHtml(payload.first_paragraph.slice(0, 500)) + (payload.first_paragraph.length > 500 ? '…' : '') + '</p>');
  const a = payload.analysis;
  if (a && typeof a === 'object') {
    if (a.summary) parts.push('<h3>Резюме</h3><p>' + escapeHtml(a.summary) + '</p>');
    if (a.strengths?.length) parts.push('<h3>Сильные стороны</h3><ul>' + a.strengths.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    if (a.weaknesses?.length) parts.push('<h3>Слабые стороны</h3><ul>' + a.weaknesses.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    if (a.unique_offers?.length) parts.push('<h3>Уникальные предложения</h3><ul>' + a.unique_offers.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    if (a.recommendations?.length) parts.push('<h3>Рекомендации</h3><ul>' + a.recommendations.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
  }
  if (parts.length === 0) {
    return '<p class="placeholder">По этому URL не удалось извлечь контент или анализ пуст.</p>';
  }
  return parts.join('');
}

function renderAnalyzeUrl(payload) {
  if (!payload || typeof payload !== 'object') return '<p class="placeholder">Нет данных.</p>';
  const parts = [];
  if (payload.url) parts.push('<p><strong>URL:</strong> ' + escapeHtml(payload.url) + '</p>');
  const a = payload.analysis;
  if (a && typeof a === 'object') {
    parts.push('<h3>Анализ сайта</h3>');
    if (a.summary) parts.push('<p>' + escapeHtml(a.summary) + '</p>');
    const scores = [];
    if (a.design_score != null) scores.push('Дизайн: ' + escapeHtml(String(a.design_score)) + ' / 10');
    if (a.usability_score != null) scores.push('Удобство: ' + escapeHtml(String(a.usability_score)) + ' / 10');
    if (a.content_quality != null) scores.push('Качество контента: ' + escapeHtml(String(a.content_quality)) + ' / 10');
    if (scores.length) parts.push('<p>' + scores.join(' &nbsp;|&nbsp; ') + '</p>');
    if (a.unique_selling_points?.length) parts.push('<p><strong>Уникальные торговые предложения:</strong> ' + escapeHtml(a.unique_selling_points.join(', ')) + '</p>');
    if (a.franchise_info?.length) parts.push('<p><strong>Франшиза:</strong> ' + escapeHtml(a.franchise_info.join('; ')) + '</p>');
    if (a.price_category) parts.push('<p><strong>Ценовая категория:</strong> ' + escapeHtml(a.price_category) + '</p>');
    if (a.target_audience) parts.push('<p><strong>Целевая аудитория:</strong> ' + escapeHtml(a.target_audience) + '</p>');
    if (a.strengths?.length) parts.push('<h4>Сильные стороны</h4><ul>' + a.strengths.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    if (a.weaknesses?.length) parts.push('<h4>Слабые стороны</h4><ul>' + a.weaknesses.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    if (a.recommendations?.length) parts.push('<h4>Рекомендации</h4><ul>' + a.recommendations.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    return parts.join('');
  }
  const screen = payload.screenshot_analysis, text = payload.text_analysis;
  if (screen && typeof screen === 'object') {
    parts.push('<h3>Анализ скриншота</h3>');
    if (screen.design_score != null) parts.push('<p>Дизайн: ' + escapeHtml(String(screen.design_score)) + ' / 10</p>');
    if (screen.usability_score != null) parts.push('<p>Удобство: ' + escapeHtml(String(screen.usability_score)) + ' / 10</p>');
    if (screen.unique_selling_points?.length) parts.push('<p><strong>Уникальные торговые предложения:</strong> ' + escapeHtml(screen.unique_selling_points.join(', ')) + '</p>');
    if (screen.additional_notes) parts.push('<p>' + escapeHtml(screen.additional_notes) + '</p>');
  }
  if (text && typeof text === 'object') {
    parts.push('<h3>Анализ текста</h3>');
    if (text.strengths?.length) parts.push('<ul>' + text.strengths.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
    if (text.weaknesses?.length) parts.push('<ul>' + text.weaknesses.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>');
  }
  return parts.length ? parts.join('') : '<p class="placeholder">Нет данных анализа.</p>';
}

function escapeHtml(s) {
  if (typeof s !== 'string') return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function parseJsonResponse(res, label) {
  return res.text().then(function (raw) {
    if (!raw || !raw.trim()) {
      throw new Error('Пустой ответ (статус ' + res.status + '). Откройте http://127.0.0.1:8000/static/index.html и запустите: python run.py');
    }
    try {
      return JSON.parse(raw);
    } catch (e) {
      var preview = raw.length > 80 ? raw.slice(0, 80) + '…' : raw;
      throw new Error('Ответ не JSON (статус ' + res.status + '): ' + preview + '. Откройте строго http://127.0.0.1:8000/static/index.html и перезапустите python run.py (закройте все старые окна терминала с сервером).');
    }
  });
}

// Tabs
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById('panel-' + tab);
    if (panel) panel.classList.add('active');
  });
});

// Analyze button
document.getElementById('btn-analyze').addEventListener('click', async () => {
  const activeTab = document.querySelector('.tab.active').dataset.tab;
  setError('');
  setPlaceholder(false);
  setResultContent(true, '<p>Загрузка…</p>');

  const btn = document.getElementById('btn-analyze');
  btn.disabled = true;

  try {
    if (activeTab === 'text') {
      const text = document.getElementById('text-input').value.trim();
      const pdfInput = document.getElementById('pdf-input');
      const hasPdf = pdfInput && pdfInput.files && pdfInput.files.length > 0 && (pdfInput.files[0].name || '').toLowerCase().endsWith('.pdf');
      if (!text && !hasPdf) {
        setError('Введите текст (минимум 10 символов) или загрузите PDF.');
        setPlaceholder(true);
        setResultContent(false);
        return;
      }
      let res;
      if (hasPdf) {
        const form = new FormData();
        if (text) form.append('text', text);
        form.append('file', pdfInput.files[0]);
        res = await fetch(API_BASE + '/analyze_text', { method: 'POST', body: form });
      } else {
        res = await fetch(API_BASE + '/analyze_text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        });
      }
      let data = await parseJsonResponse(res, 'analyze_text');
      if (!res.ok) {
        throw new Error(data.detail || data.error || res.statusText || 'Ошибка запроса');
      }
      setError('');
      setPlaceholder(false);
      if (data && data.error) {
        setResultContent(true, '<p class="error">' + escapeHtml(data.error) + '</p>');
        document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return;
      }
      const textAnalysis = (data && data.analysis !== undefined) ? data.analysis : data;
      if (!textAnalysis || typeof textAnalysis !== 'object') {
        setResultContent(true, '<p class="placeholder">Нет данных анализа. Попробуйте снова.</p>');
        document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return;
      }
      const html = renderTextAnalysis(textAnalysis);
      setResultContent(true, html || '<p class="placeholder">Ответ модели пуст. Попробуйте другой текст или PDF.</p>');
      document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else if (activeTab === 'image') {
      const input = document.getElementById('image-input');
      if (!input.files?.length) {
        setError('Выберите изображение.');
        setPlaceholder(true);
        setResultContent(false);
        return;
      }
      const form = new FormData();
      form.append('file', input.files[0]);
      const res = await fetch(API_BASE + '/analyze_image', {
        method: 'POST',
        body: form,
      });
      let data = await parseJsonResponse(res, 'analyze_image');
      if (!res.ok) {
        throw new Error(data.detail || data.error || res.statusText || 'Ошибка запроса');
      }
      setError('');
      setPlaceholder(false);
      if (data && data.error) {
        setResultContent(true, '<p class="error">' + escapeHtml(data.error) + '</p>');
        return;
      }
      const imageAnalysis = (data && data.analysis !== undefined) ? data.analysis : data;
      if (imageAnalysis && typeof imageAnalysis === 'object' && (imageAnalysis.description !== undefined || imageAnalysis.marketing_insights)) {
        setResultContent(true, renderImageAnalysis(imageAnalysis));
      } else {
        setResultContent(true, '<p class="placeholder">Нет данных анализа. Попробуйте другое изображение.</p>');
      }
      document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else if (activeTab === 'url') {
      const url = document.getElementById('url-input').value.trim();
      if (!url) {
        setError('Введите URL.');
        setPlaceholder(true);
        setResultContent(false);
        return;
      }
      // /analyze_url всегда использует Selenium (скриншот + текст) — корректно для JS-сайтов (Шоколадница и др.)
      const res = await fetch(API_BASE + '/analyze_url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      let data = await parseJsonResponse(res, 'analyze_url');
      if (!res.ok) {
        throw new Error(data.detail || data.error || res.statusText || 'Ошибка запроса');
      }
      setError('');
      setPlaceholder(false);
      if (data && data.error) {
        setResultContent(true, '<p class="error">' + escapeHtml(data.error) + '</p>' + (data.url ? '<p><strong>URL:</strong> ' + escapeHtml(data.url) + '</p>' : ''));
        document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return;
      }
      if (data && (data.analysis || data.url)) {
        setResultContent(true, renderAnalyzeUrl(data));
      } else {
        setResultContent(true, '<p class="placeholder">По URL не удалось получить данные. Проверьте доступность сайта и наличие Chrome.</p>');
      }
      document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  } catch (e) {
    setError(e.message || 'Произошла ошибка');
    setResultContent(true, '<p class="error">' + escapeHtml(e.message || 'Произошла ошибка') + '</p>');
    setPlaceholder(false);
    document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } finally {
    btn.disabled = false;
  }
});

// History: при клике по элементу с result показываем полный результат в блоке «Результат»
function showResultFromHistory(item) {
  const result = item.result;
  const type = (item.request_type || item.type || '').toLowerCase();
  if (!result || typeof result !== 'object') {
    setResultContent(true, '<p class="placeholder">Результат этого запроса не сохранён (старая запись).</p>');
    setPlaceholder(false);
    setError('');
    return;
  }
  if (result.error && !result.analysis && !result.title && !result.strengths) {
    setResultContent(true, '<h3>Ответ на запрос</h3><p class="error">' + escapeHtml(result.error) + '</p>' + (result.url ? '<p><strong>URL:</strong> ' + escapeHtml(result.url) + '</p>' : ''));
    setPlaceholder(false);
    setError('');
    document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return;
  }
  let html = '';
  if (type === 'text') {
    html = renderTextAnalysis(result);
  } else if (type === 'image') {
    html = renderImageAnalysis(result);
  } else if (type === 'parse') {
    html = renderParseDemo(result);
  } else if (type === 'analyze_url') {
    html = renderAnalyzeUrl(result);
  } else {
    html = '<pre>' + escapeHtml(JSON.stringify(result, null, 2)) + '</pre>';
  }
  setResultContent(true, html || '<p class="placeholder">Нет данных для отображения.</p>');
  setPlaceholder(false);
  setError('');
  document.querySelector('.result-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Один обработчик клика по списку истории (делегирование), чтобы просмотр ответа работал
document.getElementById('history-list').addEventListener('click', (ev) => {
  const itemEl = ev.target.closest('.history-item[data-has-result="true"]');
  if (!itemEl || !window.__historyItems) return;
  const idx = parseInt(itemEl.getAttribute('data-idx'), 10);
  if (Number.isNaN(idx) || idx < 0 || idx >= window.__historyItems.length) return;
  const item = window.__historyItems[idx];
  if (item) {
    show(document.getElementById('history-panel'), false);
    showResultFromHistory(item);
  }
});

document.getElementById('btn-history').addEventListener('click', async () => {
  const panel = document.getElementById('history-panel');
  const list = document.getElementById('history-list');
  list.innerHTML = '<p>Загрузка…</p>';
  show(panel, true);
  try {
    const res = await fetch(API_BASE + '/history');
    const data = await res.json();
    const items = data.items || data.entries || [];
    if (!items.length) {
      list.innerHTML = '<p class="placeholder">История пуста.</p>';
      window.__historyItems = [];
      return;
    }
    window.__historyItems = items;
    list.innerHTML = items.map((e, idx) => {
      const type = e.request_type || e.type || '';
      const time = e.timestamp || e.created_at || '';
      const req = e.request_summary || e.input_summary || '';
      const resp = e.response_summary || e.response_preview || '';
      const hasResult = e.result != null && typeof e.result === 'object';
      const clickable = hasResult ? ' clickable' : '';
      const hint = hasResult ? ' — нажмите, чтобы посмотреть запрос и ответ' : '';
      return `
      <div class="history-item${clickable}" data-idx="${idx}" data-has-result="${hasResult}">
        <div class="meta">${escapeHtml(type)} · ${escapeHtml(time)}${hint}</div>
        <div class="preview">${escapeHtml(req)}</div>
        ${resp ? '<div class="meta">' + escapeHtml(resp) + '</div>' : ''}
      </div>
    `}).join('');
  } catch {
    list.innerHTML = '<p class="error">Не удалось загрузить историю.</p>';
    window.__historyItems = [];
  }
});

document.getElementById('btn-close-history').addEventListener('click', () => {
  show(document.getElementById('history-panel'), false);
});
