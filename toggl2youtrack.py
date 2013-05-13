import datetime
import operator
import itertools
import re
import os
import time
import tomlpython
import logging

from BeautifulSoup import BeautifulStoneSoup
import requests

# Set up logging
logger = logging.getLogger('toggl2youtrack')
logger.setLevel(logging.INFO)
handler = logging.FileHandler('/var/log/toggl2youtrack.log')
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s: %(message)s')
handler.setFormatter(formatter)
handler.setLevel(logging.INFO)
logger.addHandler(handler)

BEGINNING_OF_TIME = datetime.datetime(year=1970, month=1, day=1)

config_file_path = os.path.join(os.path.realpath(os.path.dirname(os.path.realpath(__file__))), "config.toml")

with open(config_file_path) as config_file:
     config = tomlpython.parse(config_file.read())


def login_to_youtrack(username, password):
    result = requests.post('{base_api_url}user/login'.format(base_api_url=config['youtrack']['base_api_url']),
        data={'login': username, 'password': password}
    )
    return result.headers['set-cookie']


def get_youtrack_time_entries(cookie_header, task_id):
    result = requests.get(
        '{base_api_url}issue/{task_id}/timetracking/workitem/'.format(base_api_url=config['youtrack']['base_api_url'], task_id=task_id),
        headers={'Cookie': cookie_header}
    )
    return BeautifulStoneSoup(result.content)


def add_time_entry_to_youtrack(drone_name, cookie_header, task_id, time_entry):
    xml_payload = '''
        <workItem>
            <date>{date}</date>
            <duration>{duration}</duration>
            <description>{description}</description>
        </workItem>
    '''.format(date=str(int(time.time() * 1000)), duration=time_entry['duration_in_minutes'], description=time_entry['description'])

    response = requests.post(
        '{base_api_url}issue/{task_id}/timetracking/workitem/'.format(base_api_url=config['youtrack']['base_api_url'], task_id=task_id),
        headers={'content-type': 'application/xml', 'Cookie': cookie_header},
        data=xml_payload,
    )
    log_txt = ' {task_id} for {drone_name}: {description} ({duration_in_minutes}m)'.format(
        drone_name=drone_name,
        task_id=task_id,
        description=time_entry['description'],
        duration_in_minutes=time_entry['duration_in_minutes']
    )
    if response.status_code == 201:
        logger.info('Added youtrack time entry to {log_txt}'.format(log_txt=log_txt))
    else:
        logger.error('Failed, for some reason, to add youtrack time entry to {log_txt}'.format(log_txt=log_txt))


def get_all_toggl_time_entries(api_key):
    return requests.get(
        '{base_api_url}/time_entries.json?start_date={start_date}'.format(
            base_api_url=config['toggl']['base_api_url'],
            start_date=BEGINNING_OF_TIME.isoformat()
        ),
        auth=((api_key, 'api_token'))
    )


def already_entered(prospective_entry_details, existing_descriptions):
    toggl_id_fingerprint = re.compile('^\[%s\].*$' % prospective_entry_details['toggl_id'])
    for existing_description in existing_descriptions:
        if toggl_id_fingerprint.match(existing_description):
            return True
    return False


# For each worker (aka drone), transfer any unadded time from toggl to youtrack
for drone_name, drone_details in config['user_credentials'].iteritems():
    # Get all toggl time entries that pertain to youtrack tasks
    all_toggl_time_entries = get_all_toggl_time_entries(drone_details['toggl_api_key'])
    youtrack_tasks = []
    youtrack_fingerprint = re.compile('^.*(?P<youtrack_task_id>COT-[0-9]*).*$')
    for entry in all_toggl_time_entries.json()['data']:
        try:
            if 'project' in entry:
                if entry['project']['name'].lower() in \
                    [p.lower() for p in config['toggl']['approved_project_names']]:
                    # Currently toggld on tasks have a negative duration - we want to ignore them
                    if entry['duration'] > 0:
                        result = youtrack_fingerprint.match(entry['description'])
                        if result:
                            youtrack_tasks.append(dict(
                                youtrack_task_id=result.groupdict()['youtrack_task_id'],
                                toggl_id=entry['id'],
                                description=entry['description'],
                                duration=entry['duration'])
                            )
        except KeyError as e:
            logger.error(e)

    # Group toggl entries by youtrack task ID
    youtrack_tasks.sort(key=operator.itemgetter('youtrack_task_id'))
    grouped_youtrack_tasks = []
    for task_id, items in itertools.groupby(youtrack_tasks, operator.itemgetter('youtrack_task_id')):
        grouped_youtrack_tasks.append(list(items))

    # Now add any toggl entries that haven't already been added, to youtrack
    youtrack_cookie = login_to_youtrack( \
        drone_details['youtrack_username'], drone_details['youtrack_password'])
    for time_entries_by_task in grouped_youtrack_tasks:
        youtrack_task_id = time_entries_by_task[0]['youtrack_task_id']

        # Marshall the descriptions for all existing youtrack time entries for the task
        existing_youtrack_time_entries = get_youtrack_time_entries(youtrack_cookie, youtrack_task_id)
        existing_descriptions = []
        try:
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
                add_time_entry_to_youtrack(drone_name, youtrack_cookie, youtrack_task_id, time_entry_to_add)
        except TypeError as e:
            logging.error('Error with this one: {youtrack_task_id} for {drone_name}'.format(
                youtrack_task_id=youtrack_task_id, drone_name=drone_name))
