# python: 3.7
# author: oldseven
# Completed Date: 2019-8-8
# Function: Use Google cloud Pub/Sub to get new coming email of gmail.
# And send email content to mattermost group.

import pickle
import os.path

import base64
import email
from apiclient import errors

import asyncio
import threading
import json
import requests
import logging
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import html2markdown

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://mail.google.com/', 
'https://www.googleapis.com/auth/gmail.readonly', 
'https://www.googleapis.com/auth/gmail.modify']

RUNTIME_STORAGE = threading.local()

RUNTIME_STORAGE.NEW_HISTORY_ID = None
RUNTIME_STORAGE.OLD_HISTORY_ID = None


def config():
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('gmail', 'v1', credentials=creds)
    return service


async def watch(service, label_id):
    while True:
        body = {
            "labelIds": [label_id],
            "labelFilterAction": "include",
            "topicName": "projects/quickstart-1565230748884/topics/cacti"            
        }
        results = service.users().watch(userId='me', body=body).execute()
        RUNTIME_STORAGE.NEW_HISTORY_ID = results['historyId']
        logging.info("watch: sleep 5s...")
        await asyncio.sleep(5)


def send_mm_notification(message):
    message = html2markdown.convert(message)
    body = {
        "message": message,
        "receiver": "bwy4n7aru3rbzr3n63x74gfpdw",
        "message_type": 1,
    }
    r = requests.post("http://track.easydevops.net/api/sendMsg",
        headers = {
            "Content-Type": "application/json",
            "token": 'gzyr9supv9xkrisjliDkjHflfanzhlnw',
        },
        data = json.dumps(body)
    )
    logging.debug(r)


async def GetMimeMessage(service, msg_id):
    try:
        message = service.users().messages().get(userId='me', id=msg_id,format='raw').execute()
        msg_str = base64.urlsafe_b64decode(message['raw'].encode('ASCII'))
        mime_msg = email.message_from_string(msg_str)
        send_mm_notification(mime_msg)
    except errors.HttpError as error:
      logging.error(error)


async def GetMessage(service, msg_id):
  """Get a Message with given ID.

  Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    msg_id: The ID of the Message required.

  Returns:
    A Message.
  """
  try:
      message = service.users().messages().get(userId='me', id=msg_id).execute()
      content = base64.urlsafe_b64decode(message["payload"]["parts"][0]["body"]["data"]).decode('UTF-8')
      content = html2markdown.convert(content)
      logging.info("mail content:%s\n" % content)
      send_mm_notification(content)
  except errors.HttpError as error:
      logging.error(error)


async def ListHistory(service, label_id):
    """List History of all changes to the user's mailbox.

    Args:
      service: Authorized Gmail API service instance.
      'me': User's email address. The special value "me"
      can be used to indicate the authenticated user.
      start_history_id: Only return Histories at or after start_history_id.

    Returns:
      A list of mailbox changes that occurred after the start_history_id.
    """
    while True:
        try:
            start_history_id = RUNTIME_STORAGE.NEW_HISTORY_ID
            logging.debug("old_id: %s" % RUNTIME_STORAGE.OLD_HISTORY_ID)
            logging.debug("new_id: %s" % RUNTIME_STORAGE.NEW_HISTORY_ID)

            if start_history_id == RUNTIME_STORAGE.OLD_HISTORY_ID:
                logging.info("Nothing to do and continue...")
            else:
                history = (service.users().history().list(
                    userId='me',
                    historyTypes='messageAdded',
                    labelId=label_id, # cacti
                    startHistoryId=RUNTIME_STORAGE.OLD_HISTORY_ID or start_history_id).execute())
                logging.info("History: %s\n" % history)
                changes = history['history'] if 'history' in history else []
                while 'nextPageToken' in history:
                    page_token = history['nextPageToken']
                    history = (service.users().history().list(userId='me',
                        startHistoryId=start_history_id,
                        pageToken=page_token).execute())
                    changes.extend(history['history'])
                logging.info("changes: %s\n" % changes)
                RUNTIME_STORAGE.OLD_HISTORY_ID = start_history_id
                for change in changes:
                    messages =  change['messages']
                    for message in messages:
                        await GetMessage(service, message['id'])

        except errors.HttpError as error:
            logging.error(error)

        finally:
            logging.info("List history: sleep 5s...\n")
            await asyncio.sleep(5)


def get_label_id(service, name):
    try:
        response = service.users().labels().list(userId='me').execute()
        labels = response['labels']
        for label in labels:
            if label["name"] == name:
                return label["id"]
    except errors.HttpError as error:
        logging.error(error)

async def main():
    log_format = "%(asctime)s::%(levelname)s::%(message)s"
    logging.basicConfig(filename='cacti.log', level='DEBUG', format=log_format)
    logging.info("Start running main()\n")
    service = config()
    label_id = get_label_id(service, 'cacti')
    logging.info("Lable id: %s\n" % label_id)
    if label_id:
        task1 = asyncio.create_task(watch(service, label_id))
        task2 = asyncio.create_task(ListHistory(service, label_id))
        await task1
        await task2


if __name__ == '__main__':
    asyncio.run(main())
