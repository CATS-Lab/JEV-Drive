import json
import pytest
from jev_drive.evaluation.previews import render_attempts


@pytest.mark.asyncio
async def test_each_attempt_rendered_including_zero_decisions(tmp_path, monkeypatch):
    import jev_drive.evaluation.previews as module
    attempts=[]; calls=[];cards=[]
    for i in range(3):
        out=tmp_path/f'attempt-{i:02d}';out.mkdir()
        (out/'decisions.jsonl').write_text(json.dumps({'event':'decision' if i<2 else 'failure'})+'\n')
        attempts.append({'output':str(out)})
    class Process:
        async def wait(self):return 0
    async def spawn(*args,**kwargs):calls.append(args);return Process()
    monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(module,'status_cards',lambda a:cards.append(a))
    result=await render_attempts({'attempts':attempts},'artifact','renderer')
    assert len(calls)==2 and len(cards)==1
    assert all(r['status']=='completed' for r in result)
    assert [r['attempt'] for r in result]==['attempt-00','attempt-01','attempt-02']
