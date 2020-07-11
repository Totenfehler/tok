# tok
This is a program to help scrape tiktok accounts and track posts.

### Setup
#### Installs
You need npm and python installed. Install [tiktok-signature](https://github.com/carcabot/tiktok-signature)
```
$ npm install -g tiktok-signature
```
This will install the node package that can be run on localhost to generate API signatures. To run `listen.js` you can find your npm root path
```
$ npm root -g
/path/to/node_modules
$ node /path/to/node_modules/tiktok-signature/listen.js
TikTok Signature server started
```
To install Python `requests` and `tqdm` packages, `pip install requests tqdm`.

Configure your scraper script by opening `tok.py` and editing the config values near the top.
```
#############################CONFIG#############################
DL_DIR = Path("/directory/to/download/to") # Set to the parent directory to where you want dl directories to be places.
DB_FILE = "/path/to/db/file.db" # Set to where you want to create/load database file.
GLOBAL_SLEEP = 5 # Sleep time when downloading to reduce temporary IP bans, can be increased/reduced.
SIG_HOST = "http://localhost:8080" # Host of signature server, package default is localhost:8080
WINDOWS = False # Set to True if running on Windows
################################################################
```
#### Testing
To verify setup run `python tok.py info`(make `tok.py` directly executable if you want) you should see the following
```
======TTG Scraper======
Tokkers: 0
Posts:   0
Files:   0
Music:   0
Space:   --
DB:      4.0K
```
### Usage Scenario
#### Add and Download clips of a new user.
Scraping a new user is a three step process of adding them, tracking their posts, and downloading their videos.
```
$ python tok.py add llovesanime 
[llovesanime] Added
$ python tok.py check llovesanime
Checking llovesanime
Total New Posts: 1115
$ python tok.py dl llovesanime
Downloading posts for llovesanime
Tracking 1115 posts for llovesanime
Saved: 0, Failed: 0, Unsaved: 1115
Extracting 1115 HD posts ids for llovesanime
...
```
Note that you may pass more than one user to most commands, e.g., `python tok.py add userA userB userC`.
#### Adding a user you have already partially archived using another tool.
This program will attempt to download all unsaved videos. If you have already saved most of a user's videos you can prevent duplicate effort by importing your files.
```
$ python tok.py import llovesanime /my_old_post_archive/
Import 1120 posts by llovesanime from /my_old_post_archive/ to ~/tiktok/clips/uids/6792773423049081862?
[this will not erase original files]
y
Imported 1120/1120 posts
$ python tok.py info llovesanime
==== llovesanime ====
UID: 6792773423049081862
Posts: 1120
Downloads: 1120
Files: 1120
```
When importing post files `tok.py` will determine the post id using the filenames so they should be real tiktok post ids. Any invalid files will be skipped and logged.
##### My existing archive is messy?
If you don't have a clean directory of post files to import but still want to prevent scraping of a user's older posts you can import a recent single post file before running `check` on that user. `check` by default will stop ingesting post data when it passes the latest post saved.
```
$ python tok.py import llovesanime ~/messy_files/6848095707597982982.mp4 
Import post 6848095707597982982 by llovesanime to ~/tiktok/clips/uids/6792773423049081862/6848095707597982982.mp4?
[this will not erase original file]
y
Imported post.
$ python tok.py check llovesanime
Checking llovesanime
Total New Posts: 1                                
$ python tok.py info llovesanime
==== llovesanime ====
UID: 6792773423049081862
Posts: 2
Downloads: 1
Files: 1
```
#### Check for new posts and download
Running `check` will check and save new posts for all tracked users.
```
$ python tok.py check
Found 1 new posts for llovesanime
Found 2 new posts for lallablomy
```
To download the new post videos you can run `scan` or `scan threshold`; `scan` will attempt to download videos for all tracked users where the number of new posts is below threshold (default 20). This allows for quick repeat scraping of new posts while full scraping newly added users can be done in parallel.
```
$ python tok.py scan
Downloading 1 posts for llovesanime
Tracking 1120 posts for llovesanime
Saved: 1119, Failed: 0, Unsaved: 1
Extracting 1 HD posts ids for llovesanime
...
```
#### The program was killed while saving videos
`tok` does its best to be safe about downloading to prevent an inconsistent state, but if the program is interrupted after saving video files but before saving their location in the database they will be untracked. To fix this call `repair username`.
```
$ python tok.py info llovesanime
==== llovesanime ====
UID: 6792773423049081862
Posts: 1120
Downloads: 1119
Files: 1120
$ python tok.py repair llovesanime
Found untracked download 6847705553657957638.mp4
Repaired.
$ python tok.py info llovesanime
==== llovesanime ====
UID: 6792773423049081862
Posts: 1120
Downloads: 1120
Files: 1120
```
If you forget to run `repair` you will not break anything but untracked videos will be redownloaded and log an error when attempting to overwrite the existing video.
#### I'm on a different drive but I want to save posts
`tok` does not support merging multiple DBs currently, but if you have access to the DB file and not the video directory, .e.g, it's on a larger disconnected external HDD you can continue to scrape locally and move the files later. First edit your configured `DL_DIR` in `tok.py` to an existing directory then run as normal. **Note** `tok` uses SQLite in WAL mode by default so for moving or backing up your DB you **MUST** back up the `db`,`wal`,`sh` files if they exist.

Later when you have access to your main download directory you can move an individual user's posts using `tok move user` or all posts at a location using `mvall src dest`.
#### I'm getting 403s but the posts are public
When downloading `tok` uses the saved video urls from when the posts were scraped. If you wait a long time (1 day+) to run `dl` these may be expired.

To resave fresh video urls run `python tok.py refresh username`, this will recheck their public posts and overwrite the stale entries in the db.
#### The program terminated due to IP ban
If multiple zero-byte responses from tiktok are detected `tok` will terminate due to probable IP ban. You will need to wait a bit or change IP. If it happens often increase the sleep time.
#### The program failed to download some videos
Download failures due to 404, 403, etc will be logged to the user. This likely means the post has been deleted or made private, `tok` will not attempt to redownload these posts unless you call `refresh`.
If the reported failures were not individually logged then they were 429s or timeouts, these are intermitent and will be retried the next time you call `dl` or `scan`.

### All Commands
- `info [usernames...]` print global or username info
- `add usernames...` add or update users
- `ls` list tracked users
- `lookup [usernames|uids...]` lookup usernames/ids for name changes
- `lup post_id|filename` print local info/status of a post (will strip file extension)
- `import file|dir` import outside posts
- `dl usernames...` download for given users
- `check [usernames...]` check for new posts of usernames or all tracke users
- `refesh [usernames...]` resave all of users public posts in db
- `update` update all tracked users profiles and stats
- `scan` download latest posts
- `hp` check that all downloads have existing file
- `repair username` fix up db downloads for user
- `move username src dest` move users files from src to dest
- `mvall src dest` move all user files from src to dest

### ToDos
- single post download command with support for adding users not flagged for normal scraping
- possible retry logic for 429 status responses
- command to clear hd url cache
