"""Read ("finished") state for a paired book.

Apple Books keeps it in ZBKLIBRARYASSET.ZISFINISHED and Kindle in
ZBOOK.ZRAWREADSTATE. Neither app uploads a value written into its database by
another program, so a change is made through the app's own book menu by the
bundled `readstate` helper, using Accessibility.
"""
import json
import os
from pathlib import Path
import subprocess

from . import paths
from .apple import discover, snapshot


def apple_state(apple_id):
    library, _ = discover()
    with snapshot(library) as db:
        row = db.execute('SELECT ZTITLE,ZAUTHOR,ZISFINISHED FROM ZBKLIBRARYASSET WHERE ZASSETID=?', (apple_id,)).fetchone()
    if row is None:
        raise ValueError('Apple Books book is missing')
    return {'title': row[0], 'author': row[1] or '', 'finished': bool(row[2])}


def kindle_state(modules, kindle_id):
    db = Path(modules['ksdk'].LASSEN_DATA) / 'Library/Protected/BookData.sqlite'
    with snapshot(db) as con:
        row = con.execute('SELECT ZDISPLAYTITLE,ZRAWREADSTATE FROM ZBOOK WHERE ZBOOKID=?',
                          ('A:' + kindle_id + '-0',)).fetchone()
    if row is None:
        raise ValueError('Kindle book is missing')
    return {'title': row[0], 'finished': row[1] == 1}


def status(modules, apple_id, kindle_id, baseline):
    apple, kindle = apple_state(apple_id), kindle_state(modules, kindle_id)
    result = {'apple': apple['finished'], 'kindle': kindle['finished']}
    if apple['finished'] == kindle['finished']:
        result['state'] = 'synced'
        return result
    base = baseline.get('read')
    if base and base.get('apple') == apple['finished']:
        target = 'apple'      # Kindle changed
    elif base and base.get('kindle') == kindle['finished']:
        target = 'kindle'     # Apple changed
    else:
        target = 'kindle' if apple['finished'] else 'apple'  # finished wins
    result.update(state='changed', default_target=target)
    return result


def tool():
    resources = os.environ.get('AKB_RESOURCES')
    return Path(resources) / 'readstate' if resources else paths.ROOT / '.runtime' / 'readstate'


def write(modules, apple_id, kindle_id, target):
    """Copy the other side's read state to `target` through that app's menu."""
    apple, kindle = apple_state(apple_id), kindle_state(modules, kindle_id)
    if target == 'kindle':
        args = ['kindle', kindle_id, kindle['title'], 'read' if apple['finished'] else 'unread']
    else:
        args = ['books', apple['title'], apple['author'], 'finished' if kindle['finished'] else 'reading']
    run = subprocess.run([str(tool()), *args], capture_output=True, text=True, timeout=120)
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError:
        raise ValueError('The read-state helper failed: ' + (run.stderr or run.stdout)[:200])
    if result.get('status') not in ('done', 'already'):
        raise ValueError(result.get('message') or 'Book not found in the app library')
    return result


def baseline(modules, apple_id, kindle_id):
    return {'apple': apple_state(apple_id)['finished'], 'kindle': kindle_state(modules, kindle_id)['finished']}
