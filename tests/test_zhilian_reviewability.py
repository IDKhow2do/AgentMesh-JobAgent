import pytest

from jobagent.domain.reviewability import is_reviewable_salary
from jobagent.platforms.zhilian.collect import _detail_snapshot_failure
from jobagent.platforms.zhilian.detail import merge_zhilian_detail_into_job
from jobagent.platforms.zhilian.parser import (
    is_reviewable_zhilian_job,
    parse_zhilian_job,
)
from jobagent.platforms.zhilian.selectors import build_zhilian_snapshot_script


def test_zhilian_parser_rejects_generic_detail_link_as_job_title():
    job = parse_zhilian_job(
        {
            "positionId": "ZL-GENERIC-TITLE",
            "jobTitle": "查看更多信息",
            "companyName": "深圳示例科技有限公司",
            "salary": "20-30K",
            "cityName": "深圳",
            "jobUrl": "https://www.zhaopin.com/jobdetail/ZL-GENERIC-TITLE.htm",
            "rawText": (
                "查看更多信息 深圳示例科技有限公司 深圳 20-30K 本科 立即投递"
            ),
        }
    )

    assert job.name == ""
    assert is_reviewable_zhilian_job(job) is False


def test_zhilian_detail_replaces_generic_title_and_completes_review_fields():
    card_job = parse_zhilian_job(
        {
            "positionId": "ZL-REPAIR-1",
            "jobTitle": "查看更多信息",
            "jobUrl": "https://www.zhaopin.com/jobdetail/ZL-REPAIR-1.htm",
            "cityName": "深圳",
        }
    )
    repaired = merge_zhilian_detail_into_job(
        card_job,
        {
            "ok": True,
            "jobTitle": "数据运营经理",
            "companyName": "深圳示例科技有限公司",
            "salary": "25-35K",
            "rawText": (
                "数据运营经理 25-35K 深圳 本科 公司信息 "
                "深圳示例科技有限公司 职位发布者 王女士"
            ),
        },
    )

    assert repaired.name == "数据运营经理"
    assert repaired.company == "深圳示例科技有限公司"
    assert repaired.salary == "25-35K"
    assert is_reviewable_zhilian_job(repaired) is True


def test_zhilian_snapshot_contract_prefers_stable_review_fields():
    script = build_zhilian_snapshot_script(limit=5)

    assert "genericLinkLabels" in script
    assert "stable_title_node" in script
    assert "stable_company_node" in script
    assert "looksLikeCompanyMeta" in script
    assert "深圳示例科技有限公司" in script


def test_explicit_negotiable_or_undisclosed_salary_is_reviewable():
    assert is_reviewable_salary("薪资面议") is True
    assert is_reviewable_salary("薪资不公开") is True
    assert is_reviewable_salary("薪酬保密") is True
    assert is_reviewable_salary("待遇优厚") is False


def test_zhilian_detail_nav_login_entry_is_not_a_forced_login_wall():
    snapshot = {
        "ok": True,
        "url": "https://www.zhaopin.com/jobdetail/ZL-NAV-LOGIN.htm",
        "readyState": "complete",
        "loginRequired": True,
        "loginEvidence": "header_login_link",
        "jobTitle": "基础设施运维管理专家",
        "companyName": "深圳示例云技术服务有限公司",
        "salary": "薪资不公开",
    }

    assert _detail_snapshot_failure(snapshot) == ""


@pytest.mark.parametrize(
    "evidence",
    ["login_url", "credential_form", "security_challenge"],
)
def test_zhilian_detail_strong_login_evidence_still_fails_closed(evidence):
    snapshot = {
        "ok": True,
        "url": "https://www.zhaopin.com/jobdetail/ZL-LOGIN.htm",
        "readyState": "complete",
        "loginRequired": True,
        "loginEvidence": evidence,
    }

    assert _detail_snapshot_failure(snapshot) == "zhilian_login_required"
