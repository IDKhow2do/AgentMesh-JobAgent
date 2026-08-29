from __future__ import annotations
import argparse,json
from pathlib import Path
from jobagent.official import build_official_queue,claim_items,read_json,update_item,write_json,authorize_final_review,review_is_valid,queue_digest

def dump(v): print(json.dumps(v,ensure_ascii=False,indent=2))
def cmd_prepare(a):
 p=read_json(Path(a.input)); jobs=p.get("jobs",[]) if isinstance(p,dict) else p; q=build_official_queue(jobs,a.threshold); out=Path(a.out) if a.out else Path(a.input).with_name("official-queue.json"); write_json(out,q); dump({"ok":True,"queue":str(out),"count":len(q["items"]),"policy":q["policy"],"review_digest":q["review_digest"],"next":"Show the COMPLETE queue to the user for final review. Do not submit anything yet."}); return 0
def cmd_claim(a):
 p=Path(a.queue); q=read_json(p); claimed=claim_items(q,a.kind); write_json(p,q); dump({"ok":True,"claimed":claimed,"count":len(claimed),"final_review_valid":review_is_valid(q)}); return 0
def cmd_review(a):
 p=Path(a.queue); q=read_json(p)
 if not a.approve: dump({"ok":False,"error":"explicit_approval_required","digest":queue_digest(q),"items":q.get("items",[])}); return 2
 auth=authorize_final_review(q,a.key or None); write_json(p,q); dump({"ok":True,"authorization":auth,"items":q.get("items",[]),"next":"The exact reviewed queue is authorized. Submission may proceed serially; any later queue change invalidates this approval."}); return 0
def cmd_update(a):
 p=Path(a.queue); q=read_json(p)
 try: item=update_item(q,a.key,a.status,error=a.error,submitted_via=a.submitted_via)
 except ValueError as e: dump({"ok":False,"error":str(e),"final_review_valid":review_is_valid(q)}); return 2
 write_json(p,q); dump({"ok":True,"item":item,"final_review_valid":review_is_valid(q)}); return 0
def cmd_status(a):
 q=read_json(Path(a.queue)); counts={}
 for i in q.get("items",[]): counts[i.get("status","unknown")]=counts.get(i.get("status","unknown"),0)+1
 dump({"ok":True,"policy":q.get("policy",{}),"counts":counts,"final_review_valid":review_is_valid(q),"review_authorization":q.get("review_authorization"),"items":q.get("items",[]) if a.details else None}); return 0
def build_parser():
 p=argparse.ArgumentParser(prog="jobagent-official",description="Official-first queue with mandatory user final review gate"); sub=p.add_subparsers(dest="command",required=True)
 x=sub.add_parser("prepare"); x.add_argument("--input",required=True); x.add_argument("--out"); x.add_argument("--threshold",type=float,default=.80); x.set_defaults(func=cmd_prepare)
 x=sub.add_parser("claim"); x.add_argument("--queue",required=True); x.add_argument("--kind",choices=["browser","form"],default="form"); x.set_defaults(func=cmd_claim)
 x=sub.add_parser("review"); x.add_argument("--queue",required=True); x.add_argument("--approve",action="store_true",help="Record explicit user approval of the final queue"); x.add_argument("--key",action="append",help="Approve only these canonical job keys; omit to approve all currently eligible items"); x.set_defaults(func=cmd_review)
 x=sub.add_parser("update"); x.add_argument("--queue",required=True); x.add_argument("--key",required=True); x.add_argument("--status",required=True); x.add_argument("--error"); x.add_argument("--submitted-via"); x.set_defaults(func=cmd_update)
 x=sub.add_parser("status"); x.add_argument("--queue",required=True); x.add_argument("--details",action="store_true"); x.set_defaults(func=cmd_status); return p
def main():
 a=build_parser().parse_args(); raise SystemExit(a.func(a))
if __name__=="__main__": main()
