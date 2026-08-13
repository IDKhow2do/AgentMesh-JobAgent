"""Zhilian live read-only DOM selectors."""

from __future__ import annotations

import json

ZHILIAN_SELECTOR_VERSION = "2026-08-13.2"

_ZHILIAN_SESSION_PROBE_JS = r"""
      function zhilianSessionProbe(){
        const href = location.href || '';
        const title = document.title || '';
        const readyState = document.readyState || 'unknown';
        const navigationEntry = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
        const navigationElapsedMs = Math.round(
          navigationEntry && Number.isFinite(navigationEntry.duration) && navigationEntry.duration > 0
            ? navigationEntry.duration
            : performance.now()
        );
        const bodyText = (document.body && (document.body.innerText || document.body.textContent) || '').trim();
        function clean(value){
          return String(value || '').replace(/\s+/g, ' ').trim();
        }
        function visible(el){
          if (!el || !(el instanceof Element)) return false;
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity || '1') !== 0
            && rect.width > 6
            && rect.height > 6;
        }
        const sessionEvidenceVersion = 2;
        const authRoute = /passport|(?:^|[/._-])login(?:[/._?=-]|$)/i.test(href);
        const weakLoginEvidence = [];
        const strongLoginEvidence = [];
        const accountEvidence = [];
        const strongAccountEvidence = [];
        const controls = Array.from(document.querySelectorAll('a,button,[role="button"],[aria-label]'))
          .filter(visible);
        for (const el of controls){
          const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
          const target = clean(el.getAttribute('href') || '');
          if (/^(登录|登录[/]注册|注册[/]登录|扫码登录|验证码登录|手机验证码)$/.test(text)
              || /passport|(?:^|[/._-])login(?:[/._?=-]|$)/i.test(target)) {
            weakLoginEvidence.push('visible_login_control');
          }
          if (/^(我的|消息|个人中心|简历中心|我的简历|在线简历|求职中心)$/.test(text)
              || (/[/](?:my|user|personal|account|resume|message)(?:[/._?=-]|$)/i.test(target)
                  && !/passport|login/i.test(target))) {
            accountEvidence.push('account_navigation');
          }
        }
        const visibleInputs = Array.from(document.querySelectorAll('input')).filter(visible);
        const credentialInputs = visibleInputs.filter((el) => {
          const type = clean(el.getAttribute('type') || '').toLowerCase();
          const hint = clean([
            el.getAttribute('name'),
            el.getAttribute('placeholder'),
            el.getAttribute('autocomplete'),
            el.getAttribute('aria-label')
          ].join(' '));
          return type === 'password'
            || /密码|手机号|手机号码|验证码|账号|username|password|one-time-code|tel/i.test(hint);
        });
        const authSurfaces = Array.from(document.querySelectorAll(
          'form,[role="dialog"],[aria-modal="true"],[class*="login"],[class*="Login"],[class*="passport"]'
        )).filter(visible).filter((el) => /登录|验证码|扫码|密码/.test(clean(el.innerText || el.textContent || '')));
        if (authRoute) strongLoginEvidence.push('auth_route');
        if (credentialInputs.some((input) => authSurfaces.some((surface) => surface.contains(input)))) {
          strongLoginEvidence.push('visible_credential_form');
        }
        if (authSurfaces.some((surface) => {
          const text = clean(surface.innerText || surface.textContent || '');
          return /扫码登录|验证码登录|密码登录/.test(text)
            && !!surface.querySelector('img,canvas,svg,[class*="qr"],[class*="Qr"]');
        })) {
          strongLoginEvidence.push('visible_login_challenge');
        }
        const identitySelectors = [
          '[data-user-name]',
          '[data-account-name]',
          '[aria-label*="个人头像"]',
          '[aria-label*="用户中心"]',
          '[class*="user-info"] [class*="name"]',
          '[class*="userInfo"] [class*="name"]'
        ].join(',');
        if (Array.from(document.querySelectorAll(identitySelectors)).some((el) => {
          if (!visible(el)) return false;
          const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
          return !!text && !/登录|注册/.test(text);
        })) {
          strongAccountEvidence.push('profile_identity');
        }
        const resumeMarkers = ['在线简历', '上传附件', '我的简历', '简历中心', '简历管理']
          .filter((marker) => bodyText.includes(marker));
        if (new Set(resumeMarkers).size >= 2) {
          strongAccountEvidence.push('resume_management');
        }
        const hasDeliveryActivity = /我的投递|投递记录|投递反馈|投递进度|投递统计|投递\s*\d+/.test(bodyText);
        const hasInterviewActivity = /我的面试|面试邀请|面试通知|面试记录|面试统计|面试\s*\d+/.test(bodyText);
        if (hasDeliveryActivity && hasInterviewActivity) {
          strongAccountEvidence.push('application_activity');
        }
        const contentEvidence = [];
        const searchInput = Array.from(document.querySelectorAll('input[type="text"],input[type="search"],input:not([type])'))
          .find(visible);
        if (searchInput) contentEvidence.push('search_input');
        if (Array.from(document.querySelectorAll('a[href*="/jobdetail/"]')).some(visible)) {
          contentEvidence.push('job_results');
        }
        const weakLogin = Array.from(new Set(weakLoginEvidence));
        const strongLogin = Array.from(new Set(strongLoginEvidence));
        const account = Array.from(new Set(accountEvidence));
        const strongAccount = Array.from(new Set(strongAccountEvidence));
        const hasAccountNavigation = account.includes('account_navigation');
        const hasStrongAccount = strongAccount.length >= 2
          || (hasAccountNavigation && strongAccount.length >= 1);
        const hasStrongLogin = strongLogin.length > 0;
        let sessionState = 'unknown';
        let sessionReason = 'insufficient_evidence';
        if (authRoute) {
          sessionState = 'login_required';
          sessionReason = 'authentication_route';
        } else if (readyState !== 'complete') {
          sessionState = 'loading';
          sessionReason = 'document_loading';
        } else if (hasStrongLogin && hasStrongAccount) {
          sessionState = 'unknown';
          sessionReason = 'strong_login_and_account_conflict';
        } else if (hasStrongLogin) {
          sessionState = 'login_required';
          sessionReason = 'strong_login_evidence';
        } else if (hasStrongAccount) {
          sessionState = 'logged_in';
          sessionReason = weakLogin.length
            ? 'strong_account_overrides_weak_login_control'
            : 'strong_account_evidence';
        } else if (weakLogin.length && account.length) {
          sessionState = 'unknown';
          sessionReason = 'weak_login_and_account_evidence';
        } else if (weakLogin.length) {
          sessionState = 'login_required';
          sessionReason = 'weak_login_without_account_evidence';
        } else if (account.length) {
          sessionState = 'unknown';
          sessionReason = 'account_evidence_below_threshold';
        } else if (contentEvidence.length) {
          sessionState = 'page_ready';
          sessionReason = 'public_content_ready';
        }
        return {
          url: href,
          title,
          readyState,
          navigationElapsedMs,
          sessionEvidenceVersion,
          sessionState,
          sessionReason,
          loginRequired: sessionState === 'login_required',
          loginEvidence: Array.from(new Set([...weakLogin, ...strongLogin])),
          weakLoginEvidence: weakLogin,
          strongLoginEvidence: strongLogin,
          accountEvidence: account,
          strongAccountEvidence: strongAccount,
          contentEvidence: Array.from(new Set(contentEvidence)),
          evidenceDecision: {
            reason: sessionReason,
            hasStrongLogin,
            hasStrongAccount,
            hasAccountNavigation,
            strongAccountThreshold: hasAccountNavigation ? 1 : 2
          },
          bodySnippet: bodyText.slice(0, 800)
        };
      }
"""


