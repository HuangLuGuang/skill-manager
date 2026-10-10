#!/usr/bin/env python3
import os, pwd, sys
if len(sys.argv)<4: raise SystemExit("usage: launch_as_user.py UID CWD COMMAND [ARGS...]")
uid=int(sys.argv[1]); account=pwd.getpwuid(uid); os.setsid(); os.chdir(sys.argv[2])
os.initgroups(account.pw_name, account.pw_gid); os.setgid(account.pw_gid); os.setuid(uid)
os.environ.update(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name)
os.environ["PATH"]=os.path.dirname(sys.argv[3])+":/usr/bin:/bin:/usr/sbin:/sbin"
os.execvpe(sys.argv[3],sys.argv[3:],os.environ)
