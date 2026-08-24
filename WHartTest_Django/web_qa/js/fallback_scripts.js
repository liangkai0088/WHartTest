// web-qa-bot src/browser.ts:354-709 DOM 降级脚本（逐字移植）+ 迷你 dispatcher。
// 占位符 __A__/__B__/__C__/__KIND__ 由 Python 侧以 json.dumps 注入（等价于原 ${JSON.stringify(...)} 内插）。

// ---------- 1. type-by-accessible-name ----------
function typeBySelector(selector, value) {
  return (() => {
    const selector = __A__;
    const value = __B__;
    const parsed = (() => {
      const index = selector.indexOf(':');
      if (index > 0) return { role: selector.slice(0, index).trim().toLowerCase(), name: selector.slice(index + 1).trim().toLowerCase() };
      return { role: '', name: selector.trim().toLowerCase() };
    })();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const labelFor = (el) => {
      const id = el.getAttribute('id');
      if (!id) return '';
      return text(document.querySelector('label[for="' + CSS.escape(id) + '"]'));
    };
    const nearbyText = (el) => {
      const parent = el.parentElement;
      if (!parent) return '';
      const formItem = el.closest('.el-form-item, .ant-form-item, [class*="form-item"], [class*="FormItem"]');
      return [text(parent).replace(el.value || '', '').trim(), text(formItem)].filter(Boolean).join(' ');
    };
    const accessibleName = (el) => [
      el.getAttribute('aria-label') || '',
      el.getAttribute('placeholder') || '',
      el.getAttribute('title') || '',
      labelFor(el),
      text(el.closest('label')),
      nearbyText(el)
    ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
    const roleOf = (el) => {
      const explicit = (el.getAttribute('role') || '').toLowerCase();
      if (explicit) return explicit;
      const tag = el.tagName.toLowerCase();
      if (tag === 'textarea') return 'textbox';
      if (tag === 'input') return (el.getAttribute('type') || 'text').toLowerCase() === 'checkbox' ? 'checkbox' : 'textbox';
      if (el.isContentEditable) return 'textbox';
      return '';
    };
    const candidates = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], [role="textbox"]')).filter(visible);
    const found = candidates.find(el => (!parsed.role || roleOf(el) === parsed.role) && accessibleName(el).includes(parsed.name));
    if (!found) return false;
    found.focus();
    if ('value' in found) {
      found.value = '';
      found.dispatchEvent(new Event('input', { bubbles: true }));
      found.value = value;
      found.dispatchEvent(new Event('input', { bubbles: true }));
      found.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      found.textContent = value;
      found.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    }
    return true;
  })()
}

// ---------- 2. click-row-action ----------
function clickRowAction(rowText, actionText) {
  return (() => {
    const rowTarget = __A__.replace(/\s+/g, ' ').trim().toLowerCase();
    const actionTarget = __B__.replace(/\s+/g, ' ').trim().toLowerCase();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const disabled = (el) => Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled') || el.classList.contains('is-disabled')));
    const clickElement = (el) => {
      if (!el || !visible(el) || disabled(el)) return false;
      const clickable = el.closest('button, a, [role="button"], .el-button') || el;
      if (!visible(clickable) || disabled(clickable)) return false;
      clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      clickable.click();
      return true;
    };

    const dataRows = Array.from(document.querySelectorAll('.el-table__body-wrapper .el-table__row, .el-table__body-wrapper tbody tr, tbody tr, [role="row"]')).filter(visible);
    const rowIndex = dataRows.findIndex(el => text(el).toLowerCase().includes(rowTarget));
    if (rowIndex < 0) return false;

    const pickAction = (root) => {
      const candidates = Array.from(root.querySelectorAll('button, a, span, [role="button"]')).filter(visible);
      return candidates.find(el => text(el).toLowerCase() === actionTarget && !Array.from(el.children || []).some(child => text(child).toLowerCase() === actionTarget));
    };

    const fixedRows = Array.from(document.querySelectorAll('.el-table__fixed-right .el-table__body-wrapper .el-table__row, .el-table__fixed-right tbody tr, .el-table__fixed .el-table__body-wrapper .el-table__row, .el-table__fixed tbody tr')).filter(visible);
    const fixedAction = fixedRows[rowIndex] ? pickAction(fixedRows[rowIndex]) : undefined;
    if (clickElement(fixedAction)) return true;

    const rowAction = pickAction(dataRows[rowIndex]);
    return clickElement(rowAction);
  })()
}