def build_zhilian_session_probe_script() -> str:
    return f"""
    (function(){{
      {_ZHILIAN_SESSION_PROBE_JS}
      return JSON.stringify({{ok: true, ...zhilianSessionProbe()}});
    }})()
    """


def build_zhilian_keyword_search_script(keyword: str) -> str:
    safe_keyword = json.dumps(keyword, ensure_ascii=False)
    return f"""
    (function(){{
      const mode = 'zhilian_keyword_search';
      const keyword = {safe_keyword};
      {_ZHILIAN_SESSION_PROBE_JS}
      const session = zhilianSessionProbe();
      const href = session.url;
      const title = session.title;
      const bodyText = (document.body && (document.body.innerText || document.body.textContent) || '').trim();
      function clean(value){{
        return String(value || '').replace(/\\s+/g, ' ').trim();
      }}
      function visible(el){{
        if (!el || !(el instanceof Element)) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
          && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0
          && rect.width > 8
          && rect.height > 8;
      }}
      function clickPoint(el){{
        const rect = el.getBoundingClientRect();
        return {{
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2),
          tag: el.tagName,
          className: String(el.className || '').slice(0, 120),
          text: clean(el.innerText || el.textContent || '')
        }};
      }}
      if (session.loginRequired) {{
        return JSON.stringify({{ok: false, mode, error: 'zhilian_login_required', ...session}});
      }}
      if (session.sessionState === 'loading' || session.sessionState === 'unknown') {{
        return JSON.stringify({{ok: false, mode, error: 'zhilian_page_state_pending', ...session}});
      }}
      const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])'))
        .filter(visible)
        .map((el) => {{
          const placeholder = clean(el.getAttribute('placeholder') || '');
          const name = clean(el.getAttribute('name') || '');
          const id = clean(el.id || '');
          const score =
            (/职位|公司|搜索|关键/.test(placeholder) ? 8 : 0)
            + (/keyword|search|kw/i.test(name + ' ' + id) ? 4 : 0)
            + (el.getBoundingClientRect().top < 320 ? 2 : 0);
          return {{el, score, placeholder}};
        }})
        .sort((a, b) => b.score - a.score);
      const input = inputs[0] && inputs[0].score > 0 ? inputs[0].el : null;
      if (!input) {{
        return JSON.stringify({{ok: false, mode, error: 'zhilian_keyword_input_not_found', url: href, title}});
      }}
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, keyword);
      input.dispatchEvent(new Event('input', {{bubbles: true}}));
      input.dispatchEvent(new Event('change', {{bubbles: true}}));
      const inputRect = input.getBoundingClientRect();
      const buttons = Array.from(document.querySelectorAll('button, [role="button"], a'))
        .filter(visible)
        .map((el) => {{
          const rect = el.getBoundingClientRect();
          const text = clean(el.innerText || el.textContent || '');
          const distance = Math.abs(rect.left - inputRect.right)
            + Math.abs(rect.top - inputRect.top);
          return {{el, text, rect, distance}};
        }})
        .filter((item) => /^(搜索|搜职位|找工作)$/.test(item.text))
        .filter((item) => item.rect.top < 400)
        .sort((a, b) => a.distance - b.distance);
      const button = buttons[0] && buttons[0].el;
      if (!button) {{
        return JSON.stringify({{
          ok: false,
          mode,
          error: 'zhilian_keyword_submit_not_found',
          keyword,
          observedValue: clean(input.value),
          url: href,
          title
        }});
      }}
      const originalTarget = clean(button.getAttribute('target') || '');
      const targetNormalized = originalTarget.toLowerCase() === '_blank';
      if (targetNormalized) {{
        button.setAttribute('target', '_self');
      }}
      return JSON.stringify({{
        ok: true,
        mode,
        action: 'submit_keyword',
        keyword,
        observedValue: clean(input.value),
        originalTarget,
        targetNormalized,
        clickPoint: clickPoint(button),
        urlBefore: href,
        ...session
      }});
    }})()
    """


