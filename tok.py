#!/usr/bin/env python
import random, time
from urllib.parse import urlencode
from urllib.request import urlopen
from multiprocessing.pool import ThreadPool
import requests
import json
import sqlite3
from tqdm import tqdm
from pathlib import Path
import os
import sys
import shutil
import subprocess
from datetime import datetime
from distutils.util import strtobool

#############################CONFIG#############################
DL_DIR = Path("/path/to/my/video/directory/") # Set to the parent directory to where you want dl directories to be places.
DB_FILE = "/path/to/my/database/file.db" # Set to where you want to create/load database file.
GLOBAL_SLEEP = 5 # Sleep time when downloading to reduce temporary IP bans, can be increased/reduced.
SIG_HOST = "http://localhost:8080" # Host of signature server, package default is localhost:8080
WINDOWS = False # Set to True if running on Windows
################################################################

assert DL_DIR.exists()
USERS_DIR = DL_DIR.joinpath("users")
UIDS_DIR = DL_DIR.joinpath("uids")
SCRATCH_DIR = DL_DIR.joinpath("scratch")
CLIP_DIRS = [DL_DIR, USERS_DIR, UIDS_DIR, SCRATCH_DIR]

GLOBAL_ZERO_BYTE_COUNTER = 0
PROG_TITLE = "======" + "TTG Scraper" + "======"
FK_PRAGMA = "PRAGMA foreign_keys = ON"
USER_VERSION_PRAGMA = "PRAGMA user_version = 1"
WAL_PRAGMA = "PRAGMA journal_mode=WAL;"
VID_URL = "https://api2-16-h2.musical.ly/aweme/v1/play/?ratio=default&improve_bitrate=1&video_id="
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 11_0 like Mac OS X) AppleWebKit/604.1.38 (KHTML, like Gecko) Version/11.0 Mobile/15A372 Safari/604.1"
BASE_HEADERS = {"user-agent": USER_AGENT}
BASE_PARAMS = {
	'id':'',
	'secUid': '',
	'sourceType': '8',
	'count': '2',
	'minCursor': '0',
	'lang': '',
	'verifyFp': '',
	'_signature': '',
	'maxCursor': '0'
}

BASE_HEADERS = {
	"method": "GET",
	"accept-encoding": "gzip, deflate, br",
	"Referer": "https://www.tiktok.com/",
	"user-agent": USER_AGENT
}

FK_PRAGMA = "PRAGMA foreign_keys = ON"
TOKKERS_TABLE = """
	CREATE TABLE IF NOT EXISTS tokkers (
		uid	TEXT NOT NULL UNIQUE,
		nick TEXT
	);
"""
USERNAMES_TABLE = """
	CREATE TABLE IF NOT EXISTS usernames (
		username TEXT NOT NULL,
		ts INTEGER,
		uid TEXT NOT NULL,
		FOREIGN KEY(uid) REFERENCES tokkers(uid)  
	);
"""
PROFILES_TABLE = """
	CREATE TABLE IF NOT EXISTS profiles (
		description TEXT NOT NULL,
		subname TEXT NOT NULL,
		ts INTEGER,
		uid TEXT NOT NULL,
		FOREIGN KEY(uid) REFERENCES tokkers(uid)  
	);
"""
PROFILE_STATS_TABLE = """
	CREATE TABLE IF NOT EXISTS profile_stats (
		following INTEGER,
		fans INTEGER,
		heart INTEGER,
		video INTEGER,
		digg INTEGER,
		ts INTEGER,
		uid TEXT NOT NULL,
		FOREIGN KEY(uid) REFERENCES tokkers(uid)  
	);

"""
MUSIC_TABLE = """
	CREATE TABLE IF NOT EXISTS music (
		mid TEXT NOT NULL UNIQUE,
		title TEXT,
		author TEXT,
		original INTEGER
	);
"""
POSTS_TABLE = """
	CREATE TABLE IF NOT EXISTS posts (
		pid TEXT NOT NULL UNIQUE,
		uid TEXT NOT NULL,
		mid TEXT,
		description TEXT,
		created INTEGER,
		FOREIGN KEY(uid) REFERENCES tokkers(uid),
		FOREIGN KEY(mid) REFERENCES music(mid)  
	);
"""
RAW_POSTS_TABLE = """
	CREATE TABLE IF NOT EXISTS raw_posts (
		pid TEXT NOT NULL UNIQUE,
		json TEXT,
		status INTEGER,
		FOREIGN KEY(pid) REFERENCES posts(pid)  
	);
"""
DOWNLOADS_TABLE = """
	CREATE TABLE IF NOT EXISTS downloads (
		pid TEXT NOT NULL UNIQUE,
		location TEXT,
		hd INTEGER,
		FOREIGN KEY(pid) REFERENCES posts(pid)  
	);
"""
HD_TABLE = """
	CREATE TABLE IF NOT EXISTS hd_urls (
		pid TEXT NOT NULL UNIQUE,
		url TEXT,
		FOREIGN KEY(pid) REFERENCES posts(pid)  
	);
"""

