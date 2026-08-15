"""Zhilian read-only detail-page extraction."""

from __future__ import annotations

import json
import re
from typing import Any

from jobagent.domain.models import Job
from jobagent.domain.reviewability import (
    is_reviewable_company,
    is_reviewable_job_title,
    is_reviewable_salary,
    normalize_reviewable_salary,
)


ZHILIAN_DETAIL_SELECTOR_VERSION = "2026-08-15.0"


def build_zhilian_detail_snapshot_script() -> str:
    return f"""
    (function(){{
      const selectorVersion = "{ZHILIAN_DETAIL_SELECTOR_VERSION}";
      const href = location.href || '';
      const title = document.title || '';
      const text = (document.body && (document.body.innerText || document.body.textContent) || '').trim();
      function clean(value){{
        return String(value || '').replace(/\\s+/g, ' ').trim();
      }}
      function visible(el){{
        if (!el || !(el instanceof Element)) return false;
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0 && rect.width > 0 && rect.height > 0;
      }}
      const loginUrlDetected = /[/](?:passport|login)(?:[/]|$)|passport\\./i.test(href);
      const strongLoginForm = Array.from(document.querySelectorAll(
        'form,[class*="login-dialog"],[class*="passport-login"],[class*="sign-content"]'
      )).filter(visible).some(el => {{
        const value = clean(el.innerText || el.textContent || '');
        return !!el.querySelector('input[type="password"],input[autocomplete="one-time-code"]')
          || (/密码登录|验证码登录|扫码登录/.test(value)
            && !!el.querySelector('input[type="tel"],input[name*="phone"]'));
      }});
      const securityChallenge = /[/](?:verify|security)(?:[/]|$)|code=36/i.test(href)
        || /安全验证|访问验证|人机验证|滑块验证/.test(title)
        || Array.from(document.querySelectorAll(
          '[class*="verify"],[class*="captcha"],[class*="security-check"]'
        )).filter(visible).some(el => /验证|滑块|captcha/i.test(clean(el.innerText || el.textContent || el.className)));
      const loginRequired = loginUrlDetected || strongLoginForm || securityChallenge;
      function firstValue(values){{
        return values.map(clean).find(Boolean) || '';
      }}
      function readPath(root, path){{
        let current = root;
        for (const key of path) {{
          if (!current || typeof current !== 'object') return '';
          current = current[key];
        }}
        return current;
      }}
      function normalizeSalary(value){{
        const salary = clean(value);
        if (!salary) return '';
        if (/薪资不公开|薪酬不公开|工资不公开|薪资保密|薪酬保密|工资保密/.test(salary)) return '薪资不公开';
        if (/薪资面议|薪酬面议|待遇面议|工资面议|^面议$/.test(salary)) return '薪资面议';
        const match = salary.match(/\\d+(?:\\.\\d+)?\\s*[-~—至]\\s*\\d+(?:\\.\\d+)?\\s*(?:万|千|[kK]|元)(?:[/／](?:月|年|天))?(?:·\\d+薪)?/);
        return match ? clean(match[0]) : '';
      }}
      function parseDocumentTitle(value){{
        const stripped = clean(value).replace(/\\s*-\\s*智联招聘\\s*$/, '');
        const marker = '招聘_';
        const index = stripped.indexOf(marker);
        if (index <= 0) return {{jobTitle: '', companyName: ''}};
        const jobTitle = clean(stripped.slice(0, index));
        const companyName = clean(stripped.slice(index + marker.length).replace(/招聘$/, ''));
        return {{jobTitle, companyName}};
      }}
      function parseJsonLd(){{
        for (const node of Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 20)) {{
          try {{
            const parsed = JSON.parse(node.textContent || '{{}}');
            const values = Array.isArray(parsed) ? parsed : [parsed];
            for (const value of values) {{
              if (!value || typeof value !== 'object') continue;
              const type = Array.isArray(value['@type']) ? value['@type'].join(' ') : value['@type'];
              if (!/JobPosting/i.test(String(type || ''))) continue;
              const organization = value.hiringOrganization || {{}};
              const baseSalary = value.baseSalary || {{}};
              const salaryValue = baseSalary.value || baseSalary;
              let salary = '';
              if (typeof salaryValue === 'string' || typeof salaryValue === 'number') {{
                salary = normalizeSalary(salaryValue);
              }} else if (salaryValue && typeof salaryValue === 'object') {{
                const min = clean(salaryValue.minValue);
                const max = clean(salaryValue.maxValue);
                const unit = clean(baseSalary.unitText || salaryValue.unitText).toUpperCase();
                const suffix = unit === 'YEAR' ? '元/年' : unit === 'DAY' ? '元/天' : '元/月';
                if (min && max) salary = normalizeSalary(`${{min}}-${{max}}${{suffix}}`);
              }}
              return {{
                jobTitle: clean(value.title || value.name),
                companyName: clean(organization.name || value.companyName),
                salary
              }};
            }}
          }} catch (_error) {{}}
        }}
        return {{jobTitle: '', companyName: '', salary: ''}};
      }}
      const genericLinkLabels = new Set([
        '更多','更多信息','了解更多','查看','查看信息','查看详情','查看更多',
        '查看更多信息','查看职位','查看职位详情','职位详情','详情','展开','点击查看'
      ]);
      const initialState = globalThis.__INITIAL_STATE__ && typeof globalThis.__INITIAL_STATE__ === 'object'
        ? globalThis.__INITIAL_STATE__ : {{}};
      const detailedPosition = readPath(initialState, ['jobDetail', 'detailedPosition']) || {{}};
      const detailedCompany = readPath(initialState, ['jobDetail', 'detailedCompany']) || {{}};
      const stateTitle = firstValue([
        detailedPosition.positionName,
        detailedPosition.jobTitle,
        detailedPosition.title
      ]);
      const stateCompany = firstValue([
        detailedCompany.companyName,
        detailedPosition.companyName
      ]);
      const stateSalary = normalizeSalary(firstValue([
        detailedPosition.salary,
        detailedPosition.salaryReal,
        detailedPosition.salary60
      ]));
      const jsonLd = parseJsonLd();
      const titleFields = parseDocumentTitle(title);
      const heading = Array.from(document.querySelectorAll(
        '.publisher-seo__job-title,h1,[class*="job-title"],[class*="jobTitle"],'
          + '[class*="position-name"],[class*="positionName"]'
      )).filter(visible)
        .map(el => clean(el.innerText || el.textContent || ''))
        .find(value => value.length >= 2 && value.length <= 80 && !genericLinkLabels.has(value)) || '';
      const meta = {{}};
      const rows = Array.from(document.querySelectorAll('li,span,p,div')).slice(0, 500);
      for (const el of rows) {{
        const value = clean(el.innerText || el.textContent || '');
        if (!value || value.length > 120) continue;
        if (!meta.experience && /(经验不限|应届|\\d+-\\d+年|\\d+年以上)/.test(value)) meta.experience = value.match(/经验不限|应届|\\d+-\\d+年|\\d+年以上/)[0];
        if (!meta.degree && /(博士|硕士|本科|大专|学历不限)/.test(value)) meta.degree = value.match(/博士|硕士|本科|大专|学历不限/)[0];
      }}
      const companyCandidates = Array.from(document.querySelectorAll('a[href*="company"],a[href*="comdetail"],[class*="company"]'))
        .filter(visible).map(el => clean(el.innerText || el.textContent || ''))
        .filter(value => value.length >= 2 && value.length <= 80 && !/职位|招聘|登录|立即/.test(value));
      const salaryNode = Array.from(document.querySelectorAll(
        '.jobs-deliver__salary,.summary-planes__salary:not(.summary-planes__salary--hidden),'
          + '[data-testid="job-salary"],[class*="job-salary"],[class*="jobSalary"]'
      )).find(visible) || null;
      const domSalary = normalizeSalary(salaryNode ? salaryNode.innerText || salaryNode.textContent : '');
      const explicitSalaryLabel = Array.from(document.querySelectorAll('span,p,div'))
        .filter(visible)
        .map(el => clean(el.innerText || el.textContent || ''))
        .find(value => value.length <= 24 && /^(?:薪资|薪酬|工资|待遇)?(?:面议|不公开|保密)$/.test(value)) || '';
      const jobTitle = firstValue([stateTitle, heading, jsonLd.jobTitle, titleFields.jobTitle]);
      const companyName = firstValue([stateCompany, companyCandidates[0], jsonLd.companyName, titleFields.companyName]);
      const salary = firstValue([stateSalary, jsonLd.salary, domSalary, normalizeSalary(explicitSalaryLabel)]);
      return JSON.stringify({{
        ok: true,
        platform: 'zhilian',
        mode: 'detail_read_only',
        selectorVersion,
        url: href,
        title,
        readyState: document.readyState || '',
        loginRequired,
        loginEvidence: loginUrlDetected ? 'login_url' : strongLoginForm ? 'credential_form' : securityChallenge ? 'security_challenge' : 'none',
        jobTitle,
        companyName,
        salary,
        titleSource: stateTitle ? 'initial_state' : heading ? 'stable_detail_node' : jsonLd.jobTitle ? 'json_ld' : titleFields.jobTitle ? 'document_title' : '',
        companySource: stateCompany ? 'initial_state' : companyCandidates[0] ? 'stable_company_node' : jsonLd.companyName ? 'json_ld' : titleFields.companyName ? 'document_title' : '',
        salarySource: stateSalary ? 'initial_state' : jsonLd.salary ? 'json_ld' : domSalary ? 'stable_salary_node' : salary ? 'explicit_disclosure_label' : '',
        experience: meta.experience || '',
        degree: meta.degree || '',
        rawText: text.slice(0, 5000)
      }});
    }})()
    """