def build_zhilian_pagination_script(page: int) -> str:
    safe_page = max(1, int(page))
    return f"""
    (function(){{
      const mode = 'zhilian_pagination';
      const targetPage = {safe_page};
      function clean(value){{
        return String(value || '').replace(/\\s+/g, ' ').trim();
      }}
      function visible(el){{
        if (!el || !(el instanceof Element)) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
          && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0
          && rect.width > 8
          && rect.height > 8;
      }}
      function point(el){{
        const rect = el.getBoundingClientRect();
        return {{x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2)}};
      }}
      if (targetPage <= 1) {{
        return JSON.stringify({{ok: true, mode, alreadySelected: true, page: 1}});
      }}
      const candidates = Array.from(document.querySelectorAll('a, button, li, [role="button"]'))
        .filter(visible)
        .filter((el) => clean(el.innerText || el.textContent || '') === String(targetPage))
        .map((el) => {{
          const rect = el.getBoundingClientRect();
          const selected = /active|selected|current/.test(String(el.className || ''))
            || el.getAttribute('aria-current') === 'page';
          return {{el, rect, selected}};
        }})
        .filter((item) => item.rect.top > 300)
        .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
      if (!candidates.length) {{
        return JSON.stringify({{ok: false, mode, error: 'zhilian_page_option_not_found', page: targetPage, url: location.href || ''}});
      }}
      const item = candidates[0];
      if (item.selected) {{
        return JSON.stringify({{ok: true, mode, alreadySelected: true, page: targetPage, url: location.href || ''}});
      }}
      return JSON.stringify({{
        ok: true,
        mode,
        action: 'select_page',
        page: targetPage,
        clickPoint: point(item.el),
        urlBefore: location.href || ''
      }});
    }})()
    """