TABLE_STMTS = [TOKKERS_TABLE, USERNAMES_TABLE, PROFILES_TABLE,
	PROFILE_STATS_TABLE, MUSIC_TABLE, POSTS_TABLE, RAW_POSTS_TABLE, DOWNLOADS_TABLE,
	HD_TABLE]

def get_sig(url):
	resp = requests.post(SIG_HOST + "/signature", data=url, timeout=5)
	resp.raise_for_status()
	return resp.json()

def du(path):
	if not WINDOWS:
		return subprocess.check_output(['du','-sh', path]).split()[0].decode('utf-8')
	p = Path(path)
	if p.is_file():
		return convert_bytes(p.stat().st_size)
	return "--"

def get_posts(userid, count, cursor="0"):
	URL = "https://m.tiktok.com/api/item_list/"
	params = dict(BASE_PARAMS)
	headers = dict(BASE_HEADERS)
	params["id"] = userid
	params["count"] = count
	params["maxCursor"] = cursor
	params.pop('_signature', None)
	params.pop('verifyFp', None)
	params["bust"] = int(random.random()*1E10)
	qs = urlencode(params)
	partial_url = URL + "?" + qs
	sig_data = get_sig(partial_url)
	params["_signature"] = sig_data["signature"]
	params["verifyFp"] = sig_data["verifyFp"]
	resp = requests.get(URL, headers=headers, params=params)
	resp.raise_for_status()
	return resp.json()

def get_all_posts(userid, count, seen="-1", log=True):
	cursor = "0"
	total = 0
	check = False
	result = []
	while 1:
		data = get_posts(userid, count, cursor=cursor)
		cursor = data["maxCursor"]
		if "items" in data:
			for post in data["items"]:
				if int(post["id"]) <= int(seen):
					check = True
					break
				total += 1
				result.append(post)
		if check:
			break
		final = "?" if data["hasMore"] else total
		if log: 
			print(" Found {}/{} posts".format(total, final), end="\r")
		if not data["hasMore"]:
			break
	if log:
		print(" "*50, end="\r")
		print("Total New Posts: {}".format(total))
	return result

def make_dirs(root):
	dirs = [root/"uids", root/"users", root/"scratch"]
	for path in dirs:
		path.mkdir(parents=True, exist_ok=True)

def make_user_dirs(root, uid, usernames):
	path = root/"uids"/uid
	path.mkdir(parents=True, exist_ok=True)
	for name in usernames:
		p = root/"users"/name
		if not p.exists():
			if WINDOWS:
				subprocess.check_call('mklink /J "%s" "%s"' % (p, path), shell=True)
			else:
				p.symlink_to(path, target_is_directory=True)

def ts():
	return int(round(time.time() * 1000))

def fetch_tokker(username):
	url = "https://m.tiktok.com/node/share/user/@" + username
	resp = requests.get(url, headers={"user-agent":USER_AGENT, "cookie": "1"}, timeout=5)
	resp.raise_for_status()
	data = resp.json()["body"]
	if "userData" not in data:
		print("no userData for " + username)
		return None
	data["userData"]["__myTs"] = ts()
	return username,data["userData"]