def parse_zhilian_detail_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    """Extract useful fields from a Zhilian detail snapshot."""
    text = re.sub(r"\s+", " ", str(snapshot.get("rawText") or "")).strip()
    title_fallback, company_fallback = _trusted_document_title_fields(snapshot)
    fields = {
        "name": _clean_title(
            snapshot.get("jobTitle") or title_fallback
        ),
        "company": _clean_company(
            snapshot.get("companyName") or company_fallback or _company_from_text(text)
        ),
        "salary": _clean_salary(snapshot.get("salary")),
        "city": _clean(_match_first(text, [
            r"(?:北京|上海|深圳|广州|杭州|成都|武汉|南京|苏州|西安|郑州|天津|重庆|东莞|泉州|保定|沈阳|长沙|临沂|青岛|合肥|佛山|福州|厦门|济南|无锡|大连|长春|石家庄|南昌|贵阳|南宁)(?=·|\s|$)",
        ])),
        "area": _clean(_area_from_text(text)),
        "experience": _clean(snapshot.get("experience") or _match_first(text, [r"\d+-\d+年", r"\d+年以上", r"经验不限", r"应届"])),
        "degree": _clean(snapshot.get("degree") or _match_first(text, [r"博士", r"硕士", r"本科", r"大专", r"学历不限"])),
        "boss": _clean(_boss_from_text(text)),
    }
    return {key: value for key, value in fields.items() if value}