def build_zhilian_city_filter_script(city: str) -> str:
    safe_city = json.dumps(city, ensure_ascii=False)
    return f"""
    (function(){{
      const mode = 'zhilian_city_filter';
      const targetCity = {safe_city};
      {_ZHILIAN_SESSION_PROBE_JS}
      const session = zhilianSessionProbe();
      const href = session.url;
      const title = session.title;
      const bodyText = (document.body && (document.body.innerText || document.body.textContent) || '').trim();
      if (!targetCity) {{
        return JSON.stringify({{ok: true, mode, skipped: true}});
      }}
      if (session.loginRequired) {{
        return JSON.stringify({{ok: false, mode, error: 'zhilian_login_required', ...session}});
      }}
      if (session.sessionState === 'loading' || session.sessionState === 'unknown') {{
        return JSON.stringify({{ok: false, mode, error: 'zhilian_page_state_pending', ...session}});
      }}
      function clean(value){{
        return String(value || '').replace(/\\s+/g, ' ').trim();
      }}
      function visible(el){{
        if (!el || !(el instanceof Element)) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
          && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0
          && rect.width > 8
          && rect.height > 8;
      }}
      function directText(el){{
        const own = Array.from(el.childNodes || [])
          .filter((node) => node.nodeType === Node.TEXT_NODE)
          .map((node) => node.textContent || '')
          .join('');
        return clean(own) || clean(el.innerText || el.textContent || '');
      }}
      function clickPoint(el){{
        const target = el.closest('a,button,label,li,span,div') || el;
        const rect = target.getBoundingClientRect();
        return {{
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2),
          tag: target.tagName,
          className: String(target.className || '').slice(0, 120),
          text: directText(target)
        }};
      }}
      const cityNames = ['北京','上海','广州','深圳','天津','武汉','西安','成都','大连','长春','沈阳','南京','济南','青岛','杭州','苏州','无锡','宁波','重庆','郑州','长沙','福州','厦门','哈尔滨'];
      const visibleElements = Array.from(document.querySelectorAll('body *')).filter(visible);
      function cityCount(text){{
        return cityNames.reduce((count, name) => count + (text.includes(name) ? 1 : 0), 0);
      }}
      function findLocationHeader(){{
        const matches = visibleElements
          .filter((el) => /^地点\\s*[⌄∨▾⌃∧▲▼]?$/.test(directText(el)) || directText(el) === '地点')
          .map((el) => {{
            const rect = el.getBoundingClientRect();
            return {{el, rect, area: rect.width * rect.height}};
          }})
          .filter((item) => item.rect.top < 320)
          .sort((a, b) => a.area - b.area);
        return matches[0] && matches[0].el;
      }}
      function findCurrentCityControl(){{
        const matches = visibleElements
          .filter((el) => {{
            const rect = el.getBoundingClientRect();
            const className = String(el.className || '');
            const parentClass = String(el.parentElement && el.parentElement.className || '');
            const text = directText(el);
            return rect.top < 320
              && cityNames.includes(text)
              && (
                className.includes('content-s__item__text')
                || parentClass.includes('content-s__item')
              );
          }})
          .map((el) => {{
            const rect = el.getBoundingClientRect();
            return {{el, rect, area: rect.width * rect.height}};
          }})
          .sort((a, b) => a.area - b.area);
        return matches[0] && matches[0].el;
      }}
      const currentCityControl = findCurrentCityControl();
      const currentCity = currentCityControl ? directText(currentCityControl) : '';
      if (currentCityControl && currentCity === targetCity) {{
        return JSON.stringify({{
          ok: true,
          mode,
          city: targetCity,
          observedCity: currentCity,
          alreadySelected: true,
          source: 'visible_current_city',
          url: href,
          title
        }});
      }}
      function findLocationRoot(){{
        const header = findLocationHeader();
        if (header) {{
          let root = header;
          let best = header;
          for (let i = 0; i < 8 && root.parentElement; i++) {{
            root = root.parentElement;
            if (!visible(root)) continue;
            const rect = root.getBoundingClientRect();
            const plausibleFilterRoot = rect.top < 320 && rect.height <= 700 && rect.width >= 200;
            const text = clean(root.innerText || root.textContent || '');
            if (text.includes('地点') && plausibleFilterRoot) best = root;
            if (plausibleFilterRoot && text.includes('地点') && text.includes(targetCity) && cityCount(text) >= 4) {{
              return root;
            }}
          }}
          return best;
        }}
        const candidates = visibleElements
          .map((el) => {{
            const text = clean(el.innerText || el.textContent || '');
            const rect = el.getBoundingClientRect();
            return {{el, text, rect, count: cityCount(text)}};
          }})
          .filter((item) => item.rect.top < 700 && item.text.includes(targetCity) && item.count >= 4)
          .sort((a, b) => a.text.length - b.text.length);
        return candidates[0] && candidates[0].el;
      }}
      let root = findLocationRoot();
      let expanded = false;
      if (!root || !clean(root.innerText || root.textContent || '').includes(targetCity) || cityCount(clean(root.innerText || root.textContent || '')) < 4) {{
        const header = findLocationHeader() || currentCityControl;
        if (header) {{
          expanded = true;
        }}
        return JSON.stringify({{
          ok: false,
          mode,
          error: 'zhilian_city_options_collapsed',
          action: 'expand_location',
          expanded,
          clickPoint: header ? clickPoint(header) : null,
          city: targetCity,
          url: href,
          title
        }});
      }}
      const options = Array.from(root.querySelectorAll('a,button,label,li,span,div'))
        .filter(visible)
        .filter((el) => directText(el) === targetCity)
        .map((el) => {{
          const rect = el.getBoundingClientRect();
          const className = String(el.className || '');
          const selected = /active|selected|checked|current/.test(className);
          return {{el, rect, selected}};
        }})
        .filter((item) => item.rect.top < 700)
        .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
      if (!options.length) {{
        return JSON.stringify({{
          ok: false,
          mode,
          error: 'zhilian_city_option_not_found',
          city: targetCity,
          rootText: clean(root.innerText || root.textContent || '').slice(0, 500),
          url: href,
          title
        }});
      }}
      const option = options[0];
      if (option.selected) {{
        return JSON.stringify({{ok: true, mode, city: targetCity, alreadySelected: true, url: href, title}});
      }}
      return JSON.stringify({{
        ok: true,
        mode,
        city: targetCity,
        applied: true,
        action: 'select_city',
        clickPoint: clickPoint(option.el),
        urlBefore: href,
        title
      }});
    }})()
    """