// ---------- 3. pagination ----------
function clickPagination(pageTarget) {
  return (() => {
    const target = __A__.replace(/\s+/g, ' ').trim().toLowerCase();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const disabled = (el) => Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled') || el.classList.contains('is-disabled')));
    const clickElement = (el) => {
      if (!el || !visible(el) || disabled(el)) return false;
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      el.click();
      return true;
    };

    const roots = Array.from(document.querySelectorAll('.el-pagination, .ant-pagination, [class*="pagination"], [class*="Pagination"]')).filter(visible);
    roots.push(document.body);

    const findItems = (root) => Array.from(root.querySelectorAll('.el-pager li, li.number, .number, .ant-pagination-item, button, a, li, [role="button"]')).filter(visible);
    const allItems = roots.flatMap(findItems);

    if (target === 'last' || target === '最后一页') {
      const numbered = allItems
        .map(el => ({ el, n: Number(text(el)) }))
        .filter(item => Number.isInteger(item.n) && item.n > 0 && !disabled(item.el));
      numbered.sort((a, b) => b.n - a.n);
      if (clickElement(numbered[0]?.el)) return true;

      const totalText = text(document.body);
      const totalMatch = totalText.match(new RegExp('共\\s*(\\d+)\\s*条'));
      const pageSizeMatch = totalText.match(new RegExp('(\\d+)\\s*条/页'));
      const lastPage = totalMatch && pageSizeMatch ? Math.ceil(Number(totalMatch[1]) / Number(pageSizeMatch[1])) : undefined;
      if (lastPage) {
        const jumper = Array.from(document.querySelectorAll('.el-pagination__jump input, input[type="number"], input')).filter(visible).pop();
        if (jumper) {
          jumper.focus();
          jumper.value = String(lastPage);
          jumper.dispatchEvent(new Event('input', { bubbles: true }));
          jumper.dispatchEvent(new Event('change', { bubbles: true }));
          jumper.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
          jumper.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
          return true;
        }
      }
      return false;
    }

    const exact = allItems.find(el => text(el).toLowerCase() === target && !disabled(el));
    return clickElement(exact);
  })()
}

// ---------- 4. has-text ----------
function hasText(labelText) {
  return (() => {
    const target = __A__.replace(/\s+/g, ' ').trim().toLowerCase();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim().toLowerCase();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    return Array.from(document.querySelectorAll('body *')).some(el => visible(el) && text(el).includes(target));
  })()
}

// ---------- 5. click-by-text ----------
function clickByText(labelText) {
  return (() => {
    const target = __A__.replace(/\s+/g, ' ').trim().toLowerCase();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const disabled = (el) => Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled') || el.classList.contains('is-disabled')));
    const clickElement = (el) => {
      if (!el || !visible(el) || disabled(el)) return false;
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      el.click();
      return true;
    };
    const candidates = Array.from(document.querySelectorAll('button, a, li, span, div, [role="button"], [role="tab"]'))
      .filter(visible)
      .filter(el => text(el).toLowerCase() === target);
    const preferred = candidates.find(el => el.matches('button, a, [role="button"], .el-pager li, li.number, .number')) || candidates[0];
    return clickElement(preferred);
  })()
}

// ---------- 6. select-option ----------
function selectOption(value) {
  return (() => {
    const target = __A__.replace(/\s+/g, ' ').trim().toLowerCase();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const disabled = (el) => Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled') || el.classList.contains('is-disabled')));

    const candidates = Array.from(document.querySelectorAll('.el-select-dropdown__item, .ant-select-item, .ant-select-item-option-content, .el-dropdown-menu__item, .ant-dropdown-menu-item, [role="option"], [role="menuitem"], [role="listitem"]'))
      .filter(visible)
      .filter(el => text(el).toLowerCase() === target);

    if (candidates.length === 0) return false;

    const el = candidates[0];
    const clickable = el.closest('li, [role="option"], [role="menuitem"], .el-select-dropdown__item, .ant-select-item') || el;
    if (disabled(clickable)) return false;

    clickable.scrollIntoView({ block: 'center', inline: 'center' });
    clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
    clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
    clickable.click();
    return true;
  })()
}