def add_user(username, user_data, cursor):
	assert username == user_data["uniqueId"]
	uid = data["userId"]
	subname = data["nickName"]
	description = data["signature"]
	following = data["following"]
	fans = int(data["fans"])
	heart = int(data["heart"])
	video = int(data["video"])
	digg = int(data["digg"])
	ts = data["__myTs"]
	cursor.execute('SELECT * FROM tokkers WHERE uid=?', (uid,))
	tokker = cursor.fetchone()
	msg = None
	if tokker is None:
		cursor.execute("INSERT INTO tokkers (uid) VALUES (?)", (uid,))
		cursor.execute("INSERT INTO usernames (username,ts,uid) VALUES (?,?,?)",(username,ts,uid))
		cursor.execute("INSERT INTO profiles (description,subname,ts,uid) VALUES (?,?,?,?)",
			(description,subname,ts,uid))
		cursor.execute("INSERT INTO profile_stats (following,fans,heart,video,digg,ts,uid) VALUES (?,?,?,?,?,?,?)",
			(following,fans,heart,video,digg,ts,uid))
		msg = "[{}] Added".format(username)
	else:
		tt = []
		username_row = cursor.execute("SELECT * FROM usernames WHERE uid=? ORDER BY ts DESC", (uid,)).fetchone()
		profile = cursor.execute("SELECT * FROM profiles WHERE uid=? ORDER BY ts DESC", (uid,)).fetchone()
		stats = cursor.execute("SELECT * FROM profile_stats WHERE uid=? ORDER BY ts DESC", (uid,)).fetchone()
		if username != username_row["username"]:
			tt.append("username")
			cursor.execute("INSERT INTO usernames (username,ts,uid) VALUES (?,?,?)",(username,ts,uid))
		if description != profile["description"] or subname != profile["subname"]:
			tt.append("profile")
			cursor.execute("INSERT INTO profiles (description,subname,ts,uid) VALUES (?,?,?,?)",
				(description,subname,ts,uid))
		if tuple(stats[:5]) != (following,fans,heart,video,digg):
			tt.append("stats")
			cursor.execute("INSERT INTO profile_stats (following,fans,heart,video,digg,ts,uid) VALUES (?,?,?,?,?,?,?)",
				(following,fans,heart,video,digg,ts,uid))
		if len(tt):
			msg = "[{}] updated {}".format(username, ", ".join(tt))
	return msg

def save_posts(posts, cursor):
	music_rows = []
	post_rows = []
	raw_rows = []
	for post in posts:
		music = post["music"]
		music_rows.append((music["id"], music["title"], music.get("authorName"), music["original"]))
		post_rows.append((post["id"], post["author"]["id"], music["id"], post["desc"], post["createTime"]*1000))
		raw_rows.append((post["id"], json.dumps(post, separators=(",",":")), None))
	cursor.executemany("INSERT OR REPLACE INTO music VALUES (?,?,?,?)", music_rows)
	cursor.executemany("INSERT INTO posts VALUES (?,?,?,?,?)", post_rows)
	cursor.executemany("INSERT INTO raw_posts VALUES (?,?,?)", raw_rows)

def update_posts(posts, cursor):
	music_rows = []
	post_rows = []
	raw_rows = []
	for post in posts:
		assert "video" in post
		music = post["music"]
		music_rows.append((music["id"], music["title"], music.get("authorName"), music["original"]))
		post_rows.append((post["id"], post["author"]["id"], music["id"], post["desc"], post["createTime"]*1000))
		raw_rows.append((post["id"], json.dumps(post, separators=(",",":")),None))
	cursor.executemany("INSERT OR REPLACE INTO music VALUES (?,?,?,?)", music_rows)
	cursor.executemany("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)", post_rows)
	cursor.executemany("INSERT OR REPLACE INTO raw_posts VALUES (?,?,?)", raw_rows)

def get_hd(url):
	with requests.get(url, timeout=30, headers=BASE_HEADERS, stream=True) as resp:
		if resp.status_code != 200:
			raise Exception(resp.status_code)
		chunks = []
		for chunk in resp.iter_content(chunk_size=128*1012):
			index = chunk.find(b"vid:")
			if index != -1:
				return True, chunk[index+4:index+36]
			chunks.append(chunk)
		content = b"".join(chunks) # check in case needle was on chunk boundary
		index = content.find(b"vid:")
		if index != -1:
			return True,content[index+4:index+36]
		return False,content	
	return None
	
def post2hd(post):
	if post["id"] in HD_URL_CACHE:
		return HD_URL_CACHE[post["id"]]
	vid_url = post["video"]["playAddr"]
	try:
		vid_id = get_hd(vid_url)
		if vid_id is not None and vid_id[0]:
			vid_id = vid_id[1].decode("UTF-8")
			return VID_URL+vid_id
		else:
			print("Failed", post["id"], "No HD id found, saving SD.")
			return vid_id[1]
	except Exception as e:
		if str(e) not in {"429"}:
			print("Failed", post["id"], e)
		return e
	return None