def build_zhilian_snapshot_script(limit: int = 20) -> str:
    safe_limit = max(1, int(limit))
    return f"""
    (function(){{
      const selectorVersion = "{ZHILIAN_SELECTOR_VERSION}";
      const limit = {safe_limit};
      {_ZHILIAN_SESSION_PROBE_JS}
      const session = zhilianSessionProbe();
      const text = (document.body && (document.body.innerText || document.body.textContent) || '').trim();
      const title = session.title;
      const href = session.url;
      const loginRequired = session.loginRequired;
      function visible(el){{
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 40 && rect.height > 20;
      }}
      function clean(value){{
        return String(value || '').replace(/\\s+/g, ' ').trim();
      }}
      function visibleSearchInput(el){{
        if (!visible(el)) return false;
        const placeholder = clean(el.getAttribute('placeholder') || '');
        const name = clean(el.getAttribute('name') || '');
        const id = clean(el.id || '');
        return /职位|公司|搜索|关键/.test(placeholder)
          || /keyword|search|kw/i.test(name + ' ' + id);
      }}
      function lines(value){{
        return String(value || '').split(/\\n+/).map(clean).filter(Boolean);
      }}
      const ctaLabels = new Set(['立即投递', '立即沟通', '继续沟通', '继续聊', '聊一聊', '投递简历', '申请职位', '收藏', '举报']);
      function looksLikeMeta(line){{
        return !line || ctaLabels.has(line)
          || /^\\d+(?:\\.\\d+)?[-~—至]\\d+(?:\\.\\d+)?(?:万|千|[kK]|元)/.test(line)
          || /^面议$/.test(line)
          || /^(北京|上海|深圳|广州|杭州|成都|武汉|南京|苏州|西安|郑州|天津|重庆|临沂|长沙|泉州|保定|青岛)/.test(line)
          || /^(经验不限|\\d+-\\d+年|\\d+年以上|应届|本科|大专|硕士|博士|学历不限)/.test(line)
          || /^(高回复率|\\d+小时内回复可能性大|12小时内回复可能性大|今日活跃|昨日活跃|刚刚活跃)$/.test(line);
      }}
      function titleFrom(root, label){{
        const cleanLabel = clean(label);
        if (cleanLabel && !ctaLabels.has(cleanLabel) && cleanLabel.length >= 2 && cleanLabel.length <= 80) return cleanLabel;
        for (const line of lines(root.innerText || root.textContent || '')) {{
          if (line.length < 2 || line.length > 80) continue;
          if (looksLikeMeta(line)) continue;
          return line;
        }}
        return cleanLabel;
      }}
      function cardRoot(anchor){{
        let root = anchor;
        let best = anchor;
        for (let i = 0; i < 9 && root.parentElement; i++) {{
          root = root.parentElement;
          const raw = clean(root.innerText || root.textContent || '');
          const hasJobSignal = /立即投递|立即沟通|今日回复|刚刚活跃|高回复率|\\d+(?:\\.\\d+)?[-~—至]\\d+(?:\\.\\d+)?(?:万|千|[kK]|元)|面议/.test(raw);
          const hasAction = /立即投递|立即沟通|继续沟通|投递简历|申请职位/.test(raw);
          const hasCompanySignal = /公司|集团|有限公司|股份|科技|信息|咨询|人力资源/.test(raw);
          if (raw.length >= 20 && hasJobSignal) {{
            best = root;
            const applyMentions = (raw.match(/立即投递/g) || []).length;
            if (raw.length >= 60 && raw.length <= 2200 && applyMentions <= 2 && (hasAction || hasCompanySignal)) break;
          }}
        }}
        return best;
      }}
      const anchors = Array.from(document.querySelectorAll('a[href]')).filter(visible);
      const searchInput = Array.from(document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])'))
        .find(visibleSearchInput);
      const platformError = /搜索内容.{0,12}(全部|全为|都是)特殊字符|关键词.{0,12}(全部|全为|都是)特殊字符|请重新输入搜索/.test(text.slice(0, 1200))
        ? 'zhilian_keyword_rejected'
        : '';
      const navLabels = new Set(['首页', '职位推荐', '城市频道', '政企招聘', '校园招聘', '高端职位', '海外招聘', '驻外专区', '测评及培训', '职Q社区', '我要招人']);
      const cityNames = ['北京','上海','广州','深圳','天津','武汉','西安','成都','大连','长春','沈阳','南京','济南','青岛','杭州','苏州','无锡','宁波','重庆','郑州','长沙','福州','厦门','哈尔滨'];
      const selectedCityCandidates = Array.from(document.querySelectorAll('body *'))
        .filter(visible)
        .filter((el) => cityNames.includes(clean(el.innerText || el.textContent || '')))
        .filter((el) => {{
          const className = String(el.className || '') + ' ' + String(el.parentElement && el.parentElement.className || '');
          return /active|selected|checked|current/i.test(className)
            || el.getAttribute('aria-selected') === 'true'
            || el.getAttribute('aria-current') === 'true';
        }})
        .map((el) => ({{
          city: clean(el.innerText || el.textContent || ''),
          rect: el.getBoundingClientRect()
        }}))
        .filter((item) => item.rect.top < 420)
        .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
      const visibleCity = selectedCityCandidates.length ? selectedCityCandidates[0].city : '';
      const cards = [];
      const seen = new Set();
      for (const anchor of anchors) {{
        const url = anchor.href || '';
        const label = clean(anchor.innerText || anchor.textContent || '');
        if (!url || !/[/]jobdetail[/]/.test(url)) continue;
        if (navLabels.has(label)) continue;
        const root = cardRoot(anchor);
        const rawText = clean(root.innerText || root.textContent || '');
        if (!rawText || rawText.length < 20) continue;
        const hasJobSignal = /立即投递|立即沟通|今日回复|刚刚活跃|高回复率|\\d+(?:\\.\\d+)?[-~—至]\\d+(?:\\.\\d+)?(?:万|千|[kK]|元)|面议/.test(rawText);
        if (!hasJobSignal) continue;
        const title = titleFrom(root, label);
        if (!title || ctaLabels.has(title)) continue;
        const key = url.split('?')[0];
        if (seen.has(key)) continue;
        seen.add(key);
        const salary = (rawText.match(/\\d+(?:\\.\\d+)?[-~—至]\\d+(?:\\.\\d+)?万(?:·\\d+薪)?|\\d+(?:\\.\\d+)?[-~—至]\\d+(?:\\.\\d+)?千(?:·\\d+薪)?|\\d+[kK][-~—至]\\d+[kK](?:·\\d+薪)?|\\d+-\\d+元(?:[/]月)?|面议/) || [''])[0];
        const city = (rawText.match(/北京|上海|深圳|广州|杭州|成都|武汉|南京|苏州|西安|郑州|天津|重庆/) || [''])[0];
        cards.push({{
          jobTitle: title,
          jobUrl: url,
          salary,
          cityName: city,
          rawText: rawText.slice(0, 1200)
        }});
        if (cards.length >= limit) break;
      }}
      return JSON.stringify({{
        ok: true,
        platform: 'zhilian',
        selectorVersion,
        url: href,
        title,
        loginRequired,
        readyState: session.readyState,
        navigationElapsedMs: session.navigationElapsedMs,
        sessionEvidenceVersion: session.sessionEvidenceVersion,
        sessionState: session.sessionState,
        sessionReason: session.sessionReason,
        loginEvidence: session.loginEvidence,
        weakLoginEvidence: session.weakLoginEvidence,
        strongLoginEvidence: session.strongLoginEvidence,
        accountEvidence: session.accountEvidence,
        strongAccountEvidence: session.strongAccountEvidence,
        contentEvidence: session.contentEvidence,
        evidenceDecision: session.evidenceDecision,
        visibleCity,
        searchKeyword: searchInput ? clean(searchInput.value) : '',
        searchKeywordVisible: !!searchInput,
        platformError,
        candidateCount: cards.length,
        cards,
        bodySnippet: text.slice(0, 1200)
      }});
    }})()
    """