// ---------- 7. checkbox-by-text ----------
function clickCheckboxByText(labelText) {
  return (() => {
    const target = __A__.replace(/\s+/g, ' ').trim().toLowerCase();
    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const disabled = (el) => Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('is-disabled')));
    const clickElement = (el) => {
      if (!el || disabled(el)) return false;
      const clickable = visible(el) ? el : el.closest('label, .el-checkbox, .ant-checkbox-wrapper, [role="checkbox"]');
      if (!clickable || !visible(clickable) || disabled(clickable)) return false;
      clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      clickable.click();
      const input = clickable.matches('input[type="checkbox"]') ? clickable : clickable.querySelector('input[type="checkbox"]');
      if (input) input.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    };

    for (const label of Array.from(document.querySelectorAll('label'))) {
      if (!text(label).toLowerCase().includes(target)) continue;
      if (clickElement(label.closest('.el-checkbox, .ant-checkbox-wrapper') || label)) return true;
    }

    for (const node of Array.from(document.querySelectorAll('.el-checkbox, .ant-checkbox-wrapper, [role="checkbox"]'))) {
      if (text(node).toLowerCase().includes(target) && clickElement(node)) return true;
    }

    for (const input of Array.from(document.querySelectorAll('input[type="checkbox"]'))) {
      let node = input;
      for (let depth = 0; node && depth < 6; depth++) {
        if (text(node).toLowerCase().includes(target) && clickElement(node)) return true;
        node = node.parentElement;
      }
    }

    return false;
  })()
}

// ---------- 8. get-value ----------
function getValue(selector) {
  return (() => {
    const selector = __A__;
    if (selector.startsWith('@')) return undefined;

    const parsed = (() => {
      const index = selector.indexOf(':');
      if (index > 0) {
        return { role: selector.slice(0, index).trim().toLowerCase(), name: selector.slice(index + 1).trim().toLowerCase() };
      }
      return { role: '', name: selector.trim().toLowerCase() };
    })();

    const text = (node) => (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
    const byId = (id) => id ? document.getElementById(id) : null;
    const labelFor = (el) => {
      const id = el.getAttribute('id');
      if (!id) return '';
      const label = document.querySelector('label[for="' + CSS.escape(id) + '"]');
      return text(label);
    };
    const labelledBy = (el) => (el.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .map(id => text(byId(id)))
      .filter(Boolean)
      .join(' ');
    const wrappingLabel = (el) => text(el.closest('label'));
    const nearbyText = (el) => {
      const parent = el.parentElement;
      if (!parent) return '';
      const labels = Array.from(parent.querySelectorAll('label, .label, [class*=label], [class*=Label]')).map(text).filter(Boolean);
      if (labels.length) return labels.join(' ');
      return text(parent).replace(el.value || '', '').trim();
    };
    const accessibleName = (el) => [
      el.getAttribute('aria-label') || '',
      el.getAttribute('placeholder') || '',
      el.getAttribute('title') || '',
      labelledBy(el),
      labelFor(el),
      wrappingLabel(el),
      nearbyText(el)
    ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();

    const roleOf = (el) => {
      const explicit = (el.getAttribute('role') || '').toLowerCase();
      if (explicit) return explicit;
      const tag = el.tagName.toLowerCase();
      if (tag === 'textarea') return 'textbox';
      if (tag === 'select') return 'combobox';
      if (tag === 'input') {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        if (['button', 'submit', 'reset'].includes(type)) return 'button';
        if (['checkbox', 'radio', 'slider'].includes(type)) return type;
        return 'textbox';
      }
      if (el.isContentEditable) return 'textbox';
      return '';
    };

    const roleMatches = (el) => {
      if (!parsed.role) return true;
      const actual = roleOf(el);
      if (actual === parsed.role) return true;
      return parsed.role === 'textbox' && ['searchbox'].includes(actual);
    };
    const nameMatches = (el) => {
      if (!parsed.name) return true;
      const name = accessibleName(el);
      return name === parsed.name || name.includes(parsed.name);
    };
    const readValue = (el) => {
      if ('value' in el) return el.value;
      return text(el);
    };

    const candidates = Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"], [role="textbox"], [role="combobox"], [role="searchbox"]'));
    const exact = candidates.find(el => roleMatches(el) && accessibleName(el) === parsed.name);
    const found = exact || candidates.find(el => roleMatches(el) && nameMatches(el));
    return found ? readValue(found) : undefined;
  })()
}

// ---------- 迷你 dispatcher ----------
window.__web_qa_dispatch = function (kind, a, b, c) {
  switch (kind) {
    case 'type_by_selector': return typeBySelector(a, b);
    case 'click_row_action': return clickRowAction(a, b);
    case 'click_pagination': return clickPagination(a);
    case 'has_text': return hasText(a);
    case 'click_by_text': return clickByText(a);
    case 'select_option': return selectOption(a);
    case 'click_checkbox_by_text': return clickCheckboxByText(a);
    case 'get_value': return getValue(a);
  }
  return null;
};

window.__web_qa_dispatch('__KIND__', __A__, __B__, __C__);
