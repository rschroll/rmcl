import datetime
import enum

RFC3339Nano = "%Y-%m-%dT%H:%M:%SZ"
USER_AGENT = "rmcl <https://github.com/rschroll/rmcl>"
DEVICE_TOKEN_URL = "https://my.remarkable.com/token/json/2/device/new"
USER_TOKEN_URL = "https://my.remarkable.com/token/json/2/user/new"
DEVICE = "desktop-windows"
SERVICE_MGR_URL = "https://service-manager-production-dot-remarkable-production.appspot.com/service/json/1/document-storage?environment=production&group=auth0%7C5a68dc51cb30df3877a1d7c4&apiVer=2"  # noqa
# Number of bytes of file to request to get file size of source doc
# For notes, the central directory runs 5 pages / KB, as a rough guess
NBYTES = 1024*100
FILE_LIST_VALIDITY = datetime.timedelta(minutes=5)
ROOT_ID=''
TRASH_ID='trash'


class FileType(enum.Enum):
    pdf = 'pdf'
    epub = 'epub'
    notes = 'notes'
    unknown = 'unknown'

    def __str__(self):
        return self.name