def print_info(username, cursor):
	if username not in name2uid:
		sys.exit("Unknown user: " + username)
	uid = name2uid[username]
	usernames = [row["username"] for row in cursor.execute("SELECT username FROM usernames WHERE uid = ?", (uid,))]
	post_count = cursor.execute("select count(*) from posts join tokkers on tokkers.uid = posts.uid where tokkers.uid = ?", (uid,)).fetchone()
	dl_count = cursor.execute("select count(*) from downloads join posts on posts.pid = downloads.pid join tokkers on tokkers.uid = posts.uid where tokkers.uid = ?", (uid,)).fetchone()
	path = UIDS_DIR / uid
	file_count = 0
	if path.exists():
		file_count = len([fname for fname in os.listdir(UIDS_DIR / uid) if ".mp4" in fname or ".webm" in fname])
	print("==== " + ",".join(usernames) + " ====")
	print("UID: {}".format(uid))
	print("Posts: {}".format(post_count[0]))
	print("Downloads: {}".format(dl_count[0]))
	print("Files: {}".format(file_count))

def download_tok(uid, pid, url, safe=True):
	global GLOBAL_SLEEP
	global GLOBAL_ZERO_BYTE_COUNTER
	fname = pid+".mp4"
	temp_path = SCRATCH_DIR / fname
	final_path = UIDS_DIR / uid / fname
	if safe and final_path.exists():
		raise Exception("Clip already exists at {}".format(final_path))
	headers = {"user-agent":str(int(random.random()*10000))}
	with requests.get(url, stream=True, timeout=20, headers=headers) as resp:
		if resp.status_code == 429:
			raise Exception(resp.status_code)
		resp.raise_for_status()
		total = int(resp.headers["Content-Length"])
		if total == 0:
			GLOBAL_ZERO_BYTE_COUNTER += 1
			raise Exception("Download failed zero-byte response[{}]".format(GLOBAL_ZERO_BYTE_COUNTER))
		if GLOBAL_ZERO_BYTE_COUNTER < 5:
			time.sleep(GLOBAL_SLEEP) # prevent IP ban
		# print("Downloading {:2.2f}MB video".format(total/1000000))
		chunk_size = 512 * 1024
		t0 = time.time()
		saved,saved_window = 0,0
		n = total//chunk_size + bool(total%chunk_size) # extra read for leftover if needed
		with open(temp_path, 'wb') as f:
			for chunk in resp.iter_content(chunk_size=chunk_size):
				if not chunk:
					raise Exception("Unexpected end to resource")
				f.write(chunk)
				saved += len(chunk)
				saved_window += len(chunk)
				t1 = time.time()
				if t1 - t0 >= 1:
					# print(" Percent: {:3.3f}% Speed: {:2.2f}MB/s".format(100*saved/total, saved_window/1000000/(t1-t0)), flush=True, end="\r")
					t0 = t1
					saved_window = 0
		if safe and final_path.exists():
			raise Exception("Clip already exists at {}, clip is in scratch".format(final_path))
		temp_path.rename(final_path)
		# print(" "*50, end="\r")
		# print("Saved {:2.2f}MB video".format(total/1000000))
		return (pid,final_path,True)

def download_inmem(uid, pid, content, safe=True):
	fname = pid+".mp4"
	temp_path = SCRATCH_DIR / fname
	final_path = UIDS_DIR / uid / fname
	if safe and final_path.exists():
		raise Exception("Clip already exists at {}".format(final_path))
	with open(temp_path, 'wb') as f:
		f.write(content)
	if safe and final_path.exists():
		raise Exception("Clip already exists at {}, clip is in scratch".format(final_path))
	temp_path.rename(final_path)
	return (pid,final_path,False)

def dl_helper(args):
	if isinstance(args[2], str):
		try:
			return download_tok(*args)
		except Exception as e:
			if str(e) not in {"429"}:
				print("Clip DL failed pid={}".format(args[1]), e)
	elif isinstance(args[2], bytes):
		try:
			return download_inmem(*args)
		except Exception as e:
			print("In Memory Clip Save failed pid={}".format(args[1]), e)
	else:
		print("Unexpected type", type(args[2]))
	return None

def convert_bytes(num):
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0

