"""Exact Moments identity helpers; submission is handled by the native adapter."""
import re

def normal(value):return re.sub(r'\s+',' ',str(value or '')).strip()

def same_post(left,right):
    return (str(left.get('id'))==str(right.get('id')) and left.get('username')==right.get('username')
            and normal(left.get('text'))==normal(right.get('text')))

def submit(adapter,post,text,*,dry_run=False,allowed=lambda:True):
    return adapter.comment_moment(post,text,dry_run=dry_run,allowed=allowed)
