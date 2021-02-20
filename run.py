#!/usr/bin/python3
from users import users
from subprocess import run
import argparse

parser = argparse.ArgumentParser()

# -d 参数代表执行 “晨午晚检” 不加代表执行 “每日填报”
parser.add_argument('--dailyup','-d',action='store_true')

args = parser.parse_args()

for user in users:
    program = 'main.py'
    if args.dailyup:
        program = 'main2.py'
    cmd = ['python3', program]
    cmd.append('--bupt-sso-user={}'.format(user['username']))
    cmd.append('--bupt-sso-pass={}'.format(user['pass']))
    SCKEY = user.get('SCKEY',None)
    if SCKEY:
        cmd.append('--server-chan-sckey={}'.format(SCKEY))
    run(cmd)
