"""Official-careers routing helpers for the Codex-native workflow.

Codex discovers and verifies official career/ATS URLs. This module provides
routing, dedupe, queue state and a mandatory user-owned final review gate.
No real submission may begin until the exact queue snapshot has been approved.
"""
from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_MAX_OPEN_TABS=4
DEFAULT_MAX_FORM_TABS=2
DEFAULT_MAX_SUBMITS=1
OFFICIAL_CONFIDENCE_THRESHOLD=0.80
ATS_HOST_HINTS={"greenhouse":("greenhouse.io","boards.greenhouse.io"),"lever":("lever.co","jobs.lever.co"),"ashby":("ashbyhq.com","jobs.ashbyhq.com"),"workday":("myworkdayjobs.com","workday.com"),"smartrecruiters":("smartrecruiters.com",),"icims":("icims.com",),"jobvite":("jobvite.com",),"oracle":("oraclecloud.com","taleo.net"),"sap":("successfactors.com",),"moka":("mokahr.com","moka.com"),"beisen":("beisen.com",)}

def _norm(v:Any)->str:
    t=str(v or "").lower().strip(); t=re.sub(r"\s+","",t); return re.sub(r"[（()）【】\[\]·•,，。._\-/\\]","",t)
def canonical_job_key(job):
    seed="|".join([_norm(job.get("company")),_norm(job.get("title") or job.get("name")),_norm(job.get("city") or job.get("area"))]); return hashlib.sha256(seed.encode()).hexdigest()[:20]
def detect_ats(url):
    host=(urlparse(str(url or "")).hostname or "").lower()
    for n,hints in ATS_HOST_HINTS.items():
        if any(h in host for h in hints): return n
    return "generic_official"
def official_verified(job,threshold=OFFICIAL_CONFIDENCE_THRESHOLD):
    url=str(job.get("official_url") or "").strip()
    try: confidence=float(job.get("official_match_confidence",0))
    except (TypeError,ValueError): confidence=0
    return url.startswith(("https://","http://")) and confidence>=threshold and bool(job.get("official_evidence"))
def merge_cross_channel_jobs(jobs):
    grouped={}
    for raw in jobs:
        if not isinstance(raw,dict): continue
        key=canonical_job_key(raw); source={"platform":raw.get("platform"),"url":raw.get("url"),"id":raw.get("id")}; existing=grouped.get(key)
        if existing is None:
            existing=dict(raw); existing["canonical_job_key"]=key; existing["sources"]=[source]; grouped[key]=existing
        else:
            existing.setdefault("sources",[]).append(source)
            for f in ("jd","salary","experience","degree","skills"):
                if not existing.get(f) and raw.get(f): existing[f]=raw[f]
            if official_verified(raw) and not official_verified(existing):
                for f in ("official_url","official_match_confidence","official_evidence"): existing[f]=raw.get(f)
    return list(grouped.values())
@dataclass(frozen=True)
class BrowserLimits:
    max_open_tabs:int=DEFAULT_MAX_OPEN_TABS; max_form_tabs:int=DEFAULT_MAX_FORM_TABS; max_submits:int=DEFAULT_MAX_SUBMITS
    def __post_init__(self):
        if self.max_open_tabs<1: raise ValueError("max_open_tabs must be >= 1")
        if self.max_form_tabs<1 or self.max_form_tabs>self.max_open_tabs: raise ValueError("max_form_tabs must be between 1 and max_open_tabs")
        if self.max_submits!=1: raise ValueError("official submission must remain serial: max_submits=1")
@dataclass
class OfficialQueueItem:
    canonical_job_key:str; company:str; title:str; city:str; official_url:str|None; ats:str; preferred_channel:str; fallback_platform:str|None; fallback_url:str|None; status:str="queued"; last_error:str|None=None; submitted_via:str|None=None
    def to_dict(self): return asdict(self)
def queue_digest(queue):
    material=[{k:i.get(k) for k in ("canonical_job_key","company","title","city","official_url","preferred_channel","fallback_platform","fallback_url")} for i in queue.get("items",[]) if i.get("status") not in {"skipped","submitted"}]
    return hashlib.sha256(json.dumps(material,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def build_official_queue(jobs,threshold=OFFICIAL_CONFIDENCE_THRESHOLD):
    items=[]
    for job in merge_cross_channel_jobs(jobs):
        if str(job.get("decision") or "").lower() not in {"selected","review"}: continue
        official=official_verified(job,threshold); fp=str(job.get("platform") or "") or None
        items.append(OfficialQueueItem(str(job["canonical_job_key"]),str(job.get("company") or ""),str(job.get("title") or job.get("name") or ""),str(job.get("city") or job.get("area") or ""),str(job.get("official_url") or "") or None,detect_ats(job.get("official_url")) if official else "none","official" if official else "platform",fp,str(job.get("url") or "") or None).to_dict())
    q={"schema":"jobagent-official-queue-v2","policy":{"official_first":True,"official_confidence_threshold":threshold,"cross_channel_submit_once":True,"browser_limits":asdict(BrowserLimits()),"submit_is_serial":True,"final_user_review_required":True},"review_authorization":None,"items":items}
    q["review_digest"]=queue_digest(q); return q
def authorize_final_review(queue,approved_keys=None):
    approved=set(approved_keys or [i.get("canonical_job_key") for i in queue.get("items",[]) if i.get("status") not in {"skipped","submitted"}])
    for item in queue.get("items",[]):
        if item.get("status") in {"submitted","skipped"}: continue
        if item.get("canonical_job_key") not in approved: item["status"]="skipped"; item["last_error"]="excluded_by_user_final_review"
    digest=queue_digest(queue); queue["review_digest"]=digest
    queue["review_authorization"]={"approved":True,"approved_at":datetime.now().isoformat(timespec="seconds"),"digest":digest,"approved_keys":sorted(approved)}
    return queue["review_authorization"]
def review_is_valid(queue):
    auth=queue.get("review_authorization") or {}
    return bool(auth.get("approved") and auth.get("digest")==queue_digest(queue))
def claim_items(queue,kind="form"):
    limits=BrowserLimits(**queue.get("policy",{}).get("browser_limits",{})); cap=limits.max_form_tabs if kind=="form" else limits.max_open_tabs
    active=[i for i in queue.get("items",[]) if i.get("status") in {"claimed","filling","submitting"}]; available=max(0,cap-len(active)); claimed=[]
    for item in queue.get("items",[]):
        if available<=0: break
        if item.get("status")!="queued": continue
        item["status"]="claimed"; claimed.append(item); available-=1
    return claimed
def update_item(queue,key,status,*,error=None,submitted_via=None):
    allowed={"queued","claimed","filling","human_required","ready_to_submit","submitting","submitted","failed","skipped","fallback_platform"}
    if status not in allowed: raise ValueError(f"unsupported queue status: {status}")
    if status in {"submitting","submitted"} and not review_is_valid(queue): raise ValueError("final_user_review_required: queue changed or has not been explicitly approved")
    if status=="submitting" and any(i.get("status")=="submitting" and i.get("canonical_job_key")!=key for i in queue.get("items",[])): raise ValueError("submit concurrency is 1; another job is already submitting")
    for item in queue.get("items",[]):
        if item.get("canonical_job_key")==key:
            item["status"]=status; item["last_error"]=error
            if submitted_via: item["submitted_via"]=submitted_via
            return item
    raise KeyError(key)
def read_json(path:Path): return json.loads(path.read_text(encoding="utf-8"))
def write_json(path:Path,payload): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
