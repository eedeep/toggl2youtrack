import datetime
import operator
import itertools
import re
import os
import time

from BeautifulSoup import BeautifulStoneSoup
import requests

BEGINNING_OF_TIME = datetime.datetime(year=1970, month=1, day=1)

TOGGL_BASE_API_URL = 'https://www.toggl.com/api/v6/'
TOGGL_API_KEY = os.environ['TOGGL_API_KEY']
TOGGL_APPROVED_PROJECT_NAMES = ['Cotton On', 'BAU ANZ']
YOUTRACK_BASE_API_URL = 'https://cottonon.myjetbrains.com/youtrack/rest/'
YOUTRACK_USERNAME = os.environ['YOUTRACK_USERNAME']
YOUTRACK_PASSWORD = os.environ['YOUTRACK_PASSWORD']


def login_to_youtrack():
    result = requests.post('{base_api_url}user/login'.format(base_api_url=YOUTRACK_BASE_API_URL),
        data={'login': YOUTRACK_USERNAME, 'password': YOUTRACK_PASSWORD}
    )
    return result.headers['set-cookie']


def get_youtrack_time_entries(cookie_header, task_id):
    result = requests.get(
        '{base_api_url}issue/{task_id}/timetracking/workitem/'.format(base_api_url=YOUTRACK_BASE_API_URL, task_id=task_id),
        headers={'Cookie': cookie_header}
    )
    return BeautifulStoneSoup(result.content)
   

def add_time_entry_to_youtrack(cookie_header, task_id, time_entry):
    xml_payload = '''
        <workItem>
            <date>{date}</date>
            <duration>{duration}</duration>
            <description>{description}</description>
        </workItem>
    '''.format(date=str(int(time.time() * 1000)), duration=time_entry['duration_in_minutes'], description=time_entry['description'])

    requests.post(
        '{base_api_url}issue/{task_id}/timetracking/workitem/'.format(base_api_url=YOUTRACK_BASE_API_URL, task_id=task_id),
        headers={'content-type': 'application/xml', 'Cookie': cookie_header},
        data=xml_payload,
    )


def get_all_toggl_time_entries():
    return requests.get(
        '{base_api_url}/time_entries.json?start_date={start_date}'.format(
            base_api_url=TOGGL_BASE_API_URL,
            start_date=BEGINNING_OF_TIME.isoformat()
        ),
        auth=((TOGGL_API_KEY, 'api_token'))
    )


def already_entered(prospective_entry_details, existing_descriptions):
    toggl_id_fingerprint = re.compile('^\[%s\].*$' % prospective_entry_details['toggl_id'])
    for existing_description in existing_descriptions:
        if toggl_id_fingerprint.match(existing_description):
            return True
    return False


# Get all toggl time entries that pertain to youtrack tasks
all_toggl_time_entries = get_all_toggl_time_entries()
youtrack_tasks = []
youtrack_fingerprint = re.compile('^.*(?P<youtrack_task_id>COT-[0-9]*).*$')
for entry in all_toggl_time_entries.json()['data']:
    try:
        if entry['project']['name'].lower() in [p.lower() for p in TOGGL_APPROVED_PROJECT_NAMES]:
            result = youtrack_fingerprint.match(entry['description'])
            if result:
                youtrack_tasks.append(dict(
                    youtrack_task_id=result.groupdict()['youtrack_task_id'],
                    toggl_id=entry['id'],
                    description=entry['description'],
                    duration=entry['duration'])
                )
    except KeyError as e:
        print e
        
# Group toggl entries by youtrack task ID
youtrack_tasks.sort(key=operator.itemgetter('youtrack_task_id'))
grouped_youtrack_tasks = []
for task_id, items in itertools.groupby(youtrack_tasks, operator.itemgetter('youtrack_task_id')):
    grouped_youtrack_tasks.append(list(items))

# Now add any toggl entries that haven't already been added, to youtrack
youtrack_cookie = login_to_youtrack()
for time_entries_by_task in grouped_youtrack_tasks:
    youtrack_task_id = time_entries_by_task[0]['youtrack_task_id']

    # Marshall the descriptions for all existing youtrack time entries for the task
    existing_youtrack_time_entries = get_youtrack_time_entries(youtrack_cookie, youtrack_task_id)
    existing_descriptions = []
    for workitem in existing_youtrack_time_entries.find('workitems'):
        description = workitem.find('description')
        if description:
            existing_descriptions.append(description.text)

    # Prepare the toggl entries that haven't already been added to youtrack
    total_in_minutes = 0
    time_entries_to_add = []
    for time_entry in time_entries_by_task:
        if not already_entered(time_entry, existing_descriptions):
            time_entry_minutes = time_entry['duration'] / 60
            time_entries_to_add.append(dict(
                description='[{toggl_id}] {desc}'.format(
                    toggl_id=time_entry['toggl_id'],
                    desc=time_entry['description'],
                ),
                duration_in_minutes=time_entry_minutes
            ))
            total_in_minutes += time_entry_minutes

    # Add time entries to youtrack for those as-yet-unadded toggl entries
    for time_entry_to_add in time_entries_to_add:
        add_time_entry_to_youtrack(youtrack_cookie, youtrack_task_id, time_entry_to_add)

    #print '{task_id} ({total_in_minutes}m):'.format(
    #    task_id=time_entries_by_task[0]['youtrack_task_id'],
    #    total_in_minutes=total_in_minutes
    #)
    #print '\t\n'.join(time_entries_to_add)