def merge_zhilian_detail_into_job(job: Job, snapshot: dict[str, Any]) -> Job:
    """Fill missing search-card fields from a read-only detail snapshot."""
    fields = parse_zhilian_detail_snapshot(snapshot)
    raw_data = dict(job.raw_data or {})
    raw_data["detail_snapshot"] = snapshot
    return Job(
        name=job.name if is_reviewable_job_title(job.name) else fields.get("name", ""),
        salary=(
            job.salary if is_reviewable_salary(job.salary) else fields.get("salary", "")
        ),
        company=(
            job.company if is_reviewable_company(job.company) else fields.get("company", "")
        ),
        area=job.area or fields.get("area", ""),
        experience=job.experience or fields.get("experience", ""),
        degree=job.degree or fields.get("degree", ""),
        skills=job.skills,
        boss=job.boss or fields.get("boss", ""),
        city=fields.get("city", "") or job.city,
        url=job.url,
        platform=job.platform,
        raw_data=raw_data,
    )


def unwrap_zhilian_detail_js_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and "raw" in result:
        try:
            parsed = json.loads(result["raw"])
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {"ok": False, "error": "detail_snapshot_parse_failed", "raw": result["raw"]}
    return result if isinstance(result, dict) else {"ok": False, "error": "detail_snapshot_empty_result"}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_title(value: Any) -> str:
    title = _clean(value)
    return title if is_reviewable_job_title(title) else ""


def _clean_salary(value: Any) -> str:
    return normalize_reviewable_salary(value)


def _trusted_document_title_fields(snapshot: dict[str, Any]) -> tuple[str, str]:
    url = _clean(snapshot.get("url"))
    if not re.match(r"^https://(?:www\.)?zhaopin\.com/jobdetail/", url, re.I):
        return "", ""
    title = re.sub(r"\s*-\s*智联招聘\s*$", "", _clean(snapshot.get("title")))
    marker = "招聘_"
    if marker not in title:
        return "", ""
    job_title, company = title.split(marker, 1)
    company = re.sub(r"招聘$", "", company).strip()
    return _clean_title(job_title), _clean_company(company)


def _area_from_text(text: str) -> str:
    location = _match_first(text, [
        r"(?:北京|上海|深圳|广州|杭州|成都|武汉|南京|苏州|西安|郑州|天津|重庆|东莞|泉州|保定|沈阳|长沙|临沂|青岛|合肥|佛山|福州|厦门|济南|无锡|大连|长春|石家庄|南昌|贵阳|南宁)(?:·[\u4e00-\u9fa5A-Za-z0-9]+){1,3}",
    ])
    return location.split("·", 1)[1] if "·" in location else ""


def _company_from_text(text: str) -> str:
    patterns = [
        r"公司信息\s+([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,80})",
        r"企业名称\s+([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,80})",
        r"公司[:：]\s*([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,80})",
        r"企业[:：]\s*([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _clean_company(value: Any) -> str:
    company = _clean(value)
    if not company:
        return ""
    for marker in (" 未融资", " 不需要融资", " 已上市", " 合资", " 民营", " · ", " 20-", " 100-"):
        if marker in company:
            company = company.split(marker, 1)[0].strip()
    labels = ("客户公司名称 ", "公司名称 ")
    for label in labels:
        if company.startswith(label):
            company = company[len(label):].strip()
    return company if is_reviewable_company(company) else ""


def _boss_from_text(text: str) -> str:
    publisher = re.search(r"职位发布者\s+([\u4e00-\u9fa5]{2,4}(?:女士|先生|HR)?)", text)
    if publisher:
        return publisher.group(1)
    return _match_first(text, [r"[\u4e00-\u9fa5]{1,3}(?:女士|先生|HR)"])


def _match_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return ""
