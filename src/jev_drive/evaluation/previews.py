"""Render every attempt, including an explicit card when no decision completed."""
import asyncio
from pathlib import Path
import sys
from .retries import decisions


def status_cards(attempt):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    import textwrap
    out = Path(attempt['output']) / 'previews'
    out.mkdir(parents=True, exist_ok=True)
    for lang in ['en', 'zh']:
        title = 'No completed driving decision' if lang == 'en' else '未完成驾驶决策'
        font = FontProperties(family='sans-serif' if lang == 'en' else 'Noto Sans CJK JP')
        fig, ax = plt.subplots(figsize=(12, 4)); ax.axis('off')
        ax.text(.03, .85, title, fontproperties=font, fontsize=18)
        ax.text(.03, .68, Path(attempt['output']).name + '\n' + textwrap.fill(str(attempt.get('error') or 'No recorded trajectory'), 110), va='top', fontsize=10, fontproperties=font)
        fig.savefig(out / f'status-{lang}.png', bbox_inches='tight'); plt.close(fig)


async def render_attempts(result, artifact, script):
    reports = []
    for attempt in result.get('attempts', []):
        out = Path(attempt['output'])
        record = {'attempt': out.name}
        try:
            if not decisions(out / 'decisions.jsonl'):
                status_cards(attempt)
                record.update(status='completed', kind='no_decision_card')
            else:
                with (out / 'preview.log').open('w') as log:
                    process = await asyncio.create_subprocess_exec(sys.executable, str(script), '--run', str(out), '--artifact', str(artifact), stdout=log, stderr=log)
                    code = await process.wait()
                record.update(status='completed' if code == 0 else 'failed', kind='trajectory', exit_code=code)
        except Exception as exc:
            record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        reports.append(record)
    return reports
