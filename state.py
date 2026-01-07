class PlayerState:
    def __init__(self):
        self.msg = None
        self.start_t = 0
        self.duration = 0
        self.title = ""
        self.is_paused = False
        self.pause_start = 0

# Global State Instances
STATE = PlayerState()
SONG_QUEUES = {}
CACHED_SONG_INDEX = []
LAST_VIEWED_LISTS = {} 
DOWNLOAD_ABORTED = False
