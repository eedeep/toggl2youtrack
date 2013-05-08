import pudb
import requests
import datetime
import pprint
import operator
import itertools
import re
import os

BASE_API_URL = 'https://www.toggl.com/api/v6/'
BEGINNING_OF_TIME = datetime.datetime(year=1970, month=1, day=1)
APPROVED_PROJECT_NAMES = ['Cotton On', 'BAU ANZ']
API_KEY = os.environ['TOGGL_API_KEY']


def get_all_time_entries():
    return requests.get(
        '{base_api_url}/time_entries.json?start_date={start_date}'.format(
            base_api_url=BASE_API_URL,
            start_date=BEGINNING_OF_TIME.isoformat()
        ),
        auth=((API_KEY, 'api_token'))
    )


all_time_entries = get_all_time_entries()

"""
{u'billable': True,
 u'currency': u'AUD',
 u'description': u'#624 Get setup and oriented with various project management tools such as acunote, campfire and toggl',
 u'duration': 10800,
 u'hourly_rate': u'70.0',
 u'id': 27424896,
 u'ignore_start_and_stop': False,
 u'project': {u'client_project_name': u'Cotton On - Cotton On',
  u'id': 1193252,
  u'name': u'Cotton On'},
 u'start': u'2012-02-27T07:09:00+11:00',
 u'stop': u'2012-02-27T10:09:00+11:00',
 u'tag_names': [],
 u'updated_at': u'2012-03-02T17:47:59+11:00',
 u'user_id': 284401,
 u'workspace': {u'id': 179261, u'name': u'Common Code'}}
"""

youtrack_tasks = []
youtrack_fingerprint = re.compile('^.*(?P<youtrack_task_id>COT-[0-9]*).*$')
for entry in all_time_entries.json()['data']:
    try:
        if entry['project']['name'].lower() in [p.lower() for p in APPROVED_PROJECT_NAMES]:
            result = youtrack_fingerprint.match(entry['description'])
            if result:
                youtrack_tasks.append(dict(
                    youtrack_task_id=result.groupdict()['youtrack_task_id'],
                    toggl_id=entry['id'], 
                    description=entry['description'], 
                    duration=entry['duration'])
                )
    except KeyError as e:
        pass
        
youtrack_tasks.sort(key=operator.itemgetter('youtrack_task_id'))

grouped_youtrack_tasks = []
for task_id, items in itertools.groupby(youtrack_tasks, operator.itemgetter('youtrack_task_id')):
    grouped_youtrack_tasks.append(list(items))

for time_entries_by_task in grouped_youtrack_tasks:
    total_in_minutes = 0
    detail_lines = []
    for time_entry in time_entries_by_task:
        time_entry_minutes = time_entry['duration'] / 60
        detail_lines.append('\t[{toggl_id}] {desc} ({duration_in_minutes}m)'.format(
            toggl_id=time_entry['toggl_id'],
            desc=time_entry['description'],
            duration_in_minutes=time_entry_minutes
        ))
        total_in_minutes += time_entry_minutes

    print '{task_id} ({total_in_minutes}m):'.format(
        task_id=time_entries_by_task[0]['youtrack_task_id'],
        total_in_minutes=total_in_minutes
    )
    print '\t\n'.join(detail_lines)