def chunkify(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def download_user(username, cursor):
	result = cursor.execute("SELECT uid FROM usernames WHERE username = ?", (username,)).fetchone()
	assert result is not None
	uid = result["uid"]
	usernames = [row["username"] for row in cursor.execute("SELECT username FROM usernames WHERE uid = ?", (uid,))]
	assert len(usernames) > 0
	make_user_dirs(DL_DIR, uid, usernames)
	post_rows = cursor.execute("SELECT posts.pid,json,location,status from posts left join raw_posts on posts.pid = raw_posts.pid left join downloads on downloads.pid = posts.pid where uid = ?", (uid,)).fetchall()
	print("Tracking {} posts for {}".format(len(post_rows), username))
	accum,nsaved,nfailed,nleft = [],0,0,0
	for row in post_rows:
		if row["location"] is not None:
			nsaved += 1
		elif row["status"] is not None and row["status"] not in (429,):
			nfailed += 1
		else:
			accum.append(row)
			nleft += 1
	post_rows = accum
	print("Saved: {}, Failed: {}, Unsaved: {}".format(nsaved, nfailed, nleft))
	print("Extracting {} HD posts ids for {}".format(len(post_rows), username))
	pids = [row["pid"] for row in post_rows]
	posts = [json.loads(row["json"]) for row in post_rows]
	pool = ThreadPool(processes=5)
	hd_urls = list(tqdm(pool.imap(post2hd, posts), total=len(posts)))
	assert len(hd_urls) == len(pids)
	failed_rows = [(None if url is None else str(url),pid) for pid,url in zip(pids,hd_urls) if url is None or isinstance(url,Exception)]
	cursor.executemany("UPDATE raw_posts SET status = ? where pid = ?", failed_rows)
	print("Marking {} failed HD id extractions.".format(len(failed_rows)) +
		"These may be retried if not 404/403." if len(failed_rows) else "")
	hd_rows = [(pid,url) for pid,url in zip(pids,hd_urls) if url is not None and isinstance(url, str) and pid not in HD_URL_CACHE]
	print("Caching {} HD urls".format(len(hd_rows)))
	cursor.executemany("INSERT OR REPLACE INTO hd_urls VALUES (?,?)", hd_rows)
	conn.commit()
	dl_tasks = [(uid,pid,url) for pid,url in zip(pids,hd_urls) if url is not None and not isinstance(url,Exception)]
	print("Downloading {} posts of {} for {}".format(len(dl_tasks), len(post_rows), username))
	chunks = list(chunkify(dl_tasks, 10))
	flag = False
	for i,chunk in enumerate(chunks):
		t0 = time.time()
		dl_results = list(tqdm(pool.imap(dl_helper, chunk), total=len(chunk)))
		tot = len(dl_results)
		dl_results = [(r[0], str(r[1]), r[2]) for r in dl_results if r is not None]
		cursor.executemany("INSERT INTO downloads VALUES (?,?,?)", dl_results)
		conn.commit()
		t1 = time.time()
		flag = flag or (tot-len(dl_results))
		print("Saved {}/{} posts for {} chunk[{}/{}][{}s]".format(
			len(dl_results), tot, username, i+1, len(chunks), round(t1-t0,1)))
		if GLOBAL_ZERO_BYTE_COUNTER > 4:
			print("Probable IP ban. Quitting.")
			break
	if flag:
		print("There were download failures. Retry.")

def repair(uid, cursor):
	path = UIDS_DIR / uid
	if path.exists():
		fnames = [Path(fname) for fname in os.listdir(path) if ".mp4" in fname or ".webm" in fname]
		rows = cursor.execute("SELECT uid,posts.pid,location from downloads join posts on posts.pid = downloads.pid where uid = ?", (uid,))
		downloaded_pids = {row["pid"] for row in rows}
		fixed = []
		for name in fnames:
			if name.stem not in downloaded_pids:
				location = str(path/name)
				print("Found untracked download", name)
				fixed.append((name.stem, location, 1))
		cursor.executemany("INSERT INTO downloads VALUES (?,?,?)", fixed)
		conn.commit()
		print("Repaired.")
def check_helper(args):
	uid,seen = args
	username = uid2name[uid][-1]
	if seen is None:
		seen = "-1"
	posts = get_all_posts(uid, 50, seen, False)
	if len(posts):
		print("Found {} new posts for {}".format(len(posts), username))
	return posts

def get_current_username(uid):
	posts = get_posts(uid, 1)
	return posts["items"][0]["author"]["uniqueId"]

conn = None
dbinit = Path(DB_FILE).exists()
conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute(FK_PRAGMA)
cursor.execute(USER_VERSION_PRAGMA)
cursor.execute(WAL_PRAGMA)
if not dbinit:
	for stmt in TABLE_STMTS:
		cursor.execute(stmt)
	conn.commit()
HD_URL_CACHE = {}
uid2name = {}
name2uid = {}
rows = cursor.execute("SELECT nick,tokkers.uid,username FROM tokkers INNER JOIN usernames ON tokkers.uid = usernames.uid ORDER BY usernames.ts ASC")
for row in rows:
	assert row["username"] not in name2uid
	if row["uid"] in uid2name:
		uid2name[row["uid"]].append(row["username"])
	else:
		uid2name[row["uid"]] = [row["username"]]
	name2uid[row["username"]] = row["uid"]

make_dirs(DL_DIR)

COMMANDS = {
	"refresh": "resave/add a tokker's posts to get valid vid links",
	"dl": "dl a tokker",
	"update": "check and update stats for registered tokkers",
	"add": "add a tokker",
	"check": "check for new posts for all tokkers",
	"move": "move a tokkers files from src -> dest",
	"mvall": "move all files from src -> dest",
	"info": "print info on a tokker",
	"ls": "list tokkers",
	"lookup": "look up uid",
	"repair": "check mismatches",
	"scan": "dl for tokkers starting from smallest first",
	"lup": "lookup a post id",
	"hp": "health check",
	"import": "import a post file from outside source"
	}
args = list(sys.argv)
if len(args) > 1:
	cmd = args[1]
	if cmd in COMMANDS:
		if "check" == cmd:
			assert len(args) > 1
			if len(args) == 2:
				updates = cursor.execute("SELECT tokkers.uid, max(pid) AS pid FROM tokkers LEFT JOIN posts ON tokkers.uid = posts.uid GROUP BY tokkers.uid").fetchall()
				posts = []
				pool = ThreadPool(processes=5)
				results = list(tqdm(pool.imap(check_helper, updates), total=len(updates)))
				posts = [post for r in results for post in r]
				save_posts(posts, cursor)
				conn.commit()
			else:
				uids = tuple(name2uid[username] for username in args[2:])
				q = "SELECT tokkers.uid, max(pid) AS pid FROM tokkers LEFT JOIN posts ON tokkers.uid = posts.uid WHERE tokkers.uid in ({}) GROUP BY tokkers.uid".format(",".join("?"*len(uids)))
				updates = cursor.execute(q,uids).fetchall()
				for row in updates:
					uid,seen = row
					username = uid2name[uid][-1]
					if seen is None:
						seen = "-1"
					print("Checking", username)
					posts = get_all_posts(uid, 50, seen)
					save_posts(posts, cursor)
					conn.commit()
			
		elif "info" == cmd:
			if len(args) > 2:
				for username in args[2:]:
					print_info(username, cursor)
			else:
				ntokkers = cursor.execute("SELECT count(*) FROM tokkers").fetchone()[0]
				ntoks = cursor.execute("SELECT count(*) FROM posts").fetchone()[0]
				nfiles = cursor.execute("SELECT count(*) FROM downloads").fetchone()[0]
				nmusic = cursor.execute("SELECT count(*) FROM music").fetchone()[0]
				print(PROG_TITLE)
				print("Tokkers:", ntokkers)
				print("Posts:  ", ntoks)
				print("Files:  ", nfiles)
				print("Music:  ", nmusic)
				print("Space:  ", du(DL_DIR))
				print("DB:     ", du(DB_FILE))
		elif "lookup" == cmd:
			assert len(args) > 2
			for arg in args[2:]:
				if arg in name2uid:
					uid = name2uid[arg]
					data = get_current_username(uid)
					print("{} -> {} -> {}".format(arg, uid, data))
				elif arg.isdigit():
					data = get_current_username(arg)
					print("{} -> {}".format(arg, data))
				else:
					print("Unknown username/Invalid uid:", arg)
		elif "import" == cmd:
			assert len(args) == 4
			username = args[2]
			if username in name2uid:
				uid = name2uid[username]
				names = uid2name[uid]
				make_user_dirs(DL_DIR, uid, names)
				fpath = Path(args[3])
				if fpath.exists():
					if fpath.is_file():
						location = UIDS_DIR / uid / fpath.name
						pid = fpath.stem
						print("Import post {} by {} to {}?\n[this will not erase original file]".format(pid, username, location))
						if location.exists():
							print("Warning: target file already exists!")
						response = input()
						if strtobool(response):
							shutil.copy(str(fpath), str(location))
							post = (pid,uid,None,None,ts())
							dl = (pid,str(location),1)
							row = cursor.execute("SELECT * FROM posts WHERE pid = ?", (pid,)).fetchone()
							if row is None:
								cursor.execute("INSERT INTO posts VALUES (?,?,?,?,?)", post)
							cursor.execute("INSERT INTO downloads VALUES (?,?,?)", dl)
							conn.commit()
							print("Imported post.")
						else:
							print("Cancelled.")
					elif fpath.is_dir():
						user_dir = UIDS_DIR / uid
						fpaths = [Path(fname) for fname in os.listdir(fpath) if ".mp4" in fname or ".webm" in fname]
						print("Import {} posts by {} from {} to {}?\n[this will not erase original files]".format(
							len(fpaths), username, fpath, user_dir))
						response = input()
						if strtobool(response):
							fails = 0
							saved_posts = set(row["pid"] for row in cursor.execute("SELECT * FROM posts WHERE uid = ?", (uid,)))
							dl_rows,post_rows = [],[]
							for p in tqdm(fpaths):
								if p.stem.isdigit():
									location = user_dir/p
									if not location.exists():
										pid = p.stem
										shutil.copy(str(fpath/p), str(location))
										if pid not in saved_posts:
											post_rows.append((pid,uid,None,None,ts()))
										dl_rows.append((pid,str(location),1))
									else:
										fails += 1
										print("File {} already exists skipping.".format(location))
								else:
									print("File {} does not have numerical name skipping.".format(p.name))
									fails += 1
							cursor.executemany("INSERT INTO posts VALUES (?,?,?,?,?)", post_rows)
							cursor.executemany("INSERT INTO downloads VALUES (?,?,?)", dl_rows)
							conn.commit()
							print("Imported {}/{} posts".format(len(fpaths)-fails, len(fpaths)))
						else:
							print("Cancelled.")
					else:
						print("Unknown non-dir/file type", fpath)
				else:
					print("No file/dir", fpath)
			else:
				print("Unknown user, please add.")

		elif "lup" == cmd:
			assert len(args) == 3
			pid = args[2]
			if ".mp4" in pid:
				pid = pid[:-4]
			post = cursor.execute("SELECT username,posts.pid,description,location from posts JOIN tokkers ON tokkers.uid = posts.uid JOIN usernames ON usernames.uid = tokkers.uid LEFT JOIN downloads on posts.pid = downloads.pid WHERE posts.pid = ?", (pid,)).fetchone()
			if post:
				print("{}: {} {}\n{}".format(*post))
			else:
				print("No post found.")
		elif "dl" == cmd:
			assert len(args) > 2
			for row in cursor.execute("SELECT * FROM hd_urls"):
				HD_URL_CACHE[row["pid"]] = row["url"]
			for username in args[2:]:
				if username in name2uid:
					print("Downloading posts for", username)
					download_user(username, cursor)
					conn.commit()
				if GLOBAL_ZERO_BYTE_COUNTER > 4:
					break
		elif "repair" == cmd:
			assert len(args) == 3
			username = args[2]
			if username in name2uid:
				repair(name2uid[username], cursor)
			else:
				print("Unknown user", username)
		elif "move" == cmd:
			assert len(args) == 5
			username,src,dest = args[2:5]
			src,dest = Path(src),Path(dest)
			make_dirs(dest)
			uid = name2uid[username]
			usernames = [row["username"] for row in cursor.execute("SELECT username FROM usernames WHERE uid = ?", (uid,))]
			make_user_dirs(dest, uid, usernames)
			rows = cursor.execute("SELECT uid,posts.pid,location from downloads join posts on posts.pid = downloads.pid where uid = ?", (uid,))
			new_rows = []
			for row in rows:
				uid,pid = row["uid"],row["pid"]
				full_path = Path(row["location"])
				root_path = Path(*full_path.parts[:-3])
				file_path = Path(*full_path.parts[-3:])
				if root_path == src:
					new_path = dest/file_path
					# full_path.rename(new_path)
					shutil.move(full_path, new_path)
					new_rows.append((pid,str(new_path)))
			cursor.executemany("INSERT OR REPLACE INTO downloads VALUES (?,?)", new_rows)
			conn.commit()
		elif "mvall" == cmd:
			assert len(args) == 4
			src,dest = args[2:4]
			src,dest = Path(src),Path(dest)
			make_dirs(dest)
			qq = (str(src)+"%",)
			rows = cursor.execute("SELECT uid,posts.pid,location,hd FROM downloads JOIN posts ON downloads.pid = posts.pid WHERE location LIKE ?", qq).fetchall()
			new_rows = []
			for row in rows:
				uid,pid,hd = row["uid"],row["pid"],row["hd"]
				usernames = [row["username"] for row in cursor.execute("SELECT username FROM usernames WHERE uid = ?", (uid,))]
				full_path = Path(row["location"])
				root_path = Path(*full_path.parts[:-3])
				file_path = Path(*full_path.parts[-3:])
				if root_path == src:
					new_path = dest/file_path
					make_user_dirs(dest, uid, usernames)
					shutil.move(full_path, new_path)
					new_rows.append((pid,str(new_path),hd))
			cursor.executemany("INSERT OR REPLACE INTO downloads VALUES (?,?,?)", new_rows)
			conn.commit()
		elif "hp" == cmd:
			assert len(args) == 2
			rows = cursor.execute("SELECT location FROM downloads").fetchall()
			for row in rows:
				full_path = Path(row["location"])
				if not full_path.exists():
					print("WARNING: {} missing!".format(full_path))
		elif "ls" == cmd:
			assert len(args) in (2,3)
			if len(args) == 2:
				rows = cursor.execute("SELECT username,ts FROM usernames ORDER BY ts DESC").fetchall()
			else:
				if args[2].isdigit():
					limit = int(args[2])
					rows = cursor.execute("SELECT username,ts FROM usernames ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
			pad = 0
			for row in rows:
				pad = max(len(row["username"]), pad)
			results = reversed(["{} {}".format(row["username"].ljust(pad), datetime.utcfromtimestamp(row["ts"]//1000).strftime('%Y-%m-%d %H:%M:%S')) for row in rows])
			print("\n".join(results))
		elif "refresh" == cmd:
			assert len(args) > 2
			for username in args[2:]:
				uid = name2uid[username]
				print("Refreshing: {} {}".format(username, uid))
				posts = get_all_posts(uid, 50)
				print(len(posts))
				rows = cursor.execute("SELECT posts.pid,location FROM posts LEFT JOIN downloads ON posts.pid=downloads.pid WHERE uid = ?", (uid,)).fetchall()
				saved = [row["pid"] for row in rows]
				print(len(saved))
				a = set(saved)
				b = set(p["id"] for p in posts)
				print("Saved but missing:", a-b)
				print("Unsaved but public:", b-a)
				print("Saved", len(a))
				print("seen", len(b))
				## don't update posts we downloaded already
				notdl = {row["pid"] for row in rows if row["location"] is None}
				inp = [post for post in posts if post["id"] in notdl]
				print("Updating {} posts that are not downloaded.".format(len(inp)))
				update_posts(inp, cursor)
				conn.commit()
		elif "update" == cmd:
			assert len(args) == 2
			pool = ThreadPool(processes=5)
			usernames = [row["username"] for row in cursor.execute("SELECT username from usernames")]
			user_data = list(tqdm(pool.imap(fetch_tokker, usernames), total=len(usernames)))
			user_data = [d for d in user_data if d is not None]
			print(len(usernames), len(user_data))
			for username,data in user_data:
				msg = add_user(username, data, cursor)
				if msg:
					print(msg)
				conn.commit()
		elif "scan" == cmd:
			assert len(args) in (2,3)
			threshold = 20
			if len(args) == 3:
				threshold = int(args[2])
			names = []
			rows = cursor.execute("SELECT tokkers.uid,count(posts.pid) as pps ,downloads.location from tokkers join posts on tokkers.uid=posts.uid left join downloads on posts.pid = downloads.pid JOIN raw_posts ON posts.pid = raw_posts.pid where downloads.location is NULL AND (raw_posts.status IS NULL OR raw_posts.status IN (429)) group by tokkers.uid ORDER BY pps ASC").fetchall()
			for row in rows:
				uid = row["uid"]
				username = uid2name[uid][-1]
				count = row["pps"]
				if count > threshold:
					print("Count > {} stopping".format(threshold))
					break
				names.append(username)
				if username in name2uid:
					print("Downloading {} posts for {}".format(count, username))
					download_user(username, cursor)
					conn.commit()
				if GLOBAL_ZERO_BYTE_COUNTER > 4:
					break
		elif "add" == cmd:
			assert len(args) > 2
			for username in args[2:]:
				_,data = fetch_tokker(username)
				if data is not None:
					msg = add_user(username, data, cursor)
					if msg:
						print(msg)
					else:
						print(username, "was already added.")
					conn.commit()
				else:
					print("No user found", username)
	else:
		print("Invalid Command", args[1:])
else:
	print(PROG_TITLE)
	for cmd in COMMANDS:
		print("{}: {}".format(cmd, COMMANDS[cmd]))

conn.close()