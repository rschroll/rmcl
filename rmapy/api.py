import asks
from logging import getLogger
import enum
import io
import json
import trio
from uuid import uuid4

from .config import load, dump
from .items import Item, Folder, VirtualFolder
from .utils import now
from .zipdir import ZipHeader
from .exceptions import (
    AuthError,
    DocumentNotFound,
    ApiError,)
from .const import (RFC3339Nano,
                    USER_AGENT,
                    BASE_URL,
                    DEVICE_TOKEN_URL,
                    USER_TOKEN_URL,
                    DEVICE,
                    NBYTES,
                    FILE_LIST_VALIDITY,
                    ROOT_ID,
                    TRASH_ID)

asks.init('trio')
log = getLogger("rmapy")


class FileType(enum.Enum):
    pdf = 'pdf'
    epub = 'epub'
    notes = 'notes'
    unknown = 'unknown'

    def __str__(self):
        return self.name


class Client:
    """API Client for Remarkable Cloud

    This allows you to authenticate & communicate with the Remarkable Cloud
    and does all the heavy lifting for you.
    """

    token_set = {
        "devicetoken": "",
        "usertoken": ""
    }

    def __init__(self):
        config = load()
        if "devicetoken" in config:
            self.token_set["devicetoken"] = config["devicetoken"]
        if "usertoken" in config:
            self.token_set["usertoken"] = config["usertoken"]

        root = VirtualFolder('', ROOT_ID)
        trash = VirtualFolder('.trash', TRASH_ID, root.id)
        self.by_id = {root.id: root, trash.id: trash}
        self.refresh_deadline = None
        self.update_lock = trio.Lock()

    async def request(self, method: str, path: str,
                      data=None,
                      body=None, headers=None,
                      params=None, stream=False) -> asks.response_objects.Response:
        """Creates a request against the Remarkable Cloud API

        This function automatically fills in the blanks of base
        url & authentication.

        Args:
            method: The request method.
            path: complete url or path to request.
            data: raw data to put/post/...
            body: the body to request with. This will be converted to json.
            headers: a dict of additional headers to add to the request.
            params: Query params to append to the request.
            stream: Should the response be a stream?
        Returns:
            A Response instance containing most likely the response from
            the server.
        """

        if headers is None:
            headers = {}
        if not path.startswith("http"):
            if not path.startswith('/'):
                path = '/' + path
            url = f"{BASE_URL}{path}"
        else:
            url = path

        _headers = {
            "user-agent": USER_AGENT,
        }

        if self.token_set["usertoken"]:
            token = self.token_set["usertoken"]
            _headers["Authorization"] = f"Bearer {token}"
        for k in headers.keys():
            _headers[k] = headers[k]
        log.debug(url, _headers)
        return await asks.request(method, url,
                                  json=body,
                                  data=data,
                                  headers=_headers,
                                  params=params,
                                  stream=stream)

    async def register_device(self, code: str):
        """Registers a device on the Remarkable Cloud.

        This uses a unique code the user gets from
        https://my.remarkable.com/connect/remarkable to register a new device
        or client to be able to execute api calls.

        Args:
            code: A unique One time code the user can get
                at https://my.remarkable.com/connect/remarkable .
        Returns:
            True
        Raises:
            AuthError: We didn't recieved an devicetoken from the Remarkable
                Cloud.
        """

        uuid = str(uuid4())
        body = {
            "code": code,
            "deviceDesc": DEVICE,
            "deviceID": uuid,

        }
        response = await self.request("POST", DEVICE_TOKEN_URL, body=body)
        if response.ok:
            self.token_set["devicetoken"] = response.text
            dump(self.token_set)
            return True
        else:
            raise AuthError("Can't register device")

    async def renew_token(self):
        """Fetches a new user_token.

        This is the second step of the authentication of the Remarkable Cloud.
        Before each new session, you should fetch a new user token.
        User tokens have an unknown expiration date.

        Returns:
            True

        Raises:
            AuthError: An error occurred while renewing the user token.
        """

        if not self.token_set["devicetoken"]:
            raise AuthError("Please register a device first")
        token = self.token_set["devicetoken"]
        response = await self.request("POST", USER_TOKEN_URL, None, headers={
                "Authorization": f"Bearer {token}"
            })
        if response.status_code < 400:
            self.token_set["usertoken"] = response.text
            dump(self.token_set)
            return True
        else:
            raise AuthError("Can't renew token: {e}".format(
                e=response.status_code))

    def is_auth(self) -> bool:
        """Is the client authenticated

        Returns:
            bool: True if the client is authenticated
        """

        return self.token_set["devicetoken"] and self.token_set["usertoken"]

    async def update_items(self):
        response = await self.request('GET', '/document-storage/json/2/docs')
        try:
            response_json = response.json()
        except json.decoder.JSONDecodeError:
            log.error(f"Failed to decode JSON from {response.content}")
            log.error(f"Response code: {response.status_code}")
            raise ApiError("Failed to decode JSON data")

        old_ids = set(self.by_id) - {'', 'trash'}
        self.by_id[''].children = []
        self.by_id['trash'].children = []
        for item in response_json:
            old = self.by_id.get(item['ID'])
            if old:
                old_ids.remove(old.id)
            if not old or old.version != item['Version']:
                new = Item.from_metadata(item)
                self.by_id[new.id] = new
            elif isinstance(old, Folder):
                old.children = []

        for id_ in old_ids:
            del self.by_id[id_]

        for i in self.by_id.values():
            if i.parent is not None:
                self.by_id[i.parent].children.append(i)

        self.refresh_deadline = now() + FILE_LIST_VALIDITY

    async def get_by_id(self, id_):
        async with self.update_lock:
            if not self.refresh_deadline or now() > self.refresh_deadline:
                await self.update_items()

        return self.by_id[id_]

    async def get_metadata(self, id_, downloadable=True):
        response = await self.request('GET', '/document-storage/json/2/docs',
                                params={'doc': id_, 'withBlob': downloadable})
        for meta in response.json():
            if meta['ID'] == id_:
                return meta
        raise DocumentNotFound(f"Could not find document {id_}")

    async def get_blob(self, url):
        response = await self.request('GET', url)
        return response.content

    async def get_blob_size(self, url):
        response = await self.request('HEAD', url)
        return int(response.headers.get('Content-Length', 0))

    async def get_file_details(self, url):
        response = await self.request('GET', url, headers={'Range': f'bytes=-{NBYTES}'})
        # Want to start a known file extension - file name length - fixed header length
        key_index = response.content.rfind(b'.content') - 36 - 46
        if key_index < 0:
            return FileType.unknown, None

        stream = io.BytesIO(response.content[key_index:])
        item = ZipHeader.from_stream(stream)
        while item is not None:
            if item.filename.endswith(b'.pdf'):
                return FileType.pdf, item.uncompressed_size
            if item.filename.endswith(b'.epub'):
                return FileType.epub, item.uncompressed_size
            item = ZipHeader.from_stream(stream)
        return FileType.notes, None

    async def delete(self, item: Item):
        """Delete a document from the cloud.

        Args:
            doc: A Document or folder to delete.
        Raises:
            ApiError: an error occurred while uploading the document.
        """

        response = await self.request("PUT", "/document-storage/json/2/delete",
                                      body=[{
                                          "ID": item.id,
                                          "Version": item.version
                                      }])
        self.refresh_deadline = None

        return self.check_response(response)

    async def update_metadata(self, item: Item):
        """Send an update of the current metadata of a meta object

        Update the meta item.

        Args:
            docorfolder: A document or folder to update the meta information
                from.
        """

        # Copy the metadata so that the object gets out of date and will be refreshed
        metadata = item._metadata.copy()
        metadata['Version'] += 1
        metadata["ModifiedClient"] = now().strftime(RFC3339Nano)
        res = await self.request("PUT",
                                 "/document-storage/json/2/upload/update-status",
                                 body=[metadata])
        self.refresh_deadline = None

        return self.check_response(res)

    async def upload(self, item, contents):
        res = await self.request('PUT', '/document-storage/json/2/upload/request',
                                 body=[{
                                     'ID': item.id,
                                     'Version': item.version + 1,
                                     'Type': item._metadata['Type']
                                 }])
        self.check_response(res)
        try:
            dest = res.json()[0]['BlobURLPut']
        except (IndexError, KeyError):
            log.error("Failed to get upload URL")
            raise ApiError("Failed to get upload URL", response=res)
        up_res = await self.request('PUT', dest, data=contents.read(),
                                    headers={'Content-Type': ''})
        if up_res.status_code >= 400:
            log.error(f"Upload failed with status {up_res.status_code}")
            raise ApiError(f"Upload failed with status {up_res.status_code}", response=up_res)
        await self.update_metadata(item)

    @staticmethod
    def check_response(response: asks.response_objects.Response):
        """Check the response from an API Call

        Does some sanity checking on the Response

        Args:
            response: A API Response

        Returns:
            True if the response looks ok

        Raises:
            ApiError: When the response contains an error
        """

        if response.status_code >= 400:
            log.error(f"Got An invalid HTTP Response: {response.status_code}")
            raise ApiError(f"Got An invalid HTTP Response: {response.status_code}",
                           response=response)

        if len(response.json()) == 0:
            log.error("Got an empty response")
            raise ApiError("Got An empty response", response=response)

        if not response.json()[0]["Success"]:
            log.error("Got a non-success response")
            msg = response.json()[0]["Message"]
            log.error(msg)
            raise ApiError(msg, response=response)

        return True


_client = None
async def get_client():
    global _client
    if _client is None:
        print("Gettting client!")
        _client = Client()
        await _client.renew_token()
    return _client
